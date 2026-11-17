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


def test_the_tx_lo_leak_null_survives_a_vga_change_through_set_gain(monkeypatch):
    """wifi_trx_cal#6 (wifitrx 0.7.41, B43): ``dc_pre`` sits before the VGA
    and the leak it cancels after it, so a gain change scales the correction
    and not the leak.  ``Frontend60.set_vga_for_obo`` moves the VGA through
    ``tx.set_gain``, which rescales ``dc_pre``: one calibration at the preset
    back-off serves 15 dB as well as the sequence run anew there.  Until
    2026-11-17 the trim was a bare assignment and single carrier lost about
    10 dB at 15 dB, all of it DC the CFO carries past the receiver's DC
    removal; the same trim done that way here brings the loss back (so the
    first assertion is the frontend's set_gain, not luck)."""
    import copy

    from mmw60.calcheck import run_cal_ay
    from mmw60.vendor.wifitrx.units import power_dbm
    cfg = dc.replace(ay_60ghz("ay_sc", 16), channel=FLAT)
    low = dc.replace(cfg, frontend=dc.replace(cfg.frontend, pa=dc.replace(cfg.frontend.pa, obo_db=15.0)))
    fe, fe_low = Frontend60.from_config(cfg), Frontend60.from_config(low)
    once, here = run_cal_ay(fe, cfg), run_cal_ay(fe_low, low)

    def ev(c, run):
        sim = LinkSim(c, frontend=Frontend60.from_config(c), chains=copy.deepcopy(run.chains[:2]))
        return float(np.mean([sim.packet(None, np.random.default_rng(i)).rx.evm_db for i in range(2)]))
    fresh, kept = ev(low, here), ev(low, once)
    assert fresh < -25 and abs(kept - fresh) < 1.0, (kept, fresh)

    def bare(self, tx, x_digital, tol_db=0.02):       # the trim before 2026-11-17
        if not self.pa_enabled:
            return power_dbm(tx(x_digital))
        target = self.target_pout_dbm()
        for _ in range(12):
            err = target - power_dbm(tx(x_digital))
            if abs(err) < tol_db:
                break
            tx.params.vga_gain_db += err * 1.2
        return power_dbm(tx(x_digital))
    monkeypatch.setattr(Frontend60, "set_vga_for_obo", bare)
    broken, broken_no_cfo = ev(low, once), ev(dc.replace(low, xo_ppm_tx=0.0, xo_ppm_rx=0.0), once)
    assert broken > fresh + 6 and broken_no_cfo < fresh + 1.5, (broken, broken_no_cfo, fresh)


def test_the_two_ay_rows_of_the_comparison_table():
    """Milestone 3 stage 2b: the comparison table's ay rows — the same front-end
    instance, one calibration shared by both, floors read per payload
    constellation, the cap by the EDMG limits at its highest rate under the
    be rows' rule (the floor assumed.mcs_evm_margin_db under the limit; iron
    rule 2), and the power blocks with no decoder counted."""
    from mmw60 import compare
    from mmw60.config import zero_if_60ghz
    fe = Frontend60.from_config(zero_if_60ghz(k=8))
    rep = compare.build([s for s in compare.scheme_matrix(ks=(8,)) if s.status == "built"
                         and s.waveform in ("ay_ofdm", "ay_sc")], fe, time_domain=False)
    by = {r["waveform"]: r for r in rep["ay_rows"]}
    assert set(by) == {"ay_sc", "ay_ofdm"} and not rep["rows"]
    for wf, r in by.items():
        assert r["frontend_id"] == id(fe) and r["cfo_captured"] and r["channel"] == 2
        assert set(r["floor_cal_db"]) == {e.tone_order for e in edmg.mcs_table(wf)}
        assert all(r["floor_cal_db"][o] < r["floor_raw_db"][o] - 10 for o in r["floor_cal_db"])
        assert r["cap_margin_db"] == spec.value("assumed.mcs_evm_margin_db") > 0
        cap = edmg.mcs_entry(wf, r["cap_cal"])
        assert r["floor_cal_db"][cap.tone_order] <= cap.evm_limit_db - r["cap_margin_db"]
        assert r["rate_cal_mbps"] == pytest.approx(cap.rate_bps() / 1e6)
        # no faster MCS passes the same rule; without the margin (example 15's reading) one does
        fl = r["floor_cal_db"]
        assert not [e for e in edmg.mcs_table(wf) if fl[e.tone_order] <= e.evm_limit_db - r["cap_margin_db"]
                    and e.rate_bps() > cap.rate_bps()]
        assert r["rate_cal_at_limit_mbps"] > r["rate_cal_mbps"]
        p = r["power_cal"]
        assert "decoder" not in p["blocks"] and any("decoder" in o for o in p["omitted"])
        assert p["pj_per_bit"] == pytest.approx(sum(b["pj_per_bit"] for b in p["blocks"].values()), rel=1e-6)
    # the preset back-off: single carrier's lower floor reaches a faster MCS than OFDM's
    assert by["ay_sc"]["rate_cal_mbps"] > by["ay_ofdm"]["rate_cal_mbps"]
    assert "802.11ay rows" in compare.to_markdown(rep)


