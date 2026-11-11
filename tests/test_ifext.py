"""Topology A (the IF extender, ``mmw60.ifext``): the insertion point, the shared
front end, the CFO it catches, the calibration it actually runs, and the
acceptance numbers of ROADMAP A1."""
from __future__ import annotations

import dataclasses as dc

import numpy as np
import pytest

from mmw60 import compare
from mmw60.config import ChannelConfig, Mmw60Config, if_extender_60ghz, zero_if_60ghz
from mmw60.frontend import Frontend60
from mmw60.frontend.grid import analytic_floors
from mmw60.ifext import (IfFilter, MmwRxStage, MmwTxStage, build_chip_wifitrx,
                         calibrated_chip, chip_facts, if_plan)
from mmw60.impairments.cfo import CfoModel, MloCfo
from mmw60.sim.link import LinkSim, evm_at
from mmw60.vendor.wifitrx.cal.deps import validate_order
from mmw60.vendor.wifitrx.chain.rx import RxChain
from mmw60.vendor.wifitrx.chain.tx import TxChain
from mmw60.vendor.wifitrx.impairments.phase_noise import cpe_partition
from mmw60.vendor.wifitrx.link.evm_budget import PN_BAND_HZ, EvmBudget

FLAT = ChannelConfig(model="flat")
BW, OS = 20e6, 4
FS = BW * OS


def small(**kw) -> Mmw60Config:
    """Topology A on the 20 MHz 11be base: the chip's calibration takes a second."""
    return dc.replace(if_extender_60ghz(standard="11be", bandwidth_hz=BW), channel=FLAT, **kw)


def with_obo(cfg, obo):
    return dc.replace(cfg, frontend=dc.replace(cfg.frontend, pa=dc.replace(cfg.frontend.pa, obo_db=float(obo))))


# ---------------------------------------------------------------- iron rule 2: the insertion point
def test_law2_stage_off_is_the_unmodified_wifitrx_chain_bit_for_bit():
    """The 60 GHz stage is inserted after wifitrx's RF output and before its RF
    input; with it off the subclasses are the parent chains, bit for bit."""
    tx, rx = build_chip_wifitrx(BW, FS, seed=5)
    ref_tx, ref_rx = TxChain(tx.params, FS), RxChain(rx.params, FS)
    rng = np.random.default_rng(0)
    x = 0.1 * (rng.standard_normal(4096) + 1j * rng.standard_normal(4096))
    assert isinstance(tx, TxChain) and isinstance(rx, RxChain) and tx.stage is None
    assert np.array_equal(tx(x), ref_tx(x))
    y = ref_tx(x) * 1e-3
    assert np.array_equal(rx(y, rng=np.random.default_rng(1)), ref_rx(y, rng=np.random.default_rng(1)))
    # a stage attached but switched off changes nothing either; switched on it is applied to that output
    tx.stage = MmwTxStage(pa=None, if_filter=IfFilter(enabled=False), interstage_gain_db=-6.0)
    tx.stage_on = False
    assert np.array_equal(tx(x), ref_tx(x))
    tx.stage_on = True
    assert np.allclose(tx(x), ref_tx(x) * 10 ** (-6.0 / 20)) and np.array_equal(tx.chip(x), ref_tx(x))
    rx.stage = MmwRxStage(if_filter=IfFilter(enabled=False))
    rx.stage_on = True
    assert np.array_equal(rx(y, rng=np.random.default_rng(1)), ref_rx(y, rng=np.random.default_rng(1)))


