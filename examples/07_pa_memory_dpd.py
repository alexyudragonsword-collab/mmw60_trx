#!/usr/bin/env python
"""What electrical memory in the 60 GHz PA costs the predistorter at K > 1.

The preset PA is memoryless (the 11ad modified Rapp).  This example puts a
PA with memory (wifitrx's ReferencePA at the front end's gain / Psat) into
the topology-B chain and runs wifitrx's calibration sequence on it at K = 4,
8 and 32 (11be 80 MHz base), at the two ends of the question upclocking
raises: does the PA's memory scale with the signal (taps one sample apart
at any clock), or is it fixed in seconds (taps 1 / fir_fs apart, so
fs_eff / fir_fs samples apart at K)?  The DPD's GMP tap spacing is measured
on the chain at each candidate, not set to fs_eff / fir_fs.

Every number here is on an assumed PA model (data/spec:
assumed.pa_memory_model, assumed.pa_memory_fir_fs_hz); the comparison table
(example 04) keeps the memoryless Rapp.

    python examples/07_pa_memory_dpd.py [--quick]
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from mmw60 import ENGINE_BANNER, __version__, pamemory, spec     # noqa: E402
from mmw60.config import zero_if_60ghz                            # noqa: E402
from mmw60.frontend import Frontend60                             # noqa: E402

BASE_HZ, STANDARD = 80e6, "11be"
HEAD = (f"{'PA':<50} {'DPD taps':>9} {'OBO':>5} {'dpd step':>9} {'TX EVM':>7} {'loopback':>9}")


def _line(r: pamemory.MemoryRow, mark: str = "") -> str:
    taps = "off" if r.tap_spacing is None else f"x{r.tap_spacing}"
    dpd = "    —" if r.dpd_evm_db is None else f"{r.dpd_evm_db:9.1f}"
    obo = "  —" if r.obo_db is None else f"{r.obo_db:5.1f}"
    fail = f"  FAILED: {', '.join(r.failed)}" if r.failed else ""
    return f"{r.label:<50} {taps:>9} {obo} {dpd:>9} {r.tx_evm_db:7.1f} {r.loop_evm_db:9.1f}{mark}{fail}"


def _cost_line(head: str, scales, sample, matched, best=None, off=None) -> str:
    line = (f"{head} {scales.tx_evm_db:8.1f} {sample.tx_evm_db:10.1f} {matched.tx_evm_db:15.1f} "
            f"{sample.tx_evm_db - scales.tx_evm_db:11.1f} {matched.tx_evm_db - scales.tx_evm_db:16.1f}")
    if best is not None:
        line += f" {best.tx_evm_db:12.1f} {'x' + str(best.tap_spacing):>10} {off.tx_evm_db:12.1f}"
        line += "   DPD does not help" if best.tx_evm_db >= off.tx_evm_db else ""
    return line


def main(argv=None) -> int:
    print(ENGINE_BANNER)
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--jobs", type=int, default=1, help="accepted for symmetry with the other examples; this one is serial")
    a = ap.parse_args(argv)
    quick = a.quick or os.environ.get("MMW60_SMOKE") == "1"
    t0 = time.time()
    fe = Frontend60.from_config(zero_if_60ghz(k=8))
    fir = pamemory.default_fir_fs_hz()
    obo = fe.obo_db
    base = 20e6 if quick else BASE_HZ          # the smoke run takes the narrow base: the same code, seconds not minutes
    print(f"mmw60 {__version__}; {'QUICK' if quick else 'full'}; base {STANDARD} {base / 1e6:g} MHz, 2x oversampling; "
          f"PA gain {fe.pa_gain_db:g} dB, Psat {fe.psat_dbm:g} dBm; memory PA: {spec.value('assumed.pa_memory_model')} "
          f"(assumed), taps defined at {fir / 1e6:g} MS/s = {1e9 / fir:g} ns apart (assumed)")
    print(f"every row's last EVM check sits at the same output back-off: {obo:g} dB from Psat, the front end's preset "
          "(the drive is trimmed and the sequence rerun until it does)")
    print("EVM columns in dB: 'dpd step' is the DPD step's own PA-output reading, 'TX EVM' and 'loopback' are the last "
          "step's, as a standard receiver reads them; OBO is the back-off that check landed on")
    print("the Rapp rows: this PA's P1dB is 9.5 dB under Psat, so at this back-off the average sits above P1dB and "
          "wifitrx's DPD step (2 ILA iterations) has little headroom: compare its off / x1 rows")

    summary = []
    for k in ((8,) if quick else (4, 8, 32)):
        rows = pamemory.study(fe, k, base, STANDARD, obo_db=obo)
        fs = rows[0].fs_eff_hz
        print(f"\n== K = {k}: {rows[0].bw_eff_hz / 1e6:g} MHz at {fs / 1e9:.2f} GS/s; a {1e9 / fir:g} ns tap is "
              f"{pamemory.memory_stride(fs, fir)} samples; back-off {obo:g} dB ==")
        print(HEAD)
        best = pamemory.best_spacing(rows)
        for r in rows:
            print(_line(r, "  <- best spacing" if r is best else ""), flush=True)
        scales = next(r for r in rows if r.law == pamemory.SCALES and r.tap_spacing == 1)
        sample = next(r for r in rows if r.law == pamemory.FIXED and r.tap_spacing == 1)
        matched = next(r for r in rows if r.law == pamemory.FIXED and r.tap_spacing == r.stride)
        off = next(r for r in rows if r.law == pamemory.FIXED and r.tap_spacing is None)
        summary.append((k, scales, sample, matched, best, off))
        print(f"  [{time.time() - t0:.0f}s]")

    cost_head = (f"{'scales':>8} {'fixed, x1':>10} {'fixed, matched':>15} {'cost at x1':>11} {'cost at matched':>16}")
    print(f"\n== what the memory law costs after DPD at back-off {obo:g} dB (TX EVM, dB; the reference PA only) ==")
    print(f"{'':>4} {cost_head} {'fixed, best':>12} {'best taps':>10} {'fixed, off':>12}")
    for k, scales, sample, matched, best, off in summary:
        print(_cost_line(f"{'K=' + str(k):>4}", scales, sample, matched, best, off))
    print("cost = fixed-in-seconds memory minus memory that scales with the signal; 'matched' is x(fs_eff / fir_fs); "
          "'fixed, off' is the same PA without the DPD step")

    if not quick:
        print("\n== sensitivity: the back-off (assumed.pa_memory_obo_sensitivity_db; TX EVM, dB) ==")
        print(f"{'':>4} {'OBO':>5} {cost_head}")
        for k, scales, sample, matched, _, _ in summary[1:]:
            print(_cost_line(f"{'K=' + str(k):>4} {obo:5.1f}", scales, sample, matched))
            for o in (float(v) for v in spec.value("assumed.pa_memory_obo_sensitivity_db")):
                print(_cost_line(f"{'K=' + str(k):>4} {o:5.1f}", *pamemory.cost_rows(fe, k, base, STANDARD, o)), flush=True)

        k = 32
        print(f"\n== sensitivity: how fast the PA's memory is, K = {k}, back-off {obo:g} dB (assumed.pa_memory_fir_fs_hz) ==")
        print(f"{'taps defined at':>16} {'tap':>9} {'samples':>8} {'TX EVM, x1':>11} {'TX EVM, matched':>16} {'matched - x1':>13}")
        _, scales, sample, matched, _, _ = summary[-1]
        for f in (fir, *(float(v) for v in spec.value("assumed.pa_memory_fir_fs_sensitivity_hz"))):
            stride = pamemory.memory_stride(base * k * 2, f)
            one, mat = (sample, matched) if f == fir else pamemory.cost_rows(fe, k, base, STANDARD, obo, fir_fs_hz=f)[1:]
            print(f"{f / 1e6:>11g} MS/s {1e9 / f:>6.3g} ns {stride:>8} {one.tx_evm_db:11.1f} {mat.tx_evm_db:16.1f} "
                  f"{mat.tx_evm_db - one.tx_evm_db:13.1f}", flush=True)
        print(f"{'(scales)':>16} {'—':>9} {1:>8} {scales.tx_evm_db:11.1f} {scales.tx_evm_db:16.1f} {0.0:13.1f}")
    print(f"\n[{time.time() - t0:.0f}s]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