def test_the_edmg_thresholds_come_from_the_dmg_twin_and_take_the_reference_receiver_out():
    """assumed.ay_sensitivity: an EDMG MCS takes the minimum sensitivity of
    the DMG MCS with the same bits per symbol, code rate and repetition, less
    kT·B over the occupied bandwidth and the reference receiver's NF and
    implementation loss; no twin, no threshold.  SC looks in dmg.sc_mcs and
    then in the extended MCS 9.1 / 12.1–12.6 (spec_sources#33)."""
    from fractions import Fraction

    from mmw60.vendor.wifitrx.units import KT_DBM_HZ
    sc = [edmg.dmg_twin("ay_sc", m) for m in (1, 2, 6, 7, 11, 12, 14, 15, 16, 17, 18, 21)]
    assert sc == [1, 2, None, 6, 9.1, 10, 12, 12.1, 12.2, None, 12.3, 12.6]
    ofdm = [edmg.dmg_twin("ay_ofdm", m) for m in (1, 2, 3, 6, 8, 9, 13, 16, 17, 19, 20)]
    assert ofdm == [13, 14, None, 15, 17, None, 20, None, 22, 24, None]
    of_t = spec.value("dmg.ofdm_mcs")
    for e in edmg.mcs_table("ay_sc"):
        twin = edmg.dmg_twin("ay_sc", e.mcs)
        if twin is not None:
            sc_t = spec.value("dmg.sc_mcs" if twin in spec.value("dmg.sc_mcs")["mcs"] else "dmg.sc_mcs_extended")
            i = sc_t["mcs"].index(twin)
            # the same block (448 data chips at normal GI) and the same bits: the same rate
            assert Fraction(sc_t["code_rate"][i]) == e.code_rate and sc_t["repetition"][i] == e.repetition
            assert e.rate_bps() == pytest.approx(sc_t["rate_mbps"][i] * 1e6, rel=1e-3)
    for e in edmg.mcs_table("ay_ofdm"):
        twin = edmg.dmg_twin("ay_ofdm", e.mcs)
        if twin is not None:
            i = of_t["mcs"].index(twin)
            # matched on bits per subcarrier, the twins carry the names edmg.ofdm_mcs's note gives: DCM BPSK /
            # DCM QPSK were 11ad's SQPSK / QPSK
            assert Fraction(of_t["code_rate"][i]) == e.code_rate
            assert of_t["modulation"][i] == {"DCM BPSK": "SQPSK", "DCM QPSK": "QPSK"}.get(e.modulation, e.modulation)
    ref = spec.value("dmg.sensitivity_assumptions")
    t = edmg.ideal_threshold_db("ay_sc", 14, 1.76e9)
    want = spec.ref("dmg.rx_sensitivity_dbm#dbm@mcs=12") - KT_DBM_HZ - 10 * np.log10(1.76e9) - ref["nf_db"] \
        - ref["implementation_loss_db"]
    assert t == pytest.approx(want) and 13.0 < t < 14.0
    assert edmg.ideal_threshold_db("ay_sc", 14, 1.76e9, keep_implementation_loss=True) == pytest.approx(
        t + ref["implementation_loss_db"])
    assert edmg.ideal_threshold_db("ay_sc", 17, 1.76e9) is None and edmg.ideal_threshold_db("ay_sc", 6, 1.76e9) is None
    # within a modulation the threshold rises with the code rate
    for wf in edmg.WAVEFORMS:
        for o in {e.order for e in edmg.mcs_table(wf)}:
            ts = [edmg.ideal_threshold_db(wf, e.mcs, 1.8e9) for e in edmg.mcs_table(wf)
                  if e.order == o and e.repetition == 1 and edmg.dmg_twin(wf, e.mcs) is not None]
            assert ts == sorted(ts)


