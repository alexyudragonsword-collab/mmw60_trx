# Vendored from array_tx@5815c5a7ea43143fd58502d4894ac840b5b5fb86: src/arraytx/appbridge.py
# Adapted-copy policy: see src/mmw60/vendor/__init__.py
"""The single entry point the Android app calls: ``call(route, args_json)
-> json``.

Same page, third host.  The WebView injects ``window.host`` and app.js's
``api()`` sends every request here instead of to the local server; the
routes and payloads are exactly those of ``webhost.Api`` (one dispatch, two
transports), so ``tests/test_appbridge.py`` exercises the phone's whole
surface on a laptop in seconds and the page needs one code path.

What differs on the phone, and why:

* jobs run on threads (``JobQueue(backend="thread")``): Chaquopy has no
  multiprocessing, so a cancel is cooperative between rows and a single
  long run finishes before it stops;
* one worker: a phone has the cores but not the memory for two 64-element
  bursts at once;
* ``config/load`` and ``save`` take paths under the app's own files
  directory (``ARRAYTX_HOME``, set by the activity); the page's prompts
  are plain text fields there.

Kotlin stays inert: a feature is a Python function behind ``Api`` plus a
render in app.js, never a change to the activity.
"""
from __future__ import annotations

import json
import os
import traceback
from pathlib import Path

from .config import default_config
from .webhost import Api, State, dumps

_API: Api | None = None


def _api() -> Api:
    global _API
    if _API is None:
        home = os.environ.get("ARRAYTX_HOME")
        if home:
            Path(home).mkdir(parents=True, exist_ok=True)
        _API = Api(State(default_config(), workers=1, backend="thread", home=home))
    return _API


def call(route: str, args_json: str = "{}") -> str:
    """``route`` as the page names it (``spec``, ``run``, ``jobs/3/cancel``);
    ``args_json`` the request body.  Never raises: a bad route, bad JSON or
    a bug in the library come back as ``{"ok": false, "error": ...}``."""
    try:
        req = json.loads(args_json or "{}")
        if not isinstance(req, dict):
            raise ValueError("args must be a JSON object")
        _, obj = _api().call(str(route), req)
    except Exception as exc:                            # noqa: BLE001 (in-band error)
        obj = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()}
    return dumps(obj)


def reset() -> None:
    """Forget the state (tests)."""
    global _API
    _API = None
