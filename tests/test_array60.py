"""Milestone 2: the array layer (``frontend/array60.py``) and its link and
training budget (``arraylink.py``)."""
from __future__ import annotations

import dataclasses as dc

import numpy as np
import pytest

from mmw60 import arraylink as al
from mmw60 import spec
from mmw60.config import ChannelConfig, Mmw60Config, array_frontend, if_extender_60ghz, zero_if_60ghz
from mmw60.frontend import Frontend60
from mmw60.frontend.array60 import Array60, quantise_phase
from mmw60.frontend.grid import pa_isolated_evm_db
from mmw60.sim.link import LinkSim
from mmw60.vendor.arraytx.beam import array_factor_cw

FLAT = ChannelConfig(model="flat")


def with_array(cfg, **kw):
    return dc.replace(cfg, frontend=dc.replace(cfg.frontend, array=dc.replace(cfg.frontend.array, **kw)))


def test_the_preset_is_one_element_and_the_array_config_is_checked():
    cfg = zero_if_60ghz(k=8)
    assert cfg.frontend.array.n_tx == cfg.frontend.array.n_rx == 1
    fe = Frontend60.from_config(cfg)
    ar = Array60.from_config(cfg, fe)
    assert ar.tx_gain_db(0.0, 0.0)[0] == pytest.approx(fe.antenna_gain_tx_dbi)
    assert ar.rx_gain_db(0.0, 0.0)[0] == pytest.approx(fe.antenna_gain_rx_resolved_dbi)
    assert ar.codebook_deg().tolist() == [0.0] and ar.eirp_dbm(7.0) == pytest.approx(7.0 + fe.antenna_gain_tx_dbi)
    for bad in (dict(tx_nx=0), dict(element_pattern="dipole"), dict(steering="lens"), dict(phase_bits=0),
                dict(scan_max_deg=90.0), dict(sector_oversampling=0.0)):
        with pytest.raises(ValueError, match="frontend.array"):
            with_array(cfg, **bad)
    a = array_frontend(cfg, 16)
    assert (a.frontend.array.n_tx, a.frontend.array.n_rx) == (16, 16)
    assert a.frontend.array.phase_bits == spec.value("assumed.array_phase_bits")
    assert Mmw60Config.from_dict(a.to_dict()) == a


def test_ideal_array_gain_is_20logn_on_transmit_and_10logn_on_receive_and_matches_arraytx():
    cfg = zero_if_60ghz(k=8)
    fe = Frontend60.from_config(cfg)
    for n in (2, 8, 32):
        ar = Array60.from_config(with_array(cfg, tx_nx=n, rx_nx=n), fe)
        assert ar.tx_gain_db(0.0, 0.0)[0] == pytest.approx(20 * np.log10(n), abs=1e-9)
        assert ar.rx_gain_db(0.0, 0.0)[0] == pytest.approx(10 * np.log10(n), abs=1e-9)
        # the array factor is arraytx's (normalised to 1 there, to N here) for the ideal weights
        th = np.linspace(-80, 80, 33)
        ours = ar.af("tx", ar.weights("tx", 25.0, ideal=True), th) / n
        assert np.allclose(ours, array_factor_cw(ar.tx, 25.0, 0.0, th, "phase"), atol=1e-9)
    # arraytx's cos element factor is a field amplitude: 20 log10 cos(theta) of scan loss
    ar = Array60.from_config(with_array(cfg, tx_nx=8, rx_nx=8, element_pattern="cos"), fe)
    assert ar.tx_gain_db(60.0, 60.0)[0] - ar.tx_gain_db(0.0, 0.0)[0] == pytest.approx(20 * np.log10(0.5), abs=1e-9)