def test_the_ay_range_is_the_be_budget_with_the_decoder_threshold():
    """arraylink.ay_mcs_ranges: the floor as a noise term over the threshold
    (SC: every MCS measured, MCS 1 through its rho = 2 codeword; ``source`` says which), the
    receiver input from the shared front end's NF at the AGC state, the path
    loss EIRP + G_rx − input, the distance by ``range_m``; a floor the
    decoder cannot carry has no range; the TX EVM limit is reported."""
    from mmw60 import arraylink as al
    cfg = dc.replace(ay_60ghz("ay_sc", 1), channel=FLAT)
    fe = Frontend60.from_config(cfg)
    sim = LinkSim(cfg, frontend=fe)
    clean = {o: -60.0 for o in (2, 4, 16, 64)}
    r = al.ay_mcs_ranges(sim, clean, eirp_dbm=10.0, g_rx_db=3.0, oxygen_db_km=0.0)
    assert set(r) == {e.mcs for e in edmg.mcs_table("ay_sc")}
    assert {r[m]["source"] for m in r} == {"measured"} and set(r) == {e.mcs for e in edmg.mcs_table("ay_sc")}
    x = r[14]
    assert x["threshold_db"] == spec.ay_per_threshold_db("ay_sc", 14)
    assert x["req_db"] == pytest.approx(x["threshold_db"], abs=0.01)
    assert x["sens_dbm"] == pytest.approx(sim.rx_input_dbm_for_snr(x["req_db"]))
    assert x["pl_db"] == pytest.approx(13.0 - x["sens_dbm"])
    assert x["range_m"] == pytest.approx(al.range_m(x["pl_db"], cfg.carrier_hz, 0.0))
    assert all(v["conforms"] for v in r.values())
    # the slowest MCS reaches farthest; each MCS's range shrinks as its floor rises
    assert max(r, key=lambda m: r[m]["range_m"]) == 1
    worse = al.ay_mcs_ranges(sim, {**clean, 16: -16.0}, eirp_dbm=10.0, g_rx_db=3.0, oxygen_db_km=0.0)
    assert worse[14]["range_m"] < x["range_m"] and not worse[14]["conforms"]
    assert al.ay_mcs_ranges(sim, {**clean, 16: -10.0}, 10.0, 3.0)[14]["range_m"] is None
    # the twin rule (assumed.ay_sensitivity) everywhere; with its implementation loss kept in, that costs
    # 5 dB of path loss: the free-space distance x 10^(-5/20)
    tw = al.ay_mcs_ranges(sim, clean, 10.0, 3.0, oxygen_db_km=0.0, rule="twin")
    assert set(tw) == {e.mcs for e in edmg.mcs_table("ay_sc") if edmg.dmg_twin("ay_sc", e.mcs) is not None}
    assert {v["source"] for v in tw.values()} == {"twin"} and tw[14]["range_m"] < x["range_m"]
    il = al.ay_mcs_ranges(sim, clean, 10.0, 3.0, keep_implementation_loss=True, oxygen_db_km=0.0, rule="twin")
    loss = spec.value("dmg.sensitivity_assumptions")["implementation_loss_db"]
    assert il[14]["range_m"] == pytest.approx(tw[14]["range_m"] * 10 ** (-loss / 20), rel=0.02)


def test_the_ay_operating_point_is_the_preset_rule_on_its_own_envelope():
    """assumed.ay_operating_point: the PA alone on the waveform's 16-QAM payload
    reaches the preset rule's EVM limit at the returned back-off; the single
    carrier's lower PAPR gives it a much smaller back-off than OFDM's, which
    sits near the preset."""
    from mmw60 import arraylink as al
    from mmw60.frontend.grid import operating_rule_evm_limit_db
    fe = Frontend60.from_config(ay_60ghz("ay_sc", 1))
    lim = operating_rule_evm_limit_db()
    own = {wf: al.ay_operating_obo_db(ay_60ghz(wf, 1)) for wf in edmg.WAVEFORMS}
    for wf, ob in own.items():
        assert al.ay_pa_alone_evm_db(ay_60ghz(wf, 1), ob) <= lim < al.ay_pa_alone_evm_db(ay_60ghz(wf, 1), ob - 0.1)
    assert own["ay_sc"] < fe.obo_db - 2.0 and abs(own["ay_ofdm"] - fe.obo_db) < 1.0


