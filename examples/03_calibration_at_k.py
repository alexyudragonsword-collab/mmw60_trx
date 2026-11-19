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

Every run puts its final EVM check at the preset's PA operating point
(back-off from Psat, data/spec: derived.pa60_obo_at_evm_limit_db):
``run_cal_at(obo_db=…)`` trims the drive and reruns the sequence until the
check lands there.  Until 2026-11-13 the sequence ran at wifitrx's default
drive, which lands wherever the PA's gain puts it (ROADMAP C8); the last
sensitivity section shows where that is and what it reads.

ROADMAP C7: the final check's loopback read three ways per column
(``calcheck.loopback_views``) — until wifitrx 0.7.46 the 2.56 GHz
isolation view sat 10 dB under its modem view because of the capture
alignment, not the chain (wifi_trx_cal#7); the table shows the alignment
holds now — and the calibrated 2.56 GHz column in a link over the
conference-room stand-in (the library's own receiver, per-packet
estimates), with the IQ mismatch scaled so its image is the calibrated
residual the comparison table uses (derived.irr_after_cal_measured_db).

    python examples/03_calibration_at_k.py [--quick]
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

import dataclasses as dc                                           # noqa: E402

from mmw60 import ENGINE_BANNER, __version__                       # noqa: E402
from mmw60.calcheck import DEFAULT_PLAN, QUICK_PLAN, compare_runs, loopback_views, run_cal_at  # noqa: E402
from mmw60.compare import measured_irr_after_cal_db                # noqa: E402
from mmw60.config import ChannelConfig, zero_if_60ghz              # noqa: E402
from mmw60.frontend import Frontend60                              # noqa: E402
from mmw60.frontend.grid import analytic_floors, pa_isolated_evm_db  # noqa: E402
from mmw60.sim.link import evm_at                                  # noqa: E402

#: training waveforms (``run_cal_at(waveform_seed=…)``) per cell of the capture-length table
N_SEEDS = 24
FLAT = ChannelConfig(model="flat")


def scaled_iq(cfg, s: float):
    """``cfg`` with every IQ mismatch term (gain, phase, skew, rail ripples) times ``s``."""
    iq = cfg.frontend.iq
    iq2 = dc.replace(iq, gain_db=iq.gain_db * s, phase_deg=iq.phase_deg * s, gd_mismatch_ps=iq.gd_mismatch_ps * s,
                     rail_ripple_db=iq.rail_ripple_db * s, rail_gd_ripple_ns=iq.rail_gd_ripple_ns * s)
    return dc.replace(cfg, frontend=dc.replace(cfg.frontend, iq=iq2))


def image_matched(cfg, target_db: float):
    """``cfg`` with the IQ mismatch scaled (bisection on a log scale) until the
    analytic image term reads ``target_db``."""
    def image(s):
        c = scaled_iq(cfg, s)
        return float(analytic_floors(c, Frontend60.from_config(c), None)["terms_db"]["iq_image"])     # dB
    lo, hi = -3.0, 0.0
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if image(10 ** mid) < target_db else (lo, mid)
    return scaled_iq(cfg, 10 ** (0.5 * (lo + hi))), 10 ** (0.5 * (lo + hi))


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
          f"LO IPN {fe.lo.ipn_dbc():.1f} dBc; calibrated at back-off {fe.obo_db:g} dB from {fe.obo_reference} "
          f"(Psat {fe.psat_dbm:g} dBm)")
    plan = QUICK_PLAN if quick else DEFAULT_PLAN
    runs = []
    for k, base in plan:
        print(f"\n== K = {k}, base {base / 1e6:g} MHz -> {base * k / 1e6:g} MHz at {2 * base * k / 1e9:.2f} GS/s ==")
        run = run_cal_at(fe, k, base, with_dpd=not quick, log=lambda s: print(s, flush=True),
                         standard="11be" if base == 80e6 else "11ac", obo_db=fe.obo_db)
        print(f"  operating point at the final check: Pout {run.pout_dbm:.2f} dBm, back-off "
              f"{fe.psat_dbm - run.pout_dbm:.2f} dB from Psat ({run.passes} run{'s' if run.passes > 1 else ''} "
              "of the sequence)")
        print(f"  scoring waveform: {run.waveform}; loopback EVM before/after: "
              f"{'—' if run.evm_before_db is None else f'{run.evm_before_db:.1f}'} / "
              f"{'—' if run.evm_after_db is None else f'{run.evm_after_db:.1f}'} dB  [{time.time() - t0:.0f}s]")
        if run.final_views:
            v = run.final_views
            print(f"  final EVM as a standard receiver reads it: loopback {v['evm_modem_db']:.1f}, TX alone "
                  f"{v['tx_evm_modem_db']:.1f}, RX alone {v['rx_evm_modem_db']:.1f} dB; RX NF {v['rx_nf_db']:.1f} dB")
        runs.append(run)
    print("\n== the final check's loopback read three ways (ROADMAP C7; dB) ==")
    print(f"{'column':<16} {'isolation':>10} {'CPE first':>9} {'modem':>7} {'phase ramp':>11} {'coherence':>10}")
    for r in runs:
        v = loopback_views(r)
        if v is None:
            print(f"{r.label:<16}   (no scoring waveform)")
            continue
        print(f"{r.label:<16} {v['isolation_db']:10.1f} {v['isolation_cpe_first_db']:9.1f} {v['modem_db']:7.1f} "
              f"{v['phase_ramp_rad']:9.2f} rad {v['cpe_coherence']:10.2f}")
    print("isolation = wifitrx's isolation view as it computes it (the per-tone equaliser, then each symbol's common "
          "phase; since wifitrx 0.7.45, B46); CPE first = the order it used before (the common phase over all tones "
          "on the raw symbols, then the equaliser); modem = wifitrx's modem view (LTF channel estimate, pilot CPE).  "
          "phase ramp = the linear part of the loopback's channel phase across the band (a residual delay the "
          "capture alignment leaves: none since wifitrx 0.7.46, whose delay search follows the loopback delay, "
          "wifi_trx_cal#7; before, 6.06 rad at 2.56 GHz and the CPE-first view read -13.6 dB there); coherence = "
          "|mean of e^(j phase)| over the tones: near 0 a common-phase-first estimate is pulled by the 64-QAM "
          "amplitudes")
    print("\n== the calibrated column in a link over multipath (ROADMAP C7): the library's receiver, per-packet "
          "estimates, IQ mismatch scaled to the calibrated residual the comparison table uses; EVM at no noise, dB ==")
    print(f"{'cell':<22} {'IRR':>5} {'scale':>6} {'floor CR':>9} {'floor flat':>11} {'TD flat':>8} {'TD CR':>6} "
          f"{'ideal CR':>9}")
    n_pk = 2 if quick else 16
    pa_evm = pa_isolated_evm_db(fe.pa_model, fe.obo_db, fe.obo_reference)
    for k in ((32,) if quick else (8, 16, 32)):
        c0 = zero_if_60ghz(k=k, standard="11be", bandwidth_hz=80e6)
        irr, _ = measured_irr_after_cal_db(c0.upclocked().bandwidth_eff)
        c, scale = image_matched(c0, 10 * np.log10(2 * 10 ** (-irr / 10)))
        fe_c = Frontend60.from_config(c)
        f_cr = analytic_floors(c, fe_c, pa_evm)["floor_db"]
        f_fl = analytic_floors(dc.replace(c, channel=FLAT), fe_c, pa_evm)["floor_db"]
        td = {n: evm_at(cc, None, n_packets=n_pk, frontend=fe_c)["evm_db"]
              for n, cc in (("flat", dc.replace(c, channel=FLAT)), ("cr", c))}
        ideal = evm_at(dc.replace(c0.ideal(), channel=c0.channel), None, n_packets=n_pk)["evm_db"]
        print(f"{'11be 80M x' + str(k) + f' ({80 * k / 1e3:g} GHz)':<22} {irr:5.1f} {scale:6.3f} {f_cr:9.1f} {f_fl:11.1f} "
              f"{td['flat']:8.1f} {td['cr']:6.1f} {ideal:9.1f}", flush=True)
    print(f"IRR = the calibrated residual per side (example 03's, derived.irr_after_cal_measured_db); scale = the factor on "
          f"every IQ mismatch term that puts the analytic image there; floor CR includes the ISI beyond the guard "
          f"interval on the stand-in (7 ns rms, LOS K 10 dB), floor flat does not; TD = {n_pk} packets each; ideal CR = "
          "the ideal chain on the same channel (ISI and the receiver's estimates alone)")
    if not quick:
        k, base = 32, 20e6
        print(f"\n== sensitivity: capture length at K = {k}, base {base / 1e6:g} MHz (assumed.cal_capture_symbols) ==")
        print(f"{'symbols':>8} {'samples':>8} {'dpd':>7} {'loopback':>9} {'TX alone':>9} {'RX alone':>9}   (EVM dB; the first row is the column above)")
        for n_sym in (runs[4].n_symbols, 32):
            r = runs[4] if n_sym == runs[4].n_symbols else run_cal_at(fe, k, base, standard="11ac", n_symbols=n_sym,
                                                                          obo_db=fe.obo_db)
            dpd = next(row.value for row in r.rows if row.step == "dpd")
            v = r.final_views
            print(f"{r.n_symbols:>8} {r.capture_samples:>8} {dpd:7.1f} {v['evm_modem_db']:9.1f} {v['tx_evm_modem_db']:9.1f} "
                  f"{v['rx_evm_modem_db']:9.1f}")
        no_dpd = run_cal_at(fe, k, base, standard="11ac", with_dpd=False, obo_db=fe.obo_db)
        v = no_dpd.final_views
        print(f"{no_dpd.n_symbols:>8} {no_dpd.capture_samples:>8} {'off':>7} {v['evm_modem_db']:9.1f} {v['tx_evm_modem_db']:9.1f} "
              f"{v['rx_evm_modem_db']:9.1f}")
        print(f"the training waveform's random data, waveform_seed 0-{N_SEEDS - 1} (the rows above are seed 0), at the same "
              "back-off: how often the DPD step writes a predistorter and what it gains at the PA output (dB, its own "
              "readings)")
        print(f"{'K':>3} {'symbols':>8} {'samples':>8} {'written':>8} {'gain mean':>10} {'median':>7} {'max':>6} {'>= 1 dB':>8}")
        for kk in (1, k):
            for n_sym in (runs[4].n_symbols, 32):
                gains, wrote, smp = [], 0, 0
                for s in range(N_SEEDS):
                    r = run_cal_at(fe, kk, base, standard="11ac", n_symbols=n_sym, obo_db=fe.obo_db, waveform_seed=s)
                    wrote += bool(r.dpd_kept)
                    gains.append(r.dpd_before_db - r.dpd_after_db)
                    smp = r.capture_samples
                print(f"{kk:>3} {n_sym:>8} {smp:>8} {f'{wrote}/{N_SEEDS}':>8} {np.mean(gains):10.2f} {np.median(gains):7.2f} "
                      f"{max(gains):6.2f} {sum(g >= 1.0 for g in gains):>8}", flush=True)
        print("the capture length is not what decides the DPD step here: at this back-off it writes a predistorter for a "
              "minority of training waveforms, at K = 1 as at K = 32")
    if not quick:
        k, base = 8, 20e6
        print(f"\n== sensitivity: wifitrx's default drive at K = {k}, base {base / 1e6:g} MHz (how this example ran "
              "until 2026-11-13) ==")
        print(f"{'drive':<22} {'Pout':>6} {'back-off':>9} {'from P1dB':>10} {'dpd':>7} {'loopback':>9} {'TX alone':>9} "
              f"{'RX alone':>9}")
        p1 = fe.scaled_pa().p1db_out_dbm
        free = run_cal_at(fe, k, base, standard="11ac")
        for name, r in (("preset back-off", runs[2]), ("wifitrx default", free)):
            dpd = next(row.value for row in r.rows if row.step == "dpd")
            v = r.final_views
            print(f"{name:<22} {r.pout_dbm:6.2f} {fe.psat_dbm - r.pout_dbm:9.2f} {p1 - r.pout_dbm:10.2f} {dpd:7.1f} "
                  f"{v['evm_modem_db']:9.1f} {v['tx_evm_modem_db']:9.1f} {v['rx_evm_modem_db']:9.1f}")
        print("(dBm, dB from Psat, dB below P1dB, then EVM dB.  The default drive lands where the PA's gain puts it: "
              "it is not an operating point anyone chose)")
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
