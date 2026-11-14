"""Example 06 — topology A, the IF extender: the WiFi 7 chip as it is, then a 60 GHz stage.

The chip is wifitrx's own transceiver at K = 1, randomised and run through
its delivered calibration sequence (``mmw60.ifext``); its RF output at a
6 GHz-band IF goes through the interstage level, the IF band filter, the
fixed-LO mixer and the shared front end's 60 GHz PA — and the mirror on
receive.  The 60 GHz PA, the LO phase-noise numbers, crystals, EIRP limit,
channel and receiver are topology B's (the one ``Frontend60``).

What the tables answer (ROADMAP A1):

1. the frequency plan and what the IF filter does to the channel;
2. wifitrx's calibration sequence, every step, observed on the chip's own
   coupler and through a 60 GHz observation loopback (iron rule 4);
3. the predistorter with and without that 60 GHz observation, against the
   second PA's back-off;
4. the MCS cap against the fixed LO's noise at 1 MHz, with wifitrx's
   ``EvmBudget`` next to the time-domain reading;
5. the cascade back-off table: chip PA output × 60 GHz PA back-off, and
   the chip's PA bypassed (the IF taken at its mixer output);
6. the CFO: 40 ppm at 60 GHz against the chip's estimators, the multi-link
   pre-compensation and what is left (iron rule 3);
7. the inputs this library assumed, one at a time;
8. the decoder cap checked with PER.

    python examples/06_topology_a_if_extender.py [--quick] [--jobs N]
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
from mmw60.calcheck import compare_runs, run_cal_on                             # noqa: E402
from mmw60.compare import PN_BAND_HZ                                            # noqa: E402
from mmw60.config import ChannelConfig, if_extender_60ghz, zero_if_60ghz        # noqa: E402
from mmw60.frontend import Frontend60                                           # noqa: E402
from mmw60.frontend.grid import (analytic_floors, data_rate_bps, decoder_cap,   # noqa: E402
                                 decoder_floor_db, max_mcs_for_floor, pa_isolated_evm_db)
from mmw60.ifext import (CHIP_DRIVE_RMS, IfExtender, build_chip_wifitrx,        # noqa: E402
                         chip_facts, mmw_observation_path)
from mmw60.sim.curves import CurveSpec, run_curves, save_results                # noqa: E402
from mmw60.sim.link import LinkSim, evm_at                                      # noqa: E402
from mmw60.vendor.wifitrx.cal.sequence import scoring_frame, tx_evm             # noqa: E402
from mmw60.vendor.wifitrx.chain.loopback import LoopbackPath, recommended_loopback_atten_db  # noqa: E402
from mmw60.vendor.wifitrx.impairments.phase_noise import cpe_partition          # noqa: E402
from mmw60.vendor.wifitrx.link.evm_budget import EvmBudget                      # noqa: E402
from mmw60.vendor.wifitrx.waveform.ofdm import OFDMConfig                       # noqa: E402

OUT = HERE / "output"
FLAT = ChannelConfig(model="flat")
STD, BW = "11be", 80e6
LO_AT_1MHZ = (-85.0, -90.0, -95.0, -100.0, -105.0, -110.0)       # dBc/Hz at 1 MHz offset
OBO2 = (6.0, 8.0, 10.0, 12.0, 14.0, 16.0)
#: dBm at the link's drive; None = the chip's delivered gain code.  19 dBm is the top of what
#: wifitrx's tx_power step can set on this chip (its gain-code range ends there)
CHIP_POUT = (10.0, None, 16.0, 19.0)
CASCADE_OBO2 = (6.0, 8.0, 10.0, 12.0)
TARGET = 1e-2


def with_obo(cfg, obo_db):
    return dc.replace(cfg, frontend=dc.replace(cfg.frontend, pa=dc.replace(cfg.frontend.pa, obo_db=float(obo_db))))


def with_lo_at_1mhz(cfg, level_dbchz):
    """The fixed LO's one-pole / one-zero profile with L(1 MHz) = ``level_dbchz``
    (the pole sits at 1 MHz: the plateau is 3.01 dB above the level there)."""
    pn = cfg.lo.phase_noise
    plateau = level_dbchz + 10 * np.log10(1 + (1e6 / pn.f_pole_hz) ** 2) - 10 * np.log10(1 + (1e6 / pn.f_zero_hz) ** 2)
    return dc.replace(cfg, lo=dc.replace(cfg.lo, phase_noise=dc.replace(pn, model="pole_zero", psd0_dbchz=float(plateau))))


def fmt(v, f="{:.2f}"):
    return "—" if v is None else f.format(v)


def stage_tx_evm(ifx: IfExtender, score: OFDMConfig, lo: bool = False) -> float:
    """TX EVM at the 60 GHz PA output (wifitrx's ``tx_evm``: per-tone equaliser,
    genie CPE), by default with the fixed LO's phase noise left out so the
    number is the two PAs' and the filter's."""
    st = ifx.tx.stage
    keep = st.lo_profile
    if not lo:
        st.lo_profile = None
    try:
        return float(tx_evm(ifx.tx, score, drive_scale=CHIP_DRIVE_RMS))
    finally:
        st.lo_profile = keep


def main(argv=None) -> int:
    print(ENGINE_BANNER)
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--jobs", type=int, default=max(1, min(4, os.cpu_count() or 1)))
    a = ap.parse_args(argv)
    quick = a.quick or os.environ.get("MMW60_SMOKE") == "1"
    t0 = time.time()
    cfg = dc.replace(if_extender_60ghz(standard=STD, bandwidth_hz=BW), channel=FLAT)
    fe = Frontend60.from_config(zero_if_60ghz(k=8))            # the shared front end (the one topology B's examples use)
    phy = cfg.upclocked()
    bw, fs, os_ = phy.bandwidth_eff, phy.fs_eff, phy.base.oversampling
    print(f"mmw60 {__version__}; {'QUICK (numbers meaningless)' if quick else 'full size'}; {STD} {BW / 1e6:g} MHz at K = 1, "
          f"{os_}x oversampling ({fs / 1e6:g} MS/s); chip seed {cfg.ifext.chip_seed}")
    sim = LinkSim(cfg, frontend=fe)
    assert sim.frontend is fe and sim.ifx.tx.stage.pa.pa_model is fe.pa_model and sim.ifx.tx.stage.lo_profile is fe.lo.profile
    d = sim.describe()["if_extender"]
    plan = d["plan"]

    # ---------------------------------------------------------------- 1. plan
    print("\n== 1. frequency plan (positions only: this engine endorses no spur level) ==")
    print(f"carrier {plan['carrier_hz'] / 1e9:.2f} GHz = IF {plan['if_hz'] / 1e9:.2f} GHz (the chip's channel) + fixed LO "
          f"{plan['lo_hz'] / 1e9:.2f} GHz = {plan['n_mult']} x PLL {plan['pll_hz'] / 1e9:.3f} GHz ({cfg.lo.scheme})")
    alt = 4 if plan["n_mult"] == 3 else 3
    print(f"the other scheme: x{alt} from a PLL at {plan['lo_hz'] / alt / 1e9:.3f} GHz; the phase-noise numbers are given at the LO output, "
          "so N enters the plan and the PLL frequency only")
    print(f"image sideband {plan['image_hz'] / 1e9:.2f} GHz ({plan['image_offset_hz'] / 1e9:.2f} GHz below the carrier), LO feedthrough "
          f"{plan['lo_hz'] / 1e9:.2f} GHz ({plan['lo_offset_hz'] / 1e9:.2f} GHz below): in the 57-71 GHz band: "
          f"{'no' if not plan['notes'] else '; '.join(plan['notes'])}")
    print(f"channel in the unlicensed band: {plan['in_unlicensed_band']}; not modelled: {plan['not_modelled']}")
    f = sim.ifx.tx.stage.if_filter
    print(f"IF filter: Chebyshev-I order {f.order}, {f.ripple_db:g} dB ripple, {f.bandwidth_hz / 1e9:g} GHz passband centred "
          f"{cfg.ifext.filter_center_hz / 1e9:.3f} GHz; the channel sits {f.offset_hz / 1e6:+.0f} MHz from its centre: in-channel ripple "
          f"{d['if_filter_ripple_db']:.2f} dB, group-delay spread {d['if_filter_gd_spread_ps']:.0f} ps "
          f"(GI {phy.t_gi_eff * 1e9:.0f} ns)")
    print(f"receive image band: rejection {cfg.ifext.image_rejection_db:g} dB -> noise-figure penalty {d['image_noise_penalty_db']:.3f} dB "
          "(topology A only: a zero-IF receiver has no image band)")
    print(f"operating point: chip PA {d['chip_pout_dbm']:.1f} dBm (its Psat {chip_facts(cfg, bw, fs)['psat_dbm']:g} dBm), interstage "
          f"{d['interstage_gain_db']:.1f} dB, 60 GHz PA {d['pout_dbm']:.1f} dBm = Psat {fe.psat_dbm:g} - OBO {fe.obo_db:g}")

    # ---------------------------------------------------------------- 2. calibration, every step
    print("\n== 2. wifitrx's calibration sequence on the chip (profile factory): its own coupler / the 60 GHz observation loopback ==")
    score = OFDMConfig(bandwidth_hz=bw, qam_order=64, n_symbols=8, oversampling=os_)
    probe = scoring_frame(score)[0].x * CHIP_DRIVE_RMS
    runs = []
    evm_tab = []
    for name in ("chip coupler", "60 GHz observation"):
        tx, rx = build_chip_wifitrx(bw, fs, cfg.ifext.chip_seed)                # a fresh, uncalibrated chip
        tx.stage, rx.stage = sim.ifx.tx.stage, sim.ifx.rx.stage                  # the same stage objects the link runs on
        fresh = IfExtender(tx=tx, rx=rx, plan=plan, chip="wifitrx")
        tx.stage_on = rx.stage_on = True
        e_before = stage_tx_evm(fresh, score)
        if name == "chip coupler":
            tx.stage_on = rx.stage_on = False
            path = LoopbackPath(atten_db=recommended_loopback_atten_db(bw), delay_ns=6.0)
        else:
            path = mmw_observation_path(tx, bw, probe)
            tx.stage.lo_shared_loopback = rx.stage.lo_shared_loopback = True
        print(f"-- {name}: coupler {path.atten_db:.1f} dB --")
        try:
            run = run_cal_on(tx, rx, path, 1, bw, os_, profile="factory", with_dpd=not quick,
                             log=lambda s: print(s, flush=True), drive_scale=CHIP_DRIVE_RMS)
        finally:
            tx.stage.lo_shared_loopback = rx.stage.lo_shared_loopback = False
        run.waveform = name
        runs.append(run)
        tx.stage_on = rx.stage_on = False
        e_chip = float(tx_evm(tx, score, drive_scale=CHIP_DRIVE_RMS))
        tx.stage_on = rx.stage_on = True
        evm_tab.append((name, e_before, e_chip, stage_tx_evm(fresh, score), run.evm_before_db, run.evm_after_db))
    print("\nstep                   " + "".join(f"{n:>40}" for n in ("chip coupler", "60 GHz observation")))
    for row in compare_runs(runs):
        cells = []
        for r in runs:
            st = next((x for x in r.rows if x.step == row["step"]), None)
            cells.append(f"{'—':>40}" if st is None else
                         f"{st.status + ' ' + (st.metric + ' ' + fmt(st.value) if st.metric else ''):>40}")
        print(f"{row['step']:<22} " + "".join(cells))
    print("\nTX EVM [dB] (wifitrx tx_evm, fixed-LO phase noise left out)    60 GHz PA out before   chip out after   60 GHz PA out after   "
          "loopback before / after")
    for name, e0, e_chip, e1, lb, la in evm_tab:
        print(f"  calibrated on the {name:<20}             {e0:8.2f}          {e_chip:8.2f}         {e1:8.2f}           "
              f"{fmt(lb, '{:.1f}')} / {fmt(la, '{:.1f}')}")

    # ---------------------------------------------------------------- 3. DPD with / without the 60 GHz observation
    print("\n== 3. the predistorter against the 60 GHz PA's back-off: TX EVM at the 60 GHz PA output [dB] ==")
    print("OBO2[dB]  Pout[dBm]   no DPD   chip-only DPD   60 GHz-observed fit, as its step reads none / pass 1 / 2 / 3   kept    "
          "fitted vs chip-only   programmed    TX EVM programmed   gain of the observation")
    dpd_rows = []
    for obo in (OBO2[1::3] if quick else OBO2):
        c = with_obo(cfg, obo)
        f2 = Frontend60.from_config(c)
        s_chip = LinkSim(c, frontend=f2)
        e_chip = stage_tx_evm(s_chip.ifx, score)
        keep = s_chip.ifx.tx.dpd
        s_chip.ifx.tx.dpd = None
        e_none = stage_tx_evm(s_chip.ifx, score)
        s_chip.ifx.tx.dpd = keep
        s_mmw = LinkSim(dc.replace(c, ifext=dc.replace(c.ifext, dpd_observation="mmw", dpd_max_iterations=3)), frontend=f2)
        m = s_mmw.ifx.dpd_mmw
        e_prog = stage_tx_evm(s_mmw.ifx, score)
        obs = m["observed_by_pass_db"]
        kept = "none" if m["kept_pass"] == 0 else f"pass {m['kept_pass']}"
        prog = "chip-only" if m["chip_dpd_kept"] else kept
        dpd_rows.append((obo, e_chip, e_prog, m["programmed"]))
        print(f"{obo:7.0f}  {s_chip.pout_dbm:9.2f}  {e_none:7.2f}  {e_chip:14.2f}        "
              f"{obs[0]:7.2f} / {obs[1]:7.2f} / {obs[2]:7.2f} / {obs[3]:7.2f}                 {kept:<7} "
              f"{m['evm_fitted_db']:7.2f} vs {m['evm_chip_dpd_db']:7.2f}   {prog:<12}  {e_prog:17.2f}  {e_chip - e_prog:+23.2f}")
    print("no DPD / chip-only / TX EVM programmed: wifitrx tx_evm on the 64-QAM scoring frame. The four pass columns are wifitrx's "
          "own readings on the observation path at the training drive (no predistorter, then after each ILA pass); its step keeps "
          "the best of them (wifi_trx_cal >= 0.7.39). 'fitted vs chip-only' is this library's check: the kept one and the chip's "
          "own predistorter, both back at the same output power, EVM at the 60 GHz PA output on the fit's 256-QAM stimulus with "
          "the LO's phase noise cancelled; the better stays programmed (the preset lets the step try 2 passes: "
          "assumed.ifext_dpd_max_iterations).")

    # ---------------------------------------------------------------- 4. MCS cap vs the fixed LO's noise
    print("\n== 4. MCS cap against the fixed LO's phase noise at 1 MHz (one-pole / one-zero profile, TX and RX LO) ==")
    print("L(1MHz)   IPN 10k-100M   ICI analytic   EvmBudget PN   TD, LO only   budget-TD   floor   TD all   conf cap   dec cap   Mb/s@dec")
    pa_evm = pa_isolated_evm_db(fe.pa_model, fe.obo_db, fe.obo_reference)
    lo_rows = []

    def lo_row(c):
        f2 = Frontend60.from_config(c)
        prof = f2.lo.profile
        t_fft = phy.t_fft_eff
        ici = 2 * cpe_partition(prof.psd, t_fft, 1e3, fs / 2)["ici_rad2"]
        ipn_dbc = f2.lo.lo_model().ipn_dbc(*PN_BAND_HZ)
        # ipn_dbc is single-sideband (phase power / 2); two LOs: 2 x (2 x 10^(dBc/10))
        budget = EvmBudget(lo_profile=prof, t_fft_s=t_fft, pn_band_hz=PN_BAND_HZ, ipn_rad2=2 * 2 * 10 ** (ipn_dbc / 10))
        b_pn = budget.components_db()["phase_noise"]
        # the fixed LO alone: the ideal front end with only this LO on, on its own front-end instance
        lo_only = dc.replace(c.ideal(), lo=c.lo)
        td_lo = evm_at(lo_only, None, n_packets=1 if quick else 3, frontend=Frontend60.from_config(lo_only))["evm_db"]
        a_ = analytic_floors(c, f2, pa_evm)
        td = evm_at(c, None, n_packets=1, frontend=f2)["evm_db"]
        conf = max_mcs_for_floor(a_["floor_db"], STD)
        dcap = decoder_cap(decoder_floor_db(a_["floor_db"], td, a_["cfo_captured"]), STD, BW)
        rate = None if dcap["mcs"] is None else data_rate_bps(STD, BW, dcap["mcs"], phy.t_symbol_eff) / 1e6
        cols = (f"{ipn_dbc:13.1f}  {10 * np.log10(ici):13.1f}  {b_pn:13.1f}  {td_lo:12.1f}  {b_pn - td_lo:+9.2f}  "
                f"{a_['floor_db']:6.1f}  {td:7.1f}   {fmt(conf, 'MCS{}'):>7}   {fmt(dcap['mcs'], 'MCS{}'):>7}   {fmt(rate, '{:.0f}'):>8}")
        return (10 * np.log10(ici), b_pn, td_lo, conf, dcap["mcs"]), cols, f2

    for lvl in (LO_AT_1MHZ[1::3] if quick else LO_AT_1MHZ):
        vals, cols, _ = lo_row(with_lo_at_1mhz(cfg, lvl))
        lo_rows.append((lvl, *vals))
        print(f"{lvl:7.0f}  {cols}")
    # the pllsim synthesizer at the fixed LO: wu19 retuned to 6.0 GHz through pllsim's x9 block to
    # f_c - f_IF = 54.0 GHz (its model stops at 12 GHz, so not the preset's x3 from 18.0 GHz)
    x9 = spec.value("survey.clock_profile_wu19_x9")
    c9 = dc.replace(cfg, lo=dc.replace(cfg.lo, scheme="fixed_lo_x9", phase_noise=dc.replace(
        cfg.lo.phase_noise, model="profile", profile_path=x9["file"])))
    _, cols, f9 = lo_row(c9)
    l1m = 10 * np.log10(f9.lo.profile.psd(np.array([1e6]))[0] / 2)
    print(f"{l1m:7.1f}  {cols}   <- pllsim wu19 {x9['f_in_hz'] / 1e9:g} GHz x{x9['multiply_by']} = "
          f"{f9.lo.profile_hz / 1e9:g} GHz (survey.clock_profile_wu19_x9, lo.scheme fixed_lo_x9)")
    print("the pllsim row: L(1MHz) read off its profile; the profile sits at the LO frequency, not the carrier "
          "(20*log10(60.48/54) = 1.0 dB less than at 60.48 GHz)")
    print("ICI analytic = this library's term (cpe_partition to fs/2, both LOs); EvmBudget PN = wifitrx's budget term (IPN 10 kHz-100 MHz "
          "less the CPE-tracked share, both LOs); TD, LO only = the time-domain chain with nothing else on. floor / TD all / caps: "
          f"the whole link at OBO {fe.obo_db:g} dB (PA isolated EVM {pa_evm:.1f} dB, chip residual and chip LO included).")
    steps = [(lo_rows[i][0], lo_rows[i + 1][0], lo_rows[i][1] - lo_rows[i + 1][1], lo_rows[i][2] - lo_rows[i + 1][2],
              lo_rows[i][3] - lo_rows[i + 1][3]) for i in range(len(lo_rows) - 1)]
    print("per step of the LO level: " + "; ".join(f"{a_:g}->{b_:g}: analytic {x:.2f}, budget {y:.2f}, TD {z:.2f} dB" for a_, b_, x, y, z in steps))

    # ---------------------------------------------------------------- 5. cascade back-off
    print("\n== 5. cascade back-off: chip PA output x 60 GHz PA back-off (link EVM, flat channel, no noise; decoder cap) ==")
    print("chip Pout[dBm] (OBO1 from its Psat)   chip residual   " + "   ".join(f"OBO2 {o:g}: EVM / cap" for o in CASCADE_OBO2))
    cas = {}
    for cp in (CHIP_POUT[1:2] if quick else CHIP_POUT):
        c0 = dc.replace(cfg, ifext=dc.replace(cfg.ifext, chip_pout_dbm=cp))
        facts = chip_facts(c0, bw, fs)
        cells = []
        for obo in (CASCADE_OBO2[1:2] if quick else CASCADE_OBO2):
            c = with_obo(c0, obo)
            f2 = Frontend60.from_config(c)
            td = evm_at(c, None, n_packets=1, frontend=f2)["evm_db"]
            a_ = analytic_floors(c, f2)
            dcap = decoder_cap(decoder_floor_db(a_["floor_db"], td, a_["cfo_captured"]), STD, BW)
            cas[(cp, obo)] = (td, dcap["mcs"])
            cells.append(f"{td:6.1f} / {fmt(dcap['mcs'], 'MCS{}'):<5}")
        print(f"{facts['pout_dbm']:8.1f} ({facts['psat_dbm'] - facts['pout_dbm']:4.1f})               {fmt(facts['residual_evm_db'], '{:.1f}'):>8}        "
              + "        ".join(cells) + f"     chip PA DC {facts['pa_dc_w'] * 1e3:.0f} mW")
    print("the chip's output is padded down to the 60 GHz PA's drive (interstage), so its back-off costs DC power, not link EVM, "
          "until its own residual reaches the 60 GHz PA's.")

    # ---------------------------------------------------------------- 5b. the chip PA bypassed
    print("\n== 5b. the chip's PA bypassed: the IF taken at its mixer output, the PA powered down "
          "(assumed.ifext_chip_pa_bypass) ==")
    cfg_b = dc.replace(cfg, ifext=dc.replace(cfg.ifext, chip_pa_bypass=True))
    sim_b = LinkSim(cfg_b, frontend=fe)
    res_on = {r.name: r for r in sim.ifx.cal_results}
    res_by = {r.name: r for r in sim_b.ifx.cal_results}
    print(f"wifitrx's sequence on the bypassed chain: the coupler ahead of the PA, its attenuation lowered by the PA's "
          f"measured gain {sim_b.ifx.tx.pa_bypass_gain_db:.1f} dB; {len(res_by)} steps run ({len(res_on)} with the PA in: "
          f"{', '.join(n for n in res_on if n not in res_by)} not run); failed: "
          f"{', '.join(n for n, r in res_by.items() if r.passed is False) or 'none'}")
    print(f"{'step':<22} {'reading':<14} {'chip PA in':>11} {'bypassed':>9}")
    for name, key in (("tx_iq", "irr_min_db"), ("rx_iq", "irr_min_db"), ("rx_iip2", "iip2_dbm"),
                      ("tx_lo_leak_loopback", "lo_leak_dbc"), ("final_loopback_evm", "evm_db"),
                      ("final_loopback_evm", "tx_evm_db"), ("final_loopback_evm", "rx_evm_db")):
        a_v, b_v = (float(r[name].metrics_after[key]) for r in (res_on, res_by))
        print(f"{name:<22} {key:<14} {a_v:11.2f} {b_v:9.2f}")
    g_on, g_by = sim.ifx.tx.stage.interstage_gain_db, sim_b.ifx.tx.stage.interstage_gain_db
    need = ("an attenuation either way: no driver needed" if max(g_on, g_by) <= 0 else
            "a gain: a driver ahead of the 60 GHz PA is needed, its power is not counted")
    print(f"interstage to the 60 GHz PA: {g_on:+.2f} dB with the chip PA in, {g_by:+.2f} dB bypassed ({need}); "
          f"60 GHz PA out {sim.pout_dbm:.2f} / {sim_b.pout_dbm:.2f} dBm")
    rep_b = compare.build([compare.Scheme("chip PA in (the preset)", "if_extender", "be", cfg),
                           compare.Scheme("chip PA bypassed", "if_extender", "be", cfg_b)], fe, time_domain=not quick)
    print(f"{'':<26} {'floor':>6} {'TD':>6} {'dec cap':>8} {'Mb/s':>6} {'pJ/bit':>7} {'of it chip PA':>13}")
    for r in rep_b["rows"]:
        pdc = r["power_dec"] or {}
        chip_pj = (pdc.get("blocks") or {}).get("chip_pa", {}).get("pj_per_bit")
        print(f"{r['label']:<26} {r['floor_db']:6.1f} {fmt(r['td_evm_db'], '{:6.1f}'):>6} {fmt(r['dec_mcs'], 'MCS{}'):>8} "
              f"{fmt(r['dec_rate_mbps'], '{:.0f}'):>6} {fmt(pdc.get('pj_per_bit'), '{:.0f}'):>7} {fmt(chip_pj, '{:.0f}'):>13}")
    print("the 320 MHz pair against topology B's 80 MHz x 4 is in example 04 (tables 4 / 4b)")

    # ---------------------------------------------------------------- 6. CFO
    print("\n== 6. CFO (iron rule 3): crystals x carrier against the chip's estimators, and the multi-link pre-compensation ==")
    mlo = sim.cfo
    print(f"raw offset (ppm_tx + ppm_rx) x f_c = {cfg.xo_ppm_tx + cfg.xo_ppm_rx:g} ppm x {cfg.carrier_hz / 1e9:.2f} GHz = "
          f"{mlo.cfo_hz / 1e6:.3f} MHz = {mlo.cfo_hz / phy.scs_eff:.1f} subcarriers; the chip's L-STF reaches +-{phy.stf_capture_hz / 1e3:.0f} kHz")
    print(f"sub-7 GHz link at {mlo.sub7_hz / 1e9:g} GHz: offset {mlo.sub7_cfo_hz / 1e3:.1f} kHz, ratio f_c / f_sub7 = {mlo.ratio:.2f}")
    print("sub-7 SNR[dB]   sub-7 estimate rms error[Hz]   60 GHz residual rms / max[kHz]   in subcarriers (max)   inside the L-STF range")
    for snr in ((20.0,) if quick else (5.0, 10.0, 20.0, 30.0)):
        m = dc.replace(mlo, sub7_snr_db=snr)
        st = m.residual_stats(n=40 if quick else 400, seed=1)
        print(f"{snr:10.0f}   {st['rms_hz'] / m.ratio:26.0f}   {st['rms_hz'] / 1e3:17.2f} / {st['max_abs_hz'] / 1e3:6.2f}   "
              f"{st['max_abs_hz'] / phy.scs_eff:18.2f}   {'yes' if st['max_abs_hz'] <= phy.stf_capture_hz else 'NO'}")
    rows6 = [("MLO pre-compensation on (the preset)", cfg),
             ("MLO off: the raw offset reaches the chip", dc.replace(cfg, ifext=dc.replace(cfg.ifext, mlo_enabled=False))),
             ("ppm = 0 (the CFO term off)", dc.replace(cfg, xo_ppm_tx=0.0, xo_ppm_rx=0.0))]
    for name, c in rows6:
        e = evm_at(c, None, n_packets=1 if quick else 3, frontend=fe)
        print(f"  {name:<42} link EVM {e['evm_db']:7.2f} dB")

    # ---------------------------------------------------------------- 7. assumed inputs, one at a time
    print("\n== 7. sensitivity: one assumed input at a time (link EVM, flat channel, no noise) ==")
    base_e = evm_at(cfg, None, n_packets=1, frontend=fe)["evm_db"]
    edge = cfg.ifext.filter_center_hz - cfg.ifext.filter_bw_hz / 2 + bw / 2
    sens = [("preset", cfg, fe),
            ("IF filter off", dc.replace(cfg, ifext=dc.replace(cfg.ifext, filter_enabled=False)), fe),
            ("channel at the filter's band edge", dc.replace(cfg, lo=dc.replace(cfg.lo, if_hz=edge)), fe),
            ("IF filter ripple 2 dB", dc.replace(cfg, ifext=dc.replace(cfg.ifext, filter_ripple_db=2.0)), fe),
            ("another chip (seed 6)", dc.replace(cfg, ifext=dc.replace(cfg.ifext, chip_seed=6)), fe),
            ("chip without DPD", dc.replace(cfg, ifext=dc.replace(cfg.ifext, with_dpd=False)), fe),
            ("the shared front end's own chain as the chip (uncalibrated, like B's)",
             dc.replace(cfg, ifext=dc.replace(cfg.ifext, chip="frontend"),
                        frontend=dc.replace(zero_if_60ghz(k=1).frontend, model="if_extender_chain")), fe),
            ("phase noise on the RX LO only", dc.replace(cfg, lo=dc.replace(cfg.lo, phase_noise=dc.replace(cfg.lo.phase_noise, apply="rx"))), fe)]
    for name, c, f2 in (sens[:3] if quick else sens):
        s2 = LinkSim(c, frontend=f2)
        e = evm_at(c, None, n_packets=1, frontend=f2)["evm_db"]
        d2 = s2.describe()["if_extender"]
        print(f"  {name:<70} EVM {e:7.2f} dB ({e - base_e:+.2f})   ripple {d2['if_filter_ripple_db']:.2f} dB, "
              f"group-delay spread {d2['if_filter_gd_spread_ps']:.0f} ps")
    for irr in (30.0, 20.0, 10.0, 0.0):
        print(f"  image rejection {irr:4.0f} dB -> noise-figure penalty {10 * np.log10(1 + 10 ** (-irr / 10)):.3f} dB (sensitivity, not EVM)")
    wide = dc.replace(if_extender_60ghz(standard="11be", bandwidth_hz=320e6), channel=FLAT)
    if not quick:
        e320 = evm_at(wide, None, n_packets=1, frontend=fe)
        d320 = e320["describe"]["if_extender"]
        a320 = analytic_floors(wide, fe)
        c320 = decoder_cap(decoder_floor_db(a320["floor_db"], e320["evm_db"], a320["cfo_captured"]), "11be", 320e6)
        r320 = None if c320["mcs"] is None else data_rate_bps("11be", 320e6, c320["mcs"], wide.upclocked().t_symbol_eff) / 1e6
        print(f"  the widest WiFi 7 channel, 11be 320 MHz: EVM {e320['evm_db']:.2f} dB, in-channel ripple {d320['if_filter_ripple_db']:.2f} dB, "
              f"chip residual {fmt(a320['chip']['residual_evm_db'], '{:.1f}')} dB, decoder cap {fmt(c320['mcs'], 'MCS{}')} "
              f"({fmt(r320, '{:.0f}')} Mb/s)")

    # ---------------------------------------------------------------- 8. the decoder cap, checked with PER
    print("\n== 8. the decoder cap checked with PER (impaired link, flat channel) ==")
    a0 = analytic_floors(cfg, fe, pa_evm)
    floor = decoder_floor_db(a0["floor_db"], base_e, a0["cfo_captured"])
    cap = decoder_cap(floor, STD, BW)
    results = []
    if cap["mcs"] is None:
        print(f"floor {floor:.1f} dB: no MCS reachable")
    else:
        above = cap["mcs"] + 1
        t_above = spec.per_threshold_db(STD, BW, above)
        lin = 10 ** (-t_above / 10) - 10 ** (floor / 10)
        pred_above = None if lin <= 0 else float(-10 * np.log10(lin))
        mp, me = (6, 2) if quick else (150, 10)
        specs = []
        for mcs, centre in ((cap["mcs"], cap["required_snr_db"]), (above, pred_above if pred_above is not None else t_above + 6)):
            grid = [round(centre - 2 + i, 2) for i in range(0, 2 if quick else 7, 3 if quick else 1)]
            specs.append(CurveSpec(f"A {STD} {BW / 1e6:g}M MCS{mcs}", dc.replace(cfg, phy=dc.replace(cfg.phy, mcs=mcs)),
                                   grid, mp, me, tags={"mcs": mcs}))
        results = run_curves(specs, TARGET, a.jobs, log=lambda s: None)
        got = {r["tags"]["mcs"]: r["snr_at_target"] for r in results}
        print("floor   cap    T[dB]  SNR needed (predicted)  measured @ PER 1e-2   one MCS above: predicted  measured")
        print(f"{floor:5.1f}   MCS{cap['mcs']:<2}  {cap['threshold_db']:5.2f}  {cap['required_snr_db']:10.2f}              "
              f"{fmt(got.get(cap['mcs'])):>8}              MCS{above}: {fmt(pred_above):>8}   {fmt(got.get(above)):>8}")
    OUT.mkdir(exist_ok=True)
    save_results(results, OUT / "06_sweeps.json")
    print(f"\nwrote {(OUT / '06_sweeps.json').relative_to(HERE.parent)}  [{time.time() - t0:.0f}s]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
