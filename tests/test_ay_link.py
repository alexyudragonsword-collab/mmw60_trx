"""Milestone 3 stage 1: the EDMG numbers wired into the skeleton, and the two
802.11ay waveforms through the shared front end (``sim/ay_link.py``)."""
import dataclasses as dc

import numpy as np
import pytest

from mmw60 import spec
from mmw60.ay import edmg, papr, sc
from mmw60.config import ChannelConfig, ay_60ghz
from mmw60.frontend import Frontend60
from mmw60.sim.link import LinkSim

FLAT = ChannelConfig(model="flat")


def _ideal(wf, mcs, model="zero_if_chain", **ay):
    c = dc.replace(ay_60ghz(wf, mcs).ideal(), channel=FLAT)
    c = dc.replace(c, frontend=dc.replace(c.frontend, model=model))
    return dc.replace(c, ay=dc.replace(c.ay, **ay)) if ay else c


def test_the_edmg_numerology_is_read_from_spec_and_the_pilots_move_with_the_channel():
    p = spec.value("edmg.ofdm_params")
    for ch in range(1, 9):
        o = edmg.ofdm_numerology(ch)
        assert (o.n_fft, o.fs_hz, len(o.data_tones), len(o.pilot_tones)) == (p["n_dft"], p["fs_hz"], 336, 16)
        assert not {-1, 0, 1} & set(o.used_tones) and max(o.used_tones) <= p["n_sr"] >= -min(o.used_tones)
        assert list(o.pilot_tones) == spec.ref(f"edmg.ofdm_pilot_tones_ncb1#tones@channel={ch}")
    assert edmg.ofdm_numerology(1).pilot_tones != edmg.ofdm_numerology(4).pilot_tones
    assert [edmg.ofdm_numerology(2, gi).cp for gi in edmg.GIS] == [48, 96, 192]
    assert edmg.ofdm_numerology(2).scs_hz == pytest.approx(5.15625e6)
    s = edmg.sc_numerology()
    assert (s.block, s.guard, s.fs_hz, s.data_per_block) == (512, 64, 1.76e9, 448)
    assert [edmg.sc_numerology(gi).guard for gi in edmg.GIS] == [32, 64, 128]
    assert edmg.chain_rate()["fs_hz"] == 5.28e9 and edmg.channel_spacing_hz() == 2.16e9
    assert edmg.channel_of(60.48e9) == 2
    with pytest.raises(ValueError, match="channel centre"):
        edmg.channel_of(60.0e9)


def test_the_mcs_tables_rates_and_limits_and_the_cap_on_a_non_monotonic_table():
    o, s = edmg.mcs_table("ay_ofdm"), edmg.mcs_table("ay_sc")
    assert [e.mcs for e in o] == list(range(1, 21)) and [e.mcs for e in s] == list(range(1, 22))
    # the derived rates recompute from the spec numbers (SC: chip rate × 448/512 × bits × R / repetition)
    for e in s:
        assert e.rate_bps() == pytest.approx(1.76e9 * 448 / 512 * np.log2(e.order) * float(e.code_rate)
                                             / e.repetition, rel=1e-4)
    for e in o:
        t = 512 / 2.64e9 + 96 / 2.64e9
        assert e.rate_bps() == pytest.approx(336 * np.log2(e.order) * float(e.code_rate) / t, rel=1e-3)
    assert edmg.mcs_entry("ay_sc", 12).evm_limit_db == spec.ref("dmg.tx_evm_db#evm_db@mcs=10") == -19.0
    # EDMG OFDM MCS 6 (DCM QPSK 1/2) allows −10 dB where MCS 4 / 5 allow −12 / −13: a floor of −10.5 dB
    # passes MCS 1–3 and 6 but not 4, and the cap is the fastest of those, not the last index before
    # the first failure
    assert [e.mcs for e in o if -10.5 <= e.evm_limit_db] == [1, 2, 3, 6]
    c = edmg.conformance_cap(-10.5, "ay_ofdm")
    assert c["mcs"] == 6 and c["highest_index"] == 6 and c["rate_bps"] > edmg.mcs_entry("ay_ofdm", 4).rate_bps()
    assert edmg.conformance_cap(0.0, "ay_sc")["mcs"] is None
    assert edmg.conformance_cap(-60.0, "ay_sc")["mcs"] == 21


def test_the_ideal_link_returns_the_points_and_reads_the_in_band_snr():
    """On the ideal front end (behavioural) both waveforms come back to numerical
    precision, and with noise at an in-band SNR of 20 dB they read about −20 dB:
    the SNR is per chip for SC and per active tone for OFDM, as for the be links."""
    for wf, m in (("ay_sc", 16), ("ay_ofdm", 15)):
        sim = LinkSim(_ideal(wf, m, model="behavioural"))
        assert type(sim).__name__ == "AyLinkSim"
        assert sim.packet(None, np.random.default_rng(0)).rx.evm_db < -55
        e = [sim.packet(20.0, np.random.default_rng(i)).rx.evm_db for i in range(3)]
        assert np.mean(e) == pytest.approx(-20.0, abs=1.0), (wf, e)
        # without the GI window the single Golay pair's own noise costs about 2 dB at 20 dB
        raw = LinkSim(_ideal(wf, m, model="behavioural", ce_window=False))
        e_raw = [raw.packet(20.0, np.random.default_rng(i)).rx.evm_db for i in range(3)]
        assert np.mean(e_raw) > np.mean(e) + 1.0, (wf, e, e_raw)