def test_law2_topology_a_runs_on_the_shared_front_end_instance():
    """The 60 GHz PA, the LO profile and the EIRP limit topology A uses are the
    objects topology B's chains use — one ``Frontend60``."""
    fe = Frontend60.from_config(zero_if_60ghz(k=8))
    a = LinkSim(small(), frontend=fe)
    b = LinkSim(dc.replace(zero_if_60ghz(k=8, standard="11be", bandwidth_hz=BW), channel=FLAT), frontend=fe)
    assert a.frontend is fe and b.frontend is fe and a.frontend.eirp is b.frontend.eirp
    st = a.ifx.tx.stage
    assert st.pa.pa_model is fe.pa_model and st.lo_profile is fe.lo.profile
    assert a.ifx.rx.stage.lo_profile is fe.lo.profile
    assert b.tx.pa.pa_model is fe.pa_model
    # same operating point of the same PA: Psat − OBO within the trim tolerance
    assert a.pout_dbm == pytest.approx(fe.target_pout_dbm(), abs=0.05)
    assert b.pout_dbm == pytest.approx(fe.target_pout_dbm(), abs=0.05)


def test_config_names_topology_a_and_round_trips(tmp_path):
    cfg = if_extender_60ghz()
    assert cfg.topology == "if_extender" and cfg.waveform == "be" and cfg.upclock_k == 1
    assert cfg.lo.scheme == "fixed_lo_x3" and cfg.lo.n_mult == 3 and cfg.lo.if_hz == 6.48e9
    assert cfg.frontend.model == "if_extender_chain" and cfg.ifext.chip == "wifitrx"
    # the crystal, the LO numbers, the 60 GHz PA and the receiver are topology B's
    b = zero_if_60ghz(k=1, standard="11be", bandwidth_hz=80e6)
    assert (cfg.xo_ppm_tx, cfg.xo_ppm_rx, cfg.carrier_hz) == (b.xo_ppm_tx, b.xo_ppm_rx, b.carrier_hz)
    assert cfg.lo.phase_noise == b.lo.phase_noise and cfg.frontend.pa == b.frontend.pa and cfg.rx == b.rx
    p = tmp_path / "a.yaml"
    cfg.to_yaml(p)
    assert Mmw60Config.from_yaml(p) == cfg
    ideal = cfg.ideal()
    assert ideal.ifext.chip == "frontend" and not ideal.ifext.filter_enabled and ideal.cfo_hz == 0.0
    with pytest.raises(ValueError):
        Mmw60Config(ifext=dc.replace(cfg.ifext, chip="other"))


# ---------------------------------------------------------------- the plan and the filter
def test_if_plan_and_filter():
    p = if_plan(60.48e9, 6.48e9, 3, 320e6)
    assert p["lo_hz"] == 54.0e9 and p["pll_hz"] == 18.0e9 and p["image_hz"] == pytest.approx(47.52e9)
    assert p["ok"] and p["in_unlicensed_band"] and "no level is endorsed" in p["not_modelled"]
    assert if_plan(60.48e9, 6.48e9, 4, 320e6)["pll_hz"] == 13.5e9
    # an IF so low that the LO lands in the band is flagged
    assert any("LO feedthrough" in n for n in if_plan(60.48e9, 2.0e9, 3, 320e6)["notes"])
    f = IfFilter(bandwidth_hz=1.2e9, order=5, ripple_db=0.5, offset_hz=0.0)
    assert abs(f.response(np.array([0.0]))[0]) == pytest.approx(1.0)
    assert f.ripple_in_band_db(1.19e9) == pytest.approx(0.5, abs=0.03)          # the whole passband: the design ripple
    centre, edge = f.group_delay_spread_s(320e6), dc.replace(f, offset_hz=-440e6).group_delay_spread_s(320e6)
    assert edge > 3 * centre > 0
    x = np.random.default_rng(0).standard_normal(1024) + 0j
    assert np.array_equal(dc.replace(f, enabled=False).apply(x, 320e6), x)
    assert MmwRxStage(image_rejection_db=10.0).image_noise_penalty_db() == pytest.approx(0.414, abs=1e-3)
    assert MmwRxStage(image_rejection_db=None).image_noise_penalty_db() == 0.0


