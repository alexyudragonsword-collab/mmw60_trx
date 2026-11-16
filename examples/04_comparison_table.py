"""Example 04 — the comparison table (同台表): every scheme on one front end.

Rows: the WiFi 7 chain at K = 1 on a 6 GHz carrier, topology B at K = 1 / 4 /
8 / 16 / 32 on 60.48 GHz (11ac 20 MHz base) and K = 4 … 32 on the 11be
80 MHz base; topology A (the IF extender) on 11ac 20 MHz and 11be 80 / 320
MHz, the 320 MHz row once more with the chip's PA bypassed; the two 802.11ay
waveforms on topology B (EDMG channel 2) in their own section 1b — no analytic
sum there: the time-domain EVM, raw and on the chain wifitrx's sequence
calibrated, the cap under the be rows' margin rule.  One ``Frontend60``
instance — PA, converters, IQ, LO chain, EIRP ceiling — is handed to every
``LinkSim`` (iron rule 2).
Per row: numerology, CFO capture, the analytic EVM floor and its terms, the
time-domain EVM of the same cell (flat channel, no noise), wifitrx's
``EvmBudget`` fed the same terms, the MCS cap (uncalibrated and at the IRR
example 03 measured after calibration), rate and spectral efficiency at the
cap, the PA operating point against the EIRP limit, and the power blocks
per bit in Halo example 41's terms (ratios, not totals).  Then: the three
LO models side by side (the 11ad pole-zero shape, the WiFi 7 synthesizer
profile wifitrx ships, a pllsim clock profile moved to the carrier by
20·log10 N), and the sensitivity of the MCS cap and the pJ/bit ranking to
every coefficient and assumption the columns lean on.

    python examples/04_comparison_table.py [--quick]
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

from mmw60 import ENGINE_BANNER, __version__, compare, spec                        # noqa: E402
from mmw60.config import AY_WAVEFORMS, LoConfig, PhaseNoiseConfig, zero_if_60ghz   # noqa: E402
from mmw60.frontend import Frontend60                                              # noqa: E402
from mmw60.frontend.grid import analytic_floors, format_cap, max_mcs_for_floor, pa_isolated_evm_db  # noqa: E402
from mmw60.impairments.phase_noise import load_clock_profile                        # noqa: E402
from mmw60.sim.link import evm_at                                                   # noqa: E402

OUT = HERE / "output"
_X10 = spec.value("survey.clock_profile_wu19_x10")


def _x10_row(path: str) -> tuple[str, PhaseNoiseConfig]:
    floor = load_clock_profile(path)["floor_dbchz"]
    tag = " (assumed)" if floor == spec.value("assumed.lo_multiplier_floor_dbchz") else ""
    return (f"pllsim wu19 x{_X10['multiply_by']}, floor {floor:.0f} dBc/Hz{tag}",
            PhaseNoiseConfig(model="profile", profile_path=path))


LO_MODELS = (("pole_zero (11ad EM shape, Liu numbers)", PhaseNoiseConfig()),
             ("wifitrx_wifi7 (the WiFi 7 synthesizer)", PhaseNoiseConfig(model="wifitrx_wifi7")),
             _x10_row(_X10["file"]), *(_x10_row(f) for f in _X10["sensitivity_files"]))


def _row_line(r: dict) -> str:
    pj = "—" if not r["power"] else f"{r['power']['pj_per_bit']:7.0f}"
    td = "   —  " if r["td_evm_db"] is None else f"{r['td_evm_db']:6.1f}"
    mcs = "  —  " if r["max_mcs"] is None else f"MCS{r['max_mcs']}"
    cal = "  —  " if r["max_mcs_cal"] is None else f"MCS{r['max_mcs_cal']}"
    rate = "    —" if r["rate_mbps"] is None else f"{r['rate_mbps']:5.0f}"
    eirp = "   —  " if not r["eirp"] else f"{r['eirp']['margin_avg_db']:+5.0f} "
    return (f"{r['label']:<44} {r['bw_eff_hz'] / 1e6:6.0f} {r['scs_eff_hz'] / 1e6:6.3f} {r['t_symbol_eff_s'] * 1e9:6.0f} "
            f"{r['cfo_subcarriers']:6.2f} {'yes' if r['cfo_captured'] else 'NO ':<4} {r['floor_db']:6.1f} {td} "
            f"{r['evm_budget']['predicted_evm_db']:6.1f} {mcs:>5} {cal:>5} {rate} {eirp} {pj} {r['verdict']} {r['reason']}")


def main(argv=None) -> int:
    print(ENGINE_BANNER)
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--jobs", type=int, default=1, help="accepted for symmetry with examples 00 / 01; serial")
    a = ap.parse_args(argv)
    quick = a.quick or os.environ.get("MMW60_SMOKE") == "1"
    t0 = time.time()
    OUT.mkdir(exist_ok=True)
    ks = (1, 8) if quick else (1, 4, 8, 16, 32)
    schemes = compare.scheme_matrix(ks=ks, standard="11ac", bandwidth_hz=20e6)
    if not quick:
        # the 802.11ay rows do not depend on the WiFi base: they come once, with the first matrix
        schemes += [s for s in compare.scheme_matrix(ks=(4, 8, 16, 32), standard="11be", bandwidth_hz=80e6)
                    if s.status == "built" and s.waveform not in AY_WAVEFORMS]
        # topology A on the widest channel the chip has: the same 320 MHz at 60 GHz as 80 MHz × 4
        a320 = [s for s in compare.scheme_matrix(ks=(), standard="11be", bandwidth_hz=320e6)
                if s.key == ("if_extender", "be")]
        schemes += a320
        # the same row with the chip's PA bypassed: the IF taken at its mixer output, the PA
        # powered down (assumed.ifext_chip_pa_bypass; the chip's calibration runs on that chain)
        schemes += [compare.Scheme(s.label.replace("IF extender", "IF ext. PA bypass"), s.topology, s.waveform,
                                   dc.replace(s.cfg, ifext=dc.replace(s.cfg.ifext, chip_pa_bypass=True)))
                    for s in a320]
    fe = Frontend60.from_config(zero_if_60ghz(k=8))
    d = fe.describe()
    print(f"mmw60 {__version__}; {'QUICK' if quick else 'full'}; one Frontend60 for every row: PA {d['pa']} Psat "
          f"{d['psat_dbm']:g} dBm OBO {d['obo_db']:g} dB -> Pout {d['pout_dbm']:g} dBm, PAE_max {100 * fe.pa_pae_max:.0f} %; "
          f"LO {d['lo_profile']} IPN {d['lo_ipn_dbc']:.1f} dBc; converters -{fe.converters.bits_per_octave:g} bit/octave "
          f"from ENOB {fe.converters.enob_ref:g} @ {fe.converters.fs_ref_hz / 1e9:g} GS/s; EIRP ceiling "
          f"{fe.eirp.avg_dbm:g} dBm avg (FCC 15.255)")
    rep = compare.build(schemes, fe, time_domain=not quick)
    print(f"matrix: {len(rep['matrix'])} (topology, waveform) pairs; {len(rep['rows']) + len(rep['ay_rows'])} rows "
          f"with numbers ({len(rep['ay_rows'])} of them 802.11ay, section 1b), {len(rep['pending'])} without")
    print("\n== 1. the table (floor / TD / EvmBudget in dB; CFO in subcarriers; rate at the uncalibrated cap; "
          "EIRP margin to 40 dBm avg; pJ/bit at the cap) ==")
    print(f"{'scheme':<44} {'BW[M]':>6} {'SCS[M]':>6} {'Tsym[ns]':>6} {'CFO':>6} STF  {'floor':>6} {'TD':>6} "
          f"{'budget':>6} {'max':>5} {'IQcal':>5} {'Mb/s':>5} {'EIRP':>6} {'pJ/bit':>7} verdict")
    for r in rep["rows"]:
        print(_row_line(r), flush=True)
    for p in rep["pending"]:
        print(f"{p['label']:<44} {p['reason']}")
    print("\n== 1b. the two 802.11ay rows (same front end instance; EVM only; no analytic sum: the floor is the "
          "time-domain EVM, raw and on the chains wifitrx's sequence calibrated, per payload constellation) ==")
    print(f"{'scheme':<44} {'fs[GS/s]':>8} {'occ[GHz]':>8} {'unit[ns]':>8} {'CFO/STF[MHz]':>13} {'raw floor':>9} "
          f"{'cal floor':>9} {'raw cap':>7} {'cal cap':>7} {'Mb/s':>6} {'pJ/bit':>7} {'at limit':>8} {'Mb/s':>6}")
    for r in rep["ay_rows"]:
        rf, cf = r["floor_raw_db"], r["floor_cal_db"]
        pj = "—" if not r["power_cal"] else f"{r['power_cal']['pj_per_bit']:.0f}"
        cap_raw = "—" if r["cap_raw"] is None else f"MCS{r['cap_raw']}"
        cap_cal = "—" if r["cap_cal"] is None else f"MCS{r['cap_cal']}"
        rate = "—" if r["rate_cal_mbps"] is None else f"{r['rate_cal_mbps']:.0f}"
        cap_lim = "—" if r["cap_cal_at_limit"] is None else f"MCS{r['cap_cal_at_limit']}"
        rate_lim = "—" if r["rate_cal_at_limit_mbps"] is None else f"{r['rate_cal_at_limit_mbps']:.0f}"
        print(f"{r['label']:<44} {r['fs_eff_hz'] / 1e9:8.2f} {r['occupied_bw_hz'] / 1e9:8.3f} {r['unit_s'] * 1e9:8.1f} "
              f"{r['cfo_hz'] / 1e6:5.2f}/{r['stf_range_hz'] / 1e6:<6.2f} {max(rf.values()):9.2f} {max(cf.values()):9.2f} "
              f"{cap_raw:>7} {cap_cal:>7} {rate:>6} {pj:>7} {cap_lim:>8} {rate_lim:>6}")
    if rep["ay_rows"]:
        r0 = rep["ay_rows"][0]
        print(f"(floors: the worst constellation's; cal = wifitrx's sequence on the ay chain at the preset back-off, "
              f"IRR {r0['cal_irr_db']:.1f} dB, LO leak {r0['cal_lo_leak_dbc']:.1f} dBc; caps by the EDMG TX EVM limits "
              f"under the be rows' rule, the floor {r0['cap_margin_db']:g} dB under the limit "
              f"(assumed.mcs_evm_margin_db), the passing MCS with the highest rate; Mb/s and pJ/bit at the calibrated "
              f"cap, no decoder counted; 'at limit' = the calibrated cap with no margin, example 15's reading; "
              f"per constellation and back-off: example 15)")
        # the be rows on the same footing: their calibrated cap (the IQcal column: the analytic floor at
        # example 03's measured IRR), only rows that catch the CFO and sit in the 57-71 GHz plan
        be_cal = [r for r in rep["rows"] if r["power_cal"] and r["cfo_captured"] and r["plan_ok"] is not False]
        if be_cal:
            fast = max(be_cal, key=lambda r: r["rate_cal_mbps"])
            cheap = min(be_cal, key=lambda r: r["power_cal"]["pj_per_bit"])
            pairs = [("fastest and fewest pJ/bit", fast)] if fast is cheap else [("fastest", fast),
                                                                                  ("fewest pJ/bit", cheap)]
            for what, r in pairs:
                print(f"be rows at their calibrated cap, {what}: {r['label']} MCS{r['max_mcs_cal']} "
                      f"{r['rate_cal_mbps']:.0f} Mb/s {r['power_cal']['pj_per_bit']:.0f} pJ/bit "
                      f"(decoder {r['power_cal']['blocks'].get('decoder', {}).get('pj_per_bit', 0):.0f} of it)")
    print("\n== 2. cross-checks: analytic floor vs time-domain EVM (|Δ| ≤ 2 dB while the floor ≤ −8 dB and the CFO is "
          "caught), EvmBudget vs floor ==")
    for c in rep["cross_checks"]:
        td = "—" if c.get("td_delta_db") is None else f"{c['td_delta_db']:+.1f} dB {'ok' if c['td_ok'] else ('n/a' if c['td_ok'] is None else 'OUTSIDE')}"
        print(f"  {c['label']:<44} TD − floor {td:<18} EvmBudget − floor {c['budget_delta_db']:+.1f} dB")
    print("\n== 3. analytic terms [dB]: this library's phase-noise ICI (to fs/2) next to EvmBudget's "
          "(10 kHz–100 MHz IPN × (1 − CPE-tracked share)) ==")
    print(f"{'scheme':<44} {'pn ICI':>7} {'pn bdgt':>7} {'tracked':>7} {'iq':>7} {'conv':>7} {'pa':>7} {'isi':>7}")
    for r in rep["rows"]:
        t, b = r["terms_db"], r["evm_budget"]
        f = lambda v: "     —" if v is None or v < -150 else f"{v:7.1f}"  # noqa: E731
        own = f"   chip residual {t['chip']:.1f}, chip LO {t['chip_lo']:.1f}" if "chip" in t and "chip_lo" in t else ""
        print(f"{r['label']:<44} {f(b['pn_ici_db'])} {f(b['pn_budget_db'])} {b['cpe_tracked_fraction']:7.1%} "
              f"{f(t.get('iq_image'))} {f(t.get('converters'))} {f(t.get('pa'))} {f(t.get('isi'))}{own}")
    print("only in the IF-extender rows: the chip's residual after its own calibration (measured) and its synthesizer's ICI, "
          "the IF filter (equalised: 0 dB here) and the image band's noise (a noise-figure term, example 06); only in the "
          "zero-IF rows: the uncalibrated baseband IQ image, the converters at ENOB(fs_eff), LO leakage and RX DC")
    print("\n== 4. power blocks per bit at the cap [pJ/bit] (Halo example 41's method: public-figure coefficients, read ratios) ==")
    print(f"{'scheme':<44} {'Mb/s':>6} {'pa':>6} {'lo':>6} {'conv':>6} {'c.dpd':>6} {'fft':>6} {'dec':>6} {'total':>7}  not counted")
    for r in rep["rows"]:
        p = r["power"]
        if not p:
            print(f"{r['label']:<44}      —  (no MCS reachable)")
            continue
        bl = p["blocks"]
        g = lambda n: f"{bl[n]['pj_per_bit']:6.0f}" if n in bl else "     —"  # noqa: E731
        chip = f"; total includes the chip's PA as the driver, {bl['chip_pa']['pj_per_bit']:.0f}" if "chip_pa" in bl else ""
        print(f"{r['label']:<44} {p['bit_rate_bps'] / 1e6:6.0f} {g('pa')} {g('lo')} {g('converters')} {g('chip_dpd')} "
              f"{g('fft')} {g('decoder')} {p['pj_per_bit']:7.0f}  {'; '.join(p['omitted']) or '—'}{chip}")
    # the 802.11ay rows have no uncalibrated cap: their blocks at the calibrated one (section 1b)
    for r in rep["ay_rows"]:
        p = r["power_cal"]
        if not p:
            print(f"{r['label']:<44}      —  (no MCS reachable on the calibrated chain)")
            continue
        bl = p["blocks"]
        g = lambda n: f"{bl[n]['pj_per_bit']:6.0f}" if n in bl else "     —"  # noqa: E731
        print(f"{r['label']:<44} {p['bit_rate_bps'] / 1e6:6.0f} {g('pa')} {g('lo')} {g('converters')} {g('chip_dpd')} "
              f"{g('fft')} {g('decoder')} {p['pj_per_bit']:7.0f}  at the calibrated cap MCS{r['cap_cal']}; "
              f"{'; '.join(p['omitted']) or '—'}")
    c = rep["coefficients"]
    print(f"coefficients: Walden {c['walden_fom_fj']:g} fJ/step; Horowitz {c['mult32_pj']:g} / {c['add32_pj']:g} pJ at 45 nm "
          f"(node scale {c['node_scale']:g}); {c['word_bits']} bit; synthesizers {c['pll60_mw']:g} / {c['pll_sub7_mw']:g} mW")
    print("c.dpd = the chip's own DPD (topology A: its calibration runs it and the floor's chip residual is read after it); "
          "no row pays for a DPD on the 60 GHz PA, whose floor term is the PA without predistortion (ROADMAP C8)")

    print("\n== 4b. the decoder's cap: the EVM floor as one more noise term against the measured ideal PER thresholds "
          "(data/spec/per_thresholds.yaml); reachable while -floor >= threshold + margin ==")
    print(f"{'scheme':<44} {'floor':>6} {'conf':>5} {'dec':>6} {'next':>6} {'T[dB]':>6} {'SNRreq':>6} {'costs':>6} "
          f"{'dec-cal':>7} {'next':>6} {'Mb/s':>6} {'pJ/bit':>7}")
    for r in rep["rows"]:
        g = lambda v, fmt: "    —" if v is None else fmt.format(v)  # noqa: E731
        thr = None if r["dec_mcs"] is None else r["dec_required_snr_db"] - r["dec_penalty_db"]
        pjd = "      —" if not r["power_dec"] else f"{r['power_dec']['pj_per_bit']:7.0f}"
        print(f"{r['label']:<44} {g(r['dec_floor_db'], '{:6.1f}'):>6} {g(r['max_mcs'], 'MCS{}'):>5} "
              f"{format_cap(r['dec_mcs'], r['dec_mcs_range']):>6} {g(r['dec_next_margin_db'], '{:+6.2f}'):>6} "
              f"{g(thr, '{:6.2f}'):>6} {g(r['dec_required_snr_db'], '{:6.2f}'):>6} {g(r['dec_penalty_db'], '{:6.2f}'):>6} "
              f"{format_cap(r['dec_mcs_cal'], r['dec_mcs_cal_range']):>7} {g(r['dec_cal_next_margin_db'], '{:+6.2f}'):>6} "
              f"{g(r['dec_rate_mbps'], '{:6.0f}'):>6} {pjd}")
    print("floor = the worse of the analytic floor and the time-domain EVM of table 1 (the analytic sum is optimistic once the "
          "IQ image is no small perturbation; dec-cal has only the analytic floor at the calibrated IRR)")
    print("conf = the transmitter-conformance cap of table 1 (floor 3 dB under the standard's TX-EVM limit); dec = what the "
          "decoder carries; the rate and pJ/bit here are at the decoder cap (table 1 and 4 stay at the conformance cap)")
    print("MCS5–6 = the cap with every threshold at the upper / lower end of its 95 % interval (counting statistics "
          "only, spec.per_threshold_ci_db): the floor sits on an MCS line inside the measurement's own scatter; next = "
          "-floor - (T + margin) of the MCS above the cap, how far the floor is from one more MCS (a few hundredths "
          "of a dB is the same reading, whatever the interval says)")

    print("\n== 5. the LO models side by side (each its own Frontend60; analytic floor + MCS cap"
          f"{'' if quick else ' + TD EVM'}) ==")
    print(f"{'LO model':<52} {'K':>3} {'IPN[dBc]':>9} {'pn ICI':>7} {'floor':>6} {'TD':>6}  max MCS")
    print(f"(pllsim rows: the wu19 preset retuned to {_X10['f_in_hz'] / 1e9:g} GHz through pllsim's x{_X10['multiply_by']} block, "
          "survey.clock_profile_wu19_x10; the floor is the multiplier's, assumed.lo_multiplier_floor_dbchz)")
    pa_evm = pa_isolated_evm_db(fe.pa_model, fe.obo_db, fe.obo_reference)
    for name, pn in LO_MODELS:
        for k in ((8,) if quick else (1, 8, 32)):
            cfg = zero_if_60ghz(k=k)
            cfg = dc.replace(cfg, lo=LoConfig(phase_noise=pn))
            fe_k = Frontend60.from_config(cfg)
            fl = analytic_floors(cfg, fe_k, pa_evm)
            td = "   —  " if quick else f"{evm_at(dc.replace(cfg, channel=dc.replace(cfg.channel, model='flat')), None, n_packets=1, frontend=fe_k)['evm_db']:6.1f}"
            print(f"{name:<52} {k:>3} {fe_k.lo.ipn_dbc():9.1f} {fl['terms_db']['phase_noise']:7.1f} {fl['floor_db']:6.1f} {td}  "
                  f"MCS{max_mcs_for_floor(fl['floor_db'], '11ac')}")
    if not quick:
        print("\n== 6. sensitivity: which guesses decide the verdict (analytic side at every coefficient's range ends) ==")
        rep["sensitivity"] = compare.sensitivity(schemes, fe)
        print("base pJ/bit ranking (best first): " + " < ".join(rep["sensitivity"]["base"]["ranking"]))
        print("the decoder caps here start from the analytic floor alone (no time-domain run per knob): a row whose 4b cap "
              "came from the time-domain floor starts one MCS higher in this section")
        for e in rep["sensitivity"]["knobs"]:
            ratio = "—" if e["pj_ratio_min"] is None else f"x{e['pj_ratio_min']:.2f} … x{e['pj_ratio_max']:.2f}"
            print(f"  {e['knob']:<26} at {compare.knob_value_text(e['value']):<9} conformance cap moved on {len(e['mcs_moved']):>2} row(s), "
                  f"decoder cap on {len(e['dec_mcs_moved']):>2}; pJ/bit {ratio:<18} ranking {'CHANGED' if e['ranking_changed'] else 'same'}")
            for kind, moved in (("conformance", e["mcs_moved"]), ("decoder", e["dec_mcs_moved"])):
                if moved:
                    print(f"      {kind}: " + ", ".join(f"{lab.split(' @')[0]}: {x}->{y}" for lab, (x, y) in moved.items()))
    md = OUT / "04_comparison_table.md"
    md.write_text(compare.to_markdown(rep), encoding="utf-8")
    print(f"\nwrote {md.relative_to(HERE.parent)}")
    print(f"[{time.time() - t0:.0f}s]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
