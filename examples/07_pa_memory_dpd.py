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

The cost is read in back-off, not in EVM at one back-off: the DPD's gain
falls off a cliff as the PA nears saturation, the preset 8 dB sits on that
cliff, and the two memory laws' cliffs are 1–2 dB apart.  So the example
sweeps the back-off and compares the back-off each PA needs for the same
EVM.

Every number here is on an assumed PA model (data/spec:
assumed.pa_memory_model, assumed.pa_memory_fir_fs_hz); the comparison table
(example 04) keeps the memoryless Rapp.

    python examples/07_pa_memory_dpd.py [--quick] [--jobs N]
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


def _obo(v: float | None, exact: bool) -> str:
    if v is None:
        return f"{'not reached':>12}"
    return f"{v:9.1f} dB" if exact else f"{'<= ' + format(v, '.1f'):>9} dB"


def _cost(pen: dict) -> str:
    return f"{'—':>8}" if pen["cost"] is None else f"{pen['cost']:5.1f} dB"


def main(argv=None) -> int:
    print(ENGINE_BANNER)
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1),
                    help="worker processes (default: up to 4); the numbers do not depend on it")
    a = ap.parse_args(argv)
    quick = a.quick or os.environ.get("MMW60_SMOKE") == "1"
    t0 = time.time()
    fe = Frontend60.from_config(zero_if_60ghz(k=8))
    fir = pamemory.default_fir_fs_hz()
    obo = fe.obo_db
    base = 20e6 if quick else BASE_HZ          # the smoke run takes the narrow base: the same code, seconds not minutes
    ks = (8,) if quick else (4, 8, 32)
    sweep_ks = (8,) if quick else (8, 32)
    obos = (obo, 10.0, 12.0) if quick else tuple(float(v) for v in spec.value("assumed.pa_memory_obo_sweep_db"))
    coarse = () if quick else tuple(float(v) for v in spec.value("assumed.pa_memory_obo_sweep_coarse_db"))
    targets = tuple(float(v) for v in spec.value("assumed.pa_memory_target_evm_db"))
    firs = () if quick else tuple(float(v) for v in spec.value("assumed.pa_memory_fir_fs_sensitivity_hz"))
    k_fast = 32

    # every row of every table, run once (in worker processes with --jobs)
    keys = [key for k in ks for key in pamemory.study_keys(k, base, STANDARD, obo_db=obo)]
    keys += [key for k in sweep_ks for key in pamemory.sweep_keys(k, base, STANDARD, obos)]
    keys += [key for f in firs for key in pamemory.sweep_keys(k_fast, base, STANDARD, coarse, fir_fs_hz=f)]
    done = pamemory.run_many(fe, keys, a.jobs)

    print(f"mmw60 {__version__}; {'QUICK' if quick else 'full'}; base {STANDARD} {base / 1e6:g} MHz, 2x oversampling; "
          f"PA gain {fe.pa_gain_db:g} dB, Psat {fe.psat_dbm:g} dBm; memory PA: {spec.value('assumed.pa_memory_model')} "
          f"(assumed), taps defined at {fir / 1e6:g} MS/s = {1e9 / fir:g} ns apart (assumed)")
    print("every row's last EVM check sits at the back-off from Psat the table names (the drive is trimmed and the "
          "sequence rerun until it does)")
    print("EVM columns in dB: 'dpd step' is the DPD step's own PA-output reading, 'TX EVM' and 'loopback' are the last "
          "step's, as a standard receiver reads them; OBO is the back-off that check landed on")
    rapp = fe.scaled_pa()
    print(f"the Rapp rows: the preset PA (a measured 60 GHz CMOS PA's scale and compression, data/spec "
          f"assumed.pa60_surveyed_pick) has its P1dB {rapp.psat_dbm - rapp.p1db_out_dbm:.1f} dB under Psat, so at the "
          f"preset back-off the average sits {rapp.p1db_out_dbm - fe.target_pout_dbm():.1f} dB under P1dB: compare its "
          "off / x1 rows")
    print(f"{len(set(keys))} runs of the calibration sequence  [{time.time() - t0:.0f}s]")

    summary = []
    for k in ks:
        rows = [done[key] for key in pamemory.study_keys(k, base, STANDARD, obo_db=obo)]
        fs = rows[0].fs_eff_hz
        print(f"\n== K = {k} at the preset back-off {obo:g} dB: {rows[0].bw_eff_hz / 1e6:g} MHz at {fs / 1e9:.2f} GS/s; "
              f"a {1e9 / fir:g} ns tap is {pamemory.memory_stride(fs, fir)} samples ==")
        print(HEAD)
        best = pamemory.best_spacing(rows)
        for r in rows:
            print(_line(r, "  <- best spacing" if r is best else ""))
        scales = next(r for r in rows if r.law == pamemory.SCALES and r.tap_spacing == 1)
        sample = next(r for r in rows if r.law == pamemory.FIXED and r.tap_spacing == 1)
        matched = next(r for r in rows if r.law == pamemory.FIXED and r.tap_spacing == r.stride)
        off = next(r for r in rows if r.law == pamemory.FIXED and r.tap_spacing is None)
        summary.append((k, scales, sample, matched, best, off))

    cost_head = (f"{'scales':>8} {'fixed, x1':>10} {'fixed, matched':>15} {'gap at x1':>11} {'gap at matched':>16}")
    print(f"\n== the EVM gap at the preset back-off {obo:g} dB (TX EVM after DPD, dB; the reference PA only) ==")
    print(f"{'':>4} {cost_head} {'fixed, best':>12} {'best taps':>10} {'fixed, off':>12}")
    for k, scales, sample, matched, best, off in summary:
        print(_cost_line(f"{'K=' + str(k):>4}", scales, sample, matched, best, off))
    print("gap = fixed-in-seconds memory minus memory that scales with the signal; 'matched' is x(fs_eff / fir_fs); "
          "'fixed, off' is the same PA without the DPD step")
    print("this gap is read on the DPD's cliff (next table): it says where the two cliffs are, not what the memory costs")

    sweeps = {}
    for k in sweep_ks:
        pts = sweeps[k] = pamemory.sweep_points(done, k, base, STANDARD, obos)
        stride = pts[0].fixed_matched.stride
        print(f"\n== K = {k}: TX EVM after DPD against the back-off (assumed.pa_memory_obo_sweep_db; a tap is {stride} samples) ==")
        print(f"{'OBO[dB]':>8} {'scales':>8} {'fixed, x1':>10} {'fixed, x' + str(stride):>12} {'fixed, best':>12} "
              f"{'gap at best':>12}")
        for pt in pts:
            print(f"{pt.obo_db:8.1f} {pt.scales.tx_evm_db:8.1f} {pt.fixed_x1.tx_evm_db:10.1f} "
                  f"{pt.fixed_matched.tx_evm_db:12.1f} {pt.fixed_best_evm_db:12.1f} "
                  f"{pt.fixed_best_evm_db - pt.scales.tx_evm_db:12.1f}")

    print("\n== what the memory law costs: the back-off needed for the same TX EVM after DPD (assumed.pa_memory_target_evm_db) ==")
    print(f"{'':>4} {'target':>8} {'scales needs':>13} {'fixed needs':>12} {'cost in back-off':>17}")
    for k in sweep_ks:
        for t in targets:
            pen = pamemory.backoff_penalty(sweeps[k], t)
            print(f"{'K=' + str(k):>4} {t:5.0f} dB {_obo(pen['scales'], pen['scales_exact'])} "
                  f"{_obo(pen['fixed'], pen['fixed_exact'])}          {_cost(pen)}")
    print("'fixed needs' takes the better of the two tap spacings at each back-off; linear between the grid points; "
          "'<=' = already there at the first point of the sweep, 'not reached' = not inside the swept range (no cost then)")

    if firs:
        print(f"\n== sensitivity: how fast the PA's memory is, K = {k_fast} (assumed.pa_memory_fir_fs_hz; back-off needed, "
              "coarse grid) ==")
        print(f"{'taps defined at':>16} {'tap':>9} {'samples':>8}   " + "   ".join(
            f"{'for ' + format(t, '.0f') + ' dB: scales / fixed / cost':>40}" for t in targets))
        for f in (fir, *firs):
            pts = pamemory.sweep_points(done, k_fast, base, STANDARD, coarse, fir_fs_hz=f)
            cells = []
            for t in targets:
                pen = pamemory.backoff_penalty(pts, t)
                cells.append(f"{_obo(pen['scales'], pen['scales_exact'])} / {_obo(pen['fixed'], pen['fixed_exact'])} / "
                             f"{_cost(pen)}")
            print(f"{f / 1e6:>11g} MS/s {1e9 / f:>6.3g} ns {pts[0].fixed_matched.stride:>8}   " + "   ".join(
                f"{c:>40}" for c in cells))
    print(f"\n[{time.time() - t0:.0f}s]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
