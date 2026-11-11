"""Example 03 — wifitrx's calibration sequence on the upclocked zero-IF chain, step by step.

The chains are the shared 60 GHz front end at fs_eff (``Frontend60``), the
sequence is wifitrx's own runner table (``cal/sequence``), profile
"poweron".  K = 1 is the WiFi 7 chip as delivered (20 MHz here); K = 4 / 8 /
16 are 80 / 160 / 320 MHz — standard bandwidths, scored on the standard's
waveform there; K = 32 (640 MHz) and the 11be 80 MHz × 32 (2.56 GHz) cells
are scored on the upclocked base waveform (the base's tones and pilots at
K times the spacing — wifitrx's tone plans carry their own pilots since
96078aa; until then these two had no verdict step).  Every step is
recorded as ok / degraded / failed with the metric its own spec names and
the mechanism behind a change (``calcheck.MECHANISM``).

    python examples/03_calibration_at_k.py [--quick]
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from mmw60 import ENGINE_BANNER, __version__                       # noqa: E402
from mmw60.calcheck import compare_runs, run_cal_at                # noqa: E402
from mmw60.config import zero_if_60ghz                             # noqa: E402
from mmw60.frontend import Frontend60                              # noqa: E402


def main(argv=None) -> int:
    print(ENGINE_BANNER)
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--jobs", type=int, default=1, help="accepted for symmetry with examples 00 / 01; this example is serial")
    a = ap.parse_args(argv)
    quick = a.quick or os.environ.get("MMW60_SMOKE") == "1"
    t0 = time.time()
    fe = Frontend60.from_config(zero_if_60ghz(k=8))
    print(f"mmw60 {__version__}; {'QUICK' if quick else 'full'}; profile poweron; front end {fe.describe()['pa']} "
          f"Pout {fe.target_pout_dbm():g} dBm, TX leak {fe.lo.tx_leak_dbc:g} dBc, IQ {fe.tx_iq.gd_mismatch_ps:g} ps, "
          f"LO IPN {fe.lo.ipn_dbc():.1f} dBc")
    plan = [(1, 20e6), (8, 20e6)] if quick else [(1, 20e6), (4, 20e6), (8, 20e6), (16, 20e6), (32, 20e6), (32, 80e6)]
    runs = []
    for k, base in plan:
        print(f"\n== K = {k}, base {base / 1e6:g} MHz -> {base * k / 1e6:g} MHz at {2 * base * k / 1e9:.2f} GS/s ==")
        run = run_cal_at(fe, k, base, with_dpd=not quick, log=lambda s: print(s, flush=True),
                         standard="11be" if base == 80e6 else "11ac")
        print(f"  scoring waveform: {run.waveform}; loopback EVM before/after: "
              f"{'—' if run.evm_before_db is None else f'{run.evm_before_db:.1f}'} / "
              f"{'—' if run.evm_after_db is None else f'{run.evm_after_db:.1f}'} dB  [{time.time() - t0:.0f}s]")
        if run.final_views:
            v = run.final_views
            print(f"  final EVM as a standard receiver reads it: loopback {v['evm_modem_db']:.1f}, TX alone "
                  f"{v['tx_evm_modem_db']:.1f}, RX alone {v['rx_evm_modem_db']:.1f} dB; RX NF {v['rx_nf_db']:.1f} dB")
        runs.append(run)
    if not quick:
        k, base = 32, 20e6
        print(f"\n== sensitivity: capture length at K = {k}, base {base / 1e6:g} MHz (assumed.cal_capture_symbols) ==")
        print(f"{'symbols':>8} {'samples':>8} {'dpd':>7} {'loopback':>9} {'TX alone':>9} {'RX alone':>9}   (EVM dB; the first row is the column above)")
        for n_sym in (runs[4].n_symbols, 32):
            r = runs[4] if n_sym == runs[4].n_symbols else run_cal_at(fe, k, base, standard="11ac", n_symbols=n_sym)
            dpd = next(row.value for row in r.rows if row.step == "dpd")
            v = r.final_views
            print(f"{r.n_symbols:>8} {r.capture_samples:>8} {dpd:7.1f} {v['evm_modem_db']:9.1f} {v['tx_evm_modem_db']:9.1f} "
                  f"{v['rx_evm_modem_db']:9.1f}")
        no_dpd = run_cal_at(fe, k, base, standard="11ac", with_dpd=False)
        v = no_dpd.final_views
        print(f"{no_dpd.n_symbols:>8} {no_dpd.capture_samples:>8} {'off':>7} {v['evm_modem_db']:9.1f} {v['tx_evm_modem_db']:9.1f} "
              f"{v['rx_evm_modem_db']:9.1f}")
    print("\n== step × K (status, metric) ==")
    labels = [r.label for r in runs]
    print("step                   " + "".join(f"{lab:>18}" for lab in labels))
    for row in compare_runs(runs):
        cells = []
        for k in labels:
            st = row["by_k"].get(k)
            if st is None:
                cells.append(f"{'—':>18}")
            else:
                status, metric, value, _ = st
                v = "" if value is None else f" {value:.1f}"
                cells.append(f"{status + v:>18}")
        print(f"{row['step']:<22} " + "".join(cells))
    print("\n== mechanisms ==")
    for row in compare_runs(runs):
        print(f"- {row['step']}: {row['mechanism']}")
    print(f"\n[{time.time() - t0:.0f}s]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
