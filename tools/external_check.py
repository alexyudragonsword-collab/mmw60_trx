"""External validation against Liu 2025 Fig. 4 (Halo_Serdes ``external_check`` method).

The reference is the paper's own PER–SNR figure, read off by hand into
``src/mmw60/data/spec/liu2025_fig4.yaml`` (source survey; ±0.3 dB reading
precision).  This tool takes the sweeps example 00 wrote (or re-runs the
impaired curves) and prints, per curve, our SNR at PER 1e-2, the paper's,
and the difference; the acceptance (< 1 dB, K = 4 at PER 1 everywhere) is
stated, not enforced by retuning — a miss is investigated and recorded in
cairn/LOG.md.

What is independent on the two sides: everything (the paper's simulator is
unknown; nothing is shared).  What is *not* known on the paper's side and
therefore assumed here (data/spec/survey.yaml, source assumed): the base
bandwidth, the SNR definition, which side carries the phase noise, the
Rapp parameters and the OBO reference, the conference-room channel.

    python tools/external_check.py                       # uses examples/output/00_sweeps.json
    python tools/external_check.py --run [--quick]       # re-runs the impaired curves first
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from mmw60 import ENGINE_BANNER, spec                                   # noqa: E402
from mmw60.config import liu2025_table2                                 # noqa: E402
from mmw60.sim.curves import CurveSpec, load_results, run_curves        # noqa: E402

SWEEPS = REPO / "examples" / "output" / "00_sweeps.json"
GRIDS = {0: [x * 0.5 for x in range(0, 17)], 1: [3 + x * 0.5 for x in range(0, 17)],
         4: [12 + x * 1.0 for x in range(0, 15)]}
TOLERANCE_DB = 1.0
READING_DB = 0.3            # reading precision of the Fig. 4 read-offs (liu2025_fig4.yaml)


def cases() -> list[CurveSpec]:
    out = []
    for c in spec.fig4_readings()["curves"]:
        cfg = liu2025_table2(k=c["k"], mcs=c["mcs"])
        out.append(CurveSpec(f"K={c['k']:<2} MCS{c['mcs']} impaired", cfg, GRIDS[c["mcs"]],
                             tags={"k": c["k"], "mcs": c["mcs"], "set": "impaired"}))
    return out


def compare(results: list[dict], which: str = "impaired") -> int:
    ref = spec.fig4_readings()
    target = float(ref["per_target"])
    ours = {(r["tags"]["k"], r["tags"]["mcs"]): r for r in results
            if r["tags"].get("set") == which}
    label = {"impaired": "Table II read literally (LOS/diffuse channel, OBO from Psat)",
             "flat": "same impairments on a flat channel",
             "flat_rx": "flat channel, improved receiver (ROADMAP C1 / C2)",
             "impaired_rx": "Table II read literally, improved receiver"}.get(which, which)
    print(f"\n== Liu 2025 Fig. 4 (arXiv v1) vs example 00 set '{which}': {label}; SNR at PER {target:g} ==")
    print(f"reference: {ref['cite']}")
    print("K   MCS   paper [dB]   ours [dB]   diff [dB]   diff interval    verdict")
    print(f"(diff interval = our 95 % bootstrap interval of the crossing, widened by the figure's ±{READING_DB:g} dB "
          "reading precision; a curve is OUTSIDE only if the whole interval is)")
    bad = undecided = 0
    for c in ref["curves"]:
        key = (c["k"], c["mcs"])
        r = ours.get(key)
        if r is None:
            print(f"{c['k']:<3} {c['mcs']:<5} {_f(c['per_at_1e-2_snr_db']):>10}   {'missing':>9}")
            bad += 1
            continue
        paper = c["per_at_1e-2_snr_db"]
        mine = r["snr_at_target"]
        if paper is None:
            per_min = min(r["sweep"]["per"]) if r["sweep"]["per"] else float("nan")
            ok = mine is None and per_min >= 0.999
            verdict = "PER = 1 everywhere, as in the paper" if ok else f"paper PER = 1; ours min PER {per_min:.3g}"
            print(f"{c['k']:<3} {c['mcs']:<5} {'PER=1':>10}   {_f(mine):>9}   {'':>9}   {verdict}")
            bad += 0 if ok else 1
            continue
        if mine is None:
            per_min = min(r["sweep"]["per"]) if r["sweep"]["per"] else float("nan")
            print(f"{c['k']:<3} {c['mcs']:<5} {paper:10.1f}   {'never':>9}   {'':>9}   "
                  f"ours never reaches {target:g} (min PER {per_min:.3g}) -> investigate (LOG)")
            bad += 1
            continue
        diff = mine - paper
        ci = r.get("ci") or {}
        lo, hi = ci.get("lo_db"), ci.get("hi_db")
        if lo is None:                       # sweeps written before the interval existed
            lo = hi = mine
        # the difference is known to the counting interval plus the figure's reading precision
        d_lo, d_hi = lo - paper - READING_DB, hi - paper + READING_DB
        if max(abs(d_lo), abs(d_hi)) < TOLERANCE_DB:
            verdict, is_bad = f"within {TOLERANCE_DB:g} dB", 0
        elif (d_lo >= TOLERANCE_DB) or (d_hi <= -TOLERANCE_DB):
            verdict, is_bad = f"OUTSIDE {TOLERANCE_DB:g} dB", 1
        else:
            verdict, is_bad = f"cannot tell from {TOLERANCE_DB:g} dB at this precision", 0
            undecided += 1
        print(f"{c['k']:<3} {c['mcs']:<5} {paper:10.1f}   {mine:9.2f}   {diff:+9.2f}   [{d_lo:+5.2f}, {d_hi:+5.2f}]   {verdict}")
        bad += is_bad
    n = len(ref["curves"])
    print(f"\n{n - bad - undecided} of {n} curves agree, {undecided} cannot be told from the tolerance at this "
          f"precision, {bad} to investigate")
    return 1 if bad else 0


def _f(v) -> str:
    return "never" if v is None else f"{v:.2f}"


def main(argv=None) -> int:
    print(ENGINE_BANNER)
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true", help="re-run the impaired curves")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--sweeps", type=Path, default=SWEEPS)
    a = ap.parse_args(argv)
    if a.run:
        cs = cases()
        if a.quick:
            for c in cs:
                c.snr_db, c.max_packets, c.min_errors = c.snr_db[::6], 6, 2
        results = run_curves(cs, 1e-2, a.jobs)
    else:
        if not a.sweeps.exists():
            print(f"{a.sweeps} not found: run examples/00_liu2025_per_vs_snr.py or pass --run",
                  file=sys.stderr)
            return 2
        results = load_results(a.sweeps)
    sets = [s for s in ("impaired", "flat", "flat_rx", "impaired_rx")
            if any(r["tags"].get("set") == s for r in results)]
    codes = [compare(results, s) for s in sets]
    return max(codes) if codes else 2


if __name__ == "__main__":
    raise SystemExit(main())
