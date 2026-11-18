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

    python examples/10_array_link_and_training.py [--quick]
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

from mmw60 import ENGINE_BANNER, __version__, spec                          # noqa: E402
from mmw60 import arraylink as al                                           # noqa: E402
from mmw60.ay import edmg                                                   # noqa: E402
from mmw60.config import ChannelConfig, array_frontend, ay_60ghz, if_extender_60ghz, zero_if_60ghz  # noqa: E402
from mmw60.frontend import Frontend60                                       # noqa: E402
from mmw60.frontend.array60 import Array60                                  # noqa: E402
from mmw60.power import PowerCoefficients                                   # noqa: E402
from mmw60.sim.link import LinkSim                                          # noqa: E402
from mmw60.vendor.arraytx.beam import beam_response, beamwidth_3db_deg      # noqa: E402

FLAT = ChannelConfig(model="flat")
SIZES = (1, 4, 16, 64)
SCAN_DEG = 45.0


def schemes():
    """(label, config): topology B on the 11be 80 MHz base x 4 and the 11ac 20 MHz base x 8,
    topology A on 11be 80 MHz."""
    b_be = zero_if_60ghz(k=4, standard="11be", bandwidth_hz=80e6)
    a_be = if_extender_60ghz(standard="11be", bandwidth_hz=80e6)
    return (("B 11be 80M x4 (320 MHz)", dc.replace(b_be, channel=FLAT)),
            ("B 11ac 20M x8 (160 MHz)", dc.replace(zero_if_60ghz(k=8), channel=FLAT)),
            ("A 11be 80M (IF extender)", dc.replace(a_be, channel=FLAT)))


def fmt(v, f="{:.1f}"):
    return "—" if v is None else f.format(v)