def test_phase_quantisation_loss_matches_the_sinc_law_and_is_referenced_to_the_first_element():
    cfg = zero_if_60ghz(k=8)
    fe = Frontend60.from_config(cfg)
    th = np.linspace(-60, 60, 121)
    for bits in (1, 2, 3):
        ar = Array60.from_config(with_array(cfg, tx_nx=64, rx_nx=64, phase_bits=bits), fe)
        mean_loss = np.mean([ar.quantisation_loss_db("tx", t) for t in th])
        x = np.pi / 2 ** bits
        assert mean_loss == pytest.approx(-20 * np.log10(np.sin(x) / x), abs=0.12)
    # a progression that a 2-bit shifter holds exactly loses nothing (it used to lose 3 dB: centred
    # array, phases on the half step, round-half-even)
    ar = Array60.from_config(with_array(cfg, tx_nx=4, rx_nx=4, phase_bits=2), fe)
    assert ar.quantisation_loss_db("tx", 30.0) == pytest.approx(0.0, abs=1e-9)
    w = quantise_phase(np.exp(1j * np.array([0.3, 1.1, 2.0])), 3)
    assert np.allclose(np.abs(w), 1.0) and w[0] == pytest.approx(1.0)


def test_the_eirp_limit_backs_every_element_off_and_the_pa_gets_more_linear():
    cfg = dc.replace(zero_if_60ghz(k=4, standard="11be", bandwidth_hz=80e6), channel=FLAT)
    fe = Frontend60.from_config(cfg)
    small = al.array_budget(array_frontend(cfg, 4), fe, Array60.from_config(array_frontend(cfg, 4), fe))
    big_cfg = array_frontend(cfg, 64)
    big = al.array_budget(big_cfg, fe, Array60.from_config(big_cfg, fe))
    assert small.p_elem_dbm == pytest.approx(fe.target_pout_dbm()) and small.eirp_dbm < fe.eirp.avg_dbm
    assert big.eirp_dbm == pytest.approx(fe.eirp.avg_dbm, abs=1e-6)
    assert big.obo_db - fe.obo_db == pytest.approx(fe.target_pout_dbm() - big.p_elem_dbm)
    assert big.pa_evm_db == pytest.approx(pa_isolated_evm_db(fe.pa_model, big.obo_db, fe.obo_reference))
    assert big.pa_evm_db < small.pa_evm_db - 5 and big.floor_db < small.floor_db
    assert big.dec_mcs >= small.dec_mcs


def test_budget_ranges_are_the_receivers_own_sensitivity_over_free_space_and_oxygen():
    cfg = dc.replace(zero_if_60ghz(k=8), channel=FLAT)
    fe = Frontend60.from_config(cfg)
    c = array_frontend(cfg, 4)
    ar = Array60.from_config(c, fe)
    b = al.array_budget(c, fe, ar)
    sim = LinkSim(c, frontend=fe)
    t0 = spec.per_threshold_db("11ac", 20e6, 0)
    s0 = sim.rx_input_dbm_for_snr(al.required_snr_db(t0, b.floor_db))
    assert b.sens_by_mcs[0] == pytest.approx(s0)
    d = b.range_by_mcs[0]
    assert b.eirp_dbm + b.g_rx_db - al.path_loss_db(d, c.carrier_hz) == pytest.approx(s0, abs=1e-9)
    assert al.fspl_db(1.0, 60.48e9) == pytest.approx(68.08, abs=0.005)
    # the distance adds the oxygen estimate to free space; 0 dB/km is free space alone, and the path loss
    # (the budget's answer) does not depend on it
    a = spec.value("assumed.oxygen_absorption")
    assert al.oxygen_db_per_km() == a > 0
    for link in (90.0, 130.0, 150.0):
        d_fs, d_ox = al.range_m(link, 60.48e9, 0.0), al.range_m(link, 60.48e9)
        assert al.fspl_db(d_fs, 60.48e9) == pytest.approx(link, abs=1e-9)
        assert float(al.path_loss_db(d_ox, 60.48e9)) == pytest.approx(link, abs=1e-9)
        assert al.path_loss_db(d_ox, 60.48e9) - al.fspl_db(d_ox, 60.48e9) == pytest.approx(a * d_ox / 1e3)
        assert d_ox < d_fs and al.range_m(link, 60.48e9, 2 * a) < d_ox
    # the same array instance serves topology A: its sensitivity is its own (cascade included)
    a = array_frontend(dc.replace(if_extender_60ghz(standard="11be", bandwidth_hz=20e6), channel=FLAT), 4)
    ba = al.array_budget(a, fe, ar)
    assert ba.eirp_dbm == b.eirp_dbm and ba.g_rx_db == b.g_rx_db
    assert ba.noise_dbm == pytest.approx(LinkSim(a, frontend=fe).rx_input_dbm_for_snr(0.0))


