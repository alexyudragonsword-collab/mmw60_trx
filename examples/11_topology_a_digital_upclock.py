"""Example 11 — topology A with only the digital baseband upclocked (A x be_upclocked).

The chip's analog — its DAC / ADC, analog low-pass, 6 GHz radio — and its
14-step calibration stay those of one of its native channels; only the
digital baseband changes: the base PHY (11be 80 MHz, 11ac 20 MHz, ...) runs
on that channel at K x its clock (data/spec: assumed.ifext_upclock).  So
K x base bandwidth has to be a channel the chip has (20 ... 320 MHz).  The
60 GHz stage, the PA, the LO, the crystals and the receiver are the shared
ones (iron rule 2).  What the tables answer:

1. the same 320 MHz analog channel with the subcarrier spacing swept by the
   base PHY: floor, phase-noise term, time-domain EVM, MCS caps, rates and
   pJ/bit, next to topology B on the same occupied band;
2. the CFO (iron rule 3): the preamble is upclocked too, so the chip's own
   L-STF reaches +-625 kHz x K — with and without the multi-link
   pre-compensation; and (2b) how often it loses the offset without the
   multi-link estimate at K = 4 / 8, at low SNR, on the flat and the
   conference-room stand-in channels — next to topology B on the same
   base x K, which always runs without it;
3. that the hardware is the native channel's: the same calibrated chip,
   the same calibration results (iron rule 4).

    python examples/11_topology_a_digital_upclock.py [--quick]
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

from mmw60 import ENGINE_BANNER, __version__, compare, spec                     # noqa: E402
from mmw60.config import (ChannelConfig, if_extender_60ghz, ifext_chip_channels_hz,  # noqa: E402
                          zero_if_60ghz)
from mmw60.frontend import Frontend60                                           # noqa: E402
from mmw60.frontend.grid import analytic_floors                                # noqa: E402
from mmw60.sim.link import LinkSim, evm_at                                      # noqa: E402

FLAT = ChannelConfig(model="flat")
SNR_CFO_DB = 30.0
#: section 2b: SNRs per tone (MCS0 lives near 3 dB), packets per cell, payload (only the preamble matters)
LOCK_SNRS_DB = (0.0, 3.0, 10.0)
LOCK_PACKETS = 400
LOCK_PAYLOAD_BYTES = 64
#: (standard, base bandwidth, K) on topology A; K = 1 is the chip's own waveform
FULL = (("11be", 320e6, 1), ("11be", 80e6, 4), ("11be", 40e6, 8), ("11be", 20e6, 16),
        ("11ac", 20e6, 16), ("11ac", 20e6, 8), ("11ac", 20e6, 4))
QUICK = (("11be", 80e6, 1), ("11ac", 20e6, 4))


def fmt(v, f="{:.1f}"):
    return "—" if v is None else f.format(v)


def label(topo: str, std: str, bw: float, k: int) -> str:
    return f"{topo} {std} {bw / 1e6:g}M" + (f" x{k}" if k > 1 else "")


def a_cfg(std: str, bw: float, k: int):
    return dc.replace(if_extender_60ghz(standard=std, bandwidth_hz=bw, k=k), channel=FLAT)


def main(argv=None) -> int:
    print(ENGINE_BANNER)
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--jobs", type=int, default=1, help="accepted for symmetry; serial")
    a = ap.parse_args(argv)
    quick = a.quick or os.environ.get("MMW60_SMOKE") == "1"
    t0 = time.time()
    cases = QUICK if quick else FULL
    n_pk = 1 if quick else 4
    fe = Frontend60.from_config(zero_if_60ghz(k=8))            # the shared front end
    up = spec.value("assumed.ifext_upclock")
    print(f"mmw60 {__version__}; {'QUICK (numbers meaningless)' if quick else 'full size'}; topology A changes "
          f"{up['changes']}: the analog is {up['analog']}; chip channels "
          f"{', '.join(f'{c / 1e6:g}' for c in ifext_chip_channels_hz())} MHz ({up['channels_from']})")

    # ---------------------------------------------------------------- 1. the table
    print("\n== 1. one analog channel, the subcarrier spacing set by the base PHY (flat channel; floor / TD in dB; "
          "caps: 802.11ad TX-EVM limit / the decoder) ==")
    schemes = []
    for std, bw, k in cases:
        c = a_cfg(std, bw, k)
        schemes.append(compare.Scheme(label("A", std, bw, k), "if_extender", c.waveform, c))
        if k > 1:
            cb = zero_if_60ghz(k=k, standard=std, bandwidth_hz=bw)
            schemes.append(compare.Scheme(label("B", std, bw, k), "upclock_zero_if", cb.waveform, cb))
    rep = compare.build(schemes, fe, time_domain=True)
    print(f"{'scheme':<20} {'chan[M]':>7} {'SCS[k]':>8} {'pn ICI':>7} {'floor':>6} {'TD':>6} {'cap':>5} {'Mb/s':>6} "
          f"{'pJ/b':>6} {'dec':>5} {'Mb/s':>6} {'pJ/b':>6}  dominant")
    for r in rep["_rows"]:
        pj = None if r.power is None else r.power["pj_per_bit"]
        pjd = None if getattr(r, "power_dec", None) is None else r.power_dec["pj_per_bit"]
        pn = r.terms_db.get("phase_noise", np.nan)
        print(f"{r.label:<20} {r.bw_eff_hz / 1e6:7.0f} {r.scs_eff_hz / 1e3:8.1f} {pn:7.1f} "
              f"{r.floor_db:6.1f} {fmt(r.td_evm_db):>6} {fmt(r.max_mcs, 'MCS{}'):>5} {fmt(r.rate_mbps, '{:.0f}'):>6} "
              f"{fmt(pj, '{:.0f}'):>6} {fmt(r.dec_mcs, 'MCS{}'):>5} {fmt(r.dec_rate_mbps, '{:.0f}'):>6} "
              f"{fmt(pjd, '{:.0f}'):>6}  {r.dominant}", flush=True)
    print("A = the chip's analog at its native channel, digital at K x; B = topology B's zero-IF chain at fs x K "
          "(uncalibrated IQ in its floor; its calibrated cap is the comparison table's IQcal column)")

    # ---------------------------------------------------------------- 2. CFO
    print(f"\n== 2. CFO (iron rule 3): 40 ppm at 60.48 GHz = {a_cfg(*cases[0]).cfo_hz / 1e6:.2f} MHz against the "
          f"chip's own L-STF (+-625 kHz x K), with and without the multi-link pre-compensation (link EVM at SNR "
          f"{SNR_CFO_DB:g} dB, {n_pk} packets) ==")
    print(f"{'scheme':<20} {'K':>3} {'L-STF range':>12} {'CFO [sc]':>9} {'caught w/o MLO':>15} {'EVM MLO on':>11} "
          f"{'EVM MLO off':>12} {'|CFO err| off':>14}")
    for std, bw, k in cases:
        c = a_cfg(std, bw, k)
        off = dc.replace(c, ifext=dc.replace(c.ifext, mlo_enabled=False))
        phy = c.upclocked()
        caught = analytic_floors(off, fe)["cfo_captured"]
        e_on = evm_at(c, SNR_CFO_DB, n_packets=n_pk, frontend=fe)
        e_off = evm_at(off, SNR_CFO_DB, n_packets=n_pk, frontend=fe)
        print(f"{label('A', std, bw, k):<20} {k:>3} {phy.stf_capture_hz / 1e6:9.3f} MHz {c.cfo_hz / phy.scs_eff:9.2f} "
              f"{'yes' if caught else 'NO':>15} {e_on['evm_db']:11.2f} {e_off['evm_db']:12.2f} "
              f"{e_off['cfo_err_hz'] / 1e3:10.1f} kHz", flush=True)
    print("MLO on: the sub-7 estimate x f_c / f_sub7 is taken out first (the preset); MLO off: the raw offset reaches "
          "the chip's L-STF / L-LTF.  K = 4 at 60.48 GHz leaves 3 % of range (2.50 against 2.42 MHz); at Liu's "
          "73.44 GHz (2.94 MHz) it would need K >= 8")

    # ---------------------------------------------------------------- 2b. lock rate without MLO
    from scipy.stats import beta
    n_lock = 3 if quick else LOCK_PACKETS
    snrs = LOCK_SNRS_DB[1:2] if quick else LOCK_SNRS_DB
    print(f"\n== 2b. how often the CFO is lost (K = 4 / 8; {n_lock} packets of {LOCK_PAYLOAD_BYTES} B per cell; "
          "lost = |CFO error| beyond half a subcarrier, which the L-LTF cannot take back) ==")
    print(f"{'scheme':<20} {'K':>3} {'channel':<12} {'offset':>9} {'margin':>9} {'SNR':>4} {'beyond range':>13} "
          f"{'95 % upper':>11} {'hand-off':>9} {'rms err (kept)':>15}")

    def lock_row(c, ch_name, snr, topo="A"):
        sim = LinkSim(c, frontend=fe)
        rng = np.random.default_rng(1100 + int(snr))
        err = np.empty(n_lock)
        for i in range(n_lock):
            r = sim.packet(snr, rng)
            err[i] = r.rx.cfo_hat_hz - r.cfo_true_hz
        rng_hz, half = sim.phy.stf_capture_hz, sim.phy.scs_eff / 2
        alias = np.abs(err) > rng_hz                        # the L-STF folded the offset by 2 x its range
        handoff = (np.abs(err) > half) & ~alias             # the coarse error crossed half a subcarrier
        n_a, n_h = int(alias.sum()), int(handoff.sum())
        upper = float(beta.ppf(0.975, n_a + 1, n_lock - n_a))
        kept = err[~(alias | handoff)]
        rms = float(np.sqrt(np.mean(kept ** 2))) if kept.size else float("nan")
        margin = rng_hz - abs(c.cfo_hz)
        print(f"{label(topo, c.phy.standard, c.phy.bandwidth_hz, c.upclock_k):<20} {c.upclock_k:>3} {ch_name:<12} "
              f"{c.cfo_hz / 1e6:5.2f} MHz {margin / 1e3:5.0f} kHz {snr:4.0f} "
              f"{n_a:>5}/{n_lock:<5}  {100 * upper:8.2f} % {n_h:>4}/{n_lock:<4} {rms / 1e3:11.1f} kHz", flush=True)

    for std, bw, k in cases:
        if k not in (4, 8):
            continue
        preset_channel = if_extender_60ghz(standard=std, bandwidth_hz=bw, k=k).channel   # LOS 10 dB, 7 ns rms
        for ch_name, ch in (("flat", FLAT), ("CR stand-in", preset_channel)):
            c = dc.replace(a_cfg(std, bw, k), channel=ch, phy=dc.replace(a_cfg(std, bw, k).phy,
                                                                          packet_bytes=LOCK_PAYLOAD_BYTES))
            off = dc.replace(c, ifext=dc.replace(c.ifext, mlo_enabled=False))
            for snr in snrs:
                lock_row(off, ch_name, snr)
            if ch_name == "flat":
                # no offset at all: the estimators alone, as behind a perfect multi-link pre-compensation
                lock_row(dc.replace(off, xo_ppm_tx=0.0, xo_ppm_rx=0.0), ch_name, snrs[0])
        # topology B on the same base x K: the same estimator pair, the same front end instance and the same
        # channels; B has no multi-link estimate, the full 40 ppm always reaches its L-STF (ROADMAP A2)
        for ch_name, ch in (("flat", FLAT), ("CR stand-in", preset_channel)):
            cb = zero_if_60ghz(k=k, standard=std, bandwidth_hz=bw)
            cb = dc.replace(cb, channel=ch, phy=dc.replace(cb.phy, packet_bytes=LOCK_PAYLOAD_BYTES))
            for snr in snrs:
                lock_row(cb, ch_name, snr, topo="B")
            if ch_name == "flat":
                lock_row(dc.replace(cb, xo_ppm_tx=0.0, xo_ppm_rx=0.0), ch_name, snrs[0], topo="B")
    print("offset = what reaches the chip without the multi-link pre-compensation (40 ppm at 60.48 GHz; 0.00 = the "
          "estimators on no offset at all, as behind a perfect pre-compensation; B rows: what reaches topology B's "
          "receiver, which has no pre-compensation, on the shared front end); margin = the L-STF's range "
          "(+-625 kHz x K) minus it; beyond range = the L-STF folded the offset (95 % upper: Clopper-Pearson on those "
          "counts); hand-off = the L-STF's noisy coarse estimate missed by more than half a subcarrier and the L-LTF "
          "locked one subcarrier off — STF and LTF scale together with K, so that is the estimator pair's low-SNR "
          "behaviour at any K")

    # ---------------------------------------------------------------- 3. the same hardware
    print("\n== 3. the hardware is the native channel's (iron rules 2 and 4): one calibrated chip per channel ==")
    by_chan: dict = {}
    for std, bw, k in cases:
        sim = LinkSim(a_cfg(std, bw, k), frontend=fe)
        assert sim.frontend is fe
        x = (np.random.default_rng(5).standard_normal(4096) + 1j * np.random.default_rng(6).standard_normal(4096)) * 0.1
        y = sim.ifx.tx.chip(x, phi_lo=np.zeros(x.size))
        res = sim.ifx.cal_results
        final = next((r for r in res if r.name == "final_loopback_evm"), None)
        ch = sim.phy.bandwidth_eff
        same = ch in by_chan and np.array_equal(by_chan[ch][0], y) and by_chan[ch][1] is res
        by_chan.setdefault(ch, (y, res))
        print(f"{label('A', std, bw, k):<20} channel {ch / 1e6:5.0f} MHz at {sim.phy.fs_eff / 1e6:6.0f} MS/s; "
              f"{len(res)} calibration steps, {sum(r.passed for r in res)} passed, final loopback EVM "
              f"{fmt(None if final is None else final.metrics_after['evm_db'], '{:.1f}')} dB"
              + ("; chip output and calibration identical to the first row on this channel" if same else ""),
              flush=True)
    print(f"\n[{time.time() - t0:.0f}s]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