# ---------------------------------------------------------------- iron rule 3: the CFO
def test_law3_topology_a_cfo_is_zero_at_zero_ppm_and_the_residual_is_the_sub7_error_times_the_ratio():
    x = np.exp(1j * np.arange(256) * 0.1)
    off = MloCfo(60.48e9, 0.0, 0.0, sub7_hz=5.5e9)
    assert off.cfo_hz == 0.0 and off.residual_hz(np.random.default_rng(0)) == 0.0
    assert off.apply(x, 80e6, np.random.default_rng(0)) is x                    # the term is off: the same array
    m = MloCfo(60.48e9, 20.0, 20.0, sub7_hz=5.5e9, sub7_snr_db=20.0)
    # (ppm_tx + ppm_rx) × f_c, the same number topology B's model gives
    assert m.cfo_hz == CfoModel(60.48e9, 20.0, 20.0).cfo_hz == pytest.approx(2.4192e6)
    assert m.ratio == pytest.approx(60.48 / 5.5) and m.sub7_cfo_hz == pytest.approx(220e3)
    # residual = (true sub-7 offset − the sub-7 estimate) × f_c / f_sub7, the estimate actually run
    est = m.sub7_estimate_hz(np.random.default_rng(3))
    assert m.residual_hz(np.random.default_rng(3)) == pytest.approx((m.sub7_cfo_hz - est) * m.ratio)
    assert abs(est - m.sub7_cfo_hz) < 5e3                                       # the estimator works at 20 dB
    # with MLO off the raw offset reaches the receiver; it is outside the chip's ±625 kHz
    assert dc.replace(m, enabled=False).residual_hz() == m.cfo_hz > 625e3
    # the residual scales with the sub-7 link's noise and stays inside the range
    lo_snr = dc.replace(m, sub7_snr_db=10.0).residual_stats(120)
    hi_snr = dc.replace(m, sub7_snr_db=30.0).residual_stats(120)
    assert hi_snr["rms_hz"] < lo_snr["rms_hz"] / 3 and lo_snr["max_abs_hz"] < 625e3


@pytest.mark.slow
def test_law3_topology_a_link_declares_how_it_catches_the_cfo():
    """With the pre-compensation the link works; without it the raw 2.4 MHz is
    outside the chip's estimators and the link fails; ppm = 0 changes nothing."""
    fe = Frontend60.from_config(zero_if_60ghz(k=8))
    cfg = small()
    on = evm_at(cfg, None, n_packets=1, frontend=fe)
    off = evm_at(dc.replace(cfg, ifext=dc.replace(cfg.ifext, mlo_enabled=False)), None, n_packets=1, frontend=fe)
    zero = evm_at(dc.replace(cfg, xo_ppm_tx=0.0, xo_ppm_rx=0.0), None, n_packets=1, frontend=fe)
    assert on["evm_db"] < -15 and off["evm_db"] > -3 and abs(on["evm_db"] - zero["evm_db"]) < 0.3
    assert on["describe"]["cfo_precompensation"] == "mlo"
    a = analytic_floors(cfg, fe)
    assert a["cfo_captured"] and a["cfo_precompensation"] == "mlo" and 0 < a["cfo_residual_max_hz"] < 625e3
    assert not analytic_floors(dc.replace(cfg, ifext=dc.replace(cfg.ifext, mlo_enabled=False)), fe)["cfo_captured"]


# ---------------------------------------------------------------- iron rule 4: calibration is run
def test_law4_the_chip_is_calibrated_by_running_wifitrx_sequence():
    tx0, _ = build_chip_wifitrx(BW, FS, seed=5)
    assert tx0.w2 is None and tx0.dpd is None and tx0.dc_pre == 0               # as built: nothing programmed
    tx, rx, res = calibrated_chip(BW, FS, 5, True, None, 0.15)
    names = [r.name for r in res]
    validate_order(names)                                                       # wifitrx's own dependency rules
    assert names[-1] == "final_loopback_evm" and "dpd" in names and "tx_iq" in names and len(names) >= 12
    assert all(r.passed in (True, None) for r in res)
    # corrections programmed by the run: the IQ image filter, the LO-leakage DC, the predistorter
    assert tx.w2 is not None and tx.dc_pre != 0 and tx.dpd is not None
    final = res[-1]
    assert final.metrics_after["evm_db"] < -35
    f = chip_facts(small(), BW, FS)
    assert f["residual_evm_db"] == pytest.approx(final.metrics_after["evm_db"]) and f["pa_dc_w"] > 0
    assert 5 < f["pout_dbm"] < f["psat_dbm"] and [n for n, _ in f["steps"]] == names
    # each call hands out its own chains (a sweep must not share AGC / gain state) on the same calibration
    tx2, rx2, res2 = calibrated_chip(BW, FS, 5, True, None, 0.15)
    assert tx2 is not tx and rx2 is not rx and res2 is res and tx2.dpd is tx.dpd