def main(argv=None) -> int:
    print(ENGINE_BANNER)
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--jobs", type=int, default=1, help="accepted for symmetry; serial")
    a = ap.parse_args(argv)
    quick = a.quick or os.environ.get("MMW60_SMOKE") == "1"
    t0 = time.time()
    sizes = (1, 16) if quick else SIZES
    trials, users = (200, 5) if quick else (2000, 25)
    fe = Frontend60.from_config(zero_if_60ghz(k=8))
    geo, tr = spec.value("assumed.array_geometry"), spec.value("assumed.array_training")
    print(f"mmw60 {__version__}; {'QUICK (numbers meaningless)' if quick else 'full size'}; one Frontend60 at every "
          f"element: PA Pout {fe.target_pout_dbm():.1f} dBm (back-off {fe.obo_db:g} dB from Psat), receive NF "
          f"{fe.rx_front.nf_db:g} dB, "
          f"element {fe.antenna_gain_tx_dbi:g} dBi; EIRP limit {fe.eirp.avg_dbm:g} dBm avg (FCC 15.255)")
    print(f"arrays: n x 1 at both ends, {geo['spacing_lambda']:g} lambda, element factor {geo['element_pattern']}, "
          f"{spec.value('assumed.array_phase_bits')}-bit phase shifters, element errors "
          f"{spec.value('assumed.array_element_errors')}; line of sight at the carrier, free space plus "
          f"{al.oxygen_db_per_km():g} dB/km oxygen absorption (an estimate)")

    # ---------------------------------------------------------------- 1. faces
    base = schemes()[0][1]
    print("\n== 1. the array's faces (beam at broadside unless stated; dB) ==")
    print(f"{'N':>3} {'TX gain':>8} {'RX gain':>8} {f'scan {SCAN_DEG:g}':>8} {'BW3dB':>6} {'sectors':>8} "
          f"{'phase loss':>11} {'+errors':>8}")
    for n in sizes:
        ar = Array60.from_config(array_frontend(base, n), fe)
        ideal = Array60.from_config(dc.replace(array_frontend(base, n), frontend=dc.replace(
            array_frontend(base, n).frontend, array=dc.replace(array_frontend(base, n).frontend.array,
                                                               gain_err_db_rms=0.0, phase_err_deg_rms=0.0))), fe)
        th = np.linspace(-ar.scan_max_deg, ar.scan_max_deg, 61)
        q = float(np.mean([ideal.quantisation_loss_db("tx", t) for t in th]))
        qe = float(np.mean([ar.quantisation_loss_db("tx", t) for t in th]))
        scan = ar.tx_gain_db(SCAN_DEG, SCAN_DEG)[0] - ar.tx_gain_db(0.0, 0.0)[0]
        bw = beamwidth_3db_deg(ar.tx, 0.0) if n > 1 else float("nan")
        print(f"{n:>3} {ar.tx_gain_db(0.0, 0.0)[0]:8.2f} {ar.rx_gain_db(0.0, 0.0)[0]:8.2f} {scan:8.2f} {bw:6.1f} "
              f"{ar.codebook_deg().size:>8} {q:11.2f} {qe:8.2f}")
    print("TX gain = EIRP over one element's output (20 log10 N + element); RX gain = SNR gain (10 log10 N + element); "
          "phase loss = the shifters' gain loss averaged over the scan, +errors = with the element errors too")

    # ---------------------------------------------------------------- 2-3. budgets
    print("\n== 2. the EIRP limit and the per-element operating point; 3. the data link (largest path loss, dB) ==")
    print(f"{'scheme':<26} {'N':>3} {'Pe':>6} {'OBO':>6} {'PA EVM':>7} {'EIRP':>6} {'G_rx':>6} {'floor':>6} {'cap':>5} "
          f"{'PL MCS0':>8} {'PL cap':>7} {'d MCS0 [m]':>11} {'d cap [m]':>10}")
    budgets = {}
    for lab, cfg in schemes():
        for n in sizes:
            c = array_frontend(cfg, n)
            ar = Array60.from_config(c, fe)
            b = al.array_budget(c, fe, ar, lab)
            budgets[(lab, n)] = (c, ar, b)
            pl0 = None if 0 not in b.sens_by_mcs else b.eirp_dbm + b.g_rx_db - b.sens_by_mcs[0]
            plc = None if b.dec_mcs is None else b.eirp_dbm + b.g_rx_db - b.sens_by_mcs[b.dec_mcs]
            print(f"{lab:<26} {n:>3} {b.p_elem_dbm:6.1f} {b.obo_db:6.2f} {b.pa_evm_db:7.1f} {b.eirp_dbm:6.1f} "
                  f"{b.g_rx_db:6.1f} {b.floor_db:6.1f} {fmt(b.dec_mcs, 'MCS{}'):>5} {fmt(pl0):>8} {fmt(plc):>7} "
                  f"{fmt(b.range_by_mcs.get(0), '{:.0f}'):>11} "
                  f"{fmt(b.range_by_mcs.get(b.dec_mcs), '{:.0f}'):>10}", flush=True)
    print(f"Pe / OBO: the per-element output and its back-off from Psat (the front end's {fe.obo_db:g} dB unless the "
          f"EIRP limit asks for more); PL = EIRP + G_rx - sensitivity at the MCS's required SNR over the floor; "
          f"d = the "
          f"distance of that path loss at {base.carrier_hz / 1e9:g} GHz: free space plus {al.oxygen_db_per_km():g} "
          "dB/km oxygen (an estimate; 3b)")

    # ---------------------------------------------------------------- 3b. the oxygen estimate
    alphas = (0.0, 10.0, al.oxygen_db_per_km(), 20.0)
    print("\n== 3b. sensitivity: the MCS0 distance (m) at other oxygen absorptions (the path loss does not move) ==")
    print(f"{'scheme':<26} {'N':>3} {'PL MCS0':>8} " + " ".join(f"{f'{a:g} dB/km':>10}" for a in alphas))
    for lab, _ in schemes():
        for n in sizes:
            c, ar, b = budgets[(lab, n)]
            if 0 not in b.sens_by_mcs:
                continue
            pl0 = b.eirp_dbm + b.g_rx_db - b.sens_by_mcs[0]
            print(f"{lab:<26} {n:>3} {pl0:8.1f} "
                  + " ".join(f"{al.range_m(pl0, c.carrier_hz, a):10.0f}" for a in alphas))
    print(f"0 dB/km = free space alone; {al.oxygen_db_per_km():g} dB/km is the preset (the round figure for the "
          "absorption peak near 60 GHz at sea level, no original consulted: ROADMAP B)")

    # ---------------------------------------------------------------- 3c. power per bit
    coeffs = PowerCoefficients.from_spec()
    ps_alt = (0.0, 30e-3)
    print(f"\n== 3c. power per link direction at the decoder cap: N PAs at the per-element output, one phase shifter "
          f"per element and side ({1e3 * coeffs.phase_shifter_w:g} mW, assumed; none at N = 1), the rest as the "
          "single-element column ==")
    print(f"{'scheme':<26} {'N':>3} {'Pe':>6} {'PAE %':>6} {'PA mW':>7} {'PS mW':>7} {'rest mW':>8} {'total mW':>9} "
          f"{'cap':>5} {'Mb/s':>6} {'pJ/b':>6} " + " ".join(f"{f'PS {1e3 * w:g} mW':>9}" for w in ps_alt))
    for lab, _ in schemes():
        for n in sizes:
            c, ar, b = budgets[(lab, n)]
            rp = al.array_power_report(c, fe, ar, b, coeffs)
            if rp is None:
                print(f"{lab:<26} {n:>3}   no decoder cap")
                continue
            pae = 100 * float(fe.scaled_pa().pae(b.p_elem_dbm))
            alt = [al.array_power_report(c, fe, ar, b, coeffs.with_(phase_shifter_w=w)).pj_per_bit for w in ps_alt]
            pa_w, ps_w = rp.watts("pa"), rp.watts("phase_shifters")
            print(f"{lab:<26} {n:>3} {b.p_elem_dbm:6.1f} {pae:6.1f} {1e3 * pa_w:7.0f} {1e3 * ps_w:7.0f} "
                  f"{1e3 * (rp.total_w - pa_w - ps_w):8.0f} {1e3 * rp.total_w:9.0f} {fmt(b.dec_mcs, 'MCS{}'):>5} "
                  f"{rp.bit_rate / 1e6:6.0f} {rp.pj_per_bit:6.0f} " + " ".join(f"{v:9.0f}" for v in alt), flush=True)
    print("PA = N_tx x Pout / PAE(Pout) at the per-element output (class-B law; the EIRP limit backs every element off "
          "together from some N on, and PAE drops with it); PS = (N_tx + N_rx) phase shifters; rest = synthesizers, "
          "converters, FFT, decoder (and topology A's chip PA and DPD) as in the comparison table; LNA / mixer per "
          "receive element not counted, as in the single-element column; N = 1 is the comparison table's own column")

    # ---------------------------------------------------------------- 3d. 802.11ay
    ay_cfgs = {wf: dc.replace(ay_60ghz(wf, 1), channel=FLAT) for wf in ("ay_sc", "ay_ofdm")}
    own = {wf: al.ay_operating_obo_db(c) for wf, c in ay_cfgs.items()}
    common = {"ay_sc": 14, "ay_ofdm": 13}         # 16-QAM 3/4: the fastest MCS both have a threshold for
    print("\n== 3d. the two 802.11ay waveforms (topology B, EDMG channel 2) on the same arrays and front end: floors "
          "on the chain wifitrx's sequence calibrated at each per-element back-off; thresholds measured with "
          "spec_sources#33's codes (data/spec/ay_per_thresholds.yaml; SC MCS 1's repetition and OFDM's DCM "
          "through spec_sources#43); the decoder cap by the be rows' rule ==")
    print("each element at the shared preset back-off, and at the waveform's own operating point — the preset rule "
          "(the PA alone at the 802.11ad 16-QAM 3/4 TX EVM limit) on its own 16-QAM payload "
          "(assumed.ay_operating_point): "
          + "; ".join(f"{wf} {own[wf]:.2f} dB (the PA alone at the preset {fe.obo_db:g} dB: "
                      f"{al.ay_pa_alone_evm_db(c, fe.obo_db):.1f} dB)" for wf, c in ay_cfgs.items()))
    print(f"{'waveform':<8} {'point':<6} {'N':>3} {'Pe':>6} {'OBO':>6} {'PA EVM':>7} {'EIRP':>6} {'G_rx':>6} "
          f"{'floor':>6} {'cap':>5} {'Mb/s':>6} {'d MCS1':>7} {'d 16Q3/4':>9} {'d cap':>7} {'pJ/b':>6} "
          f"{'mp 16Q3/4':>10}")
    cal_cache = {}
    ay_budgets = {}
    for wf, c in ay_cfgs.items():
        for view, ob in (("preset", None), ("own", own[wf])):
            for n in sizes:
                cn = array_frontend(c, n)
                ar = Array60.from_config(cn, fe)
                b = al.ay_array_budget(cn, fe, ar, wf, obo_db=ob, cal_cache=cal_cache)
                ay_budgets[(wf, view, n)] = (cn, ar, b)
                rp = al.array_power_report(cn, fe, ar, b, coeffs)
                rate = None if b.dec_mcs is None else b.rate_by_mcs[b.dec_mcs] / 1e6
                print(f"{wf:<8} {view:<6} {n:>3} {b.p_elem_dbm:6.1f} {b.obo_db:6.2f} {b.pa_evm_db:7.1f} "
                      f"{b.eirp_dbm:6.1f} {b.g_rx_db:6.1f} {b.floor_db:6.1f} {fmt(b.dec_mcs, 'MCS{}'):>5} "
                      f"{fmt(rate, '{:.0f}'):>6} {fmt(b.range_by_mcs.get(1), '{:.0f}'):>7} "
                      f"{fmt(b.range_by_mcs.get(common[wf]), '{:.0f}'):>9} "
                      f"{fmt(b.range_by_mcs.get(b.dec_mcs), '{:.0f}'):>7} "
                      f"{fmt(None if rp is None else rp.pj_per_bit, '{:.0f}'):>6} "
                      f"{fmt(b.range_multipath_by_mcs.get(common[wf]), '{:.0f}'):>10}", flush=True)
    print("PA EVM = the PA alone on the waveform's 16-QAM payload at the per-element back-off; floor = the cap "
          "MCS's constellation on the calibrated chain; d = metres (free space plus oxygen) at MCS1 (the slowest), "
          "at 16-QAM 3/4 (SC MCS14 / OFDM MCS13) and at the cap; pJ/b at the cap as in 3c.  Every MCS of both "
          "waveforms has a threshold measured the same way (cairn/ay.md 9d).  mp 16Q3/4 = the 16-QAM 3/4 distance "
          "with the threshold of the CR stand-in (rms "
          f"{spec.value('assumed.cr_rms_delay_ns'):g} ns): SC's measured there "
          "(data/spec/ay_per_thresholds.yaml, multipath), OFDM's its flat one plus "
          f"{spec.value('assumed.ay_ofdm_multipath_margin_db'):g} dB (assumed.ay_ofdm_multipath_margin_db: the "
          "16 / 64-QAM interleaver permutation is not public); the cap and every other column stay on the flat "
          "thresholds")
    print(f"\nthe smallest array that reaches the EIRP limit ({fe.eirp.avg_dbm:g} dBm) at each operating point, "
          f"and its cost (PA = N x Pout / PAE; PS = 2N x {1e3 * coeffs.phase_shifter_w:g} mW; d and pJ/b at "
          f"16-QAM 3/4):")
    print(f"{'waveform':<8} {'point':<6} {'OBO':>6} {'N':>4} {'Pe':>6} {'PAE %':>6} {'PA mW':>7} {'PS mW':>7} "
          f"{'G_rx':>6} {'d MCS1':>7} {'d 16Q3/4':>9} {'pJ/b':>6} {'mp 16Q3/4':>10}")
    for wf, c in ay_cfgs.items():
        for view, ob in (("preset", fe.obo_db), ("own", own[wf])):
            p_op = float(dc.replace(fe, obo_db=ob).target_pout_dbm())
            n_min = next(n for n in range(1, 257)
                         if p_op + Array60.from_config(array_frontend(c, n), fe).tx_gain_db(0.0, 0.0)[0]
                         >= fe.eirp.avg_dbm)
            cn = array_frontend(c, n_min)
            ar = Array60.from_config(cn, fe)
            b = al.ay_array_budget(cn, fe, ar, wf, obo_db=ob, cal_cache=cal_cache)
            m16 = common[wf]
            rp = (al.array_power_report(cn, fe, ar, dc.replace(b, dec_mcs=m16), coeffs)
                  if m16 in b.range_by_mcs else None)
            pae = float(fe.scaled_pa().pae(b.p_elem_dbm))
            print(f"{wf:<8} {view:<6} {ob:6.2f} {n_min:>4} {b.p_elem_dbm:6.2f} {100 * pae:6.1f} "
                  f"{1e3 * n_min * 10 ** (b.p_elem_dbm / 10) * 1e-3 / pae:7.0f} "
                  f"{1e3 * 2 * n_min * coeffs.phase_shifter_w:7.0f} {b.g_rx_db:6.2f} "
                  f"{fmt(b.range_by_mcs.get(1), '{:.0f}'):>7} {fmt(b.range_by_mcs.get(m16), '{:.0f}'):>9} "
                  f"{fmt(None if rp is None else rp.pj_per_bit, '{:.0f}'):>6} "
                  f"{fmt(b.range_multipath_by_mcs.get(m16), '{:.0f}'):>10}", flush=True)
    print("at the limit the PA's DC power hardly moves with the operating point: fewer elements at a smaller "
          "back-off, each at a higher PAE (the class-B law: PAE grows with the output amplitude), the product "
          "constant; what the smaller back-off saves is elements — phase shifters, area — and what it costs is "
          "receive gain (the same array at both ends, a TDD link)")

    # ---------------------------------------------------------------- 4. training
    print(f"\n== 4. beam training, MLO-triggered: training field {tr['field']}, estimator {tr['estimator']}, "
          f"a pick within "
          f"{tr['success_within_db']:g} dB of the best sector in {100 * tr['p_target']:g} % of sweeps ==")
    print(f"{'scheme':<26} {'N':>3} {'tones':>6} {'req TX':>7} {'req RX':>7} {'PL TXSS':>8} {'PL RXSS':>8} "
          f"{'TXSS-MCS0':>10} {'TXSS-cap':>9} {'sweep [us]':>11}")
    train = {}
    for lab, cfg in schemes():
        for n in sizes:
            c, ar, b = budgets[(lab, n)]
            n_tones = LinkSim(c, frontend=fe).n_active
            if n == 1:
                dash = "       —" * 2 + "        —" * 2 + "          —         —           —"
                print(f"{lab:<26} {n:>3} {n_tones:>6}{dash}   (one sector: no sweep)")
                continue
            rt = al.required_training_snr_db(ar, "tx", n_tones, trials=trials, n_users=users)
            rr = al.required_training_snr_db(ar, "rx", n_tones, trials=trials, n_users=users)
            one = float(ar.element_factor_db("rx", 0.0)[0] + ar.element_gain_rx_dbi)
            pl_tx = None if rt["snr_db"] is None else b.eirp_dbm + one - (b.noise_dbm + rt["snr_db"])
            pl_rx = None if rr["snr_db"] is None else b.eirp_dbm + b.g_rx_db - (b.noise_dbm + rr["snr_db"])
            pl0 = None if 0 not in b.sens_by_mcs else b.eirp_dbm + b.g_rx_db - b.sens_by_mcs[0]
            plc = None if b.dec_mcs is None else b.eirp_dbm + b.g_rx_db - b.sens_by_mcs[b.dec_mcs]
            d0 = None if pl_tx is None or pl0 is None else pl_tx - pl0
            dc_ = None if pl_tx is None or plc is None else pl_tx - plc
            t_sw = al.sweep_time_s(ar, c.upclocked(), "tx") + al.sweep_time_s(ar, c.upclocked(), "rx")
            train[(lab, n)] = (rt, rr, d0)
            print(f"{lab:<26} {n:>3} {n_tones:>6} {fmt(rt['snr_db']):>7} {fmt(rr['snr_db']):>7} {fmt(pl_tx):>8} "
                  f"{fmt(pl_rx):>8} {fmt(d0, '{:+.1f}'):>10} {fmt(dc_, '{:+.1f}'):>9} {1e6 * t_sw:11.1f}", flush=True)
    print("req = per-tone SNR of the best sector the sweep needs (dB); PL TXSS = the path loss the transmit sweep "
          "takes with "
          "the far end on one element, PL RXSS = the receive sweep behind the chosen transmit beam; TXSS - MCS0 / cap: "
          "positive = the training reaches further than that data rate; sweep = transmit + receive sweep, "
          "one direction")

    # ---------------------------------------------------------------- 4b. repetitions to the MCS0 edge
    rep_cfg = spec.value("assumed.array_training_repetition")
    print(f"\n== 4b. the transmit sweep's training field repeated R times per sector until it reaches the MCS0 edge "
          f"(R a power of two up to {rep_cfg['max_repetitions']}; {rep_cfg['combining']} across repetitions = the "
          "preset, coherent = a sensitivity, an optimistic bound) ==")
    print(f"{'scheme':<26} {'N':>3} {'R':>4} {'req TX':>7} {'TXSS-MCS0':>10} {'TX sweep [us]':>14} | "
          f"{'R coh':>5} {'req TX':>7} {'TXSS-MCS0':>10} {'TX sweep [us]':>14}")
    for lab, _ in schemes():
        for n in sizes:
            if n == 1:
                continue
            c, ar, b = budgets[(lab, n)]
            if 0 not in b.sens_by_mcs:
                continue
            n_tones = LinkSim(c, frontend=fe).n_active
            pl0 = b.eirp_dbm + b.g_rx_db - b.sens_by_mcs[0]
            cells = []
            for comb in (rep_cfg["combining"], "coherent"):
                r = al.repetitions_to_reach(b, ar, n_tones, pl0, combining=comb, trials=trials, n_users=users)
                t_tx = None if r["repetitions"] is None else al.sweep_time_s(ar, c.upclocked(), "tx", r["repetitions"])
                cells.append(f"{fmt(r['repetitions'], '{:d}'):>{4 if not cells else 5}} {fmt(r['req_db']):>7} "
                             f"{fmt(r['margin_db'], '{:+.1f}'):>10} {fmt(None if t_tx is None else 1e6 * t_tx):>14}")
            print(f"{lab:<26} {n:>3} " + " | ".join(cells), flush=True)
    print("R = the fewest repetitions at which the transmit sweep (far end on one element) takes at least the MCS0 "
          "data link's path loss (1 = the field as it is); TXSS - MCS0 at that R; TX sweep = every sector's R fields "
          "plus the switch (the receive sweep stays at one field).  Non-coherent: the R powers summed, nR tones' worth "
          "of statistics, no phase needed across repetitions; coherent: 2R symbols per tone, needs the phase to hold")

    # ---------------------------------------------------------------- 4c. two-stage sweep
    n_h = 16 if quick else 64
    ms = (8,) if quick else (8, 16)
    print(f"\n== 4c. a two-stage transmit sweep at N = {n_h}: the first m elements' wide sectors, then the full array "
          "inside the chosen one (the ceil(N/m) narrow sectors with the most gain toward the station), each stage "
          f"repeated until it reaches the target alone ({rep_cfg['combining']}); against the flat sweep of 4b ==")
    print(f"{'scheme':<26} {'target':<10} {'PL':>6} {'flat':>14} {'m':>3} {'wide EIRP':>10} {'wide':>16} "
          f"{'narrow':>14} {'two-stage':>10}")
    for lab, cfg in schemes():
        c, _, b = budgets[(lab, n_h)]
        n_tones = LinkSim(c, frontend=fe).n_active
        targets = (("MCS0 edge", b.eirp_dbm + b.g_rx_db - b.sens_by_mcs[0]),
                   ("cap", b.eirp_dbm + b.g_rx_db - b.sens_by_mcs[b.dec_mcs]))
        for tname, tgt in targets:
            for m in ms:
                h = al.hierarchical_training(cfg, fe, n_h, m, n_tones, tgt, trials=trials, n_users=users)

                def st(x):
                    if x["repetitions"] is None:
                        return f"{x['sectors']}x short {x['pl_db']:.1f}"
                    return f"{x['sectors']}xR{x['repetitions']} {1e6 * x['time_s']:.0f}us"
                tot = h["hierarchical_time_s"]
                print(f"{lab:<26} {tname:<10} {tgt:6.1f} {st(h['flat']):>14} {m:>3} {h['wide']['eirp_dbm']:10.1f} "
                      f"{st(h['wide']):>16} {st(h['narrow']):>14} {'—' if tot is None else f'{1e6 * tot:.0f}us':>10}",
                      flush=True)
    print("PL = the target path loss (dB): the MCS0 data link's edge, or the decoder cap's; flat / wide / narrow = "
          "sectors x repetitions and the sweep time (one direction), or 'short' and the path loss the stage takes at "
          "the most repetitions; wide EIRP = the m-element sub-array at its own per-element output (dBm).  The wide "
          "stage loses 20 log10(N/m) of EIRP, which repetitions buy back only at about 1.5 dB per doubling: the two "
          "stages save time where the link has margin, not at its edge")

    # ---------------------------------------------------------------- 4d. the 802.11ay sector sweep
    occ = ay_budgets[("ay_sc", "preset", sizes[0])][2].occupied_bw_hz
    t_ctl = edmg.control_threshold_db(occ)
    loss = float(spec.value("dmg.sensitivity_assumptions")["implementation_loss_db"])
    be_lab = schemes()[0][0]
    print(f"\n== 4d. the 802.11ay waveforms' own sector sweep: one SSW frame per sector in the DMG control PHY "
          f"(MCS 0), decoded at the far end; threshold {t_ctl:.2f} dB in-band over {occ / 1e9:.2f} GHz from its "
          f"sensitivity with the reference receiver taken out (assumed.ay_sector_sweep); the same arrays at the "
          f"preset back-off as 3d; one sweep serves both ay waveforms ==")
    print(f"{'N':>3} {'EIRP':>6} {'PL TXSS':>8} {'PL RXSS':>8}   " + "   ".join(
        f"{wf + ' MCS1':>12} {'TXSS-MCS1':>10} {'cap':>5} {'TXSS-cap':>9}" for wf in ay_cfgs)
        + f"   {'be TXSS':>8} {'TXSS-MCS0':>10}   {'ay [us]':>8} {'be [us]':>8}")
    for n in sizes:
        if n == 1:
            print(f"{n:>3}   (one sector: no sweep)")
            continue
        _, ar, b = ay_budgets[("ay_sc", "preset", n)]
        t_ay = al.ay_sweep_time_s(ar, "tx") + al.ay_sweep_time_s(ar, "rx")
        pl_tx = al.transmit_sweep_reach_db(b, ar, t_ctl)
        pl_rx = b.eirp_dbm + b.g_rx_db - (b.noise_dbm + t_ctl)
        cells = []
        for wf in ay_cfgs:
            bw = ay_budgets[(wf, "preset", n)][2]
            pl1 = bw.eirp_dbm + bw.g_rx_db - bw.sens_by_mcs[1] if 1 in bw.sens_by_mcs else None
            plc = (bw.eirp_dbm + bw.g_rx_db - bw.sens_by_mcs[bw.dec_mcs]
                   if bw.dec_mcs is not None and bw.dec_mcs in bw.sens_by_mcs else None)
            cells.append(f"{fmt(pl1):>12} {fmt(None if pl1 is None else pl_tx - pl1, '{:+.1f}'):>10} "
                         f"{fmt(bw.dec_mcs, 'MCS{}'):>5} {fmt(None if plc is None else pl_tx - plc, '{:+.1f}'):>9}")
        c_be, ar_be, b_be = budgets[(be_lab, n)]
        t_be = al.sweep_time_s(ar_be, c_be.upclocked(), "tx") + al.sweep_time_s(ar_be, c_be.upclocked(), "rx")
        rt = train.get((be_lab, n))
        be_tx = (None if rt is None or rt[0]["snr_db"] is None
                 else al.transmit_sweep_reach_db(b_be, ar_be, rt[0]["snr_db"]))
        print(f"{n:>3} {b.eirp_dbm:6.1f} {pl_tx:8.1f} {pl_rx:8.1f}   " + "   ".join(cells)
              + f"   {fmt(be_tx):>8} {fmt(None if rt is None else rt[2], '{:+.1f}'):>10}"
              + f"   {1e6 * t_ay:8.1f} {1e6 * t_be:8.1f}", flush=True)
    print(f"PL = the path loss the sweep's frame still decodes at (dB): TXSS with the far end on one element, RXSS "
          f"behind the chosen transmit beam; MCS1 / cap = the ay data link's edges at that MCS (3d, preset); positive "
          f"= the sweep reaches further.  be TXSS / TXSS-MCS0 = section 4's MLO-triggered row for {be_lab}.  The "
          f"implementation loss kept in the threshold takes {loss:g} dB off every PL.  ay [us] = transmit + receive "
          f"sweep, one direction: every sector one SSW frame of {1e6 * al.ssw_frame_s():.3f} us (a control PHY PPDU: "
          f"its preamble, then the header and the {spec.value('dmg.ssw_frame')['ssw_frame_octets']}-octet frame in "
          f"{len(al.control_phy_codewords(spec.value('dmg.ssw_frame')['ssw_frame_octets']))} LDPC codewords, "
          f"dmg.control_phy_encoding), SBIFS ({1e6 * spec.value('dmg.phy_timing')['sbifs_s']:g} us) apart; "
          f"be [us] = section 4's "
          f"sweep time for {be_lab}")

    # ---------------------------------------------------------------- 5. squint
    print(f"\n== 5. squint across the occupied band at a {SCAN_DEG:g} deg beam (phase shifters vs true time "
          "delay; dB) ==")
    print(f"{'occupied band':<34} {'N':>3} {'phase: mean':>12} {'edge':>7} {'TTD: mean':>10} {'edge':>7}")
    for lab, cfg in (("B 11be 80M x4 (320 MHz)", zero_if_60ghz(k=4, standard="11be", bandwidth_hz=80e6)),
                     ("B 11be 80M x8 (640 MHz)", zero_if_60ghz(k=8, standard="11be", bandwidth_hz=80e6)),
                     ("B 11be 80M x32 (2.56 GHz)", zero_if_60ghz(k=32, standard="11be", bandwidth_hz=80e6))):
        phy = cfg.upclocked()
        f = phy.base.active_tone_indices() * phy.scs_eff
        for n in ((16,) if quick else (16, 64)):
            ar = Array60.from_config(array_frontend(cfg, n), fe)
            row = []
            for mode in ("phase", "ttd"):
                h = np.abs(beam_response(ar.tx, SCAN_DEG, f, mode)) ** 2
                row += [round(-10 * np.log10(np.mean(h)), 2) + 0.0, round(-10 * np.log10(np.min(h)), 2) + 0.0]
            print(f"{lab:<34} {n:>3} {row[0]:12.2f} {row[1]:7.2f} {row[2]:10.2f} {row[3]:7.2f}")
    print("mean = the array gain lost averaged over the occupied tones, edge = at the worst tone (transmit; the "
          "receive "
          "array loses the same).  A per-tone equaliser takes the shape out; what is left is SNR")

    # ---------------------------------------------------------------- 6. sensitivity
    if not quick:
        n = 16
        lab, cfg = schemes()[0]
        c0, ar0, b0 = budgets[(lab, n)]
        n_tones = LinkSim(c0, frontend=fe).n_active
        rt0 = train[(lab, n)][0]
        print(f"\n== 6. sensitivity: one assumed input at a time ({lab}, N = {n}) ==")
        print(f"{'input':<44} {'TX gain':>8} {'phase loss':>11} {'sectors':>8} {'req TX':>7} {'TXSS-MCS0':>10}")

        def row(name, c, est=None, within=None):
            ar = Array60.from_config(c, fe)
            b = al.array_budget(c, fe, ar)
            th = np.linspace(-ar.scan_max_deg, ar.scan_max_deg, 61)
            q = float(np.mean([ar.quantisation_loss_db("tx", t) for t in th]))
            rt = al.required_training_snr_db(ar, "tx", n_tones, trials=trials, n_users=users, estimator=est,
                                             within_db=within)
            one = float(ar.element_factor_db("rx", 0.0)[0] + ar.element_gain_rx_dbi)
            pl_tx = None if rt["snr_db"] is None else b.eirp_dbm + one - (b.noise_dbm + rt["snr_db"])
            pl0 = b.eirp_dbm + b.g_rx_db - b.sens_by_mcs[0]
            print(f"{name:<44} {ar.tx_gain_db(0.0, 0.0)[0]:8.2f} {q:11.2f} {ar.codebook_deg().size:>8} "
                  f"{fmt(rt['snr_db']):>7} {fmt(None if pl_tx is None else pl_tx - pl0, '{:+.1f}'):>10}", flush=True)

        def arr(**kw):
            return dc.replace(c0, frontend=dc.replace(c0.frontend, array=dc.replace(c0.frontend.array, **kw)))

        row("preset", c0)
        row("element factor isotropic", arr(element_pattern="isotropic"))
        for bits in (None, 4, 2, 1):
            row(f"phase shifters {'continuous' if bits is None else f'{bits} bit'}", arr(phase_bits=bits))
        row("no element errors", arr(gain_err_db_rms=0.0, phase_err_deg_rms=0.0))
        row("codebook oversampled x2", arr(sector_oversampling=2.0))
        row("estimator: tones coherently", c0, est="coherent")
        row("success: the best sector only", c0, within=0.0)
        print(f"(preset row's req TX {fmt(rt0['snr_db'])} dB is the one in table 4)")
    print(f"\n[{time.time() - t0:.0f}s]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
