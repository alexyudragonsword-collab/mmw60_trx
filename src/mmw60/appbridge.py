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

The app shell itself (``android/``: Gradle, the activity) is not built yet — ROADMAP F.  This
module and the thread backend are what it will call.  Kotlin stays inert: a feature is a Python
function behind ``Api`` plus a render in the page, never a change to the activity.
"""
from __future__ import annotations

import json
import os
import traceback

from .webhost import Api, State, dumps

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


def reset() -> None:
    """Forget the state (tests)."""
    global _API
    _API = None
