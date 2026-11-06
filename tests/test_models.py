"""Upclocking arithmetic, the Rapp PA, the pole-zero phase noise, the CFO
estimators, the channels and the in-band SNR definition."""
import numpy as np
import pytest

from mmw60 import spec
from mmw60.channel import ExponentialTdl, FlatChannel, TapTableChannel, make_channel
from mmw60.config import liu2025_table2
from mmw60.impairments.noise import add_awgn_per_tone, per_sample_snr_offset_db
from mmw60.impairments.phase_noise import PoleZeroPhase, lo_phase
from mmw60.pa.rapp import ModifiedRappPA, apply_pa_at_obo, drive_for_obo
from mmw60.rx.cfo import ltf_fine_cfo, ltf_integer_cfo, stf_coarse_cfo
from mmw60.sim.link import LinkSim


# ---------------------------------------------------------------- upclock
@pytest.mark.parametrize("k", [1, 4, 8, 16, 32])
def test_upclock_scales_every_physical_quantity(k):
    p = liu2025_table2(k=k, mcs=0).upclocked()
    assert p.fs_eff == pytest.approx(40e6 * k) and p.scs_eff == pytest.approx(312.5e3 * k)
    assert p.t_fft_eff == pytest.approx(3.2e-6 / k) and p.t_gi_eff == pytest.approx(0.8e-6 / k)
    assert p.stf_capture_hz == pytest.approx(spec.value("liu2025.stf_capture_hz") * k)
    assert p.ltf_capture_hz == pytest.approx(spec.value("liu2025.ltf_capture_hz") * k)
    assert p.stf_period_samples == 32          # 0.8 µs at the 40 MS/s base clock, whatever K


def test_upclock_threshold_is_the_stf_capture_range():
    cfo = spec.value("derived.cfo_liu2025_hz")
    assert liu2025_table2(k=4).upclocked().stf_capture_hz < cfo < liu2025_table2(k=8).upclocked().stf_capture_hz
    assert liu2025_table2(k=16).upclocked().ltf_capture_hz < cfo     # LTF alone never catches it
    with pytest.raises(ValueError):
        liu2025_table2(k=0)


# ---------------------------------------------------------------- Rapp PA
def test_rapp_am_am_is_monotonic_and_saturates():
    pa = ModifiedRappPA()
    a = np.logspace(-4, 2, 2000)
    g = pa.am_am(a)
    assert np.all(np.diff(g) > 0) and g[-1] == pytest.approx(pa.a_sat, rel=1e-3)
    assert pa.am_am(np.array([1e-4]))[0] / 1e-4 == pytest.approx(pa.g, rel=1e-3)
    assert pa.p_sat == pa.a_sat ** 2
    assert ModifiedRappPA(ampm=False).am_pm_deg(np.array([0.1, 0.3])).tolist() == [0.0, 0.0]


def test_rapp_p1db_is_the_derived_distance_below_psat():
    pa = ModifiedRappPA()
    assert 10 * np.log10(pa.p_sat / pa.p1db) == pytest.approx(
        spec.value("derived.rapp_p1db_below_psat_db"), abs=0.1)


def test_obo_solver_hits_its_target_for_both_references():
    rng = np.random.default_rng(0)
    x = (rng.standard_normal(5000) + 1j * rng.standard_normal(5000)) / np.sqrt(2)
    pa = ModifiedRappPA()
    for ref in ("psat", "p1db"):
        y, info = apply_pa_at_obo(pa, x, 8.0, ref)
        assert info[f"obo_{ref}_db"] == pytest.approx(8.0, abs=1e-3)
        assert y.shape == x.shape
    assert drive_for_obo(pa, x, 8.0, reference="p1db") < drive_for_obo(pa, x, 8.0, reference="psat")
    assert info["nmse_db"] < -20              # P1dB-referenced: mild compression