def test_the_sweep_statistic_closed_form_matches_tone_by_tone_noise():
    """The non-central chi-square shortcut against the per-tone model it stands for."""
    rng = np.random.default_rng(1)
    n, trials = 56, 4000
    gains = np.array([0.0, -1.5, -4.0, -9.0])
    x = rng.choice([-1.0, 1.0], n)
    for snr in (-6.0, -2.0, 2.0):
        rho = 10 ** ((snr + gains) / 10)
        hits = 0
        for _ in range(trials):
            y = np.sqrt(rho)[:, None, None] * x[None, None, :] + (
                rng.standard_normal((4, 2, n)) + 1j * rng.standard_normal((4, 2, n))) / np.sqrt(2)
            t = np.sum(np.abs(np.sum(y * x[None, None, :], axis=1)) ** 2, axis=1)
            hits += gains[np.argmax(t)] >= -1.0
        brute = hits / trials
        closed = al.selection_success(gains, snr, n, np.random.default_rng(2), trials=trials)
        assert closed == pytest.approx(brute, abs=0.03)
    # more tones, less SNR needed; a single sector is always right
    g = np.array([0.0, -2.0])
    assert (al.selection_success(g, -8.0, 996, np.random.default_rng(3))
            > al.selection_success(g, -8.0, 56, np.random.default_rng(3)))
    assert al.selection_success(np.array([0.0]), -30.0, 56, np.random.default_rng(4)) == 1.0


def test_training_needs_less_snr_than_mcs0_but_the_transmit_sweep_loses_the_receive_array():
    cfg = dc.replace(zero_if_60ghz(k=4, standard="11be", bandwidth_hz=80e6), channel=FLAT)
    fe = Frontend60.from_config(cfg)
    c = array_frontend(cfg, 16)
    ar = Array60.from_config(c, fe)
    n_tones = LinkSim(c, frontend=fe).n_active
    req = al.required_training_snr_db(ar, "tx", n_tones, trials=400, n_users=7)
    assert req["sectors"] == 16 and req["snr_db"] is not None
    assert req["snr_db"] < spec.per_threshold_db("11be", 80e6, 0)
    b = al.array_budget(c, fe, ar)
    tr = al.training_ranges(b, ar, req["snr_db"], req["snr_db"], c.carrier_hz)
    assert tr["rxss_m"] > tr["txss_m"]
    # the transmit sweep's budget is the data link's less the receive array (one element there)
    one = float(ar.element_factor_db("rx", 0.0)[0] + ar.element_gain_rx_dbi)
    pl = [float(al.path_loss_db(tr[k], c.carrier_hz)) for k in ("rxss_m", "txss_m")]
    assert pl[0] - pl[1] == pytest.approx(b.g_rx_db - one, abs=1e-9)
    assert al.sweep_time_s(ar, c.upclocked()) == pytest.approx(
        16 * (al._ltf_field_s(c.upclocked()) + spec.value("assumed.array_training")["sector_switch_s"]))


