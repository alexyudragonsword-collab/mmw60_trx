"""Example 12 — Liu 2025's MCS4 floor: which assumed input reproduces the published curves' shape?

The published Fig. 3 (cairn/external-validation.md §3–§4, ROADMAP C12) has
two features at once: the impaired MCS0 / MCS1 curves fall from PER 1 to
1e-2 within about 2 dB (4.7 / 8.1 dB at 8x), while the impaired MCS4 curves
never reach 1e-2 — they flatten at PER 0.105 (8x) / 0.053 (16x) by 31 dB;
even the paper's "ideal" MCS4 (no PN, no PA) needs 19–19.7 dB.  Every set of
example 00 reaches 1e-2 at MCS4.  The PA candidate is weak: the paper's PA
model reference (IEEE 802.15-06-0477, read 2026-11-15) gives no numbers and
defines the back-off as this library does (output, from Psat), and the PA
fits in its companion 15-06-0396 sit next to the TGad numbers used here.  So
this sweeps the one assumed input that can bend high-order curves without
flattening the low-order ones: the conference-room stand-in channel's LOS
K-factor (data/spec: assumed.cr_los_k_db), 7 ns rms throughout.  Nothing
here changes a preset or tunes a parameter (AGENTS: no tuning to match).

1. K = 8, MCS 0 / 1 / 4 with Table II's impairments on: flat, LOS 10 dB (the
   preset), 6, 3, 0 dB and pure Rayleigh — SNR at PER 1e-2, the steepness of
   the fall (SNR from PER 0.5 to 0.05) and PER at the end of the paper's axis;
2. on two fading channels, MCS4 with one impairment off at a time (ideal PA,
   PN off, everything off): is the floor the channel's or the hardware's?

    python examples/12_liu2025_channel_sensitivity.py [--quick] [--jobs N]
"""
from __future__ import annotations

import argparse
import dataclasses as dc
import os
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from mmw60 import ENGINE_BANNER, __version__, spec                # noqa: E402
from mmw60.config import ChannelConfig, liu2025_table2            # noqa: E402
from mmw60.sim.curves import CurveSpec, run_curves, sweep_line    # noqa: E402

TARGET = 1e-2
K = 8
GRIDS = {0: [float(x) for x in range(0, 15)],          # 0 .. 14 dB
         1: [float(x) for x in range(3, 18)],          # 3 .. 17 dB
         4: [float(x) for x in range(13, 32, 2)]}      # 13 .. 31 dB, the paper's axis end
CHANNELS = (("flat", None), ("LOS 10 dB (preset)", 10.0), ("LOS 6 dB", 6.0), ("LOS 3 dB", 3.0),
            ("LOS 0 dB", 0.0), ("Rayleigh", "rayleigh"))


def with_channel(cfg, k_db):
    if k_db is None:
        return dc.replace(cfg, channel=ChannelConfig(model="flat"))
    los = None if k_db == "rayleigh" else float(k_db)
    return dc.replace(cfg, channel=dc.replace(cfg.channel, model="tdl_exp", los_k_db=los))


def steepness_db(r: dict, hi: float = 0.5, lo: float = 0.05) -> float | None:
    """SNR from PER ``hi`` down to PER ``lo`` (log-PER interpolation); None if the curve does not span it."""
    s = np.asarray(r["sweep"]["snr_db"], dtype=float)
    p = np.asarray(r["sweep"]["per"], dtype=float)

    def cross(level):
        for i in range(1, s.size):
            if p[i - 1] >= level > p[i] and p[i] > 0:
                a, b = np.log10(p[i - 1]), np.log10(p[i])
                return s[i - 1] + (np.log10(level) - a) / (b - a) * (s[i] - s[i - 1])
        return None
    a, b = cross(hi), cross(lo)
    return None if a is None or b is None else float(b - a)


def fmt(v, f="{:.2f}"):
    return "never" if v is None else f.format(v)


def paper_curves(ref_set: str = "impaired") -> dict:
    """The paper's 8x curves of one set (liu2025_fig4.yaml, published Fig. 3), keyed by MCS, in the
    shape ``steepness_db`` reads."""
    out = {}
    for c in spec.fig4_readings()["curves"]:
        if c["set"] == ref_set and c["k"] == K:
            pts = c["points"]
            out[c["mcs"]] = {"snr_db": c["per_at_1e-2_snr_db"], "floor_per": c.get("floor_per"),
                             "sweep": {"snr_db": [x for x, _ in pts], "per": [y for _, y in pts]}}
    return out


def paper_text(c: dict) -> str:
    st = steepness_db(c)
    head = (f"floor: PER {c['floor_per']:g} at {c['sweep']['snr_db'][-1]:g} dB" if c["floor_per"] is not None
            else f"{c['snr_db']:g} dB")
    return head + ("" if st is None else f", 0.5->0.05 in {st:.2f} dB")