def test_the_ay_array_budget_runs_on_the_shared_instance_with_the_be_rule():
    """arraylink.ay_array_budget: the same array and front end as the be rows;
    every element at the operating point until the EIRP limit binds, then all
    back off together and the chain is calibrated anew at that back-off; the
    decoder cap is the be rows' rule over the assumed thresholds; the power
    report prices the cap's rate with N PAs and the phase shifters."""
    from mmw60 import arraylink as al
    from mmw60.config import array_frontend, zero_if_60ghz
    from mmw60.frontend.array60 import Array60
    fe = Frontend60.from_config(zero_if_60ghz(k=8))
    cfg = ay_60ghz("ay_sc", 1)
    cache = {}
    b = {}
    for n in (1, 64):
        cn = array_frontend(cfg, n)
        ar = Array60.from_config(cn, fe)
        b[n] = (cn, ar, al.ay_array_budget(cn, fe, ar, "sc", cal_cache=cache))
    one, big = b[1][2], b[64][2]
    assert one.p_elem_dbm == pytest.approx(fe.target_pout_dbm()) and one.obo_db == pytest.approx(fe.obo_db)
    assert big.eirp_dbm == pytest.approx(fe.eirp.avg_dbm) and big.obo_db > fe.obo_db
    assert len(cache) == 2                          # one calibration per per-element back-off
    margin = spec.value("assumed.decoder_cap_margin_db")
    for x in (one, big):
        cap = x.dec_mcs
        t, _ = edmg.threshold_db("ay_sc", cap, x.occupied_bw_hz)
        assert -x.floor_by_order[edmg.mcs_entry("ay_sc", cap).tone_order] >= t + margin
        assert x.floor_db == x.floor_by_order[edmg.mcs_entry("ay_sc", cap).tone_order]
        assert set(x.range_by_mcs) <= set(x.rate_by_mcs) and cap in x.range_by_mcs
    # the array's gain buys distance; the back-off at the limit lowers the floor
    assert big.range_by_mcs[1] > 50 * one.range_by_mcs[1] and big.floor_db < one.floor_db
    cn64, ar64, _ = b[64]
    rp = al.array_power_report(cn64, fe, ar64, big)
    assert rp.bit_rate == pytest.approx(big.rate_by_mcs[big.dec_mcs])
    assert rp.watts("phase_shifters") > 0 and "decoder" not in {blk.name for blk in rp.blocks}


def test_the_sc_mmse_reads_the_noise_on_the_channel_estimates_scale():
    """Under multipath the unbiased MMSE beats zero forcing at a moderate SNR;
    on a flat channel the two agree.  Regression (2026-11-16): the MMSE took
    1/SNR as the noise while the estimate carries the chain's gain, sixteen
    times too much regularisation, and under multipath it read worse than ZF."""
    cr = ChannelConfig()                     # the CR stand-in (assumed.cr_rms_delay_ns / cr_los_k_db)

    def mean_evm(cfg, n=8):
        sim = LinkSim(cfg)
        rng = np.random.default_rng(1)
        e = np.asarray([sim.packet(12.0, rng).rx.evm_db for _ in range(n)])
        return float(10 * np.log10(np.mean(10 ** (e / 10))))
    mp = {eq: mean_evm(dc.replace(_ideal("ay_sc", 16, sc_equalizer=eq), channel=cr)) for eq in ("mmse", "zf")}
    flat = {eq: mean_evm(_ideal("ay_sc", 16, sc_equalizer=eq)) for eq in ("mmse", "zf")}
    assert mp["mmse"] < mp["zf"] - 0.1, mp
    assert abs(flat["mmse"] - flat["zf"]) < 0.1, flat
    base = ay_60ghz("ay_sc", 16)
    with pytest.raises(ValueError, match="sc_equalizer"):
        dc.replace(base, ay=dc.replace(base.ay, sc_equalizer="lms"))


