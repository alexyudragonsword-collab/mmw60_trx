"""Does this machine give the shipped numbers?

One check, three callers: the phone bridge (``appbridge.self_check``, asserted by the emulator
tests), a shell (``python -m mmw60.appbridge``) and a host's queue (the page's self-check button:
``webhost`` runs it as a job and keeps the outcome).

It reads the four shipped reports the way a page does (``ask``: a function ``route, body -> dict``,
the host's own dispatch), recomputes the analytic columns of the comparison table on this machine
and compares them, number by number, with the shipped baseline (``guiutil.analytic_agreement``).
It also says how long that job took here against the duration the job list quotes, which was
measured on a 4-core desktop with numba: the one honest hint a page has about this machine's speed.
"""
from __future__ import annotations

import platform
import sys
import time

from . import guistore, guiutil

#: how far a recomputed analytic table may sit from the shipped one (``analytic_agreement``'s scaled
#: difference).  Measured 3.6e-15 at worst over 777 numbers (683 identical) between Python 3.10 +
#: numpy 1.23.3 + scipy 1.8.1 and the baseline's own Python 3.13 + numpy 2.5 + scipy 1.18, and the
#: same 3.6e-15 on an Android emulator (570 identical); the bound leaves room for another libm and
#: is still far below any digit a page shows.
TOL = 1e-9
#: the job it reruns, and the progress steps it reports
JOB = "table_analytic"
NAME = "selfcheck"
STEPS = 3


def stack() -> dict:
    import numpy
    import scipy
    return {"python": platform.python_version(), "numpy": numpy.__version__, "scipy": scipy.__version__,
            "machine": platform.machine(), "system": platform.system(),
            "matplotlib_imported": "matplotlib" in sys.modules, "numba_imported": "numba" in sys.modules}


def run(ask=None, progress=None) -> dict:
    """The outcome: ``ok``, ``stack``, ``checks`` (name, zh, ok, detail), ``speed`` (the analytic
    table's seconds here, the quoted reference, their ratio), ``seconds``, ``at`` and a one-line
    ``summary``.  Never raises: a check that throws is a failed check."""
    t0 = time.time()
    checks = []
    fresh: dict = {}

    def check(name, zh, fn):
        try:
            ok, detail = fn()
        except Exception as exc:                        # noqa: BLE001 (a failed check, reported in-band)
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        checks.append({"name": name, "zh": zh, "ok": bool(ok), "detail": detail})
        if progress:
            progress(len(checks), STEPS, name)

    def reports():
        got = {}
        for name in guistore.REPORT_PART:
            j = ask("report", {"report": name, "study": {}})
            got[name] = bool(j.get("ok")) and j.get("report") is not None and j["result"]["origin"] == "baseline"
            fresh.update({part: f["state"] for part, f in j.get("freshness", {}).get("parts", {}).items()})
        return all(got.values()), got

    def state():
        return bool(fresh) and set(fresh.values()) == {"fresh"}, dict(fresh)

    speed: dict = {}

    def analytic():
        ref = guistore.load_baseline()["table"]["report"]
        res = guiutil.run_job(JOB, {})
        a = guiutil.analytic_agreement(res["report"], ref)
        a["tolerance"], a["job_seconds"] = TOL, res["seconds"]
        a["mismatches"] = a["mismatches"][:10]
        quoted = guiutil.JOBS[JOB]["seconds"][0]
        speed.update(job=JOB, seconds_here=res["seconds"], seconds_reference=quoted,
                     ratio=res["seconds"] / quoted, reference_note=guiutil.JOBS[JOB]["seconds_note"])
        return a["rows"] == len(ref["rows"]) and not a["mismatches"] and a["worst_scaled"] <= TOL, a

    if ask is not None:
        check("the four shipped reports answer through the page's route", "四份随包报告经页面用的路由读得出来", reports)
        check("every part is fresh on the presets", "预设下每个部分都是新鲜的", state)
    check("the analytic table recomputed here agrees with the shipped one", "本机重算的解析列与随包的一致", analytic)
    st = stack()
    ok = all(c["ok"] for c in checks)
    last = checks[-1]["detail"]
    agree = (f"{last['numbers']} numbers, {last['identical']} identical, worst {last['worst_scaled']:.1e}"
             if isinstance(last, dict) else str(last))
    seconds = time.time() - t0
    summary = (f"{'ok' if ok else 'FAILED'}: python {st['python']} numpy {st['numpy']} scipy {st['scipy']} "
               f"{st['machine']}; {agree}; {seconds:.0f} s"
               + "".join(f"; FAILED {c['name']}: {str(c['detail'])[:300]}" for c in checks if not c["ok"]))
    return {"ok": ok, "stack": st, "checks": checks, "speed": speed or None, "tolerance": TOL,
            "seconds": seconds, "at": time.time(), "summary": summary}