def test_law2_both_ay_waveforms_run_on_the_shared_front_end_and_one_chain():
    """One front-end instance, one sample rate, one set of chain filters for
    both ay waveforms (and the same front-end settings as the be presets)."""
    from mmw60.config import zero_if_60ghz
    sc_cfg, of_cfg = ay_60ghz("ay_sc"), ay_60ghz("ay_ofdm")
    assert sc_cfg.frontend == of_cfg.frontend == zero_if_60ghz(k=1).frontend
    fe = Frontend60.from_config(sc_cfg)
    a, b = LinkSim(sc_cfg, frontend=fe), LinkSim(of_cfg, frontend=fe)
    assert a.frontend is fe and b.frontend is fe
    assert a.phy.fs_eff == b.phy.fs_eff == 5.28e9 and a.phy.bandwidth_eff == b.phy.bandwidth_eff == 2.16e9
    assert a.tx.params.lpf.fc_nominal_hz == b.tx.params.lpf.fc_nominal_hz
    assert a.rx.params.lpf.fc_nominal_hz == b.rx.params.lpf.fc_nominal_hz
    # the PA sits at the same back-off for both: the drive is set per waveform, the output is the target
    assert a.pout_dbm == pytest.approx(fe.target_pout_dbm(), abs=0.05)
    assert b.pout_dbm == pytest.approx(fe.target_pout_dbm(), abs=0.05)


def test_law3_the_ay_links_catch_the_cfo_with_their_own_stf():
    """(ppm_tx + ppm_rx) × f_c as everywhere, exactly zero at zero ppm; the
    STF's lag-128 estimate spans ±fs/256 (±6.875 MHz SC, ±10.3 MHz OFDM) and
    catches the 2.42 MHz of 40 ppm at 60.48 GHz with no MLO; with estimation
    off neither waveform survives (0.47 of an OFDM subcarrier; 4.4 rad across
    an SC block)."""
    for wf, m in (("ay_sc", 16), ("ay_ofdm", 15)):
        ideal = _ideal(wf, m, model="behavioural")
        cfg = dc.replace(ay_60ghz(wf, m), channel=FLAT)
        with_cfo = dc.replace(ideal, xo_ppm_tx=cfg.xo_ppm_tx, xo_ppm_rx=cfg.xo_ppm_rx)
        assert ideal.cfo_hz == 0.0 and with_cfo.cfo_hz == pytest.approx(40e-6 * 60.48e9)
        sim = LinkSim(with_cfo)
        assert sim.describe()["cfo_range_hz"] >= 2.5 * with_cfo.cfo_hz
        r = sim.packet(None, np.random.default_rng(1))
        assert abs(r.rx.cfo_hat_hz - r.cfo_true_hz) < 5e3 and r.rx.evm_db < -40, (wf, r.rx.evm_db)
        z = LinkSim(ideal).packet(None, np.random.default_rng(1)).rx
        assert z.cfo_hat_hz == pytest.approx(0.0, abs=1.0)
        off = dc.replace(with_cfo, rx=dc.replace(with_cfo.rx, cfo_estimation="off"))
        assert LinkSim(off).packet(None, np.random.default_rng(1)).rx.evm_db > -5, wf


def test_the_tx_lo_leak_reaches_single_carrier_only_once_the_cfo_moves_it_off_dc():
    """The receiver removes the DC it measures on its quiet lead-in: with no CFO
    that is the TX LO leak exactly.  With the CFO the leak arrives turning,
    averages out on the lead-in and is DC again after the CFO correction —
    on OFDM's empty DC tones, on every SC chip (example 15 §3)."""
    out = {}
    for wf, m in (("ay_sc", 21), ("ay_ofdm", 15)):
        ideal = _ideal(wf, m)
        cfg = dc.replace(ay_60ghz(wf, m), channel=FLAT)
        leak = dc.replace(ideal, frontend=dc.replace(ideal.frontend, lo_leak_dbc=cfg.frontend.lo_leak_dbc))
        moved = dc.replace(leak, xo_ppm_tx=cfg.xo_ppm_tx, xo_ppm_rx=cfg.xo_ppm_rx)
        e = {k: LinkSim(v).packet(None, np.random.default_rng(0)).rx.evm_db
             for k, v in (("ideal", ideal), ("leak", leak), ("leak+cfo", moved))}
        assert e["leak"] == pytest.approx(e["ideal"], abs=0.1), (wf, e)
        out[wf] = e["leak+cfo"]
    assert out["ay_sc"] < -20 and out["ay_ofdm"] < out["ay_sc"] - 5, out


