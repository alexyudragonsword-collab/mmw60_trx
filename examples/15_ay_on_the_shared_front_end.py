"""Example 15 — the two 802.11ay waveforms on topology B's hardware (milestone 3, stage 1: EVM only).

Single channel (channel 2, 60.48 GHz, the presets' carrier), normal GI, the
EDMG numerology and MCS table from spec_sources (``edmg.*``, spec_sources#29),
the preset front end (``zero_if_60ghz``'s: the measured 60 GHz PA at 7.5 dB
from Psat, converters, IQ mismatch, LO leakage, RX DC, phase noise, the
crystals' CFO) — one instance for both waveforms, one chain at 5.28 GS/s
(data/spec: assumed.ay_chain_rate).  The question (ROADMAP milestone 3): the
single carrier's lower PAPR buys output power from the same PA; is that
worth more than what the OFDM numerology gives — at the EVM limits the
standard sets for each?

1. the numbers read from spec_sources;
2. PAPR of the transmitted payloads at 5.28 GS/s (SC with the assumed
   root-raised-cosine pulse, 0.15 / 0.35 roll-off as sensitivity rows);
3. each impairment alone on the ideal chain, at the preset back-off (no noise);
4. the floor with everything on — the raw chain, and with the IQ mismatch
   and the TX LO leakage taken as calibrated away (wifitrx's sequence has
   not been run on the ay waveforms yet: milestone 3 stage 2) — and the
   conformance cap it allows at the preset back-off;
5. EVM against back-off on the chain (IQ / LO leakage off), the back-off
   every MCS's TX EVM limit needs, and SC against OFDM at matching
   modulation and code rate;
6. at each PA output power, the best EVM-limited rate of each waveform.

    python examples/15_ay_on_the_shared_front_end.py [--quick]
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
from mmw60.ay import edmg, papr                                   # noqa: E402
from mmw60.config import ChannelConfig, ay_60ghz                  # noqa: E402
from mmw60.frontend import Frontend60                             # noqa: E402
from mmw60.sim.link import LinkSim                                # noqa: E402

FLAT = ChannelConfig(model="flat")
#: one MCS per payload constellation (the EVM payload carries its points; assumed.ay_evm_payload)
SC_REP = {"π/2-BPSK": 6, "π/2-QPSK": 11, "π/2-16-QAM": 16, "π/2-64-QAM": 21}
OFDM_REP = {"QPSK points (DCM BPSK)": 5, "16-QAM points (DCM QPSK)": 10, "16-QAM": 15, "64-QAM": 20}


def tag(key: str) -> str:
    e = spec.survey(key)
    return f"{key} [{e.source}]"


def evm(cfg, fe=None, n: int = 2, seed: int = 0) -> float:
    sim = LinkSim(cfg, frontend=fe)
    rng = np.random.default_rng(seed)
    e = [sim.packet(None, rng).rx.evm_db for _ in range(n)]
    return float(10 * np.log10(np.mean(10 ** (np.asarray(e) / 10))))


def calibrated(cfg):
    """IQ mismatch and TX LO leakage off: what wifitrx's sequence takes out (not run on ay yet)."""
    fe = cfg.frontend
    return dc.replace(cfg, frontend=dc.replace(fe, iq=dc.replace(fe.iq, enabled=False), lo_leak_dbc=None))


def at_obo(cfg, obo):
    return dc.replace(cfg, frontend=dc.replace(cfg.frontend, pa=dc.replace(cfg.frontend.pa, obo_db=float(obo))))


def cross(obos, evms, limit):
    """Smallest back-off on the grid where the EVM curve reaches ``limit`` (linear in dB between
    points); None when it never does."""
    o, e = np.asarray(obos, float), np.asarray(evms, float)
    if e[0] <= limit:
        return float(o[0])
    for i in range(1, o.size):
        if e[i - 1] > limit >= e[i]:
            return float(o[i - 1] + (e[i - 1] - limit) / (e[i - 1] - e[i]) * (o[i] - o[i - 1]))
    return None


def fmt(v, f="{:6.2f}", none="  —   "):
    return none if v is None else f.format(v)


