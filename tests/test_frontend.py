"""Milestone 1, topology B: the shared 60 GHz front end, the zero-IF chain at
fs_eff, the grid's analytic floors against the time-domain chain, the
frequency plan, the EIRP object and the DPD cost bookkeeping."""
import dataclasses as dc

import numpy as np
import pytest

from mmw60 import spec
from mmw60.config import ChannelConfig, Mmw60Config, liu2025_table2, zero_if_60ghz
from mmw60.frontend import ConverterLaw, EirpLimit, Frontend60, Lo60, ScaledRappPA, zero_if_plan
from mmw60.frontend.dpd_cost import DpdCost, dsp_ip_models
from mmw60.frontend.grid import (analytic_floors, data_rate_bps, evaluate_cell, max_mcs_for_floor,
                                 pa_isolated_evm_db)
from mmw60.pa.rapp import ModifiedRappPA
from mmw60.sim.link import LinkSim, evm_at
from mmw60.vendor.wifitrx.units import power_dbm


# ---------------------------------------------------------------- converters
def test_converter_law_scales_with_rate_and_rounds_to_bits():
    c = ConverterLaw(enob_ref=10.0, fs_ref_hz=1e9, bits_per_octave=0.5)
    assert c.enob(1e9) == 10.0 and c.enob(4e9) == 9.0 and c.enob(0.25e9) == 11.0
    assert c.bits(5.12e9) == 9 and c.enob(1e14) == c.enob_min
    assert c.sqnr_db(1e9, backoff_db=0.0) == pytest.approx(6.02 * 10 + 1.76)
    assert c.in_band_sqnr_db(2e9, 1e9) == pytest.approx(c.sqnr_db(2e9) + 10 * np.log10(2))


# ---------------------------------------------------------------- PA in dBm
def test_scaled_rapp_anchors_gain_and_psat():
    pa = ScaledRappPA(ModifiedRappPA(), gain_db=20.0, psat_dbm=15.0)
    small = np.full(1000, 1e-4 + 0j)
    assert power_dbm(pa(small)) - power_dbm(small) == pytest.approx(20.0, abs=0.01)
    big = np.full(1000, 1e3 + 0j)
    assert power_dbm(pa(big)) == pytest.approx(15.0, abs=0.01)
    assert pa.p1db_out_dbm == pytest.approx(15.0 - spec.value("derived.rapp_p1db_below_psat_db"), abs=0.1)
    assert 0 < pa.average_pae(pa(big)) <= pa.pae_max


# ---------------------------------------------------------------- the shared object (law 2)
def test_law2_frontend_instance_is_shared_not_rebuilt():
    cfg = zero_if_60ghz(k=8)
    fe = Frontend60.from_config(cfg)
    sim = LinkSim(cfg, frontend=fe)
    assert sim.frontend is fe
    assert LinkSim(cfg).frontend is not fe and LinkSim(cfg).frontend.lo == fe.lo


def test_law2_ideal_chain_reads_the_same_evm_at_k1_and_k8():
    """The zero-IF chain with every 60 GHz impairment off is the WiFi 7 chip's
    chain scaled in time: K = 8 must read the K = 1 EVM within 0.1 dB."""
    flat = ChannelConfig(model="flat")
    e = {k: evm_at(dc.replace(zero_if_60ghz(k=k).ideal(), channel=flat), None, n_packets=1)["evm_db"]
         for k in (1, 8)}
    assert abs(e[1] - e[8]) < 0.1 and e[1] < -35


def test_frontend_from_config_carries_every_knob():
    cfg = zero_if_60ghz(k=8)
    fe = Frontend60.from_config(cfg)
    assert fe.lo.carrier_hz == cfg.carrier_hz and fe.lo.tx_leak_dbc == -30.0 and fe.lo.rx_dc_dbc == -25.0
    assert fe.converters.bits(cfg.upclocked().fs_eff) == 11
    tx, rx = fe.build_chains(160e6, 320e6)
    assert tx.params.dac.bits == 11 and rx.params.adc.bits == 11 and tx.params.lo.enabled
    assert tx.params.lpf.fc_nominal_hz == pytest.approx(1.3 * 80e6) and tx.params.iq.enabled
    ideal = Frontend60.from_config(cfg.ideal())
    txi, rxi = ideal.build_chains(160e6, 320e6)
    assert not txi.params.dac.enabled and not txi.params.lo.enabled and txi.params.lo_leak_dbm is None
    assert Mmw60Config.from_dict(cfg.to_dict()) == cfg


