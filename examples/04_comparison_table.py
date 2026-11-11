"""Example 04 — the comparison table (同台表): every scheme on one front end.

Rows: the WiFi 7 chain at K = 1 on a 6 GHz carrier, topology B at K = 1 / 4 /
8 / 16 / 32 on 60.48 GHz (11ac 20 MHz base) and K = 4 … 32 on the 11be
80 MHz base; topology A and the two 802.11ay waveforms are listed with the
milestone that brings them.  One ``Frontend60`` instance — PA, converters,
IQ, LO chain, EIRP ceiling — is handed to every ``LinkSim`` (iron rule 2).
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

from mmw60 import ENGINE_BANNER, __version__, compare                              # noqa: E402
from mmw60.config import LoConfig, PhaseNoiseConfig, zero_if_60ghz                 # noqa: E402
from mmw60.frontend import Frontend60                                              # noqa: E402
from mmw60.frontend.grid import analytic_floors, max_mcs_for_floor, pa_isolated_evm_db  # noqa: E402
from mmw60.sim.link import evm_at                                                   # noqa: E402

OUT = HERE / "output"
LO_MODELS = (("pole_zero (11ad EM shape, Liu numbers)", PhaseNoiseConfig()),
             ("wifitrx_wifi7 (the WiFi 7 synthesizer)", PhaseNoiseConfig(model="wifitrx_wifi7")),
             ("pllsim wu19 profile x N (assumed.lo_multiplier_law)",
              PhaseNoiseConfig(model="profile", profile_path="bench_wu19_spll_frac_52m_6p253g.yaml")))


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
        schemes += [s for s in compare.scheme_matrix(ks=(4, 8, 16, 32), standard="11be", bandwidth_hz=80e6)
                    if s.status == "built"]
    fe = Frontend60.from_config(zero_if_60ghz(k=8))
    d = fe.describe()
    print(f"mmw60 {__version__}; {'QUICK' if quick else 'full'}; one Frontend60 for every row: PA {d['pa']} Psat "
          f"{d['psat_dbm']:g} dBm OBO {d['obo_db']:g} dB -> Pout {d['pout_dbm']:g} dBm, PAE_max {100 * fe.pa_pae_max:.0f} %; "
          f"LO {d['lo_profile']} IPN {d['lo_ipn_dbc']:.1f} dBc; converters -{fe.converters.bits_per_octave:g} bit/octave "
          f"from ENOB {fe.converters.enob_ref:g} @ {fe.converters.fs_ref_hz / 1e9:g} GS/s; EIRP ceiling "
          f"{fe.eirp.avg_dbm:g} dBm avg (FCC 15.255)")
    rep = compare.build(schemes, fe, time_domain=not quick)
    print(f"matrix: {len(rep['matrix'])} (topology, waveform) pairs; {len(rep['rows'])} rows with numbers, "
          f"{len(rep['pending'])} without")
    print("\n== 1. the table (floor / TD / EvmBudget in dB; CFO in subcarriers; rate at the uncalibrated cap; "
          "EIRP margin to 40 dBm avg; pJ/bit at the cap) ==")
    print(f"{'scheme':<44} {'BW[M]':>6} {'SCS[M]':>6} {'Tsym[ns]':>6} {'CFO':>6} STF  {'floor':>6} {'TD':>6} "
          f"{'budget':>6} {'max':>5} {'IQcal':>5} {'Mb/s':>5} {'EIRP':>6} {'pJ/bit':>7} verdict")
    for r in rep["rows"]:
        print(_row_line(r), flush=True)
    for p in rep["pending"]:
        print(f"{p['label']:<44} {p['reason']}")
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
        print(f"{r['label']:<44} {f(b['pn_ici_db'])} {f(b['pn_budget_db'])} {b['cpe_tracked_fraction']:7.1%} "
              f"{f(t.get('iq_image'))} {f(t.get('converters'))} {f(t.get('pa'))} {f(t.get('isi'))}")
    print("\n== 4. power blocks per bit at the cap [pJ/bit] (Halo example 41's method: public-figure coefficients, read ratios) ==")
    print(f"{'scheme':<44} {'Mb/s':>6} {'pa':>6} {'lo':>6} {'conv':>6} {'dpd':>6} {'fft':>6} {'dec':>6} {'total':>7}  not counted")
    for r in rep["rows"]:
        p = r["power"]
        if not p:
            print(f"{r['label']:<44}      —  (no MCS reachable)")
            continue
        bl = p["blocks"]
        g = lambda n: f"{bl[n]['pj_per_bit']:6.0f}" if n in bl else "     —"  # noqa: E731
        print(f"{r['label']:<44} {p['bit_rate_bps'] / 1e6:6.0f} {g('pa')} {g('lo')} {g('converters')} {g('dpd')} "
              f"{g('fft')} {g('decoder')} {p['pj_per_bit']:7.0f}  {'; '.join(p['omitted']) or '—'}")
    c = rep["coefficients"]
    print(f"coefficients: Walden {c['walden_fom_fj']:.0f} fJ/step; Horowitz {c['mult32_pj']:g} / {c['add32_pj']:g} pJ at 45 nm "
          f"(node scale {c['node_scale']:g}); {c['word_bits']} bit; synthesizers {c['pll60_mw']:g} / {c['pll_sub7_mw']:g} mW")

    print("\n== 4b. the decoder's cap: the EVM floor as one more noise term against the measured ideal PER thresholds "
          "(data/spec/per_thresholds.yaml); reachable while -floor >= threshold + margin ==")
    print(f"{'scheme':<44} {'floor':>6} {'conf':>5} {'dec':>5} {'T[dB]':>6} {'SNRreq':>6} {'costs':>6} {'dec-cal':>7} {'Mb/s':>6} {'pJ/bit':>7}")
    for r in rep["rows"]:
        g = lambda v, fmt: "    —" if v is None else fmt.format(v)  # noqa: E731
        thr = None if r["dec_mcs"] is None else r["dec_required_snr_db"] - r["dec_penalty_db"]
        pjd = "      —" if not r["power_dec"] else f"{r['power_dec']['pj_per_bit']:7.0f}"
        print(f"{r['label']:<44} {g(r['dec_floor_db'], '{:6.1f}'):>6} {g(r['max_mcs'], 'MCS{}'):>5} {g(r['dec_mcs'], 'MCS{}'):>5} "
              f"{g(thr, '{:6.2f}'):>6} {g(r['dec_required_snr_db'], '{:6.2f}'):>6} {g(r['dec_penalty_db'], '{:6.2f}'):>6} "
              f"{g(r['dec_mcs_cal'], 'MCS{}'):>7} {g(r['dec_rate_mbps'], '{:6.0f}'):>6} {pjd}")
    print("floor = the worse of the analytic floor and the time-domain EVM of table 1 (the analytic sum is optimistic once the "
          "IQ image is no small perturbation; dec-cal has only the analytic floor at the calibrated IRR)")
    print("conf = the transmitter-conformance cap of table 1 (floor 3 dB under the standard's TX-EVM limit); dec = what the "
          "decoder carries; the rate and pJ/bit here are at the decoder cap (table 1 and 4 stay at the conformance cap)")

    print("\n== 5. the LO models side by side (each its own Frontend60; analytic floor + MCS cap"
          f"{'' if quick else ' + TD EVM'}) ==")
    print(f"{'LO model':<52} {'K':>3} {'IPN[dBc]':>9} {'pn ICI':>7} {'floor':>6} {'TD':>6}  max MCS")
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
            print(f"  {e['knob']:<26} at {str(e['value']):<9} conformance cap moved on {len(e['mcs_moved']):>2} row(s), "
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
