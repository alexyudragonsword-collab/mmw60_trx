"""Example 00 — Liu 2025 Table II reproduced: PER vs SNR for K = 4 / 8 / 16, MCS 0 / 1 / 4.

The milestone-0 external validation (cairn/external-validation.md): the
upclocked 802.11ac VHT link at 73.44 GHz with 40 ppm crystal error, the
1-pole/1-zero LO phase noise (−93 dBc/Hz, 1 MHz / 100 MHz), the modified
Rapp PA at OBO 8 dB and the conference-room stand-in channel, with and
without the impairments.  The receiver runs the standard L-STF coarse +
L-LTF fine CFO estimate and pilot phase tracking (the paper's own "4.7"
argument assumes the STF estimator; its "we refrained from CFO estimation"
sentence is tested as the *literal* diagnostic row below).

The three original sets keep the milestone-0 receiver (per-symbol pilot CPE,
3-tone channel smoothing) — they are the external validation.  Two more
sets, "rx+", run the same links with the improved receiver of findings C1 /
C2 (pilot common phase combined across symbols, smoothing span chosen per
packet) to show how far the curves move.  Every SNR at PER 1e-2 comes with
the 95 % bootstrap interval of its own counting statistics (finding C3).

    python examples/00_liu2025_per_vs_snr.py [--quick] [--jobs N]

Writes examples/output/00_per_vs_snr.png and 00_sweeps.json (what
tools/external_check.py compares with the Fig. 4 read-offs).
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

from mmw60 import ENGINE_BANNER, __version__                      # noqa: E402
from mmw60.config import ChannelConfig, improved_rx, liu2025_table2  # noqa: E402
from mmw60.phy.bcc import active_kernel                           # noqa: E402
from mmw60.sim.curves import CurveSpec, ci_text, run_curves, save_results, sweep_line  # noqa: E402
from mmw60.sim.link import LinkSim                                # noqa: E402

OUT = HERE / "output"
TARGET = 1e-2

GRIDS = {0: [x * 0.5 for x in range(0, 17)],        # 0 .. 8 dB
         1: [3 + x * 0.5 for x in range(0, 17)],    # 3 .. 11 dB
         4: [12 + x * 1.0 for x in range(0, 15)]}   # 12 .. 26 dB


def flat(cfg):
    """The one under-specified input the paper's own curves pin down: a flat
    (AWGN-like) channel instead of the assumed conference-room stand-in;
    everything else, the literal OBO from Psat included, unchanged."""
    return dc.replace(cfg, channel=ChannelConfig(model="flat"))


#: finding C3: the two points bracketing PER 1e-2 are run on to this many
#: packet errors (or the packet cap) before the crossing is interpolated
REFINE_ERRORS, REFINE_MAX_PACKETS = 60, 3000
#: the improved receiver's curves start lower (its MCS0 threshold is ~2 dB down)
GRIDS_RX = {0: [-1 + x * 0.5 for x in range(0, 17)],    # −1 .. 7 dB
            1: [2 + x * 0.5 for x in range(0, 17)],     # 2 .. 10 dB
            4: [11 + x * 1.0 for x in range(0, 15)]}    # 11 .. 25 dB


def better_rx(cfg):
    """milestone-0 findings C1 / C2 on (``config.improved_rx``): pilot common phase combined
    across symbols, channel-estimate smoothing span chosen per packet."""
    return dc.replace(cfg, rx=improved_rx(cfg.rx), label=(cfg.label + " rx+").strip())


def specs(quick: bool) -> list[CurveSpec]:
    mp, me = (6, 2) if quick else (600, 30)
    rf = {} if quick else {"refine_errors": REFINE_ERRORS, "refine_max_packets": REFINE_MAX_PACKETS}
    out = []
    for k in (4, 8, 16):
        for mcs in (0, 1, 4):
            grid = GRIDS[mcs][::6] if quick else GRIDS[mcs]
            grid_rx = GRIDS_RX[mcs][::6] if quick else GRIDS_RX[mcs]
            cfg = liu2025_table2(k=k, mcs=mcs)
            out.append(CurveSpec(f"K={k:<2} MCS{mcs} impaired", cfg, grid, mp, me,
                                 tags={"k": k, "mcs": mcs, "set": "impaired"}, **rf))
            out.append(CurveSpec(f"K={k:<2} MCS{mcs} ideal", cfg.ideal(), grid, mp, me,
                                 tags={"k": k, "mcs": mcs, "set": "ideal"}, **rf))
            out.append(CurveSpec(f"K={k:<2} MCS{mcs} flat", flat(cfg), grid, mp, me,
                                 tags={"k": k, "mcs": mcs, "set": "flat"}, **rf))
            out.append(CurveSpec(f"K={k:<2} MCS{mcs} flat rx+", better_rx(flat(cfg)), grid_rx, mp, me,
                                 tags={"k": k, "mcs": mcs, "set": "flat_rx"}, **rf))
            out.append(CurveSpec(f"K={k:<2} MCS{mcs} impaired rx+", better_rx(cfg), grid_rx, mp, me,
                                 tags={"k": k, "mcs": mcs, "set": "impaired_rx"}, **rf))
    return out


def sensitivity_specs(quick: bool) -> list[CurveSpec]:
    """Rows that move one assumed input at a time (data/spec/survey.yaml, source assumed)."""
    mp, me = (6, 2) if quick else (300, 20)
    grid = GRIDS[4][::6] if quick else GRIDS[4][::2]
    base = liu2025_table2(k=8, mcs=4)
    pa = base.frontend.pa
    rows = [
        ("K=8  MCS4 OBO from P1dB",
         dc.replace(base, frontend=dc.replace(base.frontend, pa=dc.replace(pa, obo_reference="p1db")))),
        ("K=8  MCS4 Rayleigh (no LOS)",
         dc.replace(base, channel=dc.replace(base.channel, los_k_db=None))),
        ("K=8  MCS4 PN rx-only",
         dc.replace(base, lo=dc.replace(base.lo, phase_noise=dc.replace(base.lo.phase_noise, apply="rx")))),
        ("K=8  MCS4 ideal PA",
         dc.replace(base, frontend=dc.replace(base.frontend, pa=dc.replace(pa, model="ideal")))),
        ("K=8  MCS4 no CE smoothing", dc.replace(base, rx=dc.replace(base.rx, ce_smooth_tones=1))),
        ("K=8  MCS4 rx+ CPE window 5", dc.replace(base, rx=dc.replace(improved_rx(base.rx), cpe_window_symbols=5))),
        ("K=8  MCS4 rx+ CPE window 33", dc.replace(base, rx=dc.replace(improved_rx(base.rx), cpe_window_symbols=33))),
        ("K=8  MCS4 rx+ CPE only (CE fixed 3)", dc.replace(base, rx=dc.replace(improved_rx(base.rx), ce_smooth_auto=False))),
        ("K=8  MCS4 rx+ CE auto only", dc.replace(base, rx=dc.replace(base.rx, ce_smooth_auto=True))),
    ]
    return [CurveSpec(n, c, grid, mp, me, tags={"k": 8, "mcs": 4, "set": "sensitivity"})
            for n, c in rows]


def literal_rows(quick: bool, log) -> None:
    """The literal reading of §V-A: no CFO estimation at all, pilots only."""
    import numpy as np
    n = 3 if quick else 20
    log("\n== literal reading of Sec. V-A: CFO estimation OFF, pilot phase tracking only (SNR 20 dB) ==")
    for k in (4, 8, 16):
        cfg = liu2025_table2(k=k, mcs=0)
        cfg = dc.replace(cfg, rx=dc.replace(cfg.rx, cfo_estimation="off"))
        sim = LinkSim(cfg)
        rng = np.random.default_rng(7)
        errs = sum(int(sim.packet(20.0, rng).rx.packet_error) for _ in range(n))
        log(f"  K={k:<2} MCS0 CFO {sim.cfo.cfo_hz / 1e6:.2f} MHz = "
            f"{sim.cfo.in_subcarriers(sim.phy.scs_eff):.2f} subcarriers uncompensated: "
            f"PER {errs / n:.2f} ({errs}/{n})")


def main(argv=None) -> int:
    print(ENGINE_BANNER)
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--jobs", type=int, default=max(1, min(4, os.cpu_count() or 1)))
    a = ap.parse_args(argv)
    quick = a.quick or os.environ.get("MMW60_SMOKE") == "1"
    t0 = time.time()
    print(f"mmw60 {__version__}; Viterbi kernel: {active_kernel()}; "
          f"{'QUICK (numbers meaningless)' if quick else 'full size'}")

    sim = LinkSim(liu2025_table2(k=8, mcs=0))
    d = sim.describe()
    print(f"Liu 2025 Table II: VHT 20 MHz x K, 4096 B, fc {sim.cfg.carrier_hz / 1e9:.2f} GHz, "
          f"{sim.cfg.xo_ppm_tx:g}+{sim.cfg.xo_ppm_rx:g} ppm -> CFO {d['cfo_hz'] / 1e6:.3f} MHz; "
          f"PN {sim.cfg.lo.phase_noise.psd0_dbchz:g} dBc/Hz (fp {sim.cfg.lo.phase_noise.f_pole_hz / 1e6:g} MHz, "
          f"fz {sim.cfg.lo.phase_noise.f_zero_hz / 1e6:g} MHz) at {d['pn']}; PA {d['pa']} OBO "
          f"{d['pa_obo_db']:g} dB from {d['pa_obo_reference']}; channel {d['channel']} "
          f"{d['channel_rms_delay_ns']:g} ns rms; CFO estimation {d['cfo_estimation']}")
    print(f"SNR axis: per active subcarrier Es/N0; per-sample SNR is "
          f"{d['snr_per_sample_offset_db']:.2f} dB lower")
    print("K    SCS [MHz]  T_fft [ns]  GI [ns]  STF capture [MHz]  LTF capture [MHz]  CFO [subcarriers]")
    for k in (4, 8, 16):
        p = LinkSim(liu2025_table2(k=k, mcs=0)).phy
        print(f"{k:<4} {p.scs_eff / 1e6:8.2f}   {p.t_fft_eff * 1e9:8.0f}    {p.t_gi_eff * 1e9:5.0f}   "
              f"{p.stf_capture_hz / 1e6:12.2f}       {p.ltf_capture_hz / 1e6:12.2f}       "
              f"{p.cfo_in_subcarriers(sim.cfo.cfo_hz):8.2f}")

    print(f"\n== PER vs SNR ({'quick' if quick else 'up to 600 packets or 30 errors per point'}) ==")
    print("sets: impaired = Table II read literally (LOS/diffuse channel, OBO from Psat); "
          "ideal = no CFO/PN/PA; flat = same impairments on a flat channel; "
          "rx+ = the same link with the improved receiver (cross-symbol CPE, automatic smoothing span)")
    if not quick:
        print(f"the two points bracketing PER 1e-2 are run on to {REFINE_ERRORS} errors or {REFINE_MAX_PACKETS} packets; "
              "the bracketed interval is the 95 % bootstrap interval of the crossing from the counts")
    results = run_curves(specs(quick), TARGET, a.jobs, log=lambda s: print(s, flush=True))
    print("\ncurve                              SNR @ PER 1e-2      SNR:PER points")
    for r in results:
        print(sweep_line(r))
    print("\n== SNR at PER 1e-2 [dB] ==")
    print("K   MCS   impaired    ideal     flat")
    at = {(r["tags"]["k"], r["tags"]["mcs"], r["tags"]["set"]): r["snr_at_target"] for r in results}
    for k in (4, 8, 16):
        for mcs in (0, 1, 4):
            cells = [at.get((k, mcs, s)) for s in ("impaired", "ideal", "flat")]
            print(f"{k:<3} {mcs:<5} " + "  ".join(f"{'never' if c is None else f'{c:.2f}':>8}" for c in cells))
    by = {(r["tags"]["k"], r["tags"]["mcs"], r["tags"]["set"]): r for r in results}
    print("\n== the improved receiver (rx+) against the milestone-0 one, SNR at PER 1e-2 [dB] with its 95 % interval ==")
    print("K   MCS   flat                       flat rx+                   gain    impaired                   impaired rx+               gain")
    for k in (4, 8, 16):
        for mcs in (0, 1, 4):
            row = f"{k:<3} {mcs:<5}"
            for a_, b_ in (("flat", "flat_rx"), ("impaired", "impaired_rx")):
                ra, rb = by.get((k, mcs, a_)), by.get((k, mcs, b_))
                va, vb = ra["snr_at_target"], rb["snr_at_target"]
                fa = "never" if va is None else f"{va:5.2f}"
                fb = "never" if vb is None else f"{vb:5.2f}"
                gain = "    —" if (va is None or vb is None) else f"{va - vb:+5.2f}"
                row += f" {fa} {ci_text(ra)[:14]:<16}   {fb} {ci_text(rb)[:14]:<16}  {gain}  "
            print(row.rstrip())

    print("\n== sensitivity (one assumed input at a time, K=8 MCS4) ==")
    sens = run_curves(sensitivity_specs(quick), TARGET, a.jobs, log=lambda s: None)
    for r in sens:
        print(sweep_line(r))

    literal_rows(quick, print)

    OUT.mkdir(exist_ok=True)
    save_results(results + sens, OUT / "00_sweeps.json")
    _plot(results, OUT / "00_per_vs_snr.png")
    print(f"\nwrote {OUT / '00_sweeps.json'} and {OUT / '00_per_vs_snr.png'}  [{time.time() - t0:.0f}s]")
    return 0


def _plot(results, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 5, figsize=(25, 4.5), sharey=True)
    colors = {0: "C0", 1: "C2", 4: "C3"}
    styles = {4: ":", 8: "-", 16: "--"}
    panel = {"impaired": 0, "ideal": 1, "flat": 2, "flat_rx": 3, "impaired_rx": 4}
    for r in results:
        t = r["tags"]
        if t["set"] not in panel:
            continue
        ax = axes[panel[t["set"]]]
        sw = r["sweep"]
        ax.semilogy(sw["snr_db"], [max(p, 1e-4) for p in sw["per"]], styles[t["k"]],
                    color=colors[t["mcs"]], marker="o", ms=3, label=f"{t['k']}x MCS{t['mcs']}")
    for ax, title in zip(axes, ("Table II literal: CFO + PN + PA, LOS/diffuse channel, OBO from Psat",
                                "without impairments", "same impairments, flat channel",
                                "flat channel, improved receiver", "Table II literal, improved receiver")):
        ax.set_title(title)
        ax.set_xlabel("SNR per subcarrier (dB)")
        ax.grid(True, which="both", alpha=0.3)
        ax.set_ylim(1e-3, 1.2)
        ax.axhline(TARGET, color="k", lw=0.5)
    axes[0].set_ylabel("PER (4096 B)")
    axes[0].legend(fontsize=7, ncol=3)
    fig.suptitle("Liu 2025 Table II reproduced on upclocked wifitrx (example 00)")
    fig.tight_layout()
    fig.savefig(path, dpi=130)


if __name__ == "__main__":
    raise SystemExit(main())