def test_chain_operating_point_is_psat_minus_obo():
    cfg = dc.replace(zero_if_60ghz(k=8), channel=ChannelConfig(model="flat"))
    sim = LinkSim(cfg)
    assert sim.pout_dbm == pytest.approx(15.0 - 8.0, abs=0.05)
    r = sim.packet(None, np.random.default_rng(0))
    assert r.pa_info["pout_dbm"] == pytest.approx(7.0, abs=0.3)
    assert -22 < r.rx.evm_db < -14              # PA-dominated floor
    assert abs(r.rx.cfo_hat_hz - r.cfo_true_hz) < 0.05 * sim.phy.scs_eff


def test_chain_snr_setting_tracks_the_requested_snr():
    cfg = dc.replace(zero_if_60ghz(k=8).ideal(), channel=ChannelConfig(model="flat"))
    sim = LinkSim(cfg)
    rng = np.random.default_rng(1)
    e = [sim.packet(20.0, rng).rx.evm_db for _ in range(3)]
    # per-tone SNR 20 dB → EVM near −20 dB plus the estimator terms (≈ +1 dB)
    assert -20.5 < np.mean(e) < -17.5


def test_rx_dc_matters_only_once_the_cfo_moves_it_into_the_data():
    flat = ChannelConfig(model="flat")
    ideal = dc.replace(zero_if_60ghz(k=8).ideal(), channel=flat)
    with_dc = dc.replace(ideal, frontend=dc.replace(ideal.frontend, rx_dc_dbc=-25.0))
    e0 = evm_at(with_dc, None, n_packets=1)["evm_db"]
    e1 = evm_at(dc.replace(with_dc, xo_ppm_tx=20, xo_ppm_rx=20), None, n_packets=1)["evm_db"]
    assert e0 < -38 and -34 < e1 < -26


def test_evm_only_bases_run_without_the_coded_data_field():
    cfg = dc.replace(zero_if_60ghz(k=16, standard="11be", bandwidth_hz=80e6).ideal(),
                     channel=ChannelConfig(model="flat"))
    assert not cfg.coded
    sim = LinkSim(cfg)
    r = sim.packet(None, np.random.default_rng(0))
    assert r.rx.bit_errors is None and r.rx.evm_db < -35
    assert sim.base.n_active == 996 and sim.n_symbols == cfg.phy.evm_symbols


# ---------------------------------------------------------------- grid
def test_grid_analytic_floor_matches_the_time_domain_chain():
    fe = Frontend60.from_config(zero_if_60ghz(k=8))
    pa_evm = pa_isolated_evm_db(fe.pa_model, fe.obo_db, fe.obo_reference)
    assert -20 < pa_evm < -16
    for std, bw, k in (("11ac", 20e6, 8), ("11be", 80e6, 16)):
        c = evaluate_cell(zero_if_60ghz(k=k, standard=std, bandwidth_hz=bw), fe, isolate=False, pa_evm_db=pa_evm)
        assert abs(c.floor_db - c.td_evm_db) < 2.0, (std, bw, k, c.floor_db, c.td_evm_db)
    assert c.dominant == "iq_image" and c.max_mcs_cal is not None and c.max_mcs_cal >= c.max_mcs


