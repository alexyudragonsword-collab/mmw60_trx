"""Example 01 — beyond the paper: can K = 4 live with a wider-range CFO estimator?

Liu 2025's threshold (K > 4.7) is a property of the L-STF autocorrelation,
not of the waveform: at K = 4 the 2.94 MHz offset is 2.35 subcarriers, the
STF estimate aliases to −2.06 MHz and the packet is lost.  Here the receiver
resolves the integer-subcarrier ambiguity of the L-LTF estimate with a
frequency-domain correlation (``rx.cfo_estimation = "extended"``, ±8
tones) and the same PER curves are re-run for K = 4 / 8 / 16.  The remaining
question is then whether the K = 4 symbol (0.8 µs FFT, 200 ns GI) survives
the phase noise and the PA at the same OBO — the first conclusion this
library draws that the paper does not.

    python examples/01_cfo_extended_range.py [--quick] [--jobs N]
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
from mmw60.config import liu2025_table2                           # noqa: E402
from mmw60.sim.curves import CurveSpec, run_curves, save_results, sweep_line  # noqa: E402
from mmw60.sim.link import LinkSim                                # noqa: E402

OUT = HERE / "output"
TARGET = 1e-2
GRIDS = {0: [x * 0.5 for x in range(0, 17)], 1: [3 + x * 0.5 for x in range(0, 17)],
         4: [12 + x * 1.0 for x in range(0, 15)]}


def extended(cfg):
    return dc.replace(cfg, rx=dc.replace(cfg.rx, cfo_estimation="extended"))


def specs(quick: bool):
    mp, me = (6, 2) if quick else (600, 30)
    out = []
    for k in (4, 8, 16):
        for mcs in (0, 1, 4):
            grid = GRIDS[mcs][::6] if quick else GRIDS[mcs]
            cfg = extended(liu2025_table2(k=k, mcs=mcs))
            out.append(CurveSpec(f"K={k:<2} MCS{mcs} impaired ext", cfg, grid, mp, me,
                                 tags={"k": k, "mcs": mcs, "set": "impaired_extended"}))
    return out


def main(argv=None) -> int:
    print(ENGINE_BANNER)
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--jobs", type=int, default=max(1, min(4, os.cpu_count() or 1)))
    a = ap.parse_args(argv)
    quick = a.quick or os.environ.get("MMW60_SMOKE") == "1"
    t0 = time.time()
    print(f"mmw60 {__version__}; {'QUICK (numbers meaningless)' if quick else 'full size'}")

    import numpy as np
    print("\n== CFO estimate at K=4, one packet each, SNR 20 dB ==")
    for mode in ("stf_ltf", "extended"):
        cfg = liu2025_table2(k=4, mcs=0)
        cfg = dc.replace(cfg, rx=dc.replace(cfg.rx, cfo_estimation=mode))
        sim = LinkSim(cfg)
        r = sim.packet(20.0, np.random.default_rng(3))
        print(f"  {mode:<8} true {r.cfo_true_hz / 1e6:.3f} MHz  estimate {r.rx.cfo_hat_hz / 1e6:.3f} MHz "
              f"(stf {r.rx.cfo_stf_hz / 1e6:.3f}, ltf {r.rx.cfo_ltf_hz / 1e6:.3f}, "
              f"integer {r.rx.cfo_integer_tones:+d} tones)  EVM {r.rx.evm_db:.1f} dB  "
              f"bit errors {r.rx.bit_errors}")

    print("\n== PER vs SNR with the extended-range estimator ==")
    results = run_curves(specs(quick), TARGET, a.jobs, log=lambda s: print(s, flush=True))
    print("\ncurve                              SNR @ PER 1e-2      SNR:PER points")
    for r in results:
        print(sweep_line(r))
    OUT.mkdir(exist_ok=True)
    save_results(results, OUT / "01_sweeps.json")
    print(f"\nwrote {OUT / '01_sweeps.json'}  [{time.time() - t0:.0f}s]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
