"""Example 14 — Liu 2025's ideal 16-QAM threshold: which channel or receiver choice costs only MCS4?

What is left of the external check (ROADMAP C12, cairn/external-validation.md
§3–§4): on the paper's "ideal" set (phase noise and PA off, CFO and its
estimators kept) its MCS4 needs 19.7 / 19.0 dB (8x / 16x) for PER 1e-2, 3–4 dB
more than this library's flat ideal chain, while its MCS0 / 1 need 4.2 / 7.5 dB,
about 0.7 dB *less*.  Examples 00 / 12 / 13 ruled out the PA, the CFO and its
estimators, and the channel's K-factor with all impairments on.  This
measures, on the ideal chain, the candidates that could charge 16-QAM 3/4 and
not BPSK / QPSK 1/2, one at a time, and then the one combination the single
rows point to.  Nothing here changes a preset or tunes a parameter (AGENTS: no
tuning to match); every row is a named receiver or channel choice.

1. K = 8, MCS 0 / 1 / 4, against the flat ideal chain with the milestone-0
   receiver: the conference-room stand-in at LOS K 10 (the preset) / 6 / 3 dB;
   no channel-estimate smoothing; a single-LTF estimate without smoothing;
   LLRs not weighted by the channel (flat and LOS 10 dB); hard decisions into
   the Viterbi decoder.  "sel" = Δ(MCS4) − mean Δ(MCS0, MCS1): what the paper
   needs is the last line;
2. K = 8 and 16: the reference, hard decisions, the improved receiver of
   findings C1 / C2 (cross-symbol pilot phase, automatic smoothing span), and
   the improved receiver with hard decisions, against the paper's ideal set.

    python examples/14_liu2025_ideal_receiver_candidates.py [--quick] [--jobs N] [--cache DIR]
"""
from __future__ import annotations

import argparse
import dataclasses as dc
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from mmw60 import ENGINE_BANNER, __version__, spec                         # noqa: E402
from mmw60.config import ChannelConfig, improved_rx, liu2025_table2        # noqa: E402
from mmw60.sim.curves import CurveSpec, ci_text, run_curves, sweep_line    # noqa: E402

TARGET = 1e-2
REFINE_ERRORS, REFINE_MAX_PACKETS = 60, 3000
GRIDS = {0: [-1 + x * 0.5 for x in range(0, 31)],      # −1 .. 14 dB
         1: [2 + x * 0.5 for x in range(0, 31)],       # 2 .. 17 dB
         4: [11 + x * 1.0 for x in range(0, 20)]}      # 11 .. 30 dB
MCSS = (0, 1, 4)


def ideal_cfo(k: int, mcs: int):
    """The paper's "ideal" set on a flat channel: phase noise and PA off, the
    crystals' CFO and the L-STF / L-LTF estimators kept."""
    cfg = liu2025_table2(k=k, mcs=mcs)
    i = cfg.ideal()
    return dc.replace(i, xo_ppm_tx=cfg.xo_ppm_tx, xo_ppm_rx=cfg.xo_ppm_rx, channel=ChannelConfig(model="flat"))


def los(cfg, k_db):
    """The preset conference-room stand-in (7 ns rms, one realisation per packet) at LOS K ``k_db``."""
    preset = liu2025_table2(k=8, mcs=0).channel
    return dc.replace(cfg, channel=dc.replace(preset, los_k_db=float(k_db)))


def rx(cfg, **kw):
    return dc.replace(cfg, rx=dc.replace(cfg.rx, **kw))


def better(cfg):
    return dc.replace(cfg, rx=improved_rx(cfg.rx))


#: section 1: (label, transform of the flat ideal+CFO config)
CANDIDATES = (
    ("flat, milestone-0 receiver (ref)", lambda c: c),
    ("LOS 10 dB (the preset channel)", lambda c: los(c, 10.0)),
    ("LOS 6 dB", lambda c: los(c, 6.0)),
    ("LOS 3 dB", lambda c: los(c, 3.0)),
    ("no CE smoothing", lambda c: rx(c, ce_smooth_tones=1)),
    ("single L-LTF, no smoothing", lambda c: rx(c, ce_smooth_tones=1, ce_ltf_symbols=1)),
    ("LLR not channel-weighted", lambda c: rx(c, llr_channel_weighting=False)),
    ("LOS 10 dB, LLR not weighted", lambda c: rx(los(c, 10.0), llr_channel_weighting=False)),
    ("hard decisions", lambda c: rx(c, hard_decision=True)),
)
#: section 2: (label, transform), at K = 8 and 16
COMBOS = (
    ("milestone-0 receiver (ref)", lambda c: c),
    ("hard decisions", lambda c: rx(c, hard_decision=True)),
    ("improved receiver (C1/C2)", better),
    ("improved receiver + hard", lambda c: rx(better(c), hard_decision=True)),
)


def paper_ideal() -> dict:
    """{(k, mcs): SNR at PER 1e-2} of the paper's ideal set (liu2025_fig4.yaml)."""
    return {(c["k"], c["mcs"]): c["per_at_1e-2_snr_db"] for c in spec.fig4_readings()["curves"]
            if c["set"] == "ideal" and c.get("per_at_1e-2_snr_db") is not None}


def fmt(v, w=6):
    return f"{'never':>{w}}" if v is None else f"{v:{w}.2f}"


def delta(a, b):
    return None if a is None or b is None else a - b


def sel(d):
    return None if any(x is None for x in d) else d[2] - 0.5 * (d[0] + d[1])