def main(argv=None) -> int:
    print(ENGINE_BANNER)
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--jobs", type=int, default=max(1, min(4, os.cpu_count() or 1)))
    a = ap.parse_args(argv)
    quick = a.quick or os.environ.get("MMW60_SMOKE") == "1"
    t0 = time.time()
    mp, me = (6, 2) if quick else (300, 20)
    chans = CHANNELS[1::4] if quick else CHANNELS
    mcss = (0, 4) if quick else (0, 1, 4)
    base = liu2025_table2(k=K, mcs=0)
    paper = paper_curves("impaired")
    print(f"mmw60 {__version__}; {'QUICK (numbers meaningless)' if quick else 'full size'}; Liu 2025 Table II at "
          f"K = {K}: PA {base.frontend.pa.model} OBO {base.frontend.pa.obo_db:g} dB from "
          f"{base.frontend.pa.obo_reference}, PN {base.lo.phase_noise.psd0_dbchz:g} dBc/Hz, CFO "
          f"{base.cfo_hz / 1e6:.2f} MHz with the L-STF / L-LTF estimators; channel rms "
          f"{spec.value('assumed.cr_rms_delay_ns'):g} ns, one realisation per packet; up to {mp} packets or "
          f"{me} errors per point")

    # ---------------------------------------------------------------- 1. the channel's LOS K-factor
    print(f"\n== 1. impaired curves against the channel's LOS K-factor (K = {K}) ==")
    specs = []
    for mcs in mcss:
        grid = GRIDS[mcs][::5] if quick else GRIDS[mcs]
        for name, k_db in chans:
            cfg = with_channel(liu2025_table2(k=K, mcs=mcs), k_db)
            specs.append(CurveSpec(f"MCS{mcs} {name}", cfg, grid, mp, me, tags={"mcs": mcs, "channel": name}))
    res = run_curves(specs, TARGET, a.jobs, log=lambda s: None)
    for r in res:
        print(sweep_line(r))
    print(f"\n{'MCS':<4} {'channel':<20} {'SNR@1e-2':>9} {'0.5->0.05 [dB]':>15} {'PER at axis end':>16}   "
          "paper (impaired, 8x)")
    for r in res:
        mcs = r["tags"]["mcs"]
        st = steepness_db(r)
        per_end = r["sweep"]["per"][-1] if r["sweep"]["snr_db"][-1] == GRIDS[mcs][-1] else None
        print(f"{mcs:<4} {r['tags']['channel']:<20} {fmt(r['snr_at_target']):>9} {fmt(st):>15} "
              f"{fmt(per_end, '{:.3g}') if per_end is not None else '—':>16}   {paper_text(paper[mcs])}")
    print("0.5->0.05 = how many dB the curve takes to fall from PER 0.5 to 0.05 (the paper's columns are computed "
          "the same way from liu2025_fig4.yaml); PER at axis end = at 14 / 17 / 31 dB, '—' when the sweep stopped "
          "early below 1e-3")

    # ---------------------------------------------------------------- 2. whose floor?
    print(f"\n== 2. MCS4 on fading channels with one impairment off at a time (K = {K}) ==")
    specs2 = []
    for name, k_db in ((("Rayleigh", "rayleigh"),) if quick else (("LOS 3 dB", 3.0), ("Rayleigh", "rayleigh"))):
        cfg = with_channel(liu2025_table2(k=K, mcs=4), k_db)
        pa = cfg.frontend.pa
        rows = [("all on", cfg),
                ("ideal PA", dc.replace(cfg, frontend=dc.replace(cfg.frontend, pa=dc.replace(pa, model="ideal")))),
                ("PN off", dc.replace(cfg, lo=dc.replace(cfg.lo, phase_noise=dc.replace(cfg.lo.phase_noise,
                                                                                         apply="off")))),
                ("all off (ideal)", with_channel(liu2025_table2(k=K, mcs=4).ideal(), k_db))]
        if quick:
            rows = rows[::3]
        grid = GRIDS[4][::5] if quick else GRIDS[4]
        for what, c in rows:
            specs2.append(CurveSpec(f"MCS4 {name}: {what}", c, grid, mp, me, tags={"channel": name, "what": what}))
    res2 = run_curves(specs2, TARGET, a.jobs, log=lambda s: None)
    for r in res2:
        print(sweep_line(r))
    ideal4 = paper_curves("ideal")[4]
    print(f"\nthe paper's 8x MCS4: impaired {paper_text(paper[4])}; its 'ideal' (no PN / PA, CFO kept) "
          f"{paper_text(ideal4)}")
    print(f"\n[{time.time() - t0:.0f}s]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
