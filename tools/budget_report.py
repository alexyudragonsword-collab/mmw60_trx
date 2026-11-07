"""The comparison table (同台表) and its budget as a Markdown (or JSON) report.

    python tools/budget_report.py                              # 11ac 20 MHz, K = 1 / 4 / 8 / 16 / 32
    python tools/budget_report.py --base 11be:80e6 --k 4,8,16,32 -o table.md
    python tools/budget_report.py --json table.json --no-time-domain
    python tools/budget_report.py --sensitivity

Adapted from d2d_link tools/budget_report.py (the command line over a
``report`` module; the GUI, when there is one, renders the same dicts).
Everything comes from the config presets and one ``Frontend60`` instance
(iron rules 1 and 2): per scheme the numerology after upclocking, the CFO
and whether the L-STF catches it, the analytic EVM floor with its terms,
the time-domain EVM of the same cell on the wifitrx chain, wifitrx's
``EvmBudget`` on the same terms, the MCS cap (uncalibrated / at the IRR
example 03 measured), the rate and spectral efficiency at the cap, the PA
operating point against the shared EIRP ceiling, and the power blocks per
bit.  Every ``(topology, waveform)`` pair is listed; the unbuilt ones say
which milestone brings them.  ``--sensitivity`` reruns the analytic side at
every coefficient's range ends and lists what moves (d2d's "which guesses
decide the verdict").
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from mmw60 import compare                                   # noqa: E402
from mmw60.config import zero_if_60ghz                      # noqa: E402
from mmw60.frontend import Frontend60                       # noqa: E402


def parse_base(text: str) -> tuple[str, float]:
    std, bw = text.split(":")
    return std, float(bw)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", action="append", default=None, help="standard:bandwidth, e.g. 11ac:20e6 (repeatable)")
    ap.add_argument("--k", default="1,4,8,16,32", help="comma-separated upclocking factors")
    ap.add_argument("--carrier", type=float, default=60.48e9)
    ap.add_argument("--k1-carrier", type=float, default=6.0e9, help="carrier of the WiFi 7 chain row")
    ap.add_argument("-o", "--out", type=Path, help="Markdown file (default: stdout)")
    ap.add_argument("--json", type=Path, help="also write the report as JSON")
    ap.add_argument("--no-time-domain", action="store_true", help="analytic side only (seconds instead of minutes)")
    ap.add_argument("--sensitivity", action="store_true", help="also rerun at every coefficient's range ends")
    args = ap.parse_args(argv)
    bases = [parse_base(b) for b in (args.base or ["11ac:20e6"])]
    ks = tuple(int(k) for k in args.k.split(","))
    schemes = []
    for i, (std, bw) in enumerate(bases):
        m = compare.scheme_matrix(ks=ks, standard=std, bandwidth_hz=bw, carrier_hz=args.carrier,
                                  k1_carrier_hz=args.k1_carrier)
        schemes += m if i == 0 else [s for s in m if s.status == "built"]
    fe = Frontend60.from_config(zero_if_60ghz(k=ks[0], carrier_hz=args.carrier))
    rep = compare.build(schemes, fe, time_domain=not args.no_time_domain)
    if args.sensitivity:
        rep["sensitivity"] = compare.sensitivity(schemes, fe)
    md = compare.to_markdown(rep)
    if args.out:
        args.out.write_text(md, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(md)
    if args.json:
        args.json.write_text(json.dumps(compare.report_json(rep), indent=1, default=str), encoding="utf-8")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
