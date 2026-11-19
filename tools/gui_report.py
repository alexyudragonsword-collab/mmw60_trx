"""The interface's reports from the command line (the page reads the same dicts: ``mmw60.guiutil``).

    python tools/gui_report.py system                                   # the block diagram's facts
    python tools/gui_report.py form --set frontend.pa.obo_db=9.5        # the 22 knobs, tags, what reads what
    python tools/gui_report.py freshness --set rx.cpe_window_symbols=33 # which parts a study makes stale
    python tools/gui_report.py table --no-time-domain --json table.json # the comparison table, analytic columns
    python tools/gui_report.py table --row "be_upclocked 11ac 20M K=32 @60.48 GHz" --no-time-domain
    python tools/gui_report.py calibration --json cal.json              # wifitrx's sequence, six columns (minutes)
    python tools/gui_report.py array --json array.json                  # example 10's numbers (about ten minutes)
    python tools/gui_report.py ay --json ay.json                        # example 15's numbers (about four minutes)
    python tools/gui_report.py sources

``--set knob=value`` (repeatable) is the study: shared form knobs that differ from the presets.  A
table, calibration, array or ay run is written as a job result (the report with its study and provenance), the
form a host would store; ``freshness --results a.json b.json`` judges stored results against a study.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from mmw60 import ENGINE_BANNER, guiutil  # noqa: E402


def parse_study(pairs) -> dict:
    values = {}
    for item in pairs or []:
        key, sep, v = item.partition("=")
        if not sep:
            raise SystemExit(f"--set wants knob=value, got {item!r}")
        values[key] = v
    return guiutil.study(values)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("what", choices=("system", "form", "freshness", "table", "calibration", "array", "ay", "sources",
                                     "parts"))
    ap.add_argument("--set", action="append", metavar="KNOB=VALUE", help="a shared form knob (repeatable)")
    ap.add_argument("--json", type=Path, help="write the JSON here (default: stdout)")
    ap.add_argument("--no-time-domain", action="store_true", help="table: analytic columns only")
    ap.add_argument("--quick", action="store_true", help="table / calibration / array / ay: the smoke-size run")
    ap.add_argument("--row", action="append", help="table: only this row (repeatable)")
    ap.add_argument("--irr-from", type=Path, help="table: a calibration job result to build on (if it is this study's)")
    ap.add_argument("--results", type=Path, nargs="*", default=[], help="freshness: stored job results")
    a = ap.parse_args(argv)
    st = parse_study(a.set)
    t0 = time.time()
    if a.what == "system":
        out = guiutil.system_report(st)
    elif a.what == "form":
        out = guiutil.form(st)
    elif a.what == "sources":
        out = guiutil.sources()
    elif a.what == "parts":
        out = guiutil.freshness_matrix()
    elif a.what == "freshness":
        env = {}
        for path in a.results:
            env.update(guiutil.envelopes_of(json.loads(path.read_text(encoding="utf-8"))))
        fresh = guiutil.freshness(st, env)
        out = {"study": st, "parts": fresh, "fields": guiutil.field_states(fresh)}
    elif a.what == "table" and a.row:
        rep = guiutil.table_report(st, time_domain=not a.no_time_domain, quick=a.quick, labels=a.row)
        out = guiutil.job_result("table_analytic" if a.no_time_domain else "table", st, rep, time.time() - t0,
                                 ["table.analytic"] if a.no_time_domain else None)
    else:
        job = {"table": "table_analytic" if a.no_time_domain else "table", "calibration": "calibration_be"}.get(
            a.what, a.what)
        cal = json.loads(a.irr_from.read_text(encoding="utf-8")) if a.irr_from else None
        out = guiutil.run_job(job, st, quick=a.quick, calibration=cal,
                              log=lambda s: print(s, file=sys.stderr, flush=True))
    text = json.dumps(out, ensure_ascii=False, indent=1, allow_nan=False)
    if a.json:
        a.json.write_text(text + "\n", encoding="utf-8")
        print(ENGINE_BANNER)
        print(f"wrote {a.json} ({len(text)} bytes, {time.time() - t0:.1f} s)")
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
