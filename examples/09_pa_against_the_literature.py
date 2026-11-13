"""Example 09 — the 60 GHz PA against measured 60 GHz CMOS PAs.

Until 2026-11-12 the topology A / B presets' PA was the 11ad evaluation
methodology's modified Rapp (Liu 2025 used it) scaled to an assumed 15 dBm
Psat and 20 dB gain, backed off 8 dB from Psat; none of those numbers had a
source.  Three 60 GHz CMOS PA papers were read in the original (data/spec:
pa60.*) and the presets now carry one of them (``config.surveyed_pa``).
Since 2026-11-13 the presets' back-off is no longer Liu's: it is where the
measured PA alone meets the 802.11ad 16-QAM TX EVM limit on the OFDM
envelope (data/spec: assumed.pa60_operating_rule), the rating convention of
the 60 GHz transmitters read.  ``config.tgad_em_pa`` puts the old PA back
at Liu's 8 dB: this example is the side-by-side that motivated the switch.
Liu's own preset (examples 00 / 01) keeps the 11ad shape and the 8 dB.

What the tables answer:

1. the measured PAs, and where the 11ad EM PA sits among them — its Psat is
   in range, its shape is not: P1dB 9.5 dB below Psat against a measured
   median of 3.3 dB;
2. what the shape does to the PA alone against the back-off, read from Psat
   and from P1dB, and where the operating rule puts each shape;
3. the efficiency law behind the power column, against the two papers that
   give PAE at P1dB as well as at peak;
4. what wifitrx's DPD step buys on each PA (K = 8, the calibration sequence
   run at each back-off);
5. the comparison table's 11be 80 MHz rows with each PA: decoder cap, rate,
   pJ/bit and which term limits the row.

    python examples/09_pa_against_the_literature.py [--quick] [--jobs N]
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from mmw60 import ENGINE_BANNER, __version__, compare, spec                   # noqa: E402
from mmw60.calcheck import run_cal_at                                         # noqa: E402
from mmw60.compare import Scheme                                              # noqa: E402
from mmw60.config import tgad_em_pa, zero_if_60ghz                           # noqa: E402
from mmw60.frontend import Frontend60                                         # noqa: E402
from mmw60.frontend.grid import obo_for_isolated_evm, pa_isolated_evm_db      # noqa: E402
from mmw60.pa.rapp import ModifiedRappPA                                       # noqa: E402
from scipy.optimize import brentq                                              # noqa: E402

K_DPD, BASE_DPD = 8, 20e6
BACKOFFS = (4.0, 6.0, 7.0, 8.0, 9.0, 10.0, 12.0)
DPD_BACKOFFS = (6.0, 8.0, 10.0)                  # plus the presets' operating point
TABLE_KS = (4, 8, 16, 32)


def tag(key):
    src = spec.survey(key).source
    return f"{key} [{'survey, unverified' if src == 'survey' else src}]"


def gap_db(psat, p1db):
    return float(psat) - float(p1db)


def measured_rows():
    a, w, n = (spec.value(k) for k in ("pa60.asada_eumc2011", "pa60.wu_asscc2012", "pa60.ning_elex2011"))
    trx = spec.value("rx60.comm_asada2011")
    return (("Asada, 3-stage diff., 65 nm", a["psat_dbm"], a["p1db_dbm"], a["gain_db"], a["pae_peak"],
             tag("pa60.asada_eumc2011")),
            ("Wu, VPA 1.0 V, 65 nm", w["vpa_1v0"]["psat_dbm"], w["vpa_1v0"]["p1db_dbm"], None, w["vpa_1v0"]["pae_peak"],
             tag("pa60.wu_asscc2012")),
            ("Wu, VPA 0.7 V, 65 nm", w["vpa_0v7"]["psat_dbm"], w["vpa_0v7"]["p1db_dbm"], None, w["vpa_0v7"]["pae_peak"],
             tag("pa60.wu_asscc2012")),
            ("Li, parallel A/AB, 65 nm", n["psat_dbm"], n["p1db_dbm"], n["gain_db"], n["pae_peak"],
             tag("pa60.ning_elex2011")),
            ("(transceiver TX output, no PA stage)", trx["tx_psat_dbm"], trx["tx_p1db_dbm"], trx["tx_gain_db"], None,
             tag("rx60.comm_asada2011")))


def dpd_cell(args):
    which, obo, dpd = args
    cfg = zero_if_60ghz(k=K_DPD)
    if which == "11ad EM":
        cfg = tgad_em_pa(cfg)
    r = run_cal_at(Frontend60.from_config(cfg), K_DPD, BASE_DPD, standard="11ac", with_dpd=dpd, obo_db=obo)
    return which, obo, dpd, r.pout_dbm, r.final_views["tx_evm_modem_db"], r.final_views["evm_modem_db"]


def table_rows(f, quick):
    ks = TABLE_KS[:2] if quick else TABLE_KS
    ss = [s for s in compare.scheme_matrix(ks=ks, standard="11be", bandwidth_hz=80e6) if s.status == "built"]
    ss = [Scheme(s.label, s.topology, s.waveform, f(s.cfg)) for s in ss]
    fe = Frontend60.from_config(f(zero_if_60ghz(k=8)))           # example 04's shared instance
    return compare.build(ss, fe=fe, time_domain=not quick)


def main(argv=None) -> int:
    print(ENGINE_BANNER)
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1))
    a = ap.parse_args(argv)
    quick = a.quick or os.environ.get("MMW60_SMOKE") == "1"
    t0 = time.time()
    preset = zero_if_60ghz(k=K_DPD)
    fe_p = Frontend60.from_config(tgad_em_pa(preset))
    fe_s = Frontend60.from_config(preset)
    pa_p, pa_s = fe_p.scaled_pa(), fe_s.scaled_pa()
    print(f"mmw60 {__version__}; {'QUICK' if quick else 'full'}; back-off from {fe_s.obo_reference}: presets "
          f"{fe_s.obo_db:g} dB ({tag('derived.pa60_obo_at_evm_limit_db')}), 11ad EM PA {fe_p.obo_db:g} dB "
          f"({tag('liu2025.pa_obo_db')})")
    print("[spec] = read in the original, quoted in data/spec; [survey, unverified] = read from a search snippet "
          "only; [assumed] = this library's choice; [derived] = computed from entries")

    # ---------------------------------------------------------------- 1
    print("\n== 1. measured 60 GHz CMOS PAs, and the 11ad EM PA (the presets' until 2026-11-12) among them ==")
    print(f"{'PA':<40} {'Psat':>6} {'P1dB':>6} {'gap':>5} {'gain':>6} {'PAE pk':>7}   figure from")
    for name, psat, p1, g, pae, src in measured_rows():
        print(f"{name:<40} {psat:6.1f} {p1:6.1f} {gap_db(psat, p1):5.1f} {'—' if g is None else f'{g:.1f}':>6} "
              f"{'—' if pae is None else f'{100 * pae:.1f}':>7}   {src}")
    t1 = spec.value("pa60.eumc2011_table1")
    cols = t1["columns"]
    rows = [dict(zip(cols, r)) for r in t1["rows"]]
    for name, key in (("Psat", "psat_dbm"), ("gap", None), ("PAE pk", "pae_peak_pct")):
        vals = np.array([r["psat_dbm"] - r["p1db_dbm"] if key is None else r[key] for r in rows], dtype=float)
        print(f"{'  ' + str(len(rows)) + ' PAs compiled, ' + name:<40} min {vals.min():5.1f}  median "
              f"{np.median(vals):5.1f}  max {vals.max():5.1f}   {tag('pa60.eumc2011_table1')} (secondary)")
    print(f"{'11ad EM Rapp, assumed scale':<40} {pa_p.psat_dbm:6.1f} {pa_p.p1db_out_dbm:6.1f} "
          f"{gap_db(pa_p.psat_dbm, pa_p.p1db_out_dbm):5.1f} {pa_p.gain_db:6.1f} {100 * pa_p.pae_max:7.1f}   "
          f"{tag('tgad_em.pa_rapp_p')}, {tag('assumed.pa60_psat_dbm')}")
    print(f"{'presets (measured PA)':<40} {pa_s.psat_dbm:6.1f} {pa_s.p1db_out_dbm:6.1f} "
          f"{gap_db(pa_s.psat_dbm, pa_s.p1db_out_dbm):5.1f} {pa_s.gain_db:6.1f} {100 * pa_s.pae_max:7.1f}   "
          f"{tag('assumed.pa60_surveyed_pick')}, Rapp p {fe_s.pa_model.p:g} = {tag('derived.pa60_rapp_p_asada_eumc2011')}")
    print("(dBm, dBm, dB = Psat − P1dB, dB, %.  The 11ad EM PA's Psat is inside the measured range; its P1dB is "
          f"{gap_db(pa_p.psat_dbm, pa_p.p1db_out_dbm):.1f} dB below it, against a measured median of "
          f"{np.median([r['psat_dbm'] - r['p1db_dbm'] for r in rows]):.1f} dB: the 11ad EM shape compresses far more "
          "gradually than these PAs.  The AM/PM is the 11ad EM one in both rows: none of the papers gives it)")

    # ---------------------------------------------------------------- 2
    print("\n== 2. the PA alone against the back-off (EVM after the equaliser's complex gain, dB) ==")
    med_gap = float(np.median([r["psat_dbm"] - r["p1db_dbm"] for r in rows]))
    p_median = brentq(lambda p: 10 * np.log10(ModifiedRappPA(p=p).p_sat / ModifiedRappPA(p=p).p1db) - med_gap, 0.3, 20)
    shapes = (("11ad EM (p %.2f)" % fe_p.pa_model.p, fe_p.pa_model),
              ("presets (p %.3f)" % fe_s.pa_model.p, fe_s.pa_model),
              ("compiled median gap (p %.2f)" % p_median, ModifiedRappPA(p=p_median)))
    print(f"{'back-off from Psat':<30}" + "".join(f"{o:>7.0f}" for o in BACKOFFS) + "   (dB)")
    for name, m in shapes:
        print(f"{name:<30}" + "".join(f"{pa_isolated_evm_db(m, o, 'psat'):7.1f}" for o in BACKOFFS))
    print(f"{'back-off from P1dB':<30}" + "".join(f"{o:>7.0f}" for o in BACKOFFS))
    for name, m in shapes:
        print(f"{name:<30}" + "".join(f"{pa_isolated_evm_db(m, o, 'p1db'):7.1f}" for o in BACKOFFS))
    print(f"(at its own back-off the 11ad EM PA ({fe_p.obo_db:g} dB from Psat) runs "
          f"{pa_p.p1db_out_dbm - fe_p.target_pout_dbm():+.1f} dB from its P1dB, the presets' ({fe_s.obo_db:g} dB) "
          f"{pa_s.p1db_out_dbm - fe_s.target_pout_dbm():+.1f} dB; the medium-gap row is a sensitivity only)")
    rule = spec.value("assumed.pa60_operating_rule")
    lim = float(rule["evm_limit_db"])
    print(f"\n-- the operating rule: the back-off at which the PA alone reads {lim:g} dB, the 802.11ad 16-QAM "
          f"TX EVM limit ({tag('assumed.pa60_operating_rule')}) --")
    no_ampm = ModifiedRappPA(p=fe_s.pa_model.p, ampm=False)
    print(f"{'shape':<30} {'from Psat':>10} {'from P1dB':>10}   (dB)")
    for name, m in (*shapes, ("presets without AM/PM", no_ampm)):
        o = obo_for_isolated_evm(m, lim, "psat")
        print(f"{name:<30} {o:10.2f} {o - 10 * np.log10(m.p_sat / m.p1db):10.2f}")
    seeds = [obo_for_isolated_evm(fe_s.pa_model, lim, "psat", seed=sd) for sd in (1, 2, 3, 4, 5)]
    wu = spec.value("pa60.wu_isscc2015")
    print(f"(the presets carry {fe_s.obo_db:g} dB = {tag('derived.pa60_obo_at_evm_limit_db')}; seeds 1–5 of the "
          f"Gaussian envelope give {min(seeds):.2f}–{max(seeds):.2f} dB.  On the 11ad shape the same rule asks for "
          f"more than Liu's {fe_p.obo_db:g} dB.  The transmitter the rule is read from, {tag('pa60.wu_isscc2015')}, "
          f"is rated at {wu['tx_pout_at_evm_limit_dbm']:g} dBm for {wu['evm_limit_db']:g} dB on single-carrier "
          f"16-QAM, {wu['tx_pout_at_evm_limit_dbm'] - wu['pa_p1db_dbm']:+.1f} dB from its PA's P1dB "
          f"({wu['pa_p1db_dbm']:g} dBm, read from a figure): a lower-PAPR waveform than OFDM, so not a check of the "
          "number, only of the convention)")

    # ---------------------------------------------------------------- 3
    print("\n== 3. the efficiency law of the power column against the papers that give PAE at P1dB ==")
    print(f"{'PA':<30} {'gap':>5} {'peak':>6} {'at P1dB':>8} {'class B':>8} {'class A':>8}   figure from")
    for key, name in (("pa60.asada_eumc2011", "Asada"), ("pa60.ning_elex2011", "Li")):
        v = spec.value(key)
        g = gap_db(v["psat_dbm"], v["p1db_dbm"])
        b = v["pae_peak"] * np.sqrt(10 ** (-g / 10))
        aa = v["pae_peak"] * 10 ** (-g / 10)
        print(f"{name:<30} {g:5.1f} {100 * v['pae_peak']:6.1f} {100 * v['pae_at_p1db']:8.1f} {100 * b:8.1f} "
              f"{100 * aa:8.1f}   {tag(key)}")
    print("(dB, then PAE in %.  The power column scales the peak PAE as class B, sqrt(Pout / Psat) "
          f"({tag('assumed.pa60_pae_max')}); measured PAE at P1dB lies between the class-B and class-A readings for "
          "one PA and above class B for the other)")

    # ---------------------------------------------------------------- 4
    print(f"\n== 4. wifitrx's DPD step on each PA (K = {K_DPD}, 11ac {BASE_DPD / 1e6:g} MHz base; the calibration "
          "sequence run at each back-off from Psat) ==")
    obos = (fe_s.obo_db,) if quick else tuple(sorted({*DPD_BACKOFFS, fe_s.obo_db}))
    jobs = [(w, o, d) for w in ("11ad EM", "presets") for o in obos for d in (False, True)]
    with ProcessPoolExecutor(max(1, a.jobs)) as ex:
        res = {(w, o, d): (p, tx, lb) for w, o, d, p, tx, lb in ex.map(dpd_cell, jobs)}
    print(f"{'PA':<10} {'back-off':>9} {'Pout':>6} {'TX no DPD':>10} {'TX DPD':>8} {'gain':>6} {'loopback':>9}")
    for w in ("11ad EM", "presets"):
        for o in obos:
            p, tx0, _ = res[(w, o, False)]
            _, tx1, lb1 = res[(w, o, True)]
            print(f"{w:<10} {o:9g} {p:6.1f} {tx0:10.1f} {tx1:8.1f} {tx0 - tx1:6.1f} {lb1:9.1f}")
    print(f"(dB, dBm, then EVM in dB as a standard receiver reads it; 'gain' = what the DPD step bought; a 0.0 means "
          f"the step kept nothing better than no DPD.  {fe_s.obo_db:g} dB is the presets' operating point, "
          f"{fe_p.obo_db:g} dB the 11ad EM PA's)  [{time.time() - t0:.0f}s]")

    # ---------------------------------------------------------------- 5
    print("\n== 5. the comparison table's 11be 80 MHz rows with each PA (decoder cap, uncalibrated IQ) ==")
    reps = {"11ad EM": table_rows(tgad_em_pa, quick), "presets": table_rows(lambda c: c, quick)}
    print(f"{'row':<46} {'PA':<9} {'floor':>6} {'MCS':>4} {'rate':>7} {'pJ/bit':>7} {'EIRP':>6}   limited by")
    labels = [r.label for r in reps["11ad EM"]["_rows"]]
    for i, lab in enumerate(labels):
        for w in ("11ad EM", "presets"):
            r = reps[w]["_rows"][i]
            pj = (r.power_dec or {}).get("pj_per_bit")
            eirp = None if r.eirp is None else r.eirp["margin_avg_db"]
            print(f"{lab if w == '11ad EM' else '':<46} {w:<9} {r.dec_floor_db if r.dec_floor_db is not None else r.floor_db:6.1f} "
                  f"{'—' if r.dec_mcs is None else r.dec_mcs:>4} "
                  f"{'—' if r.dec_rate_mbps is None else f'{r.dec_rate_mbps:.0f}':>7} "
                  f"{'—' if pj is None else f'{pj:.0f}':>7} {'—' if eirp is None else f'{eirp:.1f}':>6}   {r.dominant}")
    print("(floor dB (the decoder's: analytic, or the time-domain EVM when that reads worse), MCS at the decoder cap, "
          "Mb/s, pJ/bit at that rate, average EIRP margin dB.  The PA-isolated EVM at each PA's own back-off: "
          f"11ad EM {reps['11ad EM']['pa_isolated_evm_db']:.1f} dB at {fe_p.obo_db:g}, presets "
          f"{reps['presets']['pa_isolated_evm_db']:.1f} dB at {fe_s.obo_db:g})")
    print(f"\n[{time.time() - t0:.0f}s]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
