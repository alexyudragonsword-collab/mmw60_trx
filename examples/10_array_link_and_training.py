"""Example 10 — milestone 2, the array layer: link budget and beam-training SNR budget.

N elements of the shared front end at each end (``frontend/array60.py`` on
arraytx's geometry, vendored @5815c5a; data/spec: assumed.array_*), the same
array for both topologies (iron rule 2).  What the tables answer:

1. the array's faces: gain on transmit and receive, scan loss, beamwidth,
   the codebook, the phase shifters' and the element errors' cost;
2. the EIRP limit: N elements at the front end's operating point exceed it
   from some N on, every element then backs off together — and the PA gets
   more linear: per-element output, back-off, PA EVM, floor, decoder cap;
3. the data link: the largest path loss each MCS takes (EIRP + receive
   gain - the topology's own sensitivity at that MCS's required SNR), and
   the free-space distance it means (no oxygen absorption: illustrative
   beyond a few tens of metres);
4. the beam training, MLO-triggered (data/spec: assumed.array_training):
   the per-tone SNR a sector sweep needs, the path loss the transmit sweep
   (far end on one element) and the receive sweep take against the data
   link's, and how long the sweeps last;
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
from mmw60.config import ChannelConfig, array_frontend, if_extender_60ghz, zero_if_60ghz  # noqa: E402
from mmw60.frontend import Frontend60                                       # noqa: E402
from mmw60.frontend.array60 import Array60                                  # noqa: E402
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
          f"{spec.value('assumed.array_element_errors')}; free space at the carrier, line of sight")

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
          f"free-space distance of that path loss at {base.carrier_hz / 1e9:g} GHz (no oxygen absorption, ~15 dB/km: "
          "illustrative beyond a few tens of metres)")

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
