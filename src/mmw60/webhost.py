"""The local host of the mmw60 page: static files, a small JSON API and a queue of background jobs.

One page (``webui/www``) served by the standard library on 127.0.0.1; the desktop gets it in a
Chromium-family browser's ``--app`` window whose closing stops the server, any browser can open
the same address, and a phone's WebView calls the same ``Api`` through ``mmw60.appbridge`` (the
pattern of polar_tx and array_tx: one page, three hosts).

Nothing here computes.  ``guiutil`` does, in a child process per job, and ``guistore`` keeps what
came back.  The page is a **browser of computed results**: it opens on the shipped baseline (the
presets), a changed form marks numbers stale instead of clearing them, and a recomputation is a
job in the queue.

API (JSON; every POST needs the ``X-MMW60: 1`` header, which a page from another origin cannot add
without a preflight this host does not answer):

    GET  /api/version                 library, python, vendored pins, queue backend
    GET  /api/sources                 the spec-table entries with their source labels
    GET  /api/parts                   part x knob: what reads what, the jobs, their durations
    GET  /api/jobs                    the queue
    GET  /api/jobs/<id>               one job
    GET  /api/results                 the stored results (no reports)
    POST /api/state     {study?}      the form, the freshness of every part, which result is shown
    POST /api/report    {report, study}   a stored report: table | calibration | array | ay
    POST /api/row       {label, study}    one table row opened: detail, calibration column, repro card
    POST /api/system    {study}       the block diagram's facts
    POST /api/run       {job, study}  queue a job (``guiutil.JOBS``)
    POST /api/jobs/<id>/cancel
    POST /api/results/<id>/delete     forget one of the user's results

``study`` is the form: shared knobs that differ from the presets (``guiutil.study``).  The host
remembers the last one it was sent, so a reloaded page finds its form again.

Run: ``mmw60-gui`` (or ``python -m mmw60.webhost``).
"""
from __future__ import annotations

import argparse
import itertools
import json
import mimetypes
import multiprocessing as mp
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from . import ENGINE_BANNER, __version__, guistore, guiutil

WWW = Path(__file__).resolve().parent / "webui" / "www"
POST_HEADER = "X-MMW60"
GET_ROUTES = ("version", "sources", "parts", "jobs", "results")
POST_ROUTES = ("state", "report", "row", "system", "run")
REPORTS = tuple(guistore.REPORT_JOBS)
#: the jobs a host queues: the full ones.  An analytic-only table is a command-line tool
#: (tools/gui_report.py table --no-time-domain): stored beside a full table it would be picked for
#: its fresh part and the time-domain column and the 802.11ay rows would vanish from the page.
RUNNABLE = guistore.BASELINE_JOBS


# ------------------------------------------------------------------ jobs
class Cancelled(Exception):
    """Raised inside a thread-backend job when it was cancelled between steps."""


def execute(job: str, st: dict, params: dict, emit, cancelled=None) -> None:
    """Run one job and hand its progress, then its result, to ``emit(msg, payload)``: msg is
    "progress" ([done, total, text]), "done" (the job result), "error" or "cancelled".  Used by the
    process worker (emit = pipe.send) and the thread backend.  ``cancelled()`` is polled at every
    progress step on the thread backend, where there is no process to terminate."""
    try:
        def progress(done, total, text):
            emit("progress", [done, total, text])
            if cancelled is not None and cancelled():
                raise Cancelled()
        emit("done", guiutil.run_job(job, st, quick=bool(params.get("quick")), progress=progress,
                                     calibration=params.get("calibration")))
    except Cancelled:
        emit("cancelled", None)
    except Exception:                                   # noqa: BLE001 (reported in-band)
        emit("error", traceback.format_exc())


def _worker(conn, runner, job: str, st: dict, params: dict) -> None:
    """The child process: the runner with the pipe as the sink."""
    try:
        runner(job, st, params, lambda msg, payload: conn.send((msg, payload)))
    finally:
        conn.close()