def test_grid_flags_cfo_capture_and_the_band():
    """At 73.44 GHz (Liu) K = 4 loses the STF capture; at 60.48 GHz the same
    40 ppm is 2.42 MHz, inside the ±2.5 MHz range — the threshold is K > 3.9
    there, not 4.7 (cairn/topology-b.md)."""
    fe = Frontend60.from_config(zero_if_60ghz(k=8))
    a4 = analytic_floors(zero_if_60ghz(k=4, carrier_hz=73.44e9), fe)
    a8 = analytic_floors(zero_if_60ghz(k=8, carrier_hz=73.44e9), fe)
    assert not a4["cfo_captured"] and a8["cfo_captured"]
    assert analytic_floors(zero_if_60ghz(k=4), fe)["cfo_captured"]
    c = evaluate_cell(zero_if_60ghz(k=4, carrier_hz=73.44e9), fe, time_domain=False)
    assert c.verdict == "不能" and "CFO" in c.reason
    wide = evaluate_cell(zero_if_60ghz(k=32, standard="11be", bandwidth_hz=320e6), fe, time_domain=False)
    assert not wide.plan_ok and "频率规划" in wide.reason


def test_max_mcs_mapping_and_data_rate():
    assert max_mcs_for_floor(-40.0, "11ac") == 9 and max_mcs_for_floor(-45.0, "11be") == 13
    assert max_mcs_for_floor(-40.0, "11be") == 11          # MCS12/13 need −38 − 3 dB margin
    assert max_mcs_for_floor(-21.0, "11ac") == 3 and max_mcs_for_floor(-5.0, "11ac") is None
    t_sym = 4e-6 / 8
    assert data_rate_bps("11ac", 20e6, 0, t_sym) == pytest.approx(52 * 0.5 / t_sym)
    assert data_rate_bps("11be", 80e6, 13, 13.6e-6 / 16) == pytest.approx(980 * 12 * 5 / 6 / (13.6e-6 / 16))


# ---------------------------------------------------------------- plan, EIRP, DPD cost
def test_zero_if_plan_in_and_out_of_band():
    ok = zero_if_plan(60.48e9, 160e6, 320e6, 2.5e6, 2.4e6)
    assert ok["ok"] and ok["in_unlicensed_band"] and ok["lo_hz"] == 60.48e9
    assert ok["lo_leak_lands_on_tone"] == pytest.approx(0.96)
    bad = zero_if_plan(60.48e9, 10.24e9, 20.48e9, 2.5e6)
    assert not bad["in_unlicensed_band"] and bad["notes"]
    assert zero_if_plan(60e9, 1e9, 0.5e9, 1e6)["nyquist_ok"] is False


def test_eirp_limit_from_spec():
    e = EirpLimit.fcc_15_255()
    assert e.avg_dbm == 40.0 and e.peak_dbm == 43.0 and e.in_band(57.1e9, 70.9e9) and not e.in_band(56e9, 60e9)
    assert e.check(7.0, 0.0)["ok"] and not e.check(35.0, 10.0)["ok"]


def test_dpd_cost_bookkeeping():
    m = dsp_ip_models()
    assert set(m) == {"ddr_r1_w16", "gmp510_w16"} and m["ddr_r1_w16"].msps_p4 == pytest.approx(2728)
    d = DpdCost(terms=140, area_mm2_p4=8.0, f_clk_mhz_p4=682, name="x")
    e = d.energy_pj_per_sample(16)
    assert e == pytest.approx(140 * (3.1 / 4 + 0.1 / 2))
    assert d.pj_per_bit(640e6, 100e6) == pytest.approx(e * 6.4)
    assert d.instances_for(2728e6) == pytest.approx(1.0)


def test_lo60_leak_and_dc_arithmetic():
    lo = Lo60(60e9, None, tx_leak_dbc=-30.0, rx_dc_dbc=-20.0)
    assert lo.tx_leak_dbm(-10.0) == -40.0 and lo.lo_model().enabled is False
    assert abs(lo.rx_dc(1.0)) == pytest.approx(0.1)
    assert Lo60(60e9, None).rx_dc(1.0) == 0


def test_m0_behavioural_path_is_untouched_by_the_frontend():
    cfg = liu2025_table2(k=8, mcs=0)
    assert cfg.frontend.model == "behavioural" and not cfg.frontend.iq.enabled
    assert LinkSim(cfg).frontend is None
