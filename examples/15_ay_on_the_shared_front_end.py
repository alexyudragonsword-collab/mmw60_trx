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
6. at each PA output power, the best EVM-limited rate of each waveform;
7. wifitrx's calibration sequence run on the ay chain (iron rule 4;
   ``calcheck.run_cal_ay``, the probe of data/spec: assumed.ay_cal_probe);
8. the floors, caps and matched-pair back-offs again on the chains that
   sequence calibrated, the sequence run anew at every back-off (the TX
   LO-leak cancellation holds only at the gain state it was found at) — the
   check of section 4's "calibrated away"; one row shows what a single
   calibration at the preset back-off reads at 15 dB;
8b. what the single carrier loses on the calibrated chain, item by item:
   each calibration residual (TX IQ, TX LO leak, RX IQ, RX DC) alone on the
   calibrated chain with every other impairment off — the isolation reading,
   not everything-minus-one — and two direct readings: the leak left after
   dc_pre and the TX image rejection across the band;
9. rate against range, one element, line of sight, the calibrated chain at
   every back-off: each MCS's decoder threshold from its DMG twin's
   sensitivity (data/spec: assumed.ay_sensitivity; spec_sources has no
   EDMG sensitivity), the floor as a noise term, the shared front end's
   noise figure, free space plus oxygen; per MCS the back-off that reaches
   farthest while the transmitter meets its EVM limit, and the fastest rate
   each waveform keeps at each distance.  Sensitivity rows: the reference
   receiver's implementation loss kept in, the surveyed 60 GHz front end
   (ROADMAP D4), and the thresholds against this library's measured 11be
   LDPC ones.

    python examples/15_ay_on_the_shared_front_end.py [--quick]