class JobQueue:
    """Background jobs, ``workers`` at a time.

    ``backend="process"`` (the desktop): each job in its own spawned process, a cancel is a
    terminate.  ``backend="thread"`` (Android, where Chaquopy has no multiprocessing; tests): each
    job on a worker thread, a cancel is cooperative between progress steps.  ``on_done(job,
    result)`` is called with every finished job's result and returns the id it was stored under.
    ``on_start(job) -> dict`` is called when a job leaves the queue and its return value is merged
    into the job's params: what a job builds on is decided when it starts, not when it was queued
    (a table queued behind a calibration builds on that calibration).  ``runner`` is ``execute``
    unless a test passes its own (a module-level function, so the process backend can pickle it)."""

    def __init__(self, workers: int = 1, backend: str = "process", on_done=None, runner=execute, on_start=None):
        if backend not in ("process", "thread"):
            raise ValueError(f"backend must be process or thread, got {backend!r}")
        self.backend = backend
        self.workers = max(1, int(workers))
        self.jobs: dict[str, dict[str, Any]] = {}
        self._on_done = on_done
        self._on_start = on_start
        self._runner = runner
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._ctx = mp.get_context("spawn") if backend == "process" else None
        self._procs: dict[str, Any] = {}
        self._cv = threading.Condition(self._lock)
        for _ in range(self.workers):
            threading.Thread(target=self._loop, daemon=True).start()

    def submit(self, job: str, st: dict, params: dict | None = None) -> dict:
        if job not in guiutil.JOBS:
            raise KeyError(f"no such job {job!r} (have {sorted(guiutil.JOBS)})")
        jid = str(next(self._ids))
        entry = {"id": jid, "job": job, "study": guiutil.study(st), "status": "queued", "progress": [0, None],
                 "text": "", "error": None, "created": time.time(), "started": None, "finished": None,
                 "result_id": None, "expected_seconds": guiutil.JOBS[job]["seconds"],
                 "parts": list(guiutil.JOBS[job]["parts"]), "_params": dict(params or {}), "cancel": False}
        with self._cv:
            self.jobs[jid] = entry
            self._cv.notify()
        return self.public(entry)

    def cancel(self, jid: str) -> bool:
        with self._lock:
            job = self.jobs.get(jid)
            if job is None or job["status"] in ("done", "error", "cancelled"):
                return False
            job["cancel"] = True
            if job["status"] == "queued":
                job["status"] = "cancelled"
                job["finished"] = time.time()
            p = self._procs.get(jid)
        if p is not None:
            p.terminate()
        return True

    @staticmethod
    def public(job: dict) -> dict:
        return {k: v for k, v in job.items() if not k.startswith("_") and k != "cancel"}

    def listing(self) -> list[dict]:
        with self._lock:
            return [self.public(j) for j in self.jobs.values()]

    def get(self, jid: str) -> dict | None:
        with self._lock:
            j = self.jobs.get(jid)
            return None if j is None else self.public(j)

    def busy(self) -> bool:
        with self._lock:
            return any(j["status"] in ("queued", "running") for j in self.jobs.values())

    def _next(self) -> dict:
        with self._cv:
            while True:
                for j in self.jobs.values():
                    if j["status"] == "queued":
                        j["status"] = "running"
                        j["started"] = time.time()
                        return j
                self._cv.wait()

    def _loop(self) -> None:
        while True:
            job = self._next()
            try:
                if self._on_start is not None:
                    job["_params"] = {**job["_params"], **(self._on_start(self.public(job)) or {})}
            except Exception:                           # noqa: BLE001
                with self._lock:
                    job.update(status="error", error=traceback.format_exc(), finished=time.time())
                continue
            self._run(job)

    def _take(self, job: dict, msg: str, payload) -> None:
        """One message of a running job into its entry.  A result is stored before the job reads
        as done, so a page that sees "done" finds the result."""
        if msg == "done":
            try:
                rid = self._on_done(job, payload) if self._on_done else None
            except Exception:                           # noqa: BLE001
                msg, payload = "error", traceback.format_exc()
        with self._lock:
            if msg == "progress":
                job["progress"] = [payload[0], payload[1]]
                job["text"] = str(payload[2])
            elif msg == "done":
                job["result_id"] = rid
                job["status"] = "done"
            elif msg == "error":
                job["error"] = payload
                job["status"] = "error"
            elif msg == "cancelled":
                job["status"] = "cancelled"
            if job["status"] != "running" and job["finished"] is None:
                job["finished"] = time.time()                # set with the status: never one without the other

    def _run(self, job: dict) -> None:
        if self.backend == "thread":
            try:
                self._runner(job["job"], job["study"], job["_params"], lambda m, p: self._take(job, m, p),
                             lambda: job["cancel"])
            finally:
                with self._lock:
                    if job["status"] == "running":
                        job["status"] = "cancelled" if job["cancel"] else "error"
                    job["finished"] = job["finished"] or time.time()
            return
        parent, child = self._ctx.Pipe(duplex=False)
        p = self._ctx.Process(target=_worker, args=(child, self._runner, job["job"], job["study"], job["_params"]),
                              daemon=True)
        p.start()
        child.close()
        with self._lock:
            self._procs[job["id"]] = p

        def take(timeout: float) -> str | None:
            """One message into the job, or None when none arrived in time."""
            if not parent.poll(timeout):
                return None
            try:
                msg, payload = parent.recv()
            except EOFError:
                return "eof"
            self._take(job, msg, payload)
            return msg
        try:
            while True:
                if job["cancel"]:
                    p.terminate()
                    break
                msg = take(0.1)
                if msg in ("done", "error", "eof"):
                    break
                if msg is None and not p.is_alive():
                    # the worker is gone: what it sent before exiting may still be in the pipe
                    while take(0.0) not in (None, "eof", "done", "error"):
                        pass
                    break
        finally:
            p.join(5)
            with self._lock:
                self._procs.pop(job["id"], None)
                if job["status"] == "running":
                    job["status"] = "cancelled" if job["cancel"] else "error"
                    if job["status"] == "error" and not job["error"]:
                        job["error"] = f"worker exited with code {p.exitcode}"
                job["finished"] = job["finished"] or time.time()
            parent.close()


