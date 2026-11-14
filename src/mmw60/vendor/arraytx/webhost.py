# Vendored from array_tx@5815c5a7ea43143fd58502d4894ac840b5b5fb86: src/arraytx/webhost.py
# Adapted-copy policy: see src/mmw60/vendor/__init__.py
"""The local host for the array_tx page: static files + a small JSON API +
a queue of background runs.

One page (``webui/www``), served by the standard library on 127.0.0.1; the
desktop gets it in a Chromium-family browser's ``--app`` window whose
closing stops the server (the pattern polar_tx moved to in 2026-10; a
phone WebView would serve the same directory).  Nothing here computes:
``guiutil`` does, in a child process per job, so a 21 s run of 128
elements never blocks the page and a cancel is a ``terminate()``.

API (JSON; every POST needs the ``X-ArrayTX: 1`` header, which a page from
another origin cannot add without a preflight this host does not answer):

    GET  /api/version                 lib, python, vendored pins
    GET  /api/spec                    guispec.spec()
    GET  /api/config                  the loaded config: values, provenance, yaml, sha
    POST /api/config/load   {path}    load a YAML file (desktop)
    POST /api/config/text   {yaml}    load YAML text (paste / upload)
    POST /api/validate      {values}  -> ok / error, diff vs the loaded file, sha, yaml
    POST /api/save          {values, path}   write YAML (desktop)
    POST /api/run           {values, theta0_deg, scheme, n_symbols}   -> job
    POST /api/scan          {values, scan_deg, schemes, n_symbols}    -> job
    POST /api/sweep         {values, path, points, theta0_deg, scheme, n_symbols,
                             group_path?, group_values?}  -> job (one leaf, many values; optionally per value of a second leaf)
    POST /api/rule          {values, scan_deg, backoffs, aclr_target_dbc, evm_target_db, margin_db, scheme, n_symbols}
                             -> job (scan angle x output backoff; the summary holds the |1 + Gamma| backoff rule, ex19)
    GET  /api/jobs                    the queue (no rows)
    GET  /api/jobs/<id>               one job, rows included
    GET  /api/jobs/<id>/rows/<from>   the job with rows[from:] only (the page's poll)
    POST /api/jobs/<id>/cancel

Run: ``arraytx-gui [--config configs/fr2_4el_survey.yaml]`` (or
``python -m arraytx.webhost``).
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import mimetypes
import multiprocessing as mp
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import yaml

from . import __version__
from .config import ArrayConfig, config_from_dict, default_config, load_config
from .guispec import diff, spec, to_yaml, values_from_config, values_to_config
from .guiutil import config_sha, pins

WWW = Path(__file__).resolve().parent / "webui" / "www"
POST_HEADER = "X-ArrayTX"


# ------------------------------------------------------------------ jobs
class Cancelled(Exception):
    """Raised inside a thread-backend job when it was cancelled between rows."""


def execute(kind: str, cfg_yaml: str, source_path: str | None, params: dict, emit, cancelled=None) -> None:
    """Run one job and hand every row, then the summary, to ``emit(msg,
    payload)``: msg is "row", "done" or "error".  Used by the process
    worker (emit = pipe.send) and the thread backend (emit = append under a
    lock).  ``cancelled()`` is polled between rows on the thread backend,
    where there is no process to terminate."""
    try:
        from .guiutil import rule_report, run_report, scan_report, sweep_report
        cfg = config_from_dict(yaml.safe_load(cfg_yaml), source_path)
        n_symbols = params.get("n_symbols")

        def progress(i, n, row):
            emit("row", row)
            if i < n and cancelled is not None and cancelled():     # a cancel after the last row is a finished job
                raise Cancelled()
        if kind == "run":
            rep = run_report(cfg, params.get("theta0_deg"), params.get("scheme"), n_symbols=n_symbols)
            emit("row", rep)
            emit("done", {"seconds": rep["seconds"]})
        elif kind == "scan":
            rep = scan_report(cfg, params.get("scan_deg"), params.get("schemes"), n_symbols=n_symbols, progress=progress)
            emit("done", {k: v for k, v in rep.items() if k != "rows"})
        elif kind == "sweep":
            rep = sweep_report(cfg, params["path"], params["points"], params.get("theta0_deg"), params.get("scheme"),
                               n_symbols=n_symbols, progress=progress,
                               group_path=params.get("group_path"), group_values=params.get("group_values"))
            emit("done", {k: v for k, v in rep.items() if k != "rows"})
        elif kind == "rule":
            rep = rule_report(cfg, params["scan_deg"], params["backoffs"], aclr_target_dbc=params["aclr_target_dbc"],
                              evm_target_db=params["evm_target_db"], margin_db=params["margin_db"], scheme=params["scheme"],
                              n_symbols=n_symbols, progress=progress)
            emit("done", {k: v for k, v in rep.items() if k != "rows"})
        else:
            emit("error", f"unknown job kind {kind!r}")
    except Cancelled:
        emit("cancelled", None)
    except Exception:                               # noqa: BLE001 (reported in-band)
        emit("error", traceback.format_exc())


def _worker(conn, kind: str, cfg_yaml: str, source_path: str | None, params: dict) -> None:
    """The child process: ``execute`` with the pipe as the sink."""
    try:
        execute(kind, cfg_yaml, source_path, params, lambda msg, payload: conn.send((msg, payload)))
    finally:
        conn.close()


class JobQueue:
    """Background jobs, ``workers`` at a time.

    ``backend="process"`` (the desktop): each job in its own spawned
    process, cancel is a terminate.  ``backend="thread"`` (Android, where
    Chaquopy has no multiprocessing): each job on a worker thread, cancel is
    cooperative between rows -- a long single run cannot be interrupted."""

    def __init__(self, workers: int = 2, backend: str = "process"):
        if backend not in ("process", "thread"):
            raise ValueError(f"backend must be process or thread, got {backend!r}")
        self.backend = backend
        self.workers = max(1, int(workers))
        self.jobs: dict[str, dict[str, Any]] = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._ctx = mp.get_context("spawn") if backend == "process" else None
        self._procs: dict[str, Any] = {}
        self._cv = threading.Condition(self._lock)
        for _ in range(self.workers):
            threading.Thread(target=self._loop, daemon=True).start()

    def submit(self, kind: str, cfg: ArrayConfig, params: dict, label: str) -> dict:
        jid = str(next(self._ids))
        n = {"run": 1, "scan": len(params.get("scan_deg", [])) * len(params.get("schemes", [])),
             "sweep": len(params.get("points", [])) * max(1, len(params.get("group_values") or [])),
             "rule": len(params.get("scan_deg", [])) * len(params.get("backoffs", []))}[kind]
        job = {"id": jid, "kind": kind, "label": label, "status": "queued", "progress": [0, n],
               "rows": [], "summary": None, "error": None, "created": time.time(), "started": None,
               "finished": None, "params": params, "config_sha256": config_sha(cfg),
               "_yaml": to_yaml(cfg), "_source_path": cfg.source_path, "cancel": False}
        with self._cv:
            self.jobs[jid] = job
            self._cv.notify()
        return self.public(job)

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
    def public(job: dict, with_rows: bool = False) -> dict:
        d = {k: v for k, v in job.items() if not k.startswith("_") and k not in ("rows", "cancel")}
        d["n_rows"] = len(job["rows"])
        if with_rows:
            d["rows"] = job["rows"]
        return d

    def listing(self) -> list[dict]:
        with self._lock:
            return [self.public(j) for j in self.jobs.values()]

    def get(self, jid: str, rows_from: int = 0) -> dict | None:
        """The job with its rows from index ``rows_from`` (``rows_from`` is
        echoed so the page can place them); None when there is no such job."""
        with self._lock:
            j = self.jobs.get(jid)
            if j is None:
                return None
            d = self.public(j, with_rows=True)
        if rows_from:
            d["rows"] = d["rows"][rows_from:]
        d["rows_from"] = int(rows_from)
        return d

    def _next(self) -> dict | None:
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
            if job is None:
                return
            self._run(job)

    def _run(self, job: dict) -> None:
        if self.backend == "thread":
            self._run_thread(job)
            return
        parent, child = self._ctx.Pipe(duplex=False)
        p = self._ctx.Process(target=_worker, args=(child, job["kind"], job["_yaml"], job["_source_path"], job["params"]),
                              daemon=True)
        p.start()
        child.close()
        with self._lock:
            self._procs[job["id"]] = p
        def take(timeout: float) -> str | None:
            """One message into the job, or None when none arrived in time
            (or the pipe is closed)."""
            if not parent.poll(timeout):
                return None
            try:
                msg, payload = parent.recv()
            except EOFError:
                return "eof"
            with self._lock:
                if msg == "row":
                    job["rows"].append(payload)
                    job["progress"][0] = len(job["rows"])
                elif msg == "done":
                    job["summary"] = payload
                    job["status"] = "done"
                elif msg == "error":
                    job["error"] = payload
                    job["status"] = "error"
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
                    # the worker is gone: what it sent before exiting may still
                    # be in the pipe (its 'done' lands a moment before exit)
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
                job["finished"] = time.time()
            parent.close()


    def _run_thread(self, job: dict) -> None:
        def emit(msg, payload):
            with self._lock:
                if msg == "row":
                    job["rows"].append(payload)
                    job["progress"][0] = len(job["rows"])
                elif msg == "done":
                    job["summary"] = payload
                    job["status"] = "done"
                elif msg == "error":
                    job["error"] = payload
                    job["status"] = "error"
                elif msg == "cancelled":
                    job["status"] = "cancelled"
        try:
            execute(job["kind"], job["_yaml"], job["_source_path"], job["params"], emit, lambda: job["cancel"])
        finally:
            with self._lock:
                if job["status"] == "running":
                    job["status"] = "cancelled" if job["cancel"] else "error"
                job["finished"] = time.time()


# ------------------------------------------------------------------ state
class State:
    def __init__(self, cfg: ArrayConfig, workers: int = 2, backend: str = "process", home: str | Path | None = None):
        self.cfg = cfg
        self.jobs = JobQueue(workers, backend)
        #: where a relative config path in load / save lands (the phone's own
        #: files directory); None = the process's working directory
        self.home = Path(home) if home else None

    def path(self, p: str) -> Path:
        q = Path(str(p))
        return q if q.is_absolute() or self.home is None else self.home / q

    def config_payload(self) -> dict:
        c = self.cfg
        return {"values": _jsonable(values_from_config(c)),
                "provenance": {k: {"value": _jsonable(v.value), "source": v.source, "ref": v.ref}
                               for k, v in c.provenance.items()},
                "source_path": c.source_path, "yaml": to_yaml(c), "sha256": config_sha(c)}

    def build(self, values: dict) -> ArrayConfig:
        return values_to_config(_from_json(values), self.cfg)


def _jsonable(v):
    """JSON-safe copy: non-finite floats become the strings "-inf" / "inf" /
    "nan" (json.dumps(allow_nan=False) would otherwise refuse the whole
    payload -- a report with coupling.scale_db = -inf carries
    coupling_max_offdiag_db = -inf; the page shows a dash for them, and
    ``_from_json`` turns "-inf" back into the float for config leaves)."""
    if isinstance(v, float) and not math.isfinite(v):
        return "-inf" if v < 0 else ("inf" if v > 0 else "nan")
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return v


def _from_json(values: dict) -> dict:
    out = {}
    for k, v in values.items():
        if v == "-inf":
            v = float("-inf")
        out[k] = v
    return out


# ------------------------------------------------------------------- api
class Api:
    """The JSON API, independent of the transport: the HTTP handler and the
    Android bridge (``arraytx.appbridge``) both call ``get`` / ``post`` and
    get ``(status, payload)`` back.  Payloads always carry ``ok``."""
    GET_ROUTES = ("version", "spec", "config", "jobs")

    def __init__(self, state: State):
        self.state = state

    def get(self, route: str) -> tuple[int, dict]:
        st = self.state
        if route == "version":
            return 200, {"ok": True, "lib": "arraytx", "version": __version__, "python": sys.version.split()[0],
                        "pins": pins(), "workers": st.jobs.workers}
        elif route == "spec":
            return 200, {"ok": True, **spec()}
        elif route == "config":
            return 200, {"ok": True, **st.config_payload()}
        elif route == "jobs":
            return 200, {"ok": True, "jobs": st.jobs.listing()}
        elif route.startswith("jobs/"):
            jid, _, rest = route[5:].partition("/")
            rows_from = 0
            if rest:
                if not rest.startswith("rows/"):
                    return 404, {"ok": False, "error": f"no such route /api/{route}"}
                rows_from = max(0, int(rest[5:]))
            j = st.jobs.get(jid, rows_from)
            return 200 if j else 404, {"ok": True, "job": j} if j else {"ok": False, "error": "no such job"}
        else:
            return 404, {"ok": False, "error": f"no such route /api/{route}"}
    def post(self, route: str, req: dict) -> tuple[int, dict]:
        st = self.state
        if route == "config/load":
            st.cfg = load_config(st.path(req["path"]))
            return 200, {"ok": True, **st.config_payload()}
        elif route == "config/text":
            st.cfg = config_from_dict(yaml.safe_load(str(req.get("yaml", ""))) or {}, req.get("source_path"))
            return 200, {"ok": True, **st.config_payload()}
        elif route == "validate":
            cfg = st.build(req.get("values") or {})
            return 200, {"ok": True, "sha256": config_sha(cfg), "diff": _jsonable(diff(st.cfg, cfg)), "yaml": to_yaml(cfg),
                        "provenance": {k: {"source": v.source, "ref": v.ref} for k, v in cfg.provenance.items()}}
        elif route == "save":
            cfg = st.build(req.get("values") or {})
            p = st.path(req["path"])
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(to_yaml(cfg), encoding="utf-8")
            st.cfg = load_config(p)
            return 200, {"ok": True, **st.config_payload()}
        elif route == "run":
            cfg = st.build(req.get("values") or {})
            params = {"theta0_deg": None if req.get("theta0_deg") is None else float(req["theta0_deg"]),
                      "scheme": req.get("scheme") or cfg.dpd.scheme,
                      "n_symbols": None if req.get("n_symbols") in (None, "") else int(req["n_symbols"])}
            th = cfg.beam.scan_deg[0] if params["theta0_deg"] is None else params["theta0_deg"]
            job = st.jobs.submit("run", cfg, params, f"{th:+.0f}° · {params['scheme']} · {cfg.beam.steering}")
            return 200, {"ok": True, "job": job}
        elif route == "scan":
            cfg = st.build(req.get("values") or {})
            scan = [float(t) for t in (req.get("scan_deg") or cfg.beam.scan_deg)]
            schemes = list(req.get("schemes") or ("none", "per_element", "array"))
            params = {"scan_deg": scan, "schemes": schemes,
                      "n_symbols": None if req.get("n_symbols") in (None, "") else int(req["n_symbols"])}
            job = st.jobs.submit("scan", cfg, params, f"扫描 {len(scan)}×{len(schemes)} · {cfg.beam.steering}")
            return 200, {"ok": True, "job": job}
        elif route == "sweep":
            cfg = st.build(req.get("values") or {})
            path = str(req["path"])
            if path not in values_from_config(cfg):
                raise ValueError(f"sweep: {path!r} is not a config leaf")
            points = list(req.get("points") or [])
            if not points:
                raise ValueError("sweep: points is empty")
            gpath = req.get("group_path") or None
            gvals = list(req.get("group_values") or []) if gpath else []
            if gpath and (gpath not in values_from_config(cfg) or gpath == path):
                raise ValueError(f"sweep: group_path {gpath!r} is not a config leaf other than {path!r}")
            if gpath and not gvals:
                raise ValueError("sweep: group_values is empty")
            for gv in (gvals or [None]):           # every combination must build a valid config before anything runs
                for v in points:
                    flat = values_from_config(cfg)
                    if gpath:
                        flat[gpath] = gv
                    flat[path] = v
                    values_to_config(_from_json(flat), cfg)
            params = {"path": path, "points": points, "group_path": gpath, "group_values": gvals or None,
                      "theta0_deg": None if req.get("theta0_deg") is None else float(req["theta0_deg"]),
                      "scheme": req.get("scheme") or cfg.dpd.scheme,
                      "n_symbols": None if req.get("n_symbols") in (None, "") else int(req["n_symbols"])}
            label = f"研究 {path.split('.')[-1]} × {len(points)}" + (f" ⊗ {gpath.split('.')[-1]} × {len(gvals)}" if gpath else "") + f" · {params['scheme']}"
            job = st.jobs.submit("sweep", cfg, params, label)
            return 200, {"ok": True, "job": job}
        elif route == "rule":
            # ex19 Part 1 on the page: scan_deg x element.pa.backoff_db, then the least backoff meeting the
            # targets per angle against the mean |1 + Gamma| there. Targets: design choices, source assumed.
            cfg = st.build(req.get("values") or {})
            scan = [float(t) for t in (req.get("scan_deg") or cfg.beam.scan_deg)]
            bos = [float(b) for b in (req.get("backoffs") or [0, 1, 2, 3])]
            if any(b < 0 for b in bos):
                raise ValueError("rule: backoffs must be >= 0 dB")
            params = {"scan_deg": scan, "backoffs": bos, "scheme": req.get("scheme") or "per_element",
                      "aclr_target_dbc": float(req.get("aclr_target_dbc", -45.0)), "evm_target_db": float(req.get("evm_target_db", -25.0)),
                      "margin_db": float(req.get("margin_db", 0.0)),
                      "n_symbols": None if req.get("n_symbols") in (None, "") else int(req["n_symbols"])}
            job = st.jobs.submit("rule", cfg, params, f"回退规则 {len(scan)}×{len(bos)} · {params['scheme']}")
            return 200, {"ok": True, "job": job}
        elif route.startswith("jobs/") and route.endswith("/cancel"):
            ok = st.jobs.cancel(route[5:-7])
            return 200, {"ok": ok, **({} if ok else {"error": "not cancellable"})}
        else:
            return 404, {"ok": False, "error": f"no such route /api/{route}"}
    def call(self, route: str, req: dict | None = None) -> tuple[int, dict]:
        """GET when the route is a GET route (and ``jobs/<id>``), else POST;
        errors come back in-band as the handler would send them."""
        is_get = route in self.GET_ROUTES or (route.startswith("jobs/") and not route.endswith("/cancel"))
        try:
            return self.get(route) if is_get else self.post(route, req or {})
        except (ValueError, TypeError, KeyError, OSError) as exc:
            return 400, {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        except Exception as exc:                        # noqa: BLE001
            return 500, {"ok": False, "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()}


# --------------------------------------------------------------- handler
class _Handler(BaseHTTPRequestHandler):
    server_version = "arraytx-webhost"

    def log_message(self, fmt, *args):      # quiet: this is a desktop app
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj: Any, code: int = 200) -> None:
        self._send(code, dumps(obj).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):                                   # noqa: N802
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/"):
            try:
                code, obj = self.server.api.get(path[5:])        # type: ignore[attr-defined]
                body = dumps(obj)
            except Exception as exc:                    # noqa: BLE001
                code, body = 500, dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            self._send(code, body.encode("utf-8"), "application/json; charset=utf-8")
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
            self._json({"ok": False, "error": f"missing {POST_HEADER} header"}, 403)
            return
        n = int(self.headers.get("Content-Length") or 0)
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
        except ValueError as exc:
            self._json({"ok": False, "error": f"bad request: {exc}"}, 400)
            return
        try:
            code, obj = self.server.api.post(path[5:], req)      # type: ignore[attr-defined]
        except (ValueError, TypeError, KeyError, OSError) as exc:
            code, obj = 400, {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        except Exception as exc:                        # noqa: BLE001
            code, obj = 500, {"ok": False, "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()}
        self._json(obj, code)

def _default(o):
    if hasattr(o, "item"):
        return _jsonable(o.item())
    raise TypeError(f"not JSON: {type(o).__name__}")


def dumps(obj: Any) -> str:
    """The one JSON encoder of both transports (HTTP handler, Android
    bridge): numpy scalars unwrapped, non-finite floats as strings."""
    return json.dumps(_jsonable(obj), ensure_ascii=False, allow_nan=False, default=_default)


class _Server(ThreadingHTTPServer):
    allow_reuse_address = sys.platform != "win32"
    daemon_threads = True
    state: State
    api: Api

    def handle_error(self, request, client_address):
        """A client that hangs up mid-request (the app window closing while a
        poll is in flight) is not a server error; everything else prints."""
        if isinstance(sys.exc_info()[1], ConnectionError):
            return
        super().handle_error(request, client_address)


def make_server(port: int = 0, host: str = "127.0.0.1", cfg: ArrayConfig | None = None,
                workers: int = 2) -> ThreadingHTTPServer:
    """A server bound to ``host:port`` (0 picks a free port).  Not started."""
    srv = _Server((host, port), _Handler)
    srv.state = State(cfg if cfg is not None else default_config(), workers)
    srv.api = Api(srv.state)
    return srv


# -------------------------------------------------------------- launcher
_BROWSER_NAMES = ("msedge", "microsoft-edge", "microsoft-edge-stable", "google-chrome", "google-chrome-stable",
                  "chrome", "chromium", "chromium-browser", "brave-browser")


def find_app_browser() -> str | None:
    """A browser that can open a chromeless ``--app`` window, or None
    (``ARRAYTX_BROWSER`` overrides)."""
    env = os.environ.get("ARRAYTX_BROWSER")
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


def _profile_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME")
    return Path(base or Path.home() / ".cache", "arraytx", "app-window")


def app_window_command(browser: str, url: str, profile: Path) -> list[str]:
    return [browser, f"--app={url}", f"--user-data-dir={profile}", "--no-first-run",
            "--no-default-browser-check", "--window-size=1440,920"]


HANDOFF_S = 3.0


def _stop_with_window(srv: Any, proc: Any, handoff_s: float | None = None) -> bool:
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
            return subprocess.Popen(app_window_command(browser, url, _profile_dir()),
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            print(f"could not start {browser} ({exc}); opening a browser tab")
    webbrowser.open(url)
    return None


def _is_arraytx(url: str) -> bool:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url + "api/version", timeout=3) as r:
            return json.loads(r.read()).get("lib") == "arraytx"
    except (OSError, ValueError):
        return False


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="arraytx-gui", description="array_tx workbench (one page, served locally)")
    ap.add_argument("--config", default=None, help="YAML to load at start (default: the built-in defaults)")
    ap.add_argument("--port", type=int, default=8766, help="local port (default 8766; 0 picks a free one)")
    ap.add_argument("--workers", type=int, default=2, help="runs in flight at once (default 2)")
    ap.add_argument("--tab", action="store_true", help="open a normal browser tab instead of an app window")
    ap.add_argument("--no-browser", action="store_true", help="serve only (ARRAYTX_NO_BROWSER=1 does the same)")
    a = ap.parse_args(argv)
    no_browser = a.no_browser or bool(os.environ.get("ARRAYTX_NO_BROWSER"))
    cfg = load_config(a.config) if a.config else default_config()
    try:
        srv = make_server(a.port, cfg=cfg, workers=a.workers)
    except OSError as exc:
        url = f"http://127.0.0.1:{a.port}/"
        if not _is_arraytx(url):
            raise SystemExit(f"port {a.port} is in use ({exc}); try --port 0") from exc
        print(f"arraytx is already running at {url}")
        if not no_browser:
            _open_window(url, a.tab)
        return
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    proc = None if no_browser else _open_window(url, a.tab)
    if proc is not None:
        print(f"array_tx workbench at {url}  (close its window to stop)")
        threading.Thread(target=_stop_with_window, args=(srv, proc), daemon=True).start()
    else:
        print(f"array_tx workbench at {url}  (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