@pytest.mark.slow
def test_dpd_through_the_60ghz_observation_keeps_the_best_iteration_and_never_does_worse_than_the_chip_only_one():
    """ROADMAP A1's "with / without the 60 GHz observation loopback".  wifitrx's
    indirect-learning fit iterates, and on this soft Rapp every extra
    iteration is worse than the one before near saturation; the first
    version took wifitrx's default (2) and concluded the observation was
    worth nothing at 8 dB back-off.  The fit is now run for 1 … N
    iterations and the best candidate on the observation path stays — which
    is never worse than the chip-only predistorter, and several dB better
    at deep back-off."""
    from mmw60.vendor.wifitrx.cal.sequence import tx_evm
    from mmw60.vendor.wifitrx.waveform.ofdm import OFDMConfig
    score = OFDMConfig(bandwidth_hz=BW, qam_order=64, n_symbols=8, oversampling=OS)

    def tx_evm_db(sim):
        st = sim.ifx.tx.stage
        keep, st.lo_profile = st.lo_profile, None
        try:
            return float(tx_evm(sim.ifx.tx, score, drive_scale=0.15))
        finally:
            st.lo_profile = keep

    out = {}
    for obo in (6.0, 10.0, 14.0):
        c = with_obo(small(), obo)
        fe = Frontend60.from_config(c)
        chip = LinkSim(c, frontend=fe)
        mmw = LinkSim(dc.replace(c, ifext=dc.replace(c.ifext, dpd_observation="mmw", dpd_max_iterations=3)),
                      frontend=fe)
        info = mmw.ifx.dpd_mmw
        out[obo] = (tx_evm_db(chip), tx_evm_db(mmw), info)
        it = info["evm_by_iterations_db"]
        assert set(it) == {1, 2, 3} and info["max_iterations"] == 3
        # what stays programmed is the best of what was read, the chip-only one included
        best = min([info["evm_chip_dpd_db"], *it.values()])
        assert info["evm_programmed_db"] == pytest.approx(best)
        assert info["chip_dpd_kept"] == (info["programmed"] == "chip")
        # the same output power either way, and never worse than without the observation
        assert mmw.pout_dbm == pytest.approx(chip.pout_dbm, abs=0.05)
        assert out[obo][1] < out[obo][0] + 0.5, (obo, out[obo])
    # near saturation iterating makes it worse, monotonically
    it6 = out[6.0][2]["evm_by_iterations_db"]
    assert it6[1] < it6[2] < it6[3], it6
    # at deep back-off the observation is worth several dB
    chip14, mmw14, info14 = out[14.0]
    assert not info14["chip_dpd_kept"] and mmw14 < chip14 - 3.0, out[14.0]
    assert Mmw60Config(ifext=dc.replace(small().ifext, dpd_max_iterations=1)).ifext.dpd_max_iterations == 1
    with pytest.raises(ValueError):
        Mmw60Config(ifext=dc.replace(small().ifext, dpd_max_iterations=0))