# ------------------------------------------------------------------ state
class State:
    """What a host holds: the stored results, the queue and the last form it was sent."""

    def __init__(self, workers: int = 1, backend: str = "process", home: str | Path | None = None,
                 store: guistore.Store | None = None, runner=execute):
        self.store = store if store is not None else guistore.Store(home)
        self.jobs = JobQueue(workers, backend, on_done=lambda job, result: self.store.add(result), runner=runner,
                             on_start=self.builds_on)
        self.study: dict = {}

    def builds_on(self, job: dict) -> dict:
        """What a job builds on, looked up as it starts: a table takes the calibration stored for
        its study, if there is one (else ``run_job`` looks its IRR up in the accepted table)."""
        if guiutil.JOBS[job["job"]]["report"] != "table":
            return {}
        cal = self.store.pick("calibration", job["study"])
        if cal is not None and (guiutil.signature("calibration.be", cal["result"]["study"])
                                == guiutil.signature("calibration.be", job["study"])):
            return {"calibration": cal["result"]}
        return {}

    def shown(self, st: dict) -> dict:
        """Per report, the stored result a page draws for this study (without the report)."""
        out = {}
        for report in REPORTS:
            entry = self.store.pick(report, st)
            out[report] = None if entry is None else _meta(entry)
        return out


def _meta(entry: dict) -> dict:
    res = entry["result"]
    return {"id": entry["id"], "origin": entry["origin"], "at": entry["at"], "job": res["job"], "study": res["study"],
            "parts": res["parts"], "built_on": res.get("built_on") or {}, "seconds": res.get("seconds"),
            "provenance": res["provenance"],
            # computed on other spec tables / pins than this tree's: the study still matches, the code does not
            "out_of_step": guistore.stale_reasons(res, baseline=entry["origin"] == "baseline")}