def test_repeating_the_training_field_lowers_the_snr_the_transmit_sweep_needs():
    """ROADMAP B (user's pick 2026-11-15): R repetitions summed
    non-coherently are n R tones' worth of statistics (about 1.5 dB per
    doubling with hundreds of tones), coherently 2R symbols per tone (3 dB
    per doubling); R = 1 is the field as it is; the sweep lasts R times as
    long."""
    cfg = dc.replace(zero_if_60ghz(k=4, standard="11be", bandwidth_hz=80e6), channel=FLAT)
    fe = Frontend60.from_config(cfg)
    c = array_frontend(cfg, 8)
    ar = Array60.from_config(c, fe)
    n = LinkSim(c, frontend=fe).n_active
    kw = dict(trials=400, n_users=5, seed=3)
    base = al.required_training_snr_db(ar, "tx", n, **kw)
    one_coh = al.required_training_snr_db(ar, "tx", n, repetitions=1, combining="coherent", **kw)
    assert one_coh["snr_db"] == base["snr_db"]
    assert al.required_training_snr_db(ar, "tx", n, repetitions=1, **kw)["snr_db"] == base["snr_db"]
    nc = al.required_training_snr_db(ar, "tx", n, repetitions=4, **kw)
    co = al.required_training_snr_db(ar, "tx", n, repetitions=4, combining="coherent", **kw)
    assert nc["combining"] == spec.value("assumed.array_training_repetition")["combining"] == "noncoherent"
    assert 2.0 <= base["snr_db"] - nc["snr_db"] <= 4.0, (base["snr_db"], nc["snr_db"])
    assert 5.0 <= base["snr_db"] - co["snr_db"] <= 7.0, (base["snr_db"], co["snr_db"])
    # the non-coherent statistic is the closed form over n R tones
    g = ar.sector_gains_db("tx", 10.0)
    assert al.selection_success(g, -12.0, n * 4, np.random.default_rng(1)) == pytest.approx(
        al.selection_success(g, -12.0, n * 4, np.random.default_rng(1), n_sym=2))
    with pytest.raises(ValueError):
        al.required_training_snr_db(ar, "tx", n, repetitions=0, **kw)
    with pytest.raises(ValueError, match="combining"):
        al.required_training_snr_db(ar, "tx", n, repetitions=2, combining="sometimes", **kw)
    phy = c.upclocked()
    assert al.sweep_time_s(ar, phy, "tx", 4) - al.sweep_time_s(ar, phy, "tx") == pytest.approx(
        3 * 8 * al._ltf_field_s(phy))
    # the search: the fewest repetitions that reach a path loss, None when even the largest falls short
    b = al.array_budget(c, fe, ar)
    pl1 = al.transmit_sweep_reach_db(b, ar, base["snr_db"])
    got = al.repetitions_to_reach(b, ar, n, pl1 + 2.0, **kw)
    assert got["repetitions"] in (2, 4) and got["pl_db"] >= pl1 + 2.0 and got["margin_db"] >= 0
    assert al.repetitions_to_reach(b, ar, n, pl1 - 1.0, **kw)["repetitions"] == 1
    assert al.repetitions_to_reach(b, ar, n, pl1 + 40.0, max_repetitions=4, **kw)["repetitions"] is None


