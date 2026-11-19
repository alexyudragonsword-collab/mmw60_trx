"""Example 10 — milestone 2, the array layer: link budget and beam-training SNR budget.

N elements of the shared front end at each end (``frontend/array60.py`` on
arraytx's geometry, vendored @286609e; data/spec: assumed.array_*), the same
array for both topologies (iron rule 2).  What the tables answer:

1. the array's faces: gain on transmit and receive, scan loss, beamwidth,
   the codebook, the phase shifters' and the element errors' cost;
2. the EIRP limit: N elements at the front end's operating point exceed it
   from some N on, every element then backs off together — and the PA gets
   more linear: per-element output, back-off, PA EVM, floor, decoder cap;
3. the data link: the largest path loss each MCS takes (EIRP + receive
   gain - the topology's own sensitivity at that MCS's required SNR), and
   the distance it means over line of sight: free space plus the oxygen
   absorption, an estimate (data/spec: assumed.oxygen_absorption; 3b: the
   distance at other absorptions — the path loss is the answer, the
   distance follows the estimate); 3c: the power per bit at the decoder
   cap with N PAs and one phase shifter per element (data/spec:
   assumed.array_phase_shifter_power_mw);
4. the beam training, MLO-triggered (data/spec: assumed.array_training):
   the per-tone SNR a sector sweep needs, the path loss the transmit sweep
   (far end on one element) and the receive sweep take against the data
   link's, and how long the sweeps last; 4b: how many repetitions of the
   training field the transmit sweep needs to reach the MCS0 edge (data/
   spec: assumed.array_training_repetition) and what that costs in time;
   4c: a two-stage sweep (an m-element sub-array's wide sectors, then the
   full array inside the chosen one) against the flat one at N = 64, at
   the MCS0 edge and at the decoder cap's distance;
3d. the two 802.11ay waveforms on the same arrays and the same front end
   (milestone 3): floors on the chain wifitrx's sequence calibrated at each
   per-element back-off, thresholds measured with spec_sources#33's codes
   (data/spec/ay_per_thresholds.yaml; SC MCS 1's repetition and OFDM's DCM
   through spec_sources#43), the be rows' decoder-cap rule; each element at
   the shared preset back-off and at the waveform's own operating point (the
   preset rule on its own envelope, data/spec: assumed.ay_operating_point);
   then the smallest array that reaches the EIRP limit at each operating
   point, and what it costs;
4d. the 802.11ay waveforms' own sector sweep: one SSW frame per sector in
   the DMG control PHY (data/spec: assumed.ay_sector_sweep), its threshold
   from the MCS 0 sensitivity, how far the transmit and receive sweeps reach
   on the same arrays against the ay data link's edges, next to the
   MLO-triggered be row; how long the sweep lasts (the control PHY's
   preamble, header and SSW frame, SBIFS apart: spec_sources#33) next to
   the be row's;
5. the squint of phase-shifter steering across the occupied band (arraytx's
   beam response), against true time delay;
6. the assumed inputs, one at a time.

Every number comes from ``mmw60.arrayreport.build`` (one plain dict, the
same a graphical page reads); this file only formats it, piece by piece as
the run produces it.

    python examples/10_array_link_and_training.py [--quick]
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from mmw60 import ENGINE_BANNER, arrayreport                                # noqa: E402
from mmw60.config import zero_if_60ghz                                      # noqa: E402
from mmw60.frontend import Frontend60                                       # noqa: E402

NAN = float("nan")


def fmt(v, f="{:.1f}"):
    return "—" if v is None else f.format(v)


def z2(v):
    """``v`` at two decimals without a negative zero."""
    return round(v, 2) + 0.0


# ---------------------------------------------------------------- each section: heading, row, footnote
def intro(rep, quick):
    h = rep["header"]
    print(f"mmw60 {h['version']}; {'QUICK (numbers meaningless)' if quick else 'full size'}; one Frontend60 at every "
          f"element: PA Pout {h['pa_pout_dbm']:.1f} dBm (back-off {h['obo_db']:g} dB from Psat), receive NF "
          f"{h['rx_nf_db']:g} dB, "
          f"element {h['element_gain_dbi']:g} dBi; EIRP limit {h['eirp_limit_dbm']:g} dBm avg (FCC 15.255)")
    print(f"arrays: n x 1 at both ends, {h['spacing_lambda']:g} lambda, element factor {h['element_pattern']}, "
          f"{h['phase_bits']}-bit phase shifters, element errors "
          f"{h['element_errors']}; line of sight at the carrier, free space plus "
          f"{h['oxygen_db_per_km']:g} dB/km oxygen absorption (an estimate)")


def faces_head(rep):
    scan = f"scan {rep['header']['scan_deg']:g}"
    print("\n== 1. the array's faces (beam at broadside unless stated; dB) ==")
    print(f"{'N':>3} {'TX gain':>8} {'RX gain':>8} {scan:>8} {'BW3dB':>6} {'sectors':>8} "
          f"{'phase loss':>11} {'+errors':>8}")


def faces_row(rep, r):
    bw = NAN if r["beamwidth_3db_deg"] is None else r["beamwidth_3db_deg"]
    print(f"{r['n']:>3} {r['tx_gain_db']:8.2f} {r['rx_gain_db']:8.2f} {r['scan_rel_db']:8.2f} {bw:6.1f} "
          f"{r['sectors']:>8} {r['phase_loss_db']:11.2f} {r['phase_and_error_loss_db']:8.2f}")


def faces_foot(rep):
    print("TX gain = EIRP over one element's output (20 log10 N + element); RX gain = SNR gain (10 log10 N + element); "
          "phase loss = the shifters' gain loss averaged over the scan, +errors = with the element errors too")


def link_head(rep):
    print("\n== 2. the EIRP limit and the per-element operating point; 3. the data link (largest path loss, dB) ==")
    print(f"{'scheme':<26} {'N':>3} {'Pe':>6} {'OBO':>6} {'PA EVM':>7} {'EIRP':>6} {'G_rx':>6} {'floor':>6} {'cap':>5} "
          f"{'PL MCS0':>8} {'PL cap':>7} {'d MCS0 [m]':>11} {'d cap [m]':>10}")


def link_row(rep, r):
    print(f"{r['scheme']:<26} {r['n']:>3} {r['element_pout_dbm']:6.1f} {r['obo_db']:6.2f} {r['pa_evm_db']:7.1f} "
          f"{r['eirp_dbm']:6.1f} "
          f"{r['rx_gain_db']:6.1f} {r['floor_db']:6.1f} {fmt(r['cap_mcs'], 'MCS{}'):>5} "
          f"{fmt(r['path_loss_mcs0_db']):>8} {fmt(r['path_loss_cap_db']):>7} "
          f"{fmt(r['range_mcs0_m'], '{:.0f}'):>11} "
          f"{fmt(r['range_cap_m'], '{:.0f}'):>10}", flush=True)


def link_foot(rep):
    h = rep["header"]
    print(f"Pe / OBO: the per-element output and its back-off from Psat (the front end's {h['obo_db']:g} dB unless the "
          f"EIRP limit asks for more); PL = EIRP + G_rx - sensitivity at the MCS's required SNR over the floor; "
          f"d = the "
          f"distance of that path loss at {h['carrier_ghz']:g} GHz: free space plus {h['oxygen_db_per_km']:g} "
          "dB/km oxygen (an estimate; 3b)")


def oxygen_head(rep):
    alphas = rep["header"]["oxygen_alphas_db_per_km"]
    print("\n== 3b. sensitivity: the MCS0 distance (m) at other oxygen absorptions (the path loss does not move) ==")
    print(f"{'scheme':<26} {'N':>3} {'PL MCS0':>8} " + " ".join(f"{f'{a:g} dB/km':>10}" for a in alphas))


def oxygen_row(rep, r):
    print(f"{r['scheme']:<26} {r['n']:>3} {r['path_loss_mcs0_db']:8.1f} "
          + " ".join(f"{d:10.0f}" for d in r["range_mcs0_by_alpha_m"]))


def oxygen_foot(rep):
    print(f"0 dB/km = free space alone; {rep['header']['oxygen_db_per_km']:g} dB/km is the preset (the round figure "
          "for the "
          "absorption peak near 60 GHz at sea level, no original consulted: ROADMAP B)")


def power_head(rep):
    h = rep["header"]
    print(f"\n== 3c. power per link direction at the decoder cap: N PAs at the per-element output, one phase shifter "
          f"per element and side ({h['phase_shifter_mw']:g} mW, assumed; none at N = 1), the rest as the "
          "single-element column ==")
    print(f"{'scheme':<26} {'N':>3} {'Pe':>6} {'PAE %':>6} {'PA mW':>7} {'PS mW':>7} {'rest mW':>8} {'total mW':>9} "
          f"{'cap':>5} {'Mb/s':>6} {'pJ/b':>6} " + " ".join(f"{f'PS {w:g} mW':>9}" for w in h["phase_shifter_alt_mw"]))


def power_row(rep, r):
    if r["cap_mcs"] is None:
        print(f"{r['scheme']:<26} {r['n']:>3}   no decoder cap")
        return
    print(f"{r['scheme']:<26} {r['n']:>3} {r['element_pout_dbm']:6.1f} {r['pae_pct']:6.1f} {r['pa_mw']:7.0f} "
          f"{r['phase_shifters_mw']:7.0f} "
          f"{r['rest_mw']:8.0f} {r['total_mw']:9.0f} {fmt(r['cap_mcs'], 'MCS{}'):>5} "
          f"{r['rate_mbps']:6.0f} {r['pj_per_bit']:6.0f} " + " ".join(f"{v:9.0f}" for v in r["pj_per_bit_alt"]),
          flush=True)


def power_foot(rep):
    print("PA = N_tx x Pout / PAE(Pout) at the per-element output (class-B law; the EIRP limit backs every element off "
          "together from some N on, and PAE drops with it); PS = (N_tx + N_rx) phase shifters; rest = synthesizers, "
          "converters, FFT, decoder (and topology A's chip PA and DPD) as in the comparison table; LNA / mixer per "
          "receive element not counted, as in the single-element column; N = 1 is the comparison table's own column")


def ay_head(rep):
    h = rep["header"]
    print("\n== 3d. the two 802.11ay waveforms (topology B, EDMG channel 2) on the same arrays and front end: floors "
          "on the chain wifitrx's sequence calibrated at each per-element back-off; thresholds measured with "
          "spec_sources#33's codes (data/spec/ay_per_thresholds.yaml; SC MCS 1's repetition and OFDM's DCM "
          "through spec_sources#43); the decoder cap by the be rows' rule ==")
    print("each element at the shared preset back-off, and at the waveform's own operating point — the preset rule "
          "(the PA alone at the 802.11ad 16-QAM 3/4 TX EVM limit) on its own 16-QAM payload "
          "(assumed.ay_operating_point): "
          + "; ".join(f"{o['waveform']} {o['own_obo_db']:.2f} dB (the PA alone at the preset {h['obo_db']:g} dB: "
                      f"{o['pa_alone_evm_at_preset_db']:.1f} dB)" for o in rep["ay_operating_points"]))
    print(f"{'waveform':<8} {'point':<6} {'N':>3} {'Pe':>6} {'OBO':>6} {'PA EVM':>7} {'EIRP':>6} {'G_rx':>6} "
          f"{'floor':>6} {'cap':>5} {'Mb/s':>6} {'d MCS1':>7} {'d 16Q3/4':>9} {'d cap':>7} {'pJ/b':>6} "
          f"{'mp 16Q3/4':>10}")


def ay_row(rep, r):
    print(f"{r['waveform']:<8} {r['point']:<6} {r['n']:>3} {r['element_pout_dbm']:6.1f} {r['obo_db']:6.2f} "
          f"{r['pa_evm_db']:7.1f} "
          f"{r['eirp_dbm']:6.1f} {r['rx_gain_db']:6.1f} {r['floor_db']:6.1f} {fmt(r['cap_mcs'], 'MCS{}'):>5} "
          f"{fmt(r['rate_mbps'], '{:.0f}'):>6} {fmt(r['range_mcs1_m'], '{:.0f}'):>7} "
          f"{fmt(r['range_common_m'], '{:.0f}'):>9} "
          f"{fmt(r['range_cap_m'], '{:.0f}'):>7} "
          f"{fmt(r['pj_per_bit'], '{:.0f}'):>6} "
          f"{fmt(r['range_common_multipath_m'], '{:.0f}'):>10}", flush=True)


def ay_foot(rep):
    h = rep["header"]
    print("PA EVM = the PA alone on the waveform's 16-QAM payload at the per-element back-off; floor = the cap "
          "MCS's constellation on the calibrated chain; d = metres (free space plus oxygen) at MCS1 (the slowest), "
          "at 16-QAM 3/4 (SC MCS14 / OFDM MCS13) and at the cap; pJ/b at the cap as in 3c.  Every MCS of both "
          "waveforms has a threshold measured the same way (cairn/ay.md 9d).  mp 16Q3/4 = the 16-QAM 3/4 distance "
          "with the threshold of the CR stand-in (rms "
          f"{h['cr_rms_delay_ns']:g} ns): SC's measured there "
          "(data/spec/ay_per_thresholds.yaml, multipath), OFDM's its flat one plus "
          f"{h['ay_ofdm_multipath_margin_db']:g} dB (assumed.ay_ofdm_multipath_margin_db: the "
          "16 / 64-QAM interleaver permutation is not public); the cap and every other column stay on the flat "
          "thresholds")


def ay_smallest_head(rep):
    h = rep["header"]
    print(f"\nthe smallest array that reaches the EIRP limit ({h['eirp_limit_dbm']:g} dBm) at each operating point, "
          f"and its cost (PA = N x Pout / PAE; PS = 2N x {h['phase_shifter_mw']:g} mW; d and pJ/b at "
          f"16-QAM 3/4):")
    print(f"{'waveform':<8} {'point':<6} {'OBO':>6} {'N':>4} {'Pe':>6} {'PAE %':>6} {'PA mW':>7} {'PS mW':>7} "
          f"{'G_rx':>6} {'d MCS1':>7} {'d 16Q3/4':>9} {'pJ/b':>6} {'mp 16Q3/4':>10}")


def ay_smallest_row(rep, r):
    print(f"{r['waveform']:<8} {r['point']:<6} {r['operating_obo_db']:6.2f} {r['n']:>4} {r['element_pout_dbm']:6.2f} "
          f"{r['pae_pct']:6.1f} "
          f"{r['pa_mw']:7.0f} "
          f"{r['phase_shifters_mw']:7.0f} {r['rx_gain_db']:6.2f} "
          f"{fmt(r['range_mcs1_m'], '{:.0f}'):>7} {fmt(r['range_common_m'], '{:.0f}'):>9} "
          f"{fmt(r['pj_per_bit'], '{:.0f}'):>6} "
          f"{fmt(r['range_common_multipath_m'], '{:.0f}'):>10}", flush=True)


def ay_smallest_foot(rep):
    print("at the limit the PA's DC power hardly moves with the operating point: fewer elements at a smaller "
          "back-off, each at a higher PAE (the class-B law: PAE grows with the output amplitude), the product "
          "constant; what the smaller back-off saves is elements — phase shifters, area — and what it costs is "
          "receive gain (the same array at both ends, a TDD link)")


def training_head(rep):
    h = rep["header"]
    print(f"\n== 4. beam training, MLO-triggered: training field {h['training_field']}, estimator "
          f"{h['training_estimator']}, "
          f"a pick within "
          f"{h['training_success_within_db']:g} dB of the best sector in {h['training_p_target_pct']:g} % of sweeps ==")
    print(f"{'scheme':<26} {'N':>3} {'tones':>6} {'req TX':>7} {'req RX':>7} {'PL TXSS':>8} {'PL RXSS':>8} "
          f"{'TXSS-MCS0':>10} {'TXSS-cap':>9} {'sweep [us]':>11}")


def training_row(rep, r):
    if not r["sweep"]:
        dash = "       —" * 2 + "        —" * 2 + "          —         —           —"
        print(f"{r['scheme']:<26} {r['n']:>3} {r['tones']:>6}{dash}   (one sector: no sweep)")
        return
    print(f"{r['scheme']:<26} {r['n']:>3} {r['tones']:>6} {fmt(r['req_tx_db']):>7} {fmt(r['req_rx_db']):>7} "
          f"{fmt(r['path_loss_txss_db']):>8} "
          f"{fmt(r['path_loss_rxss_db']):>8} {fmt(r['txss_minus_mcs0_db'], '{:+.1f}'):>10} "
          f"{fmt(r['txss_minus_cap_db'], '{:+.1f}'):>9} {r['sweep_us']:11.1f}", flush=True)


def training_foot(rep):
    print("req = per-tone SNR of the best sector the sweep needs (dB); PL TXSS = the path loss the transmit sweep "
          "takes with "
          "the far end on one element, PL RXSS = the receive sweep behind the chosen transmit beam; TXSS - MCS0 / cap: "
          "positive = the training reaches further than that data rate; sweep = transmit + receive sweep, "
          "one direction")


def training_repetitions_head(rep):
    h = rep["header"]
    print(f"\n== 4b. the transmit sweep's training field repeated R times per sector until it reaches the MCS0 edge "
          f"(R a power of two up to {h['max_repetitions']}; {h['repetition_combining']} across repetitions = the "
          "preset, coherent = a sensitivity, an optimistic bound) ==")
    print(f"{'scheme':<26} {'N':>3} {'R':>4} {'req TX':>7} {'TXSS-MCS0':>10} {'TX sweep [us]':>14} | "
          f"{'R coh':>5} {'req TX':>7} {'TXSS-MCS0':>10} {'TX sweep [us]':>14}")


def training_repetitions_row(rep, r):
    cells = []
    for x in r["cells"]:
        cells.append(f"{fmt(x['repetitions'], '{:d}'):>{4 if not cells else 5}} {fmt(x['req_tx_db']):>7} "
                     f"{fmt(x['txss_minus_mcs0_db'], '{:+.1f}'):>10} {fmt(x['tx_sweep_us']):>14}")
    print(f"{r['scheme']:<26} {r['n']:>3} " + " | ".join(cells), flush=True)


def training_repetitions_foot(rep):
    print("R = the fewest repetitions at which the transmit sweep (far end on one element) takes at least the MCS0 "
          "data link's path loss (1 = the field as it is); TXSS - MCS0 at that R; TX sweep = every sector's R fields "
          "plus the switch (the receive sweep stays at one field).  Non-coherent: the R powers summed, nR tones' worth "
          "of statistics, no phase needed across repetitions; coherent: 2R symbols per tone, needs the phase to hold")


def two_stage_head(rep):
    h = rep["header"]
    print(f"\n== 4c. a two-stage transmit sweep at N = {h['two_stage_n']}: the first m elements' wide sectors, then "
          "the full array "
          "inside the chosen one (the ceil(N/m) narrow sectors with the most gain toward the station), each stage "
          f"repeated until it reaches the target alone ({h['repetition_combining']}); against the flat sweep of 4b ==")
    print(f"{'scheme':<26} {'target':<10} {'PL':>6} {'flat':>14} {'m':>3} {'wide EIRP':>10} {'wide':>16} "
          f"{'narrow':>14} {'two-stage':>10}")


def two_stage_row(rep, r):
    def st(x):
        if x["repetitions"] is None:
            return f"{x['sectors']}x short {x['path_loss_db']:.1f}"
        return f"{x['sectors']}xR{x['repetitions']} {x['time_us']:.0f}us"
    tot = r["two_stage_us"]
    print(f"{r['scheme']:<26} {r['target']:<10} {r['target_path_loss_db']:6.1f} {st(r['flat']):>14} {r['m']:>3} "
          f"{r['wide']['eirp_dbm']:10.1f} "
          f"{st(r['wide']):>16} {st(r['narrow']):>14} {'—' if tot is None else f'{tot:.0f}us':>10}",
          flush=True)


def two_stage_foot(rep):
    print("PL = the target path loss (dB): the MCS0 data link's edge, or the decoder cap's; flat / wide / narrow = "
          "sectors x repetitions and the sweep time (one direction), or 'short' and the path loss the stage takes at "
          "the most repetitions; wide EIRP = the m-element sub-array at its own per-element output (dBm).  The wide "
          "stage loses 20 log10(N/m) of EIRP, which repetitions buy back only at about 1.5 dB per doubling: the two "
          "stages save time where the link has margin, not at its edge")


def ay_sweep_head(rep):
    h = rep["header"]
    print(f"\n== 4d. the 802.11ay waveforms' own sector sweep: one SSW frame per sector in the DMG control PHY "
          f"(MCS 0), decoded at the far end; threshold {h['ay_sweep_threshold_db']:.2f} dB in-band over "
          f"{h['ay_sweep_occupied_bw_ghz']:.2f} GHz from its "
          f"sensitivity with the reference receiver taken out (assumed.ay_sector_sweep); the same arrays at the "
          f"preset back-off as 3d; one sweep serves both ay waveforms ==")
    print(f"{'N':>3} {'EIRP':>6} {'PL TXSS':>8} {'PL RXSS':>8}   " + "   ".join(
        f"{wf + ' MCS1':>12} {'TXSS-MCS1':>10} {'cap':>5} {'TXSS-cap':>9}" for wf in h["ay_waveforms"])
        + f"   {'be TXSS':>8} {'TXSS-MCS0':>10}   {'ay [us]':>8} {'be [us]':>8}")


def ay_sweep_row(rep, r):
    if not r["sweep"]:
        print(f"{r['n']:>3}   (one sector: no sweep)")
        return
    cells = [f"{fmt(w['path_loss_mcs1_db']):>12} {fmt(w['txss_minus_mcs1_db'], '{:+.1f}'):>10} "
             f"{fmt(w['cap_mcs'], 'MCS{}'):>5} {fmt(w['txss_minus_cap_db'], '{:+.1f}'):>9}" for w in r["waveforms"]]
    print(f"{r['n']:>3} {r['eirp_dbm']:6.1f} {r['path_loss_txss_db']:8.1f} {r['path_loss_rxss_db']:8.1f}   "
          + "   ".join(cells)
          + f"   {fmt(r['be_path_loss_txss_db']):>8} {fmt(r['be_txss_minus_mcs0_db'], '{:+.1f}'):>10}"
          + f"   {r['ay_sweep_us']:8.1f} {r['be_sweep_us']:8.1f}", flush=True)


def ay_sweep_foot(rep):
    h = rep["header"]
    print(f"PL = the path loss the sweep's frame still decodes at (dB): TXSS with the far end on one element, RXSS "
          f"behind the chosen transmit beam; MCS1 / cap = the ay data link's edges at that MCS (3d, preset); positive "
          f"= the sweep reaches further.  be TXSS / TXSS-MCS0 = section 4's MLO-triggered row for {h['be_scheme']}.  "
          f"The "
          f"implementation loss kept in the threshold takes {h['implementation_loss_db']:g} dB off every PL.  "
          f"ay [us] = transmit + receive "
          f"sweep, one direction: every sector one SSW frame of {h['ssw_frame_us']:.3f} us (a control PHY PPDU: "
          f"its preamble, then the header and the {h['ssw_frame_octets']}-octet frame in "
          f"{h['ssw_frame_codewords']} LDPC codewords, "
          f"dmg.control_phy_encoding), SBIFS ({h['sbifs_us']:g} us) apart; "
          f"be [us] = section 4's "
          f"sweep time for {h['be_scheme']}")


def squint_head(rep):
    print(f"\n== 5. squint across the occupied band at a {rep['header']['scan_deg']:g} deg beam (phase shifters vs "
          "true time "
          "delay; dB) ==")
    print(f"{'occupied band':<34} {'N':>3} {'phase: mean':>12} {'edge':>7} {'TTD: mean':>10} {'edge':>7}")


def squint_row(rep, r):
    print(f"{r['band']:<34} {r['n']:>3} {z2(r['phase_mean_db']):12.2f} {z2(r['phase_edge_db']):7.2f} "
          f"{z2(r['ttd_mean_db']):10.2f} {z2(r['ttd_edge_db']):7.2f}")


def squint_foot(rep):
    print("mean = the array gain lost averaged over the occupied tones, edge = at the worst tone (transmit; the "
          "receive "
          "array loses the same).  A per-tone equaliser takes the shape out; what is left is SNR")


def sensitivity_head(rep):
    h = rep["header"]
    print(f"\n== 6. sensitivity: one assumed input at a time ({h['sensitivity_scheme']}, N = {h['sensitivity_n']}) ==")
    print(f"{'input':<44} {'TX gain':>8} {'phase loss':>11} {'sectors':>8} {'req TX':>7} {'TXSS-MCS0':>10}")


def sensitivity_row(rep, r):
    print(f"{r['input']:<44} {r['tx_gain_db']:8.2f} {r['phase_loss_db']:11.2f} {r['sectors']:>8} "
          f"{fmt(r['req_tx_db']):>7} {fmt(r['txss_minus_mcs0_db'], '{:+.1f}'):>10}", flush=True)


def sensitivity_foot(rep):
    print(f"(preset row's req TX {fmt(rep['header']['sensitivity_preset_req_tx_db'])} dB is the one in table 4)")


#: section -> (heading, row, footnote); 3d's operating points are printed in the ``ay`` heading
PRINT = {"faces": (faces_head, faces_row, faces_foot),
         "link": (link_head, link_row, link_foot),
         "oxygen": (oxygen_head, oxygen_row, oxygen_foot),
         "power": (power_head, power_row, power_foot),
         "ay": (ay_head, ay_row, ay_foot),
         "ay_smallest": (ay_smallest_head, ay_smallest_row, ay_smallest_foot),
         "training": (training_head, training_row, training_foot),
         "training_repetitions": (training_repetitions_head, training_repetitions_row, training_repetitions_foot),
         "two_stage": (two_stage_head, two_stage_row, two_stage_foot),
         "ay_sweep": (ay_sweep_head, ay_sweep_row, ay_sweep_foot),
         "squint": (squint_head, squint_row, squint_foot),
         "sensitivity": (sensitivity_head, sensitivity_row, sensitivity_foot)}


class Printer:
    """``arrayreport.build``'s ``progress``: prints each piece of the report as it arrives — the intro with
    the first piece of the header, a section's heading when it starts, its rows one by one, its footnote
    when the next section starts (``close`` prints the last one).  ``rep`` is the report so far."""

    def __init__(self, quick: bool):
        self.quick = quick
        self.rep = {"header": {}}
        self.section = None

    def __call__(self, section, row):
        if section == "header":
            if row is not None:
                first = not self.rep["header"]
                self.rep["header"].update(row)
                if first:
                    intro(self.rep, self.quick)
            return
        if row is None:
            self.close()
            self.rep[section] = []
            self.section = section
            if section in PRINT:
                PRINT[section][0](self.rep)
            return
        self.rep[section].append(row)
        if section in PRINT:
            PRINT[section][1](self.rep, row)

    def close(self):
        if self.section in PRINT:
            PRINT[self.section][2](self.rep)
        self.section = None


def main(argv=None) -> int:
    print(ENGINE_BANNER)
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--jobs", type=int, default=1, help="accepted for symmetry; serial")
    a = ap.parse_args(argv)
    quick = a.quick or os.environ.get("MMW60_SMOKE") == "1"
    t0 = time.time()
    out = Printer(quick)
    # the one front end at every element (iron rule 2) is named here; the schemes, the 802.11ay
    # configs and the sizes are arrayreport's defaults
    fe = Frontend60.from_config(zero_if_60ghz(k=8))
    arrayreport.build(fe=fe, progress=out, **(arrayreport.quick_kwargs() if quick else {}))
    out.close()
    print(f"\n[{time.time() - t0:.0f}s]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