# ------------------------------------------------------------------- api
class Api:
    """The JSON API, independent of the transport: the HTTP handler and the Android bridge
    (``mmw60.appbridge``) both call ``get`` / ``post`` and get ``(status, payload)`` back.
    Payloads always carry ``ok``."""

    def __init__(self, state: State):
        self.state = state

    # ------------------------------------------------------------ GET
    def get(self, route: str) -> tuple[int, dict]:
        st = self.state
        if route == "version":
            return 200, {"ok": True, "library": "mmw60_trx", "version": __version__, "python": sys.version.split()[0],
                         "engine": ENGINE_BANNER, "provenance": guiutil.provenance(), "workers": st.jobs.workers,
                         "backend": st.jobs.backend,
                         "results_dir": None if st.store.home is None else str(st.store.dir)}
        elif route == "sources":
            return 200, {"ok": True, "sources": guiutil.sources(), "counts": guiutil.source_counts()}
        elif route == "parts":
            m = guiutil.freshness_matrix()
            m["jobs"] = {j: m["jobs"][j] for j in RUNNABLE}
            return 200, {"ok": True, **m, "stored": guiutil.STORED}
        elif route == "jobs":
            return 200, {"ok": True, "jobs": st.jobs.listing()}
        elif route == "results":
            return 200, {"ok": True, "results": st.store.listing(st.study)}
        elif route.startswith("jobs/"):
            j = st.jobs.get(route[5:])
            return (200, {"ok": True, "job": j}) if j else (404, {"ok": False, "error": "no such job"})
        return 404, {"ok": False, "error": f"no such route /api/{route}"}

    # ------------------------------------------------------------ POST
    def _study(self, req: dict) -> dict:
        return guiutil.study(req.get("study") or {})

    def _fresh(self, study: dict) -> dict:
        fresh = guiutil.freshness(study, self.state.store.envelopes(study), accepted=False)
        return {"parts": fresh, "fields": guiutil.field_states(fresh)}

    def post(self, route: str, req: dict) -> tuple[int, dict]:
        st = self.state
        if route == "state":
            if "study" in req:
                st.study = self._study(req)
            study = st.study
            return 200, {"ok": True, "study": study, "form": guiutil.form(study), "freshness": self._fresh(study),
                         "shown": st.shown(study), "jobs": st.jobs.listing(), "results": st.store.listing(study)}
        elif route == "report":
            name = str(req.get("report"))
            if name not in REPORTS:
                raise ValueError(f"report must be one of {REPORTS}, got {name!r}")
            study = self._study(req)
            entry = st.store.pick(name, study)
            jobs = [j for j in guistore.REPORT_JOBS[name] if j in RUNNABLE]
            if entry is None:
                return 200, {"ok": True, "report": None, "result": None, "freshness": self._fresh(study),
                             "jobs": jobs}
            out = {"ok": True, "report": entry["result"]["report"], "result": _meta(entry),
                   "freshness": self._fresh(study), "jobs": jobs}
            if name == "table":
                # the range column: the one-element link of the array result shown for this study
                arr = st.store.pick("array", study)
                out["ranges"] = None if arr is None else guiutil.single_antenna_ranges(arr["result"]["report"])
                out["ranges_result"] = None if arr is None else _meta(arr)
            elif name == "ay":
                # who wins and by how much is computed from the array result's 802.11ay rows
                arr = st.store.pick("array", study)
                has = arr is not None and arr["result"]["report"].get("ay")
                out["headline"] = guiutil.sc_vs_ofdm_headline(arr["result"]["report"]) if has else None
                out["headline_result"] = _meta(arr) if has else None
            return 200, out
        elif route == "row":
            study = self._study(req)
            table = st.store.pick("table", study)
            if table is None:
                raise ValueError("no table result is stored")
            cal = st.store.pick("calibration", study)
            arr = st.store.pick("array", study)
            detail = guiutil.row_detail(table["result"]["report"], str(req["label"]),
                                        None if cal is None else cal["result"]["report"])
            ranges = {} if arr is None else guiutil.single_antenna_ranges(arr["result"]["report"])
            return 200, {"ok": True, **detail, "range": ranges.get(str(req["label"])),
                         "calibration": None if cal is None else cal["result"]["report"],
                         "results": {"table": _meta(table), "calibration": None if cal is None else _meta(cal),
                                     "array": None if arr is None else _meta(arr)},
                         "freshness": self._fresh(study)}
        elif route == "system":
            return 200, {"ok": True, **guiutil.system_report(self._study(req))}
        elif route == "run":
            job = str(req.get("job"))
            if job not in RUNNABLE:
                raise ValueError(f"job must be one of {list(RUNNABLE)}, got {job!r}")
            return 200, {"ok": True, "job": st.jobs.submit(job, self._study(req))}
        elif route.startswith("jobs/") and route.endswith("/cancel"):
            ok = st.jobs.cancel(route[5:-7])
            return 200, {"ok": ok, **({} if ok else {"error": "not cancellable"})}
        elif route.startswith("results/") and route.endswith("/delete"):
            ok = st.store.delete(route[8:-7])
            return 200, {"ok": ok, **({} if ok else {"error": "not one of the user's results"})}
        return 404, {"ok": False, "error": f"no such route /api/{route}"}

    def call(self, route: str, req: dict | None = None) -> tuple[int, dict]:
        """GET when the route is a GET route (and ``jobs/<id>``), else POST; errors come back
        in-band as the handler would send them."""
        is_get = route in GET_ROUTES or (route.startswith("jobs/") and not route.endswith("/cancel"))
        try:
            return self.get(route) if is_get else self.post(route, req or {})
        except (ValueError, TypeError, KeyError, OSError) as exc:
            return 400, {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        except Exception as exc:                        # noqa: BLE001
            return 500, {"ok": False, "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()}


def dumps(obj: Any) -> str:
    """The one JSON encoder of both transports.  ``guiutil`` already returns plain JSON types with
    non-finite floats as null; a float that slipped through fails here rather than reach the page
    as ``NaN`` (which is not JSON)."""
    return json.dumps(obj, ensure_ascii=False, allow_nan=False)


# --------------------------------------------------------------- handler
class _Handler(BaseHTTPRequestHandler):
    server_version = "mmw60-webhost"

    def log_message(self, fmt, *args):      # quiet: this is a desktop app
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: Any) -> None:
        self._send(code, dumps(obj).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):                                   # noqa: N802
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/"):
            route = path[5:]
            if not (route in GET_ROUTES or route.startswith("jobs/")):
                self._json(404, {"ok": False, "error": f"no such route {path}"})
                return
            self._json(*self.server.api.call(route))             # type: ignore[attr-defined]
            return
        rel = path.lstrip("/") or "index.html"
        target = (WWW / rel).resolve()
        if WWW.resolve() not in target.parents or not target.is_file():
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype)

    def do_POST(self):                                  # noqa: N802
        path = self.path.split("?", 1)[0]
        if not path.startswith("/api/"):
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        if self.headers.get(POST_HEADER) != "1":
            self._json(403, {"ok": False, "error": f"missing {POST_HEADER} header"})
            return
        n = int(self.headers.get("Content-Length") or 0)
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(req, dict):
                raise ValueError("the body must be a JSON object")
        except ValueError as exc:
            self._json(400, {"ok": False, "error": f"bad request: {exc}"})
            return
        route = path[5:]
        if route in GET_ROUTES:                          # a POST to a GET route is not a way around the header
            self._json(405, {"ok": False, "error": f"{path} is a GET route"})
            return
        self._json(*self.server.api.call(route, req))            # type: ignore[attr-defined]