def test_the_sector_sweep_threshold_is_the_control_phys_with_the_reference_receiver_out():
    """assumed.ay_sector_sweep: the SSW frame's threshold is DMG MCS 0's
    sensitivity less kT·B and the reference receiver, the same rule as the
    data MCS; the control PHY's spreading puts it below every data MCS's."""
    from mmw60.vendor.wifitrx.units import KT_DBM_HZ
    ref = spec.value("dmg.sensitivity_assumptions")
    t = edmg.control_threshold_db(1.76e9)
    want = (spec.ref("dmg.rx_sensitivity_dbm#dbm@mcs=0") - KT_DBM_HZ - 10 * np.log10(1.76e9) - ref["nf_db"]
            - ref["implementation_loss_db"])
    assert t == pytest.approx(want) and t < -10.0
    assert edmg.control_threshold_db(1.76e9, keep_implementation_loss=True) == pytest.approx(
        t + ref["implementation_loss_db"])
    data = [edmg.ideal_threshold_db(wf, e.mcs, 1.76e9) for wf in edmg.WAVEFORMS for e in edmg.mcs_table(wf)]
    assert t < min(x for x in data if x is not None) - 8.0
    # the data MCS go through the same function: one rule
    assert edmg.ideal_threshold_db("ay_sc", 14, 1.76e9) == edmg.dmg_threshold_db(12, 1.76e9)
    # how long a sweep lasts (spec_sources#33, #43): a control PHY PPDU per sector, SBIFS apart; the
    # PPDU's codewords by dmg.control_phy_encoding, every coded bit 32 chips at 1.76 GHz
    from mmw60 import arraylink as al
    from mmw60.frontend.array60 import Array60
    e = spec.value("dmg.control_phy_encoding")
    cw = al.control_phy_codewords(e["example_length"])  # the original's example: 120 octets
    assert len(cw) == e["example_n_cw"] and cw[1] == e["example_l_dpcw"] and cw[-1] == e["example_l_dplcw"]
    for n in range(14, 1024):  # codeword by codeword = the closed form (Length + 5)*8 + 168*N_CW
        cw = al.control_phy_codewords(n)
        assert cw[0] == 88 and max(cw) <= 168 and sum(cw) == 8 * (n + 5)
        assert sum(d + 168 for d in cw) == (n + 5) * 8 + 168 * (1 + -(-(n - 6) * 8 // 168))
    with pytest.raises(ValueError):
        al.control_phy_codewords(13)
    # the preamble in chips agrees with the timing table's rounded figure (4.291 us since #43)
    assert spec.value("dmg.phy_timing")["control_preamble_s"] == pytest.approx((6400 + 1152) / 1.76e9, abs=5e-10)
    frame = (6400 + 1152 + (26 + 5) * 8 * 32 + 2 * 168 * 32) / 1.76e9  # the 26-octet SSW frame: 2 codewords
    assert al.ssw_frame_s() == pytest.approx(frame, rel=1e-12)
    assert al.ssw_frame_s() == pytest.approx(14.909e-6, abs=1e-9)
    cfg = ay_60ghz("ay_sc", 14)
    cfg = dc.replace(cfg, frontend=dc.replace(cfg.frontend, array=dc.replace(cfg.frontend.array, tx_nx=16, rx_nx=16)))
    ar = Array60.from_config(cfg, Frontend60.from_config(cfg))
    n = ar.codebook_deg("tx").size
    assert n > 1 and al.ay_sweep_time_s(ar, "tx") == pytest.approx(n * (frame + 1e-6), rel=1e-12)


def test_the_coded_sc_path_with_an_80211_code_standing_in():
    """ay.coding (section 9d): whole codewords on the SC payload, max-log LLRs
    from the equalised chips, normalised min-sum, packet error = any info bit
    wrong.  The DMG / EDMG matrices wait for spec_sources#33, so an 802.11
    code stands in; ``qc_code`` lifts any base matrix as ``code`` does."""
    from mmw60.ay import coding
    from mmw60.phy import ldpc
    ref = ldpc.code(648, "1/2")
    again = ldpc.qc_code(spec.ldpc_base_matrices()[648]["1/2"], 27, "1/2")
    assert np.array_equal(ref.edge_row, again.edge_row) and np.array_equal(ref.edge_col, again.edge_col)
    with pytest.raises(ValueError, match="rate"):
        ldpc.qc_code(spec.ldpc_base_matrices()[648]["1/2"], 27, "3/4")
    sim = LinkSim(_ideal("ay_sc", 7, model="behavioural", units=4))           # π/2-QPSK 1/2
    assert coding.payload_bits(sim) == 4 * 448 * 2
    clean = coding.coded_sc_packet(sim, ref, None, np.random.default_rng(0))
    assert clean["codewords"] == 5 and not clean["packet_error"] and clean["bit_errors"] == 0
    assert coding.per(sim, ref, -3.0, 6, np.random.default_rng(1)) == 1.0
    assert coding.per(sim, ref, 6.0, 6, np.random.default_rng(1)) == 0.0
    # the transmitter carries exactly the bits handed in, DCM included
    with pytest.raises(ValueError, match="carries"):
        sim.transmit(np.random.default_rng(0), bits=np.zeros(10, dtype=np.uint8))
    for m in (13, 6):
        with pytest.raises(ValueError, match="carries"):
            LinkSim(_ideal("ay_ofdm", m, model="behavioural")).transmit(np.random.default_rng(0), bits=np.zeros(8))


def test_the_dmg_and_edmg_codes_are_spec_sources_matrices_and_agree_with_each_other():
    """spec_sources#33 (iron rule 5): the four DMG codes from dmg.ldpc_matrices
    (672 bits, z = 42); DMG's 7/8 is the 13/16 codeword with its first 48
    parity bits not sent (624 / 546), EDMG's 7/8 its own 672-bit code (588
    information bits, two shifted identities in most cells), which is DMG's
    3/4 with block rows 1 + 3 and 2 + 4 added (the cross-check spec_sources
    ran).  Every code encodes to a zero syndrome and decodes clean words."""
    from mmw60.ay import coding
    from mmw60.phy import ldpc

    def dense(c):
        h = np.zeros((c.m, c.n), dtype=np.uint8)
        h[c.edge_row, c.edge_col] = 1
        return h

    for rate, rows in (("1/2", 8), ("5/8", 6), ("3/4", 4), ("13/16", 3)):
        c = coding.dmg_code(rate)
        assert (c.n, c.m, c.base.shape) == (672, 42 * rows, (rows, 16)) and coding.edmg_code(rate) is c
        assert np.array_equal(c.base, spec.value("dmg.ldpc_matrices")["r" + rate.replace("/", "_")])
    p, e = coding.dmg_code("7/8"), coding.edmg_code("7/8")
    assert (p.n, p.k, p.rate) == (624, 546, "7/8") and p.drop == tuple(range(546, 594))
    assert (e.n, e.k) == (672, 588) and e.base.dtype == object and len(e.base[0, 0]) == 2
    h34, h78 = dense(coding.dmg_code("3/4")), dense(e)
    assert np.array_equal(h78[:42], h34[:42] ^ h34[84:126]) and np.array_equal(h78[42:], h34[42:84] ^ h34[126:])
    rng = np.random.default_rng(3)
    for rate in ("1/2", "5/8", "3/4", "13/16", "7/8"):
        for c in (coding.dmg_code(rate), coding.edmg_code(rate)):
            info = rng.integers(0, 2, (2, c.k), dtype=np.uint8)
            word = c.encode(info)
            mother = getattr(c, "mother", c)
            assert not mother.syndrome(mother.encode(info)).any()
            assert np.array_equal(word[:, :c.k], info) and word.shape == (2, c.n)
            dec, _ = c.decode(4.0 * (1.0 - 2.0 * word))           # LLR > 0 is a 0
            assert np.array_equal(dec, word), rate
    # a cell with two equal shifts would cancel over GF(2): refused
    with pytest.raises(ValueError, match="distinct"):
        ldpc.qc_code([[[3, 3]] + [-1] * 15], 42, "15/16")
    # the code of an SC MCS: EDMG's at its rate; MCS 1 (repetition 2) the rho = 2 codeword on the 1/2 code
    assert coding.sc_code(LinkSim(_ideal("ay_sc", 16, model="behavioural"))) is e
    assert coding.sc_code(LinkSim(_ideal("ay_sc", 1, model="behavioural"))) is coding.rho2_code()


def test_the_measured_edmg_thresholds_are_tagged_complete_and_rise_with_the_code_rate():
    """data/spec/ay_per_thresholds.yaml (tools/measure_ay_thresholds.py):
    every EDMG MCS measured with spec_sources#33's codes — SC MCS 1 through
    the rho = 2 codeword, OFDM's DCM through the static pairing (both
    spec_sources#43) — above the Shannon bound of its bits per chip or tone,
    rising with the code rate within a modulation; the preset rule takes
    them all (the DMG twin's stays the rule="twin" reading)."""
    doc = spec.ay_per_threshold_document()
    assert doc["source"] == "derived" and "measure_ay_thresholds.py" in doc["cite"] and doc["note"]
    assert doc["packet_bytes"] == 4096 and doc["target_per"] == 1e-2
    assert set(doc["thresholds_db"]) == {"ay_sc", "ay_ofdm"}
    for wf in ("ay_sc", "ay_ofdm"):
        t, ci = doc["thresholds_db"][wf], doc["ci_db"][wf]
        coded = list(edmg.mcs_table(wf))
        assert set(t) == {e.mcs for e in coded} and all(t[e.mcs] is not None for e in coded), wf
        for e in coded:
            eta = float(e.code_rate) * np.log2(e.order) / e.repetition
            assert t[e.mcs] > 10 * np.log10(2 ** eta - 1), (wf, e.mcs)
            assert ci[e.mcs][0] <= t[e.mcs] <= ci[e.mcs][1] and ci[e.mcs][1] - ci[e.mcs][0] < 0.5, (wf, e.mcs)
        for order in sorted({e.order for e in coded}):
            row = [t[e.mcs] for e in coded if e.order == order and e.repetition == 1]
            assert row == sorted(row), (wf, order)
    t = doc["thresholds_db"]["ay_sc"]
    assert t[1] < t[2]                          # repetition 2 at 1/2 (rate 1/4) needs less than plain 1/2
    assert edmg.threshold_db("ay_sc", 14, 1.76e9) == (t[14], "measured")
    assert edmg.threshold_db("ay_sc", 14, 1.76e9, rule="twin") == (edmg.ideal_threshold_db("ay_sc", 14, 1.76e9), "twin")
    assert edmg.threshold_db("ay_sc", 1, 1.76e9) == (t[1], "measured")
    assert edmg.threshold_db("ay_ofdm", 6, 1.8e9) == (doc["thresholds_db"]["ay_ofdm"][6], "measured")
    assert edmg.threshold_db("ay_ofdm", 13, 1.8e9) == (doc["thresholds_db"]["ay_ofdm"][13], "measured")
    assert edmg.threshold_db("ay_sc", 17, 1.76e9) == (t[17], "measured")      # no DMG twin: measured only
    assert edmg.threshold_db("ay_sc", 17, 1.76e9, rule="twin") == (None, None)
    with pytest.raises(ValueError, match="rule"):
        edmg.threshold_db("ay_sc", 14, 1.76e9, rule="best")


def test_one_measured_edmg_sc_threshold_reproduces_from_the_code():
    """The file is this code's measurement: 1 dB under the recorded
    threshold of SC MCS 14 (π/2-16-QAM 3/4) the link fails, 1 dB over it it
    holds, through per_sweep's packet hook."""
    from mmw60.ay import coding
    from mmw60.sim.link import per_sweep
    t = spec.ay_per_threshold_db("ay_sc", 14)
    sw = per_sweep(coding.threshold_config(14), [t - 1.0, t + 1.0], max_packets=40, min_errors=8, seed=5,
                   packet=coding.sweep_packet)
    assert sw["per"][0] > 0.5 and sw["per"][1] < 0.05, (t, sw["per"])


def test_the_coded_ofdm_path_puts_the_codewords_on_the_data_tones_in_order():
    """ay.coding on OFDM (assumed.ay_ofdm_tone_order): the 16-QAM / 64-QAM MCS
    carry whole 672-bit codewords on the data tones of every symbol in
    order, the DCM MCS through ay.dcm.  Clean packets decode; −3 dB loses
    them all; the bits the receiver equalises are the bits sent, tone for
    tone."""
    from mmw60.ay import coding
    from mmw60.phy.mapper import map_bits
    sim = LinkSim(_ideal("ay_ofdm", 13, model="behavioural", units=6))      # 16-QAM 3/4
    n_data = len(sim.phy.num.data_tones)
    assert coding.payload_bits(sim) == 6 * n_data * 4 and coding.ay_code(sim) is coding.edmg_code("3/4")
    rng = np.random.default_rng(0)
    bits = rng.integers(0, 2, coding.payload_bits(sim)).astype(np.uint8)
    ref, _ = sim.transmit(np.random.default_rng(1), bits=bits)
    assert np.allclose(ref.symbols.reshape(-1), map_bits(bits, 16))         # symbol after symbol, tones ascending
    code = coding.ay_code(sim)
    clean = coding.coded_packet(sim, code, None, np.random.default_rng(2))
    assert clean["codewords"] == coding.payload_bits(sim) // 672 and not clean["packet_error"]
    assert coding.per(sim, code, -3.0, 4, np.random.default_rng(3)) == 1.0
    assert coding.per(sim, code, 30.0, 4, np.random.default_rng(3)) == 0.0
    from mmw60.ay import dcm
    for m, nb in ((1, 1), (6, 2), (10, 2)):                                   # DCM BPSK 1/2, DCM QPSK 1/2, 7/8
        sd = LinkSim(_ideal("ay_ofdm", m, model="behavioural", units=4))
        assert coding.payload_bits(sd) == 4 * n_data * nb
        b = rng.integers(0, 2, coding.payload_bits(sd)).astype(np.uint8)
        r, _ = sd.transmit(np.random.default_rng(1), bits=b)
        assert np.allclose(r.symbols, dcm.map_bits(b, nb, n_data))
        clean = coding.coded_packet(sd, coding.ay_code(sd), None, np.random.default_rng(2))
        assert clean["codewords"] >= 1 and not clean["packet_error"], m
    # the thresholds' chain holds a 4096-byte PSDU in whole codewords, no more OFDM symbols than needed
    cfg = coding.threshold_config(16, waveform="ay_ofdm")
    s16 = LinkSim(cfg)
    need = coding.codewords_for(4096, coding.ay_code(s16)) * 672
    assert coding.payload_bits(s16) >= need > coding.payload_bits(s16) - n_data * 6


def test_the_dcm_mapping_is_edmg_ofdm_modulation_mappings_and_its_demapper_uses_both_tones():
    """ay.dcm (edmg.ofdm_modulation_mapping, spec_sources#43): DCM BPSK puts
    (x0 + j x1)/sqrt(2) on data tone k and (x0 - j x1)/sqrt(2) on P(k) =
    k + N_SD/2; DCM QPSK puts (x0 + 2 x1)/sqrt(5) and (-2 x0 + x1)/sqrt(5),
    x0 / x1 the QPSK points of bits (c0, c2) / (c1, c3).  Unit power, the tone
    constellations QPSK and 16-QAM (the MCS table's tone_order).  The joint
    demapper recovers every bit from either tone of a pair: with one tone
    of every pair erased (weight 0, buried in noise) the hard decisions
    still match — the frequency diversity DCM is for."""
    from mmw60.ay import dcm
    from mmw60.phy.mapper import constellation
    assert "P(k) = k + N_SD/2" in spec.value("edmg.ofdm_modulation_mapping")["stp"]
    k, pk = dcm.pairs(336)
    assert np.array_equal(k, np.arange(168)) and np.array_equal(pk, np.arange(168, 336))
    rng = np.random.default_rng(7)
    for nb, tone_order in ((1, 4), (2, 16)):
        b = rng.integers(0, 2, 3 * 336 * nb)
        x = dcm.map_bits(b, nb, 336)
        assert x.shape == (3, 336) and np.mean(np.abs(x) ** 2) == pytest.approx(1.0)
        pts, _ = constellation(tone_order)
        assert set(np.round(np.unique(np.round(x, 9)), 9)) <= set(np.round(pts, 9))
        c = b.reshape(3 * 168, 2 * nb)
        dk, dp = x[:, k].reshape(-1), x[:, pk].reshape(-1)
        s = 2 * c - 1
        if nb == 1:
            assert np.allclose(dk, (s[:, 0] + 1j * s[:, 1]) / np.sqrt(2)) and np.allclose(dp, np.conj(dk))
        else:
            x0, x1 = (s[:, 0] + 1j * s[:, 2]) / np.sqrt(2), (s[:, 1] + 1j * s[:, 3]) / np.sqrt(2)
            assert np.allclose(dk, (x0 + 2 * x1) / np.sqrt(5)) and np.allclose(dp, (-2 * x0 + x1) / np.sqrt(5))
        assert np.array_equal(dcm.llr(x, nb, 336) < 0, b.astype(bool))          # LLR > 0 is a 0
        for gone in (pk, k):                                                     # erase either tone of every pair
            z = x.copy()
            z[:, gone] = 10.0 * (rng.standard_normal((3, gone.size)) + 1j * rng.standard_normal((3, gone.size)))
            w = np.ones((3, 336))
            w[:, gone] = 0.0
            assert np.array_equal(dcm.llr(z, nb, 336, w) < 0, b.astype(bool)), (nb, gone[0])
    with pytest.raises(ValueError, match="even"):
        dcm.pairs(335)
    with pytest.raises(ValueError, match="whole number"):
        dcm.map_bits(np.zeros(10), 1, 336)


def test_the_sc_mcs1_repetition_is_dmg_data_encodings_rho2_codeword():
    """dmg.data_encoding's rho = 2 (spec_sources#43, sc_rho2_codeword /
    sc_rho2_pn): 168 data bits b, the rate-1/2 672-bit code over (b, 168
    zeros), the zeros then replaced by b XOR PN — the data scrambler's
    sequence from the all-ones state (802.11's 0000111011110010...), the
    same 168 bits in every codeword.  The mother word (b, 0, parity) has a
    zero syndrome; the receiver adds the two copies and knows the zeros, so
    either copy alone decodes, and a PSDU of 4096 octets takes
    ceil(4096 * 8 / 168) = 196 codewords (dmg.data_encoding's sc_n_cw)."""
    from mmw60.ay import coding
    from mmw60.phy.scrambler import scrambling_sequence
    enc = spec.value("dmg.data_encoding")
    assert "all ones" in enc["sc_rho2_pn"] and "XOR PN" in enc["sc_rho2_codeword"]
    c = coding.rho2_code()
    assert (c.n, c.k, c.rate) == (672, 168, "1/4") and c.mother is coding.dmg_code("1/2")
    assert np.array_equal(c.pn, scrambling_sequence(168, seed=0x7F))
    assert "".join(map(str, c.pn[:16])) == "0000111011110010"
    rng = np.random.default_rng(11)
    info = rng.integers(0, 2, (4, 168), dtype=np.uint8)
    w = c.encode(info)
    assert np.array_equal(w[:, :168], info) and np.array_equal(w[:, 168:336], info ^ np.asarray(c.pn, np.uint8))
    mother_word = w.copy()
    mother_word[:, 168:336] = 0
    assert not c.mother.syndrome(mother_word).any()
    llr = 4.0 * (1.0 - 2.0 * w)
    for gone in (slice(0, 168), slice(168, 336)):                 # either copy alone carries the data
        x = llr.copy()
        x[:, gone] = 0.0
        dec, _ = c.decode(x)
        assert np.array_equal(dec[:, :168], info), gone
    assert coding.codewords_for(4096, c) == 196