def test_single_carrier_tracks_a_drifting_phase_between_its_guards():
    """With the 60 GHz phase noise alone, interpolating the phase between the
    guard before and after each block does better than one phase per block."""
    base = _ideal("ay_sc", 21)
    cfg = ay_60ghz("ay_sc", 21)
    pn = dc.replace(base, lo=cfg.lo)
    e = {}
    for mode in ("interp", "block"):
        sim = LinkSim(dc.replace(pn, ay=dc.replace(pn.ay, sc_phase=mode)))
        e[mode] = sim.packet(None, np.random.default_rng(3)).rx.evm_db
    assert e["interp"] < e["block"] - 0.5, e
    with pytest.raises(ValueError, match="sc_phase"):
        dc.replace(cfg, ay=dc.replace(cfg.ay, sc_phase="spline"))


def test_the_single_carrier_payload_is_at_least_3_db_under_ofdm_at_low_order():
    """The acceptance line on the real numerologies: the transmitted SC payload
    (π/2-BPSK / π/2-QPSK, the assumed 0.25 roll-off) at 1e-3 sits at least
    3 dB under the OFDM payload; 16-QAM by less."""
    def payload_papr(wf, m):
        sim = LinkSim(_ideal(wf, m))
        ref, frame = sim.transmit(np.random.default_rng(1))
        x = frame.x[(ref.stf_len + ref.cef_len) * sim.phy.up:]
        return papr.papr_db(x[:-len(sim.taps)] if wf == "ay_sc" else x, 1e-3)
    p_ofdm = payload_papr("ay_ofdm", 15)
    assert 7.5 < p_ofdm < 9.5
    assert p_ofdm - payload_papr("ay_sc", 6) >= 3.0 and p_ofdm - payload_papr("ay_sc", 11) >= 3.0
    assert 1.5 < p_ofdm - payload_papr("ay_sc", 16) < 3.5


def test_the_guard_window_and_the_pair_estimate_helpers():
    rng = np.random.default_rng(0)
    h = np.zeros(512, complex)
    h[:10] = rng.standard_normal(10) + 1j * rng.standard_normal(10)
    H = np.fft.fft(h)
    assert np.allclose(sc.window_estimate(H, 64, 8), H)            # a channel inside the window loses nothing
    noisy = H + 0.1 * (rng.standard_normal(512) + 1j * rng.standard_normal(512))
    err_raw = np.mean(np.abs(noisy - H) ** 2)
    err_win = np.mean(np.abs(sc.window_estimate(noisy, 64, 8) - H) ** 2)
    assert err_raw / err_win == pytest.approx(512 / 72, rel=0.25)


def test_law4_the_ay_chain_is_calibrated_by_running_wifitrx_sequence():
    """Iron rule 4 for the ay schemes: wifitrx's sequence runs on the ay chain
    (2.16 GHz, 5.28 GS/s) on the probe of assumed.ay_cal_probe, every planned
    step leaves a row, and both waveforms on the calibrated chains climb from
    the raw chain's IQ-limited floor to within 1 dB of the "IQ and LO leak
    calibrated away" reading of example 15 §4."""
    import copy

    from mmw60.calcheck import ay_probe_config, run_cal_ay
    probe, name, p = ay_probe_config()
    assert probe.oversampling * probe.bandwidth_hz == edmg.chain_rate()["fs_hz"] and "x22" in name
    cfg = ay_60ghz("ay_sc", 16)
    fe = Frontend60.from_config(cfg)
    run = run_cal_ay(fe, cfg)
    steps = {r.step: r for r in run.rows}
    for s in ("tx_lpf_corner", "rx_dc_offset", "tx_lo_leak_loopback", "tx_iq", "rx_iq", "final_loopback_evm"):
        assert s in steps and steps[s].status in ("ok", "degraded"), (s, steps.get(s))
    assert steps["tx_iq"].value > 35 and steps["rx_iq"].value > 35 and steps["tx_lo_leak_loopback"].value < -30
    assert run.final_views["evm_modem_db"] < -18 and run.pout_dbm == pytest.approx(fe.target_pout_dbm(), abs=0.5)
    for wf, m in (("ay_sc", 16), ("ay_ofdm", 15)):
        c = dc.replace(ay_60ghz(wf, m), channel=FLAT)
        cal = LinkSim(c, frontend=fe, chains=copy.deepcopy(run.chains[:2]))
        assert cal.calibrated and cal.pout_dbm == pytest.approx(fe.target_pout_dbm(), abs=0.05)
        e_cal = cal.packet(None, np.random.default_rng(0)).rx.evm_db
        e_raw = LinkSim(c, frontend=fe).packet(None, np.random.default_rng(0)).rx.evm_db
        away = dc.replace(c, frontend=dc.replace(c.frontend, iq=dc.replace(c.frontend.iq, enabled=False),
                                                 lo_leak_dbc=None))
        e_away = LinkSim(away).packet(None, np.random.default_rng(0)).rx.evm_db
        assert e_raw > -10 and e_cal < e_raw - 10 and abs(e_cal - e_away) < 1.0, (wf, e_raw, e_cal, e_away)
    with pytest.raises(ValueError, match="rate and bandwidth"):
        LinkSim(ay_60ghz("ay_sc"), frontend=fe, chains=fe.build_chains(2.56e9, 5.12e9))