class _Server(ThreadingHTTPServer):
    allow_reuse_address = sys.platform != "win32"
    daemon_threads = True
    state: State
    api: Api

    def handle_error(self, request, client_address):
        """A client that hangs up mid-request (the app window closing while a poll is in flight)
        is not a server error; everything else prints."""
        if isinstance(sys.exc_info()[1], ConnectionError):
            return
        super().handle_error(request, client_address)


def make_server(port: int = 0, host: str = "127.0.0.1", state: State | None = None, **kw) -> _Server:
    """A server bound to ``host:port`` (0 picks a free port).  Not started.  ``kw`` goes to
    ``State`` when none is given (workers, backend, home, store, runner)."""
    srv = _Server((host, port), _Handler)
    srv.state = state if state is not None else State(**kw)
    srv.api = Api(srv.state)
    return srv


# -------------------------------------------------------------- launcher
_BROWSER_NAMES = ("msedge", "microsoft-edge", "microsoft-edge-stable", "google-chrome", "google-chrome-stable",
                  "chrome", "chromium", "chromium-browser", "brave-browser")
HANDOFF_S = 3.0


def find_app_browser() -> str | None:
    """A browser that can open a chromeless ``--app`` window, or None (``MMW60_BROWSER`` overrides)."""
    env = os.environ.get("MMW60_BROWSER")
    if env:
        return env
    for name in _BROWSER_NAMES:
        found = shutil.which(name)
        if found:
            return found
    places: list[Path] = []
    if sys.platform == "win32":
        for var in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
            base = os.environ.get(var)
            if base:
                places += [Path(base, "Microsoft", "Edge", "Application", "msedge.exe"),
                           Path(base, "Google", "Chrome", "Application", "chrome.exe")]
    elif sys.platform == "darwin":
        for app in ("Microsoft Edge", "Google Chrome", "Chromium", "Brave Browser"):
            places.append(Path("/Applications", f"{app}.app", "Contents", "MacOS", app))
    return next((str(p) for p in places if p.is_file()), None)