def main(argv=None) -> int:
    print(ENGINE_BANNER)
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--jobs", type=int, default=1, help="accepted for symmetry; this example is serial")
    a = ap.parse_args(argv)
    quick = a.quick or os.environ.get("MMW60_SMOKE") == "1"
    t0 = time.time()
    base = {"ay_sc": ay_60ghz("ay_sc", 16), "ay_ofdm": ay_60ghz("ay_ofdm", 15)}
    fe = Frontend60.from_config(base["ay_sc"])
    cr = edmg.chain_rate()
    print(f"mmw60 {__version__}; {'QUICK (numbers meaningless)' if quick else 'full size'}; channel "
          f"{edmg.channel_of(base['ay_sc'].carrier_hz)} ({base['ay_sc'].carrier_hz / 1e9:g} GHz), normal GI; one "
          f"front end for both: PA Psat {fe.psat_dbm:g} dBm at {fe.obo_db:g} dB from {fe.obo_reference} "
          f"(Pout {fe.target_pout_dbm():.1f} dBm), chain at {cr['fs_hz'] / 1e9:g} GS/s with the filters of a "
          f"{edmg.channel_spacing_hz() / 1e9:g} GHz channel; CFO {base['ay_sc'].cfo_hz / 1e6:.2f} MHz; flat channel; "
          f"no noise unless a section says")

    # ---------------------------------------------------------------- 1. the numbers
    print("\n== 1. the EDMG single-channel numbers (spec_sources#29) ==")
    o, s = edmg.ofdm_numerology(2), edmg.sc_numerology()
    print(f"OFDM ({tag('edmg.ofdm_params')}): {o.fs_hz / 1e9:g} GS/s, {o.n_fft}-point DFT, "
          f"SCS {o.scs_hz / 1e6:.5f} MHz, "
          f"{len(o.data_tones)} data + {len(o.pilot_tones)} pilot tones over ±{max(o.used_tones)}, GI {o.cp} samples; "
          f"channel 2 pilots {list(o.pilot_tones[:3])} … {list(o.pilot_tones[-2:])} "
          f"({tag('edmg.ofdm_pilot_tones_ncb1')})")
    print(f"SC ({tag('edmg.sc_params')}): {s.fs_hz / 1e9:g} Gchip/s, {s.block}-chip blocks, GI {s.guard} chips, "
          f"{s.data_per_block} data chips per block, π/2 rotation")
    print(f"{'wf':<8} {'MCS':>3}  {'modulation':<12} {'rate':>5} {'Mb/s':>8} {'EVM lim':>8}")
    for wf in edmg.WAVEFORMS:
        for e in edmg.mcs_table(wf):
            print(f"{wf:<8} {e.mcs:>3}  {e.modulation:<12} {str(e.code_rate):>5} {e.rate_bps() / 1e6:8.1f} "
                  f"{e.evm_limit_db:8.1f}")
    print(f"(rates: {tag('edmg.sc_rate_mbps')}, {tag('edmg.ofdm_rate_mbps')}; limits: {tag('edmg.sc_mcs')}, "
          f"{tag('edmg.ofdm_mcs')})")

    # ---------------------------------------------------------------- 2. PAPR
    print("\n== 2. PAPR of the transmitted payload at 5.28 GS/s (dB above the mean, exceeded by 1e-3 / 1e-4 "
          "of the samples) ==")
    papr_rows = []
    for label, m in OFDM_REP.items():
        sim = LinkSim(dc.replace(ay_60ghz("ay_ofdm", m).ideal(), channel=FLAT))
        ref, frame = sim.transmit(np.random.default_rng(1))
        x = frame.x[(ref.stf_len + ref.cef_len) * sim.phy.up:]
        papr_rows.append(("ay_ofdm", label, "", papr.papr_db(x, 1e-3), papr.papr_db(x, 1e-4)))
    rolloffs = (0.25,) if quick else (0.15, 0.25, 0.35)
    for ro in rolloffs:
        for label, m in SC_REP.items():
            c = dc.replace(ay_60ghz("ay_sc", m).ideal(), channel=FLAT)
            c = dc.replace(c, ay=dc.replace(c.ay, sc_rolloff=ro))
            sim = LinkSim(c)
            ref, frame = sim.transmit(np.random.default_rng(1))
            x = frame.x[(ref.stf_len + ref.cef_len) * sim.phy.up:-len(sim.taps)]
            papr_rows.append(("ay_sc", label, f"roll-off {ro:g}", papr.papr_db(x, 1e-3), papr.papr_db(x, 1e-4)))
    for wf, label, note, p3, p4 in papr_rows:
        print(f"{wf:<8} {label:<26} {note:<14} {p3:6.2f} {p4:6.2f}")
    print(f"(roll-off {spec.value('assumed.ay_sc_pulse')['rolloff']:g} is {tag('assumed.ay_sc_pulse')}; the others "
          f"are sensitivity rows)")

    # ---------------------------------------------------------------- 3. isolation
    print(f"\n== 3. each impairment alone on the ideal chain, at the preset back-off {fe.obo_db:g} dB (EVM dB, "
          f"no noise; payload π/2-64-QAM for SC, 16-QAM for OFDM) ==")
    n_pk = 1 if quick else 2
    iso = {}
    for wf, cfg in base.items():
        flat = dc.replace(cfg, channel=FLAT)
        ideal = flat.ideal()
        f = flat.frontend
        variants = {
            "ideal chain": ideal,
            "PA": dc.replace(ideal, frontend=dc.replace(ideal.frontend, pa=f.pa)),
            "phase noise": dc.replace(ideal, lo=flat.lo),
            "CFO (estimated)": dc.replace(ideal, xo_ppm_tx=flat.xo_ppm_tx, xo_ppm_rx=flat.xo_ppm_rx),
            "converters": dc.replace(ideal, frontend=dc.replace(ideal.frontend, converters=f.converters)),
            "IQ mismatch (raw)": dc.replace(ideal, frontend=dc.replace(ideal.frontend, iq=f.iq)),
            "TX LO leakage (raw), no CFO": dc.replace(ideal, frontend=dc.replace(ideal.frontend,
                                                                                lo_leak_dbc=f.lo_leak_dbc)),
            "TX LO leakage (raw) + CFO": dc.replace(ideal, xo_ppm_tx=flat.xo_ppm_tx, xo_ppm_rx=flat.xo_ppm_rx,
                                                     frontend=dc.replace(ideal.frontend, lo_leak_dbc=f.lo_leak_dbc)),
            "RX DC + CFO": dc.replace(ideal, xo_ppm_tx=flat.xo_ppm_tx, xo_ppm_rx=flat.xo_ppm_rx,
                                      frontend=dc.replace(ideal.frontend, rx_dc_dbc=f.rx_dc_dbc)),
        }
        if wf == "ay_sc":
            variants["phase noise, one phase per block"] = dc.replace(ideal, lo=flat.lo,
                                                                      ay=dc.replace(ideal.ay, sc_phase="block"))
        iso[wf] = {k: evm(v, n=n_pk) for k, v in variants.items()}
    for k in iso["ay_sc"]:
        o_txt = f"{iso['ay_ofdm'][k]:7.2f}" if k in iso["ay_ofdm"] else "      —"
        print(f"{k:<34} SC {iso['ay_sc'][k]:7.2f}   OFDM {o_txt}")
    print(f"(TX LO leakage {fe.lo.tx_leak_dbc:g} dBc ({tag('assumed.lo_leak_dbc')}): the receiver removes the DC it "
          f"measures on its quiet lead-in, which takes the leak out exactly while there is no CFO; with the CFO the "
          f"leak arrives turning at +CFO, averages out on the lead-in, and is DC again after the CFO correction — on "
          f"OFDM's three empty DC tones, on every SC chip.  The IQ terms are the uncalibrated mismatch, "
          f"{tag('assumed.iq_mismatch')}.  SC tracks the phase between the guards ({tag('assumed.ay_receiver')}); "
          f"'one phase per block' is the sensitivity row)")

    # ---------------------------------------------------------------- 4. floors and caps at the preset back-off
    print("\n== 4. the floor with everything on, at the preset back-off, and the conformance cap it allows ==")
    floors = {"raw": {}, "cal": {}}
    reps = {"ay_sc": SC_REP, "ay_ofdm": OFDM_REP}
    for wf, rep in reps.items():
        for label, m in rep.items():
            cfg = dc.replace(ay_60ghz(wf, m), channel=FLAT)
            e = edmg.mcs_entry(wf, m)
            floors["raw"][(wf, e.tone_order)] = evm(cfg, fe, n=n_pk)
            floors["cal"][(wf, e.tone_order)] = evm(calibrated(cfg), n=n_pk)
            print(f"{wf:<8} {label:<26} raw {floors['raw'][(wf, e.tone_order)]:7.2f}   "
                  f"IQ + LO leak calibrated away {floors['cal'][(wf, e.tone_order)]:7.2f}")

    def cap(wf, floor_of_order):
        ok = [e for e in edmg.mcs_table(wf) if floor_of_order(e.tone_order) <= e.evm_limit_db]
        if not ok:
            return None
        return max(ok, key=lambda e: (e.rate_bps(), e.mcs))

    for which in ("raw", "cal"):
        for wf in edmg.WAVEFORMS:
            best = cap(wf, lambda order: floors[which][(wf, order)])
            txt = "none" if best is None else (f"MCS{best.mcs} {best.modulation} {best.code_rate} "
                                               f"(limit {best.evm_limit_db:g} dB), {best.rate_bps() / 1e9:.3f} Gb/s")
            print(f"cap, {'raw chain' if which == 'raw' else 'IQ + LO leak calibrated away':<28} {wf:<8} {txt}")
    print("(cap = the passing MCS with the highest rate; an MCS passes when the floor of its payload's "
          "constellation is at or under its TX EVM limit)")

    # ---------------------------------------------------------------- 5. back-off per MCS limit
    obos = np.arange(1.0, 15.01, 2.0 if quick else 0.5)
    print("\n== 5. EVM against back-off from Psat on the chain (IQ + LO leak calibrated away), and the back-off "
          "each MCS's limit needs ==")
    curves = {}
    for wf, rep in reps.items():
        for label, m in rep.items():
            cfg = calibrated(dc.replace(ay_60ghz(wf, m), channel=FLAT))
            curves[(wf, edmg.mcs_entry(wf, m).tone_order)] = [evm(at_obo(cfg, ob), n=1) for ob in obos]
    print("back-off  " + "  ".join(f"{f'{wf[3:]} {lab[:12]}':>20}" for wf, rep in reps.items() for lab in rep))
    for i, ob in enumerate(obos):
        print(f"{ob:8.1f}  " + "  ".join(f"{curves[(wf, edmg.mcs_entry(wf, m).tone_order)][i]:20.2f}"
                                          for wf, rep in reps.items() for m in rep.values()))
    need = {}
    for wf in edmg.WAVEFORMS:
        for e in edmg.mcs_table(wf):
            need[(wf, e.mcs)] = cross(obos, curves[(wf, e.tone_order)], e.evm_limit_db)
    psat = fe.psat_dbm
    print(f"\n{'wf':<8} {'MCS':>3}  {'modulation':<12} {'rate':>5} {'Gb/s':>6} {'limit':>6} {'back-off':>9} "
          f"{'Pout dBm':>9}")
    for wf in edmg.WAVEFORMS:
        for e in edmg.mcs_table(wf):
            ob = need[(wf, e.mcs)]
            print(f"{wf:<8} {e.mcs:>3}  {e.modulation:<12} {str(e.code_rate):>5} {e.rate_bps() / 1e9:6.3f} "
                  f"{e.evm_limit_db:6.1f} {fmt(ob, '{:9.2f}', '    never')} "
                  f"{fmt(None if ob is None else psat - ob, '{:9.2f}', '        —')}")
    print(f"(the grid runs {obos[0]:g}–{obos[-1]:g} dB; 'never' = the floor stays above the limit there; at "
          f"{obos[0]:g} dB = met at the smallest back-off on the grid)")

    print("\nSC against OFDM at the same modulation and code rate (ΔPout = SC − OFDM; Δrate = SC / OFDM):")
    pairs = [(sm, om) for sm in range(12, 22) for om in range(11, 21)
             if edmg.mcs_entry("ay_sc", sm).order == edmg.mcs_entry("ay_ofdm", om).order
             and edmg.mcs_entry("ay_sc", sm).code_rate == edmg.mcs_entry("ay_ofdm", om).code_rate
             and edmg.mcs_entry("ay_ofdm", om).modulation[:3] != "DCM"]
    print(f"{'modulation':<10} {'rate':>5}  {'SC MCS':>6} {'limit':>6} {'back-off':>8}   {'OFDM MCS':>8} {'limit':>6} "
          f"{'back-off':>8}   {'ΔPout':>6} {'Δrate':>6}")
    for sm, om in pairs:
        es, eo = edmg.mcs_entry("ay_sc", sm), edmg.mcs_entry("ay_ofdm", om)
        bs, bo = need[("ay_sc", sm)], need[("ay_ofdm", om)]
        dp = None if bs is None or bo is None else bo - bs
        print(f"{eo.modulation:<10} {str(es.code_rate):>5}  {sm:>6} {es.evm_limit_db:6.1f} "
              f"{fmt(bs, '{:8.2f}', '   never')}"
              f"   {om:>8} {eo.evm_limit_db:6.1f} {fmt(bo, '{:8.2f}', '   never')}   {fmt(dp, '{:6.2f}')} "
              f"{es.rate_bps() / eo.rate_bps():6.3f}")

    # ---------------------------------------------------------------- 6. rate at each output power
    print("\n== 6. the best EVM-limited rate at each PA output power (Gb/s; same PA, same chain) ==")
    print(f"{'Pout dBm':>8} {'back-off':>8} {'SC':>14} {'OFDM':>14}")
    for ob in np.arange(1.0, 15.01, 1.0):
        row = []
        for wf in ("ay_sc", "ay_ofdm"):
            ok = [e for e in edmg.mcs_table(wf) if need[(wf, e.mcs)] is not None and need[(wf, e.mcs)] <= ob + 1e-9]
            best = max(ok, key=lambda e: e.rate_bps()) if ok else None
            row.append("—" if best is None else f"{best.rate_bps() / 1e9:.3f} (MCS{best.mcs})")
        print(f"{psat - ob:8.2f} {ob:8.1f} {row[0]:>14} {row[1]:>14}")
    print(f"(single element at {fe.antenna_gain_tx_dbi:g} dBi: EIRP = Pout, far under the regulatory cap; with an "
          f"array the cap binds first and the SC power margin becomes fewer elements or less DC power — stage 2)")
    print(f"\n[{time.time() - t0:.0f}s]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