def test_the_array_power_column_is_the_single_element_one_at_n1_and_counts_n_pas_and_phase_shifters():
    """ROADMAP B (user's pick 2026-11-15): N_tx PAs at the per-element
    output the EIRP limit leaves, one phase shifter per element and side
    (assumed.array_phase_shifter_power_mw), nothing else per element."""
    from mmw60.frontend.grid import data_rate_bps
    from mmw60.power import PowerCoefficients, power_report
    cfg = dc.replace(zero_if_60ghz(k=4, standard="11be", bandwidth_hz=80e6), channel=FLAT)
    fe = Frontend60.from_config(cfg)
    k = PowerCoefficients.from_spec()
    assert k.phase_shifter_w > 0
    assert k.phase_shifter_w == pytest.approx(1e-3 * spec.value("assumed.array_phase_shifter_power_mw"))
    reps = {}
    for n in (1, 16, 64):
        c = array_frontend(cfg, n)
        ar = Array60.from_config(c, fe)
        b = al.array_budget(c, fe, ar)
        reps[n] = (b, al.array_power_report(c, fe, ar, b, k))
    b1, r1 = reps[1]
    rate = data_rate_bps("11be", 80e6, b1.dec_mcs, cfg.upclocked().t_symbol_eff)
    single = power_report(array_frontend(cfg, 1), fe, rate, k, mcs_index=b1.dec_mcs)
    assert r1.blocks == single.blocks and r1.pj_per_bit == single.pj_per_bit and r1.omitted == single.omitted
    one_pa = r1.watts("pa")
    b16, r16 = reps[16]
    assert b16.p_elem_dbm == pytest.approx(fe.target_pout_dbm())
    assert r16.watts("pa") == pytest.approx(16 * one_pa)
    assert r16.watts("phase_shifters") == pytest.approx(32 * k.phase_shifter_w)
    others = lambda r: r.total_w - r.watts("pa") - r.watts("phase_shifters")  # noqa: E731
    assert others(r16) == pytest.approx(others(r1)) and r16.bit_rate == r1.bit_rate
    assert any("LNA" in o for o in r16.omitted)
    # N = 64 hits the EIRP limit: every element backs off, so each PA draws less than at the operating point
    b64, r64 = reps[64]
    assert b64.p_elem_dbm < fe.target_pout_dbm() and r64.watts("pa") < 64 * one_pa
    assert al.array_power_report(array_frontend(cfg, 16), fe, Array60.from_config(array_frontend(cfg, 16), fe), b16,
                                 k.with_(phase_shifter_w=0.0)).watts("phase_shifters") == 0.0


def test_a_two_stage_sweep_saves_time_with_margin_but_cannot_reach_further():
    """ROADMAP B (user's pick 2026-11-16): the wide stage is an m-element
    sub-array, 20 log10(N/m) dB short of the full array's EIRP, so where the
    flat sweep needs repetitions to reach the MCS0 edge the wide stage needs
    far more; with margin (the decoder cap's distance) both stages need one
    field and the two-stage sweep is shorter.  ``candidates`` restricts the
    refining stage to the sectors with the most gain toward the station."""
    cfg = dc.replace(zero_if_60ghz(k=4, standard="11be", bandwidth_hz=80e6), channel=FLAT)
    fe = Frontend60.from_config(cfg)
    n = 16
    c = array_frontend(cfg, n)
    ar = Array60.from_config(c, fe)
    b = al.array_budget(c, fe, ar)
    n_tones = LinkSim(c, frontend=fe).n_active
    kw = dict(trials=300, n_users=5, seed=2)
    base = al.required_training_snr_db(ar, "tx", n_tones, **kw)
    assert al.required_training_snr_db(ar, "tx", n_tones, candidates=None, **kw)["snr_db"] == base["snr_db"]
    assert al.required_training_snr_db(ar, "tx", n_tones, candidates=2, **kw)["snr_db"] <= base["snr_db"]
    cap = b.eirp_dbm + b.g_rx_db - b.sens_by_mcs[b.dec_mcs]
    h = al.hierarchical_training(cfg, fe, n, 8, n_tones, cap, **kw)
    assert h["wide"]["sectors"] == 8 and h["narrow"]["sectors"] == 2 and h["flat"]["sectors"] == 16
    assert h["wide"]["eirp_dbm"] == pytest.approx(h["flat"]["eirp_dbm"] - 20 * np.log10(n / 8), abs=0.6)
    assert h["flat"]["repetitions"] == h["wide"]["repetitions"] == h["narrow"]["repetitions"] == 1
    assert h["hierarchical_time_s"] < h["flat"]["time_s"]
    edge = b.eirp_dbm + b.g_rx_db - b.sens_by_mcs[0]
    e = al.hierarchical_training(cfg, fe, n, 8, n_tones, edge, max_repetitions=16, **kw)
    assert e["flat"]["repetitions"] is not None and e["wide"]["repetitions"] is None
    assert e["hierarchical_time_s"] is None and e["wide"]["pl_db"] < edge