def main(argv=None) -> int:
    print(ENGINE_BANNER)
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--jobs", type=int, default=max(1, min(4, os.cpu_count() or 1)))
    ap.add_argument("--cache", type=Path, default=None, help="keep finished curves here (resumable)")
    a = ap.parse_args(argv)
    quick = a.quick or os.environ.get("MMW60_SMOKE") == "1"
    t0 = time.time()
    mp, me = (6, 2) if quick else (600, 30)
    rf = {} if quick else {"refine_errors": REFINE_ERRORS, "refine_max_packets": REFINE_MAX_PACKETS}
    paper = paper_ideal()
    print(f"mmw60 {__version__}; {'QUICK (numbers meaningless)' if quick else 'full size'}; the paper's ideal "
          f"set (PN and PA off, CFO {ideal_cfo(8, 0).cfo_hz / 1e6:.2f} MHz and the L-STF / L-LTF estimators kept), "
          f"flat channel unless a row says otherwise; up to {mp} packets or {me} errors per point"
          + ("" if quick else f", the two points around 1e-2 run on to {REFINE_ERRORS} errors or "
             f"{REFINE_MAX_PACKETS} packets") + "; brackets: 95 % bootstrap interval of the crossing")

    def grid(mcs):
        return GRIDS[mcs][::8] if quick else GRIDS[mcs]

    # ---------------------------------------------------------------- 1. one candidate at a time
    cands = CANDIDATES[:2] + CANDIDATES[-1:] if quick else CANDIDATES
    specs = [CurveSpec(f"K=8 MCS{m} {name}", f(ideal_cfo(8, m)), grid(m), mp, me, tags={"row": name, "mcs": m}, **rf)
             for name, f in cands for m in MCSS]
    res = run_curves(specs, TARGET, a.jobs, log=lambda s: None, cache_dir=a.cache)
    by = {(r["tags"]["row"], r["tags"]["mcs"]): r for r in res}
    print("\n== 1. one candidate at a time, K = 8 (SNR at PER 1e-2 [dB]; Δ against the reference row) ==")
    for r in res:
        print(sweep_line(r))
    ref = [by[(cands[0][0], m)]["snr_at_target"] for m in MCSS]
    print(f"\n{'row':<34} " + " ".join(f"{'MCS' + str(m):>8} {'Δ':>6}" for m in MCSS) + f" {'sel':>6}")
    for name, _ in cands:
        v = [by[(name, m)]["snr_at_target"] for m in MCSS]
        d = [delta(x, y) for x, y in zip(v, ref)]
        print(f"{name:<34} " + " ".join(f"{fmt(x, 8)} {fmt(y)}" for x, y in zip(v, d)) + f" {fmt(sel(d))}")
    pv = [paper.get((8, m)) for m in MCSS]
    pd = [delta(x, y) for x, y in zip(pv, ref)]
    print(f"{'the paper (ideal, 8x)':<34} " + " ".join(f"{fmt(x, 8)} {fmt(y)}" for x, y in zip(pv, pd))
          + f" {fmt(sel(pd))}")
    print("intervals of section 1:")
    for name, _ in cands:
        print(f"  {name:<34} " + "  ".join(f"MCS{m} {ci_text(by[(name, m)])}" for m in MCSS))
    print("sel = Δ(MCS4) − mean Δ(MCS0, MCS1): how much more a row charges 16-QAM 3/4 than BPSK / QPSK 1/2; "
          "'never' = PER 1e-2 not reached on the grid")

    # ---------------------------------------------------------------- 2. the combination, against the paper
    combos = COMBOS[:1] + COMBOS[-1:] if quick else COMBOS
    ks = (8,) if quick else (8, 16)
    specs2 = [CurveSpec(f"K={k:<2} MCS{m} {name}", f(ideal_cfo(k, m)), grid(m), mp, me,
                        tags={"row": name, "k": k, "mcs": m}, **rf)
              for k in ks for name, f in combos for m in MCSS]
    res2 = run_curves(specs2, TARGET, a.jobs, log=lambda s: None, cache_dir=a.cache)
    by2 = {(r["tags"]["k"], r["tags"]["row"], r["tags"]["mcs"]): r for r in res2}
    print("\n== 2. receiver combinations against the paper's ideal set (SNR at PER 1e-2 [dB]; this − paper) ==")
    for r in res2:
        print(sweep_line(r))
    print(f"\n{'K':<3} {'row':<30} " + " ".join(f"{'MCS' + str(m):>8} {'−paper':>7}" for m in MCSS)
          + f" {'max |·|':>8}")
    for k in ks:
        for name, _ in combos:
            v = [by2[(k, name, m)]["snr_at_target"] for m in MCSS]
            d = [delta(x, paper.get((k, m))) for x, m in zip(v, MCSS)]
            worst = None if any(x is None for x in d) else max(abs(x) for x in d)
            print(f"{k:<3} {name:<30} " + " ".join(f"{fmt(x, 8)} {fmt(y, 7)}" for x, y in zip(v, d))
                  + f" {fmt(worst, 8)}")
        print(f"{k:<3} {'the paper (ideal)':<30} "
              + " ".join(f"{fmt(paper.get((k, m)), 8)} {'':>7}" for m in MCSS))
    print("intervals of section 2:")
    for k in ks:
        for name, _ in combos:
            print(f"  K={k:<2} {name:<30} " + "  ".join(f"MCS{m} {ci_text(by2[(k, name, m)])}" for m in MCSS))
    print(f"\n[{time.time() - t0:.0f}s]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
