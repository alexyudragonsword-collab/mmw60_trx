"""The single entry point a phone app calls: ``call(route, args_json) -> json``.

Same page, third host.  A WebView injects ``window.host`` and the page's ``api()`` sends every
request here instead of to the local server; routes and payloads are exactly those of
``webhost.Api`` (one dispatch, two transports), so ``tests/test_appbridge.py`` exercises the
phone's whole surface on a laptop.

What differs on a phone, and why:

* jobs run on threads (``JobQueue(backend="thread")``): Chaquopy has no multiprocessing, so a
  cancel is cooperative between progress steps and a step in flight finishes before it stops;
* one worker;
* recomputed results are kept under the app's own files directory (``MMW60_HOME``, set by the
  activity); without it they live in memory only.

The app shell is ``android/`` (Gradle, one activity).  Kotlin stays inert: a feature is a Python
function behind ``Api`` plus a render in the page, never a change to the activity.

``self_check()`` is what says the machine this runs on computes the same numbers: it reads the four
shipped reports through the very routes the page uses, recomputes the analytic columns of the
comparison table and compares them with the shipped baseline (``guiutil.analytic_agreement``).  The
emulator job of ``.github/workflows/android.yml`` asserts its verdict, and CI runs it on the numpy /
scipy versions the app is built with (``android/phone-stack.txt``).
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback

from . import guiutil, selfcheck
from .webhost import Api, State, dumps

#: the bound of the self-check (``selfcheck.TOL``), kept here for the callers that name it
SELF_CHECK_TOL = selfcheck.TOL

_API: Api | None = None


def _api() -> Api:
    global _API
    if _API is None:
        _API = Api(State(workers=1, backend="thread", home=os.environ.get("MMW60_HOME") or None))
    return _API


def call(route: str, args_json: str = "{}") -> str:
    """``route`` as the page names it (``state``, ``run``, ``jobs/3/cancel``); ``args_json`` the
    request body.  Never raises: a bad route, bad JSON or a bug in the library come back as
    ``{"ok": false, "error": ...}``."""
    try:
        req = json.loads(args_json or "{}")
        if not isinstance(req, dict):
            raise ValueError("args must be a JSON object")
        _, obj = _api().call(str(route), req)
        return dumps(obj)
    except Exception as exc:                            # noqa: BLE001 (in-band error)
        return json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()})


def self_check() -> str:
    """Does this machine give the shipped numbers?  ``selfcheck.run`` through this bridge's own
    dispatch, as JSON: ``ok``, ``stack``, ``checks``, ``speed``, ``seconds`` and a one-line
    ``summary``.  Never raises."""
    return json.dumps(selfcheck.run(lambda route, body: json.loads(call(route, json.dumps(body)))))


def reset() -> None:
    """Forget the state (tests)."""
    global _API
    _API = None


def main(argv: list[str] | None = None) -> int:
    """``python -m mmw60.appbridge [--jobs]``: does this machine give the shipped numbers?  Prints
    the self-check's checks and its summary; with ``--jobs`` also runs every job a host can queue at
    smoke size, to say that each one runs here at all.  Exit status 0 when everything holds."""
    import argparse
    ap = argparse.ArgumentParser(prog="python -m mmw60.appbridge", description=main.__doc__)
    ap.add_argument("--jobs", action="store_true", help="also run every queueable job at smoke size")
    args = ap.parse_args(argv)
    print(guiutil.ENGINE_BANNER)
    out = json.loads(self_check())
    for c in out["checks"]:
        print(f"  {'ok    ' if c['ok'] else 'FAILED'} {c['name']}")
    print(out["summary"])
    ok = out["ok"]
    if args.jobs:
        from .webhost import RUNNABLE
        for job in RUNNABLE:
            t0 = time.time()
            try:
                res = guiutil.run_job(job, {}, quick=True)
                print(f"  ok     job {job} at smoke size: parts {', '.join(res['parts'])}; {time.time() - t0:.0f} s",
                      flush=True)
            except Exception as exc:                    # noqa: BLE001 (reported, then the exit status)
                ok = False
                print(f"  FAILED job {job}: {type(exc).__name__}: {exc}", flush=True)
        print("matplotlib imported:", "matplotlib" in sys.modules, "| numba imported:", "numba" in sys.modules)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
