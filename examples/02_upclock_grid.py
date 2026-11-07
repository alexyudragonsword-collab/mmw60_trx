"""Example 02 — the "base bandwidth × K" grid for topology B on the zero-IF chain.

Bases: 802.11ac 20 / 40 / 80 / 160 MHz (312.5 kHz) and 802.11be 20 / 40 / 80 /
160 / 320 MHz (78.125 kHz); K = 4 / 8 / 16 / 32.  Every cell: the analytic
EVM floor of each impairment (phase-noise ICI after CPE, uncorrected IQ image
over the occupied band at fs_eff, DAC + ADC at ENOB(fs_eff), the Rapp at
OBO, guard-interval overflow), the floor with the IQ image replaced by a
calibrated residual, the highest MCS each allows, "能 / 不能 + 原因", the
time-domain EVM of the same cell on the wifitrx chain (all impairments and
each alone — the isolation method), the data rate at the top MCS and what
dsp_ip's P = 4 polynomial DPD would cost per bit at that rate.

    python examples/02_upclock_grid.py [--quick]
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

from mmw60 import ENGINE_BANNER, __version__                                   # noqa: E402
from mmw60.config import zero_if_60ghz                                         # noqa: E402
from mmw60.frontend import Frontend60                                          # noqa: E402
from mmw60.frontend.dpd_cost import dsp_ip_models                              # noqa: E402
from mmw60.frontend.grid import HEADER, evaluate_cell, pa_isolated_evm_db      # noqa: E402

BASES = [("11ac", 20e6), ("11ac", 40e6), ("11ac", 80e6), ("11ac", 160e6),
         ("11be", 20e6), ("11be", 40e6), ("11be", 80e6), ("11be", 160e6), ("11be", 320e6)]
KS = (4, 8, 16, 32)


def main(argv=None) -> int:
    print(ENGINE_BANNER)
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args(argv)
    quick = a.quick or os.environ.get("MMW60_SMOKE") == "1"
    t0 = time.time()
    ref = zero_if_60ghz(k=8)
    fe = Frontend60.from_config(ref)
    d = fe.describe()
    print(f"mmw60 {__version__}; {'QUICK' if quick else 'full'}; front end: PA {d['pa']} Psat {d['psat_dbm']:g} dBm "
          f"OBO {d['obo_db']:g} dB from {d['obo_reference']} -> Pout {d['pout_dbm']:g} dBm; LO IPN {d['lo_ipn_dbc']:.1f} dBc "
          f"(10 kHz–100 MHz); TX leak {d['tx_leak_dbc']:g} dBc; RX DC {d['rx_dc_dbc']:g} dBc; IQ "
          f"{ref.frontend.iq.gd_mismatch_ps:g} ps / {ref.frontend.iq.phase_deg:g} deg / {ref.frontend.iq.gain_db:g} dB; "
          f"converters ENOB {ref.frontend.converters.enob_ref:g} @ {ref.frontend.converters.fs_ref_hz / 1e9:g} GS/s, "
          f"-{ref.frontend.converters.bits_per_octave:g} bit/octave; crystal {ref.xo_ppm_tx:g}+{ref.xo_ppm_rx:g} ppm at "
          f"{ref.carrier_hz / 1e9:.2f} GHz = {ref.cfo_hz / 1e6:.3f} MHz; channel {ref.channel.model} "
          f"{ref.channel.rms_delay_ns:g} ns / LOS {ref.channel.los_k_db:g} dB")
    pa_evm = pa_isolated_evm_db(fe.pa_model, fe.obo_db, fe.obo_reference)
    print(f"PA isolated EVM at this OBO (K-independent, memoryless): {pa_evm:.1f} dB")
    print("verdict: 能 = CFO captured, plan fits, MCS0 reachable with the floor 3 dB under the MCS TX-EVM limit;"
          " maxMCS = uncorrected IQ; IQcal = IQ image at the calibrated residual (assumed.irr_after_cal_db);"
          " no-PA = the front end without the PA term (the back-off is the designer's knob per MCS, the rest is not)")
    bases = BASES[::4] if quick else BASES
    ks = (8, 32) if quick else KS
    cells = []
    print("\n" + HEADER)
    for std, bw in bases:
        for k in ks:
            cfg = zero_if_60ghz(k=k, standard=std, bandwidth_hz=bw)
            c = evaluate_cell(cfg, fe, time_domain=True, isolate=not quick, pa_evm_db=pa_evm)
            cells.append(c)
            print(c.row(), flush=True)
    print("\n== analytic terms per cell [dB] ==")
    print("std    base   K   pn     iq    conv   pa     isi   | plan in band  channels  fs_eff[GS/s]  ENOB")
    for c in cells:
        t = c.terms_db
        print(f"{c.standard:<5} {c.base_bw_hz / 1e6:5.0f} x{c.k:<3} "
              + " ".join(f"{t.get(n, float('-inf')):6.1f}" for n in ("phase_noise", "iq_image", "converters", "pa", "isi"))
              + f" | {'yes' if c.plan_ok else 'NO ':<12} {max(1, int(14e9 // c.bw_eff_hz)):>5}      {c.fs_eff_hz / 1e9:6.2f}      "
              f"{fe.converters.enob(c.fs_eff_hz):4.1f}")
    print("\n== data rate at the top MCS and the DPD cost per bit (dsp_ip dpd_poly P = 4, DDR r = 1, Horowitz 45 nm ops) ==")
    print("std    base   K   maxMCS  rate[Mb/s]  DPD rate[GS/s]  pJ/bit   P=4 datapaths")
    m = dsp_ip_models()["ddr_r1_w16"]
    for c in cells:
        if c.max_mcs is None:
            continue
        rate_dpd = 4.0 * c.bw_eff_hz
        print(f"{c.standard:<5} {c.base_bw_hz / 1e6:5.0f} x{c.k:<3} MCS{c.max_mcs:<4} {c.data_rate_mbps:9.0f}   "
              f"{rate_dpd / 1e9:8.2f}      {c.dpd_pj_per_bit:7.0f}   {m.instances_for(rate_dpd):6.2f}")
    print("\n== sensitivity: converters at -1 bit/octave (constant Walden FoM) ==")
    for std, bw, k in (("11ac", 20e6, 16), ("11be", 80e6, 16), ("11be", 160e6, 32)):
        cfg = zero_if_60ghz(k=k, standard=std, bandwidth_hz=bw)
        cfg = dc.replace(cfg, frontend=dc.replace(cfg.frontend, converters=dc.replace(
            cfg.frontend.converters, bits_per_octave=1.0)))
        fe1 = Frontend60.from_config(cfg)
        c = evaluate_cell(cfg, fe1, time_domain=False, pa_evm_db=pa_evm)
        print(f"{std:<5} {bw / 1e6:5.0f} x{k:<3} ENOB {fe1.converters.enob(c.fs_eff_hz):4.1f}  conv term "
              f"{c.terms_db.get('converters', float('nan')):6.1f} dB  floor {c.floor_db:6.1f}  maxMCS {c.max_mcs}")
    print(f"\n[{time.time() - t0:.0f}s]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