"""
from __future__ import annotations

import argparse
import copy
import dataclasses as dc
import os
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from mmw60 import ENGINE_BANNER, __version__, spec                # noqa: E402
from mmw60 import arraylink as al                                 # noqa: E402
from mmw60.ay import edmg, papr                                   # noqa: E402
from mmw60.calcheck import run_cal_ay                             # noqa: E402
from mmw60.config import ChannelConfig, ay_60ghz, surveyed_frontend  # noqa: E402
from mmw60.frontend import Frontend60                             # noqa: E402
from mmw60.sim.link import DIGITAL_DRIVE_RMS, LinkSim             # noqa: E402

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

    # ---------------------------------------------------------------- 7. calibration on the ay chain
    print("\n== 7. wifitrx's calibration sequence on the ay chain (2.16 GHz, 5.28 GS/s), PA at the preset back-off ==")
    run = run_cal_ay(fe, base["ay_sc"])
    print(f"probe: {run.waveform} ({tag('assumed.ay_cal_probe')}); no DPD (as the be rows)")
    for r in run.rows:
        print(f"  {r.step:<22} {r.status:<9} {r.metric:<16} {fmt(r.value, '{:8.2f}', '       —')}")
    v = run.final_views
    print(f"final check: isolation reading {run.evm_after_db:.2f} dB; "
          f"modem reading {v.get('evm_modem_db', np.nan):.2f} dB "
          f"(TX {v.get('tx_evm_modem_db', np.nan):.2f}, RX {v.get('rx_evm_modem_db', np.nan):.2f}); PA output "
          f"{run.pout_dbm:.2f} dBm.  The isolation reading is the wide-band capture-alignment bias of ROADMAP D5 "
          f"(2.56 GHz: −13.5 against −23.4 dB modem)")

    runs = {}

    def cal_at(obo):
        """The sequence run on fresh chains with the PA at this back-off (one run per back-off, shared by
        both waveforms: the same chain, the same PA target)."""
        if obo not in runs:
            c = at_obo(base["ay_sc"], obo)
            f2 = Frontend60.from_config(c)
            runs[obo] = (f2, run_cal_ay(f2, c))
        return runs[obo]

    def cal_evm(cfg, obo=None, n=n_pk, single=False):
        if obo is None:
            c, f2, r = cfg, fe, run
        elif single:                                     # calibrated at the preset back-off only, drive re-trimmed
            c = at_obo(cfg, obo)
            f2, r = Frontend60.from_config(c), run
        else:
            c = at_obo(cfg, obo)
            f2, r = cal_at(obo)
        sim = LinkSim(c, frontend=f2, chains=copy.deepcopy(r.chains[:2]))
        rng = np.random.default_rng(0)
        e = [sim.packet(None, rng).rx.evm_db for _ in range(n)]
        return float(10 * np.log10(np.mean(10 ** (np.asarray(e) / 10))))

    # ---------------------------------------------------------------- 8. on the calibrated chains
    print("\n== 8. on the chains the sequence calibrated: floors at the preset back-off, against section 4 ==")
    cal_floor = {}
    for wf, rep in reps.items():
        for label, m in rep.items():
            e = edmg.mcs_entry(wf, m)
            cal_floor[(wf, e.tone_order)] = cal_evm(dc.replace(ay_60ghz(wf, m), channel=FLAT))
            print(f"{wf:<8} {label:<26} calibrated {cal_floor[(wf, e.tone_order)]:7.2f}   section 4: raw "
                  f"{floors['raw'][(wf, e.tone_order)]:7.2f}, calibrated away {floors['cal'][(wf, e.tone_order)]:7.2f}")
    for wf in edmg.WAVEFORMS:
        best = cap(wf, lambda order: cal_floor[(wf, order)])
        txt = "none" if best is None else (f"MCS{best.mcs} {best.modulation} {best.code_rate} "
                                           f"(limit {best.evm_limit_db:g} dB), {best.rate_bps() / 1e9:.3f} Gb/s")
        print(f"cap, calibrated chain {wf:<8} {txt}")
    obos8 = obos
    sub = {("ay_sc", 16): SC_REP["π/2-16-QAM"], ("ay_sc", 64): SC_REP["π/2-64-QAM"],
           ("ay_ofdm", 16): OFDM_REP["16-QAM"], ("ay_ofdm", 64): OFDM_REP["64-QAM"]}
    cal_curves = {key: [cal_evm(dc.replace(ay_60ghz(key[0], m), channel=FLAT), ob, n=1) for ob in obos8]
                  for key, m in sub.items()}
    one = dc.replace(ay_60ghz("ay_sc", SC_REP["π/2-16-QAM"]), channel=FLAT)
    leak_on, leak_off = cal_evm(one, 15.0, single=True), cal_evm(dc.replace(one, xo_ppm_tx=0.0, xo_ppm_rx=0.0),
                                                                 15.0, single=True)
    print(f"\none calibration at {fe.obo_db:g} dB, run at 15 dB (drive re-trimmed, π/2-16-QAM): {leak_on:.2f} dB; "
          f"the same without the CFO {leak_off:.2f} dB; calibrated at 15 dB {cal_evm(one, 15.0):.2f} dB — the TX "
          f"LO-leak cancellation found at one gain state does not hold at another, and what is left is DC that "
          f"only the CFO carries past the receiver's DC removal")
    print("\nSC against OFDM at the same modulation and code rate on the calibrated chains (back-off from Psat; "
          "ΔPout = SC − OFDM; section 5's ΔPout beside it):")
    print(f"{'modulation':<10} {'rate':>5}  {'SC':>6} {'OFDM':>6}  {'ΔPout':>6}   {'sec. 5':>6}")
    for sm, om in pairs:
        es, eo = edmg.mcs_entry("ay_sc", sm), edmg.mcs_entry("ay_ofdm", om)
        bs = cross(obos8, cal_curves[("ay_sc", es.tone_order)], es.evm_limit_db)
        bo = cross(obos8, cal_curves[("ay_ofdm", eo.tone_order)], eo.evm_limit_db)
        dp = None if bs is None or bo is None else bo - bs
        b5s, b5o = need[("ay_sc", sm)], need[("ay_ofdm", om)]
        d5 = None if b5s is None or b5o is None else b5o - b5s
        print(f"{eo.modulation:<10} {str(es.code_rate):>5}  {fmt(bs, '{:6.2f}', ' never')} "
              f"{fmt(bo, '{:6.2f}', ' never')}  "
              f"{fmt(dp, '{:6.2f}')}   {fmt(d5, '{:6.2f}')}")

    # ---------------------------------------------------------------- 8b. the residual, item by item
    print("\n== 8b. what the single carrier loses on the calibrated chain, item by item: each calibration residual "
          "alone on the calibrated chain, every other impairment off (converters, phase noise, receiver noise; the "
          "PA switched off after the VGA was trimmed with it in), the CFO on (EVM dB, 16-QAM payloads) ==")
    items = {"tx_iq": "TX IQ", "tx_leak": "TX LO leak", "rx_iq": "RX IQ", "rx_dc": "RX DC"}

    def stripped(cfg, f2, r, keep):
        tx, rx = copy.deepcopy(r.chains[:2])
        tx.params.dac.enabled = False
        tx.params.lo.enabled = False
        rx.params.adc.enabled = False
        rx.params.lo.enabled = False
        rx.noise_enabled = False
        rx.params.nonlin_enabled = False
        if "tx_iq" not in keep:
            tx.params.iq.enabled, tx.w1, tx.w2 = False, None, None
        if "tx_leak" not in keep:
            tx.params.lo_leak_dbm, tx.dc_pre = None, 0j
        if "rx_iq" not in keep:
            rx.params.iq.enabled, rx.w1, rx.w2, rx.w2_by_state, rx.frac_delay_iq = False, None, None, {}, 0.0
        if "rx_dc" not in keep:
            rx.params.dc_offset, rx.dc_ana, rx.dc_post = tuple(0j for _ in rx.params.dc_offset), {}, {}
        sim = LinkSim(cfg, frontend=f2, chains=[tx, rx])
        sim.tx.params.pa_enabled = False          # after the VGA trim: dc_pre holds at that gain state only
        rng = np.random.default_rng(0)
        e = [sim.packet(None, rng).rx.evm_db for _ in range(n_pk)]
        return float(10 * np.log10(np.mean(10 ** (np.asarray(e) / 10))))

    def irr_db(tx, fs, f_hz, n=8192):
        t = copy.deepcopy(tx)
        t.params.lo_leak_dbm, t.dc_pre, t.params.pa_enabled, t.params.lo.enabled = None, 0j, False, False
        k = int(round(f_hz / fs * n))
        y = np.fft.fft(t(0.05 * np.exp(2j * np.pi * k * np.arange(n) / n)))
        return float(10 * np.log10(abs(y[k]) ** 2 / max(abs(y[-k]) ** 2, 1e-30)))

    edges = (0.5e9, 0.86e9, 1.0e9, 1.1e9)
    for ob in (fe.obo_db, 15.0):
        f2, r = cal_at(ob)
        print(f"back-off {ob:g} dB:")
        for wf, m in (("ay_sc", SC_REP["π/2-16-QAM"]), ("ay_ofdm", OFDM_REP["16-QAM"])):
            c = at_obo(dc.replace(ay_60ghz(wf, m), channel=FLAT), ob)
            alone = {k: stripped(c, f2, r, (k,)) for k in items}
            base_e = stripped(c, f2, r, ())
            no_cfo = stripped(dc.replace(c, xo_ppm_tx=0.0, xo_ppm_rx=0.0), f2, r, ("tx_leak",))
            no_rm = stripped(dc.replace(c, rx=dc.replace(c.rx, dc_removal=False)), f2, r, ("tx_leak",))
            away_e = evm(calibrated(c), n=n_pk)
            full = cal_evm(dc.replace(ay_60ghz(wf, m), channel=FLAT), ob)
            psum = 10 * np.log10(10 ** (away_e / 10) + sum(10 ** (v / 10) for v in alone.values()))
            print(f"  {wf:<8} none {base_e:7.2f}  " + "  ".join(f"{items[k]} {v:7.2f}" for k, v in alone.items())
                  + f"  TX LO leak without the CFO {no_cfo:7.2f}, without the lead-in DC removal {no_rm:7.2f};  "
                    f"calibrated away {away_e:7.2f} + these = "
                    f"{psum:7.2f}, the calibrated chain {full:7.2f}")
        sim = LinkSim(at_obo(dc.replace(base["ay_sc"], channel=FLAT), ob), frontend=f2,
                      chains=copy.deepcopy(r.chains[:2]))
        _, fr = sim.transmit(np.random.default_rng(0))
        tx = copy.deepcopy(sim.tx)
        tx.params.lo.enabled = False
        sig = tx(fr.x * DIGITAL_DRIVE_RMS)
        leak = copy.deepcopy(tx)(np.zeros_like(fr.x))[-1000:]
        raw = copy.deepcopy(tx)
        raw.dc_pre = 0j
        raw_leak = raw(np.zeros_like(fr.x))[-1000:]
        p_sig = float(np.mean(abs(sig) ** 2))
        uncorr = copy.deepcopy(sim.tx)
        uncorr.w1 = uncorr.w2 = None
        print(f"  direct: TX LO leak left after dc_pre {10 * np.log10(np.mean(abs(leak) ** 2) / p_sig):.1f} dBc "
              f"(without dc_pre {10 * np.log10(np.mean(abs(raw_leak) ** 2) / p_sig):.1f}); TX image rejection at "
              + ", ".join(f"{f / 1e9:g}" for f in edges) + " GHz: "
              + ", ".join(f"{irr_db(sim.tx, sim.phy.fs_eff, f):.1f}" for f in edges)
              + " dB (uncorrected " + ", ".join(f"{irr_db(uncorr, sim.phy.fs_eff, f):.1f}" for f in edges)
              + "; the probe spans ±0.86 GHz, the SC payload ±1.10 GHz)")
    print("isolation: one residual at a time, read directly (contributions do not add up as powers in general; the "
          "power sum is a check, not a decomposition).  The leak costs only with the CFO (without it the receiver's "
          "DC removal on its quiet lead-in takes the leak out exactly), and on SC 6-8 dB more than its own power: "
          "part of that is the lead-in DC removal subtracting a leak that turns at the CFO there, the rest is not "
          "attributed yet (not the SC phase tracking, not the channel-estimate window: ROADMAP milestone 3).  OFDM "
          "puts the leak on its three empty DC tones")

    # ---------------------------------------------------------------- 9. rate against range
    print("\n== 9. rate against range: one element, line of sight, the calibrated chain at every back-off "
          f"({tag('assumed.ay_sensitivity')}: the DMG twin's sensitivity, its reference NF and implementation "
          "loss taken out; the floor as a noise term) ==")
    orders = {"ay_sc": {e.tone_order: e.mcs for e in edmg.mcs_table("ay_sc")},
              "ay_ofdm": {e.tone_order: e.mcs for e in edmg.mcs_table("ay_ofdm")}}
    for wf, by_order in orders.items():
        for o, m in by_order.items():
            if (wf, o) not in cal_curves:
                cal_curves[(wf, o)] = [cal_evm(dc.replace(ay_60ghz(wf, m), channel=FLAT), ob, n=1) for ob in obos8]
    g_tx, g_rx = fe.antenna_gain_tx_dbi, fe.antenna_gain_rx_resolved_dbi
    rx_sim = {wf: LinkSim(dc.replace(ay_60ghz(wf, 1), channel=FLAT), frontend=fe, chains=copy.deepcopy(run.chains[:2]))
              for wf in orders}
    i0 = int(np.argmin(np.abs(obos8 - fe.obo_db)))

    def ranges_at(wf, i, sim=None, keep_il=False, gains=(g_tx, g_rx)):
        f2, _ = cal_at(float(obos8[i]))
        floors_i = {o: cal_curves[(wf, o)][i] for o in orders[wf]}
        return al.ay_mcs_ranges(sim or rx_sim[wf], floors_i, f2.target_pout_dbm() + gains[0], gains[1],
                                keep_implementation_loss=keep_il)

    table = {wf: [ranges_at(wf, i) for i in range(len(obos8))] for wf in orders}
    best = {}
    print(f"{'wf':<8} {'MCS':>3}  {'modulation':<12} {'rate':>5} {'Gb/s':>6} {'DMG':>4} {'T[dB]':>6}  "
          f"{'@preset m':>9}  {'best m':>7} {'back-off':>8} {'Pout':>6} {'floor':>6}")
    for wf in orders:
        for m in table[wf][0]:
            e = edmg.mcs_entry(wf, m)
            cands = [(r[m]["range_m"], i) for i, r in enumerate(table[wf]) if r[m]["conforms"] and r[m]["range_m"]]
            b = max(cands) if cands else None
            best[(wf, m)] = None if b is None else b[0]
            r0 = table[wf][i0][m]
            at_preset = r0["range_m"] if r0["conforms"] else None
            bo = None if b is None else float(obos8[b[1]])
            edge = "*" if b is not None and b[1] == 0 else " "
            print(f"{wf:<8} {m:>3}  {e.modulation:<12} {str(e.code_rate):>5} {e.rate_bps() / 1e9:6.3f} "
                  f"{table[wf][0][m]['twin']:>4} {table[wf][0][m]['threshold_db']:6.2f}  "
                  f"{fmt(at_preset, '{:9.2f}', '        —')}  {fmt(None if b is None else b[0], '{:7.2f}', '      —')} "
                  f"{fmt(bo, '{:7.1f}', '      —')}{edge} {fmt(None if b is None else psat - bo, '{:6.1f}', '     —')} "
                  f"{fmt(None if b is None else table[wf][b[1]][m]['floor_db'], '{:6.2f}', '     —')}")
    print(f"(EIRP = Pout + {g_tx:g} dBi, receive {g_rx:g} dBi, the preset receive ladder: NF "
          f"{rx_sim['ay_sc']._rx_nf_db():.1f} dB at the sensitivity's AGC state, not a 60 GHz figure — ROADMAP C9; "
          f"oxygen {al.oxygen_db_per_km():g} dB/km; '—' at the preset = the floor misses the TX EVM limit there; "
          f"* = the grid's smallest back-off ({obos8[0]:g} dB), the best may lie below it; "
          f"MCS without a DMG twin are not listed)")
    dists = (1.0, 1.5, 2.0, 3.0, 5.0, 8.0)
    print("\nthe fastest rate each waveform keeps at each distance (Gb/s, MCS; each MCS at its best back-off):")
    print(f"{'m':>5} " + " ".join(f"{wf:>16}" for wf in orders))
    for d in dists:
        cells = []
        for wf in orders:
            ok = [m for m in table[wf][0] if best[(wf, m)] is not None and best[(wf, m)] >= d]
            top = max(ok, key=lambda m: edmg.mcs_entry(wf, m).rate_bps()) if ok else None
            cells.append("—" if top is None else f"{edmg.mcs_entry(wf, top).rate_bps() / 1e9:.3f} (MCS{top})")
        print(f"{d:5.1f} " + " ".join(f"{c:>16}" for c in cells))
    caps = {"ay_sc": 14, "ay_ofdm": 13}
    print("\nsensitivity rows, at the preset back-off, for the comparison table's calibrated caps "
          "(SC MCS14, OFDM MCS13; metres):")
    sv_cfg = {wf: surveyed_frontend(dc.replace(ay_60ghz(wf, 1), channel=FLAT)) for wf in orders}
    sv_fe = {wf: Frontend60.from_config(c) for wf, c in sv_cfg.items()}
    sv_sim = {wf: LinkSim(sv_cfg[wf], frontend=sv_fe[wf]) for wf in orders}
    for wf, m in caps.items():
        base_r = table[wf][i0][m]["range_m"]
        il = ranges_at(wf, i0, keep_il=True)[m]["range_m"]
        sv = ranges_at(wf, i0, sim=sv_sim[wf], gains=(sv_fe[wf].antenna_gain_tx_dbi,
                                                      sv_fe[wf].antenna_gain_rx_resolved_dbi))[m]["range_m"]
        print(f"  {wf:<8} MCS{m}: preset {base_r:.2f}; implementation loss kept in {il:.2f}; surveyed 60 GHz front end "
              f"(NF {sv_sim[wf]._rx_nf_db():.1f} dB at its AGC state, {sv_fe[wf].antenna_gain_tx_dbi:g} + "
              f"{sv_fe[wf].antenna_gain_rx_resolved_dbi:g} dBi) {sv:.2f}")
    print("the DMG-derived thresholds against this library's measured 11be LDPC thresholds "
          "(data/spec/per_thresholds.yaml, 80 MHz) at the same modulation and code rate:")
    for lab, wf, m, be_mcs in (("QPSK 1/2", "ay_ofdm", 6, 1), ("16-QAM 1/2", "ay_ofdm", 11, 3),
                               ("16-QAM 3/4", "ay_ofdm", 13, 4), ("16-QAM 3/4", "ay_sc", 14, 4)):
        t = table[wf][0][m]["threshold_db"]
        tb = spec.per_threshold_db("11be", 80e6, be_mcs)
        print(f"  {lab:<10} {wf:<8} MCS{m:<2} {t:6.2f} dB   11be MCS{be_mcs} {tb:6.2f} dB   "
              f"difference {t - tb:+5.2f} dB")
    print(f"\n[{time.time() - t0:.0f}s]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
