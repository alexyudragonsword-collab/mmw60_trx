"""Example 08 — the shared 60 GHz front end's three faces: receive front end, TX-RX isolation, antenna gains.

A link budget and a radar (fmcw_radar, mmw60_trx#14) read three things off
``Frontend60`` that it did not say out loud before ROADMAP D4:

* the receive front end at its maximum-gain state — gain, noise figure,
  input compression.  The presets run on wifitrx's own ladder, a sub-7 GHz
  WiFi 7 chip's; ``config.surveyed_frontend`` moves it to a 60 GHz
  communication transceiver's figures;
* the isolation between the transmitter output and the receiver input;
* the transmit and receive antenna gains.

The presets do not use any of it (their numbers are the ones they always
were).  The literature figures are of two kinds (data/spec/survey.yaml):
``spec`` entries were read in the original and carry the quoted text,
``survey`` entries were read from a search snippet only.  Every table names
the entry behind each figure and which kind it is.

What the tables answer:

1. the faces, preset against surveyed, with the entry each figure comes from;
2. what the receive noise figure moves: the sensitivity (dB for dB), not the
   link EVM on an SNR axis, and the calibration sequence's own readings;
3. the transmitter's leakage at the receiver input against the receive front
   end's two compression points (in band, and before the baseband high-pass)
   — a TDD link never sees it, a full-duplex link and a radar do, and they
   read different columns;
4. the antenna gains against the EIRP limit and the path loss the link takes;
5. where the receive face is not consumed (topology A).

    python examples/08_frontend_faces.py [--quick]
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

from mmw60 import ENGINE_BANNER, __version__, spec                          # noqa: E402
from mmw60.calcheck import run_cal_at                                       # noqa: E402
from mmw60.config import ChannelConfig, if_extender_60ghz, surveyed_frontend, zero_if_60ghz  # noqa: E402
from mmw60.frontend import Frontend60                                       # noqa: E402
from mmw60.sim.link import LinkSim, evm_at                                  # noqa: E402

K, BASE_BW, STD = 8, 20e6, "11ac"
FLAT = ChannelConfig(model="flat")
SNR_AXIS_DB = 10.0
MCS_ROWS = (0, 4)

#: the receive noise figures looked at: (label, spec key or None for wifitrx's own ladder)
NF_ROWS = (("WiFi 7 chip ladder (the presets)", None),
           ("60 GHz comm. transceiver, 65 nm", "rx60.comm_asada2011"),
           ("60 GHz comm. receiver, 90 nm", "rx60.comm_iscas2015"),
           ("802.11ad sensitivity-table receiver", "dmg.sensitivity_assumptions"),
           ("60 GHz radar chip", "rx60.radar_iwr6843"))


def with_rx_nf(cfg, nf_db):
    """``cfg`` with its receive front end anchored at ``nf_db`` (the IIP3 stays the surveyed pick's)."""
    front = dc.replace(cfg.frontend.rx_front, model="anchored", nf_db=float(nf_db))
    return dc.replace(cfg, frontend=dc.replace(cfg.frontend, rx_front=front))


def tag(key):
    """``key [spec]`` or ``key [survey, unverified]``: how the entry was read."""
    src = spec.survey(key).source
    return f"{key} [{'survey, unverified' if src == 'survey' else src}]"


def fmt(v, unit="", nd=1):
    return "not specified" if v is None else f"{v:.{nd}f}{unit}"


def faces_table(preset, surveyed):
    pick, comm = tag("assumed.frontend_faces_pick"), tag("rx60.comm_asada2011")
    a, b = Frontend60.from_config(preset).faces(), Frontend60.from_config(surveyed).faces()
    rows = (("receive front end", a["rx_front"], b["rx_front"], tag("assumed.rx60_ladder_shape")),
            ("  a 60 GHz figure?", "no" if not a["rx_front_sourced"] else "yes",
             "yes: " + ", ".join(b["rx_front_given"]), pick),
            ("  gain, max state", fmt(a["rx_gain_db"], " dB"), fmt(b["rx_gain_db"], " dB"), comm),
            ("  noise figure", fmt(a["rx_nf_db"], " dB"), fmt(b["rx_nf_db"], " dB"), comm),
            ("  IIP3", fmt(a["rx_iip3_dbm"], " dBm"), fmt(b["rx_iip3_dbm"], " dBm"), comm),
            ("  input P1dB, in band", fmt(a["rx_p1db_inband_dbm"], " dBm"), fmt(b["rx_p1db_inband_dbm"], " dBm"),
             tag("assumed.rx60_p1db_from_iip3_db")),
            ("  input P1dB, out of band", fmt(a["rx_p1db_oob_dbm"], " dBm"), fmt(b["rx_p1db_oob_dbm"], " dBm"),
             "no communication paper read gives it"),
            ("  gain states", f"{a['rx_gain_states']} (down to {a['rx_gain_min_db']:g} dB)",
             f"{b['rx_gain_states']} (down to {b['rx_gain_min_db']:g} dB)", tag("assumed.rx60_ladder_shape")),
            ("TX antenna gain", fmt(a["antenna_gain_tx_dbi"], " dBi"), fmt(b["antenna_gain_tx_dbi"], " dBi"),
             comm),
            ("RX antenna gain", fmt(a["antenna_gain_rx_dbi"], " dBi") + (" (the TX antenna)" if a["shared_antenna"] else ""),
             fmt(b["antenna_gain_rx_dbi"], " dBi") + (" (the TX antenna)" if b["shared_antenna"] else ""),
             comm),
            ("TX-RX isolation", fmt(a["tx_rx_isolation_db"], " dB"), fmt(b["tx_rx_isolation_db"], " dB"),
             tag("isolation.tx_rx_tue2018")))
    print(f"{'face':<26} {'preset':<26} {'surveyed':<31} surveyed figure from")
    for name, x, y, src in rows:
        print(f"{name:<26} {x:<26} {y:<31} {src}")


def main(argv=None) -> int:
    print(ENGINE_BANNER)
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--jobs", type=int, default=1, help="accepted for symmetry with the other examples; this one is serial")
    a = ap.parse_args(argv)
    quick = a.quick or os.environ.get("MMW60_SMOKE") == "1"
    t0 = time.time()
    preset = zero_if_60ghz(k=K, standard=STD, bandwidth_hz=BASE_BW)
    surveyed = surveyed_frontend(preset)
    fe_s = Frontend60.from_config(surveyed)
    pout = fe_s.target_pout_dbm()
    print(f"mmw60 {__version__}; {'QUICK' if quick else 'full'}; topology B, K = {K} on the {STD} {BASE_BW / 1e6:g} MHz base "
          f"({BASE_BW * K / 1e6:g} MHz), carrier {preset.carrier_hz / 1e9:g} GHz, PA output {pout:g} dBm")
    print("[spec] = read in the original, quoted in data/spec; [survey, unverified] = read from a search snippet only; "
          "[assumed] = this library's choice")

    print("\n== 1. the faces: preset against config.surveyed_frontend ==")
    faces_table(preset, surveyed)
    if fe_s.rx_front.iip3_dbm == Frontend60.from_config(preset).rx_front.iip3_dbm:
        print("the surveyed IIP3 happens to equal the WiFi 7 ladder's top state's: the compression rows are the same "
              "for both, by coincidence of the two figures")

    # ---------------------------------------------------------------- 2
    print(f"\n== 2. what the receive noise figure moves (IIP3 kept at {fe_s.rx_front.iip3_dbm:g} dBm) ==")
    thr = {m: spec.per_threshold_db(STD, BASE_BW, m) for m in MCS_ROWS}
    print(f"sensitivity = the receiver input for the measured PER 1e-2 threshold of this receiver (MCS {MCS_ROWS[0]}: "
          f"{thr[MCS_ROWS[0]]:g} dB, MCS {MCS_ROWS[1]}: {thr[MCS_ROWS[1]]:g} dB per active tone; no implementation loss added)")
    print(f"link EVM = time-domain, flat channel, SNR {SNR_AXIS_DB:g} dB per active tone; calibration = wifitrx's sequence, "
          f"profile poweron{', no DPD' if quick else ''}, final check at the preset PA back-off ({fe_s.obo_db:g} dB from "
          f"{fe_s.obo_reference})")
    print(f"{'receive front end':<37} {'NF':>5} {'sens MCS' + str(MCS_ROWS[0]):>10} {'sens MCS' + str(MCS_ROWS[1]):>10} "
          f"{'link EVM':>9} {'cal RX NF':>10} {'loopback':>9} {'TX alone':>9} {'RX alone':>9}   figure from")
    nf_rows = NF_ROWS[:2] if quick else NF_ROWS
    sens0, evms, nfs = [], [], []
    for label, key in nf_rows:
        cfg = preset if key is None else with_rx_nf(surveyed, spec.value(key)["nf_db"])
        fe = Frontend60.from_config(cfg)
        sim = LinkSim(dc.replace(cfg, channel=FLAT), frontend=fe)
        s = {m: sim.rx_input_dbm_for_snr(thr[m]) for m in MCS_ROWS}
        e = evm_at(dc.replace(cfg, channel=FLAT), SNR_AXIS_DB, n_packets=1 if quick else 2, frontend=fe)["evm_db"]
        run = run_cal_at(fe, K, BASE_BW, standard=STD, with_dpd=not quick, obo_db=fe.obo_db)
        v = run.final_views
        print(f"{label:<37} {fe.rx_front.nf_db:5.1f} {s[MCS_ROWS[0]]:10.1f} {s[MCS_ROWS[1]]:10.1f} {e:9.2f} "
              f"{v['rx_nf_db']:10.1f} {v['evm_modem_db']:9.1f} {v['tx_evm_modem_db']:9.1f} {v['rx_evm_modem_db']:9.1f}   "
              f"{'wifitrx DEFAULT_LNA_STATES' if key is None else tag(key)}", flush=True)
        sens0.append(s[MCS_ROWS[0]])
        evms.append(e)
        nfs.append(fe.rx_front.nf_db)
    print(f"(dBm, dBm, dB, dB, dB, dB, dB)  [{time.time() - t0:.0f}s]")
    slope = (sens0[-1] - sens0[0]) / (nfs[-1] - nfs[0])
    print(f"sensitivity against noise figure, first to last row: {slope:.2f} dB per dB")
    print(f"link EVM on the SNR axis, spread over the rows: {max(evms) - min(evms):.2f} dB (the axis is SNR, so the noise "
          f"figure sets the input level, not the EVM)")
    print("the calibration readings move because the sequence observes through the receiver at the loopback level: "
          "'cal RX NF' is the state the AGC sits in there, not the maximum-gain state.  The hand-over levels move with "
          "the noise figure (wifitrx's balance-point rule), so a row can sit one state higher than the row above it")

    # ---------------------------------------------------------------- 3
    iso = spec.value("isolation.tx_rx_tue2018")
    radar = spec.value("rx60.radar_iwr6843")
    fig = spec.value("rx60.radar_iwr6843_fig7_2")
    radar_inband = dict(zip(fig["gain_db"], fig["p1db_inband_dbm"]))
    g_hi, g_lo = max(radar_inband), min(radar_inband)
    iso_rows = (("pick: without the isolation structure, low end", iso["with_ebg_db"] - iso["improvement_max_db"]),
                ("without the isolation structure, high end", iso["with_ebg_db"] - iso["improvement_min_db"]),
                ("with the isolation structure", iso["with_ebg_db"]))
    b = fe_s.leakage_budget()
    print(f"\n== 3. the transmitter's leakage at the receiver input (PA output {pout:g} dBm) ==")
    print("a TDD link never sees it (the receiver is off while the transmitter is on); a radar and a full-duplex link do")
    print("a receiver has two input compression points and the leakage meets one of them: a full-duplex link's leakage "
          "sits at the carrier, in band; an FMCW radar's beats to below the baseband high-pass and meets only the stages "
          "before it (out of band)")
    print(f"{'receive front end, maximum gain':<41} {'in band':>9} {'out of band':>14}   figure from")
    print(f"{'surveyed (60 GHz comm. transceiver)':<41} {b['rx_p1db_inband_dbm']:9.1f} "
          f"{fmt(b['rx_p1db_oob_dbm']):>14}   {tag('rx60.comm_asada2011')} IIP3, {tag('assumed.rx60_p1db_from_iip3_db')}")
    print(f"{'60 GHz radar chip':<41} {radar_inband[g_hi]:9.1f} {radar['p1db_in_oob_dbm']:14.1f}   "
          f"{tag('rx60.radar_iwr6843_fig7_2')} at {g_hi:g} dB gain, {tag('rx60.radar_iwr6843')}")
    print(f"(dBm.  The radar chip's in-band figure moves with its gain: {radar_inband[g_lo]:g} dBm at {g_lo:g} dB; the "
          f"surveyed receiver's {b['rx_p1db_inband_dbm']:.1f} dBm is at {fe_s.rx_front.gain_db:g} dB, so at like gains "
          f"the two in-band figures are {radar_inband[g_lo] - b['rx_p1db_inband_dbm']:.1f} dB apart; the radar chip's own "
          f"two figures are {radar['p1db_in_oob_dbm'] - radar_inband[g_lo]:g} to "
          f"{radar['p1db_in_oob_dbm'] - radar_inband[g_hi]:g} dB apart)")
    print(f"\n{'margin = level − leak':<48} {'dB':>5} {'leak':>7} | {'comm in':>8} {'comm out':>14} | "
          f"{'radar in':>9} {'radar out':>10} | {'max input':>10}   AGC state that takes it in band")
    for label, iso_db in iso_rows:
        fe = dc.replace(fe_s, tx_rx_isolation_db=float(iso_db))
        b = fe.leakage_budget()
        leak = b["leak_at_rx_dbm"]
        idx, st = fe.rx_front.state_for(leak)
        print(f"{label:<48} {iso_db:5.0f} {leak:7.1f} | {b['margin_to_p1db_inband_db']:8.1f} "
              f"{fmt(b['margin_to_p1db_oob_db']):>14} | {radar_inband[g_hi] - leak:9.1f} "
              f"{radar['p1db_in_oob_dbm'] - leak:10.1f} | {b['margin_to_dmg_max_input_db']:10.1f}   "
              f"state {idx}: gain {st.gain_db:g} dB, NF {st.nf_db:.1f} dB")
    print(f"(dB, dBm, then margins in dB; negative = the leak is above the level.  comm = the surveyed front end, "
          f"radar = the radar chip; in / out = in band / out of band; max input {b['dmg_max_input_dbm']:g} dBm is "
          f"{tag('dmg.rx_max_input_dbm')})")
    print("for a radar the column to read is 'out': the surveyed communication front end does not state that figure, so "
          "this table cannot say whether it takes the leakage; its 'in' column answers the full-duplex question only")
    print(f"the isolation figures are {tag('isolation.tx_rx_tue2018')}: one abstract; the {iso_rows[0][1]:g} and "
          f"{iso_rows[1][1]:g} dB rows are a subtraction of its numbers, not a figure it gives")

    # ---------------------------------------------------------------- 4
    gains = ((0.0, "the presets (not specified)"),
             (spec.value("rx60.comm_asada2011")["antenna_gain_dbi"], tag("rx60.comm_asada2011") + ", the pick"),
             (spec.value("antenna60.okada2013_dbi"), tag("antenna60.okada2013_dbi")))
    sim = LinkSim(dc.replace(surveyed, channel=FLAT), frontend=fe_s)
    s0 = sim.rx_input_dbm_for_snr(thr[MCS_ROWS[0]])
    print(f"\n== 4. antenna gains (the same on both ends): EIRP limit and the path loss the link takes at MCS {MCS_ROWS[0]} ==")
    print(f"{'gain':>5} {'EIRP avg':>9} {'margin avg':>11} {'margin peak':>12} {'path loss':>10}   figure from")
    for g, src in gains:
        c = fe_s.eirp.check(pout, float(g))
        print(f"{g:5.1f} {c['eirp_avg_dbm']:9.1f} {c['margin_avg_db']:11.1f} {c['margin_peak_db']:12.1f} "
              f"{pout + 2 * g - s0:10.1f}   {src}")
    print(f"(dBi, dBm, dB, dB, dB; path loss = PA output + TX gain + RX gain − sensitivity {s0:.1f} dBm, the surveyed "
          f"receive front end; one element each end, no array gain — milestone 2)")

    # ---------------------------------------------------------------- 5
    print("\n== 5. where the receive face is not consumed ==")
    if quick:
        print("topology A (skipped in quick mode: it calibrates the chip first)")
    else:
        a0 = if_extender_60ghz()
        a1 = surveyed_frontend(a0)
        t = spec.per_threshold_db(a0.phy.standard, a0.phy.bandwidth_hz, MCS_ROWS[0])
        sa = [LinkSim(dc.replace(c, channel=FLAT)).rx_input_dbm_for_snr(t) for c in (a0, a1)]
        print(f"topology A ({a0.phy.standard} {a0.phy.bandwidth_hz / 1e6:g} MHz): sensitivity at MCS {MCS_ROWS[0]}, preset "
              f"{sa[0]:.1f} dBm, surveyed front end {sa[1]:.1f} dBm, difference {sa[1] - sa[0]:.2f} dB")
        print("its 60 GHz receive stage is unit gain and adds no noise of its own (the image band's folding aside): the "
              "noise figure on its SNR axis is the WiFi 7 chip's ladder, which is what the chip is.  A 60 GHz LNA / mixer "
              "in front of it is not modelled (ROADMAP)")
    print(f"\n[{time.time() - t0:.0f}s]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