# ---------------------------------------------------------------- ROADMAP A1 acceptance: LO noise
@pytest.mark.slow
def test_lo_noise_steps_agree_between_evm_budget_the_analytic_term_and_the_time_domain_chain():
    """Each 10 dB of fixed-LO noise moves the phase-noise EVM by 10 dB in
    wifitrx's ``EvmBudget``, in this library's ICI term and in the
    time-domain chain, and the three agree within 1 dB in absolute terms."""
    base = small()
    rows = []
    for psd0 in (-83.0, -93.0, -103.0):
        c = dc.replace(base, lo=dc.replace(base.lo, phase_noise=dc.replace(base.lo.phase_noise, psd0_dbchz=psd0)))
        lo_only = dc.replace(c.ideal(), lo=c.lo)
        fe = Frontend60.from_config(lo_only)
        phy = c.upclocked()
        ici = 10 * np.log10(2 * cpe_partition(fe.lo.profile.psd, phy.t_fft_eff, 1e3, phy.fs_eff / 2)["ici_rad2"])
        ipn = fe.lo.lo_model().ipn_dbc(*PN_BAND_HZ)
        budget = EvmBudget(lo_profile=fe.lo.profile, t_fft_s=phy.t_fft_eff, pn_band_hz=PN_BAND_HZ,
                           ipn_rad2=2 * 2 * 10 ** (ipn / 10)).components_db()["phase_noise"]
        td = evm_at(lo_only, None, n_packets=3, frontend=fe)["evm_db"]
        rows.append((ici, budget, td))
    for ici, budget, td in rows:
        assert abs(budget - td) < 1.0 and abs(ici - td) < 1.0, rows
    for (i0, b0, t0), (i1, b1, t1) in zip(rows, rows[1:]):
        assert i0 - i1 == pytest.approx(10.0, abs=0.05) and b0 - b1 == pytest.approx(10.0, abs=0.05)
        assert t0 - t1 == pytest.approx(10.0, abs=0.7), rows


def test_evm_budget_reconciliation_uses_the_double_sideband_phase_variance():
    """wifitrx's ``ipn_dbc`` is single-sideband (phase power / 2).  The comparison
    table fed ``EvmBudget`` 10^(dBc/10) until A1 and its phase-noise term read
    3 dB low; the variance is twice that."""
    fe = Frontend60.from_config(zero_if_60ghz(k=8))
    cfg = zero_if_60ghz(k=8)
    pn = compare._pn_terms(cfg, fe, cfg.upclocked())
    assert pn["ipn_rad2"] == pytest.approx(2 * 10 ** (pn["ipn_dbc"] / 10))
    # ... and with it the budget's phase-noise term sits on this library's ICI term
    assert abs(10 * np.log10(pn["budget_rad2"] / pn["ici_rad2"])) < 0.5


# ---------------------------------------------------------------- the comparison-table row
def test_comparison_table_has_the_topology_a_row_with_its_own_terms_and_blocks():
    fe = Frontend60.from_config(zero_if_60ghz(k=8))
    sch = compare.scheme_matrix(ks=(8,), standard="11be", bandwidth_hz=BW)
    a = next(s for s in sch if s.key == ("if_extender", "be"))
    assert a.status == "built" and a.cfg.topology == "if_extender" and ("if_extender", "be") not in compare.PENDING
    rep = compare.build(sch, fe, time_domain=False)
    row = next(r for r in rep["rows"] if r["topology"] == "if_extender")
    # the chip's residual and its LO are terms of this row only; the image / converters of B's chain are not
    assert {"chip", "chip_lo", "phase_noise", "pa"} <= set(row["terms_db"]) and "iq_image" not in row["terms_db"]
    assert row["cfo_captured"] and row["max_mcs"] is not None and row["dec_mcs"] >= row["max_mcs"]
    blocks = row["power"]["blocks"]
    assert {"pa", "chip_pa", "lo", "converters", "dpd", "fft", "decoder"} <= set(blocks)
    b = next(r for r in rep["rows"] if r["waveform"] == "be_upclocked")
    assert "chip_pa" not in b["power"]["blocks"]
    assert blocks["pa"]["watts"] == pytest.approx(b["power"]["blocks"]["pa"]["watts"])      # the same 60 GHz PA
    assert blocks["lo"]["watts"] > b["power"]["blocks"]["lo"]["watts"]                      # two synthesizers per end