# ---------------------------------------------------------------- phase noise
def test_pole_zero_profile_asymptotes_and_synthesis_power():
    pn = PoleZeroPhase(psd0_dbchz=-93, f_pole_hz=1e6, f_zero_hz=100e6)
    assert pn.l_dbc(np.array([1e3]))[0] == pytest.approx(-93, abs=0.01)
    assert pn.l_dbc(np.array([10e6]))[0] == pytest.approx(-113, abs=0.1)
    assert pn.l_dbc(np.array([1e10]))[0] == pytest.approx(pn.floor_dbchz, abs=0.05)
    assert pn.floor_dbchz == pytest.approx(-133)
    fs, n = 320e6, 1 << 18
    phi = lo_phase(pn, n, fs, np.random.default_rng(0))
    expect = pn.integrated_rad2(fs / n, fs / 2)
    assert np.var(phi) == pytest.approx(expect, rel=0.2)
    assert not lo_phase(None, 10, fs, np.random.default_rng(0)).any()


# ---------------------------------------------------------------- CFO estimators
def _rx_at(k, snr=30.0, seed=1):
    sim = LinkSim(liu2025_table2(k=k, mcs=0).ideal().with_(xo_ppm_tx=20, xo_ppm_rx=20))
    field, frame = sim.transmit(np.random.default_rng(seed))
    y, _, _ = sim.impair(frame.x, np.random.default_rng(seed + 1), snr)
    return sim, frame, y


def test_stf_estimator_is_unbiased_inside_its_range_and_aliases_outside():
    for k, inside in ((8, True), (16, True), (4, False)):
        sim, frame, y = _rx_at(k)
        f = stf_coarse_cfo(y, sim.phy.stf_period_samples, 10, sim.phy.fs_eff)
        true = sim.cfo.cfo_hz
        if inside:
            assert abs(f - true) < 0.02 * sim.phy.scs_eff
        else:
            assert abs(f - (true - 2 * sim.phy.stf_capture_hz)) < 0.05 * sim.phy.scs_eff


def test_extended_estimator_resolves_the_integer_part_at_k4():
    sim, frame, y = _rx_at(4)
    f_frac = ltf_fine_cfo(y, frame, sim.phy.fs_eff)
    from mmw60.rx.cfo import correct
    y2 = correct(y, f_frac, sim.phy.fs_eff)
    m = ltf_integer_cfo(y2, frame, 8)
    assert m == 2
    assert f_frac + m * sim.phy.scs_eff == pytest.approx(sim.cfo.cfo_hz, abs=0.02 * sim.phy.scs_eff)


# ---------------------------------------------------------------- channels
def test_channel_models_keep_unit_power_and_their_delay_spread():
    rng = np.random.default_rng(0)
    fs = 320e6
    x = np.ones(2000, dtype=complex)
    assert np.array_equal(FlatChannel().apply(x, fs, rng)[0], x)
    ch = ExponentialTdl(rms_delay_ns=7.0, los_k_db=None)
    assert ch.realized_rms_delay_s(fs) == pytest.approx(7e-9, rel=0.15)
    p = np.mean([np.sum(np.abs(ch.realize(fs, rng)) ** 2) for _ in range(400)])
    assert p == pytest.approx(1.0, rel=0.1)
    los = ExponentialTdl(rms_delay_ns=7.0, los_k_db=10.0)
    taps = np.array([los.realize(fs, rng) for _ in range(400)])
    assert np.mean(np.abs(taps[:, 0]) ** 2) > 0.85            # LOS dominates
    tt = TapTableChannel((0.0, 10.0), (0.0, -10.0))
    assert np.sum(np.abs(tt.taps(fs)) ** 2) == pytest.approx(1.0)
    assert make_channel("flat").name == "flat"
    with pytest.raises(ValueError):
        make_channel("tgn_d")


# ---------------------------------------------------------------- noise
def test_per_tone_snr_definition():
    assert per_sample_snr_offset_db(64, 2, 56) == pytest.approx(10 * np.log10(128 / 56))
    rng = np.random.default_rng(0)
    x = np.exp(1j * rng.uniform(0, 2 * np.pi, 200000))
    y, sigma2 = add_awgn_per_tone(x, 10.0, 64, 2, 56, rng)
    assert np.var(y - x) == pytest.approx(sigma2, rel=0.02)
    assert 10 * np.log10(1 / sigma2) == pytest.approx(10.0 - per_sample_snr_offset_db(64, 2, 56), abs=0.05)