def app_window_command(browser: str, url: str, profile: Path) -> list[str]:
    return [browser, f"--app={url}", f"--user-data-dir={profile}", "--no-first-run",
            "--no-default-browser-check", "--window-size=1440,920"]


def _stop_with_window(srv: Any, proc: Any, handoff_s: float | None = None) -> bool:
    """Stop the server when the app window closes.  A browser that hands the window to an instance
    already running exits at once: then the server keeps running until Ctrl+C."""
    limit = HANDOFF_S if handoff_s is None else handoff_s
    t0 = time.monotonic()
    proc.wait()
    if time.monotonic() - t0 < limit:
        print("the window was handed to a browser that was already running; the server keeps running until Ctrl+C")
        return False
    srv.shutdown()
    return True


def _open_window(url: str, tab: bool) -> subprocess.Popen | None:
    browser = None if tab else find_app_browser()
    if browser:
        try:
            return subprocess.Popen(app_window_command(browser, url, guistore.default_home() / "app-window"),
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            print(f"could not start {browser} ({exc}); opening a browser tab")
    webbrowser.open(url)
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="The mmw60 results browser: one local page, jobs in the background.")
    ap.add_argument("--port", type=int, default=0, help="0 picks a free port")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--workers", type=int, default=1, help="jobs at a time (each is one process)")
    ap.add_argument("--home", type=Path, default=None, help="where recomputed results are kept "
                                                            "(default: MMW60_HOME or the user's cache directory)")
    ap.add_argument("--no-window", action="store_true", help="serve only; print the address")
    ap.add_argument("--tab", action="store_true", help="open a browser tab instead of an app window")
    a = ap.parse_args(argv)
    srv = make_server(a.port, a.host, workers=a.workers, home=a.home or guistore.default_home())
    url = f"http://{a.host}:{srv.server_address[1]}/"
    print(ENGINE_BANNER)
    print(f"mmw60 {__version__} at {url}  (results: {srv.state.store.dir}; Ctrl+C stops)")
    if not a.no_window:
        proc = _open_window(url, a.tab)
        if proc is not None:
            threading.Thread(target=_stop_with_window, args=(srv, proc), daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
