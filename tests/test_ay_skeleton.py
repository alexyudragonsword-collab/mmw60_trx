"""Milestone 3 skeleton: the 802.11ay waveform pieces that need no spec number.

Every numerology here is synthetic (powers of two, a 1 GS/s chip rate) on
purpose: the EDMG numbers come through spec_sources (#29), and these tests
pin down what the code does with *any* numerology — complementarity, the
guard as cyclic prefix, the pair-based channel estimate, the equalisers,
the CFO range of a repeated sequence, the PAPR of a Gaussian envelope, and
the back-off ordering of single carrier against OFDM on the shared PA.
"""
import numpy as np
import pytest

from mmw60.ay import golay, ofdm, papr, sc
from mmw60.phy.mapper import map_bits
from mmw60.rx.cfo import stf_coarse_cfo
from mmw60.vendor.wifitrx.metrics.evm import evm

FS = 1e9


def _qam(rng, n, order=4, rotation=0.0):
    return map_bits(rng.integers(0, 2, int(np.log2(order)) * n), order) * np.exp(1j * rotation * np.arange(n))


def _sc_setup(rng, rotation=np.pi / 2, n_blocks=20):
    num = sc.ScNumerology(block=128, guard=16, fs_hz=FS, rotation_rad=rotation)
    guard, _ = golay.golay_pair([1, 2, 4, 8], [1, 1, -1, 1])
    pair = golay.golay_pair([64, 1, 2, 4, 8, 16, 32], [1] * 7)
    sym = _qam(rng, num.data_per_block * n_blocks)
    return num, sym, sc.build(sym, num, guard, pair)


def _channel(rng, taps, decay):
    h = (rng.standard_normal(taps) + 1j * rng.standard_normal(taps)) * np.exp(-np.arange(taps) / decay)
    return h / np.linalg.norm(h)


def test_golay_pairs_are_complementary_for_any_delay_permutation_and_weights():
    rng = np.random.default_rng(0)
    for k in range(1, 8):
        for _ in range(3):
            d = list(rng.permutation([1 << i for i in range(k)]))
            w = list(rng.choice([1, -1, 1j, -1j], k))
            a, b = golay.golay_pair(d, w)
            assert len(a) == len(b) == 1 << k and golay.is_complementary(a, b), (d, w)
    a, b = golay.golay_pair([2, 1, 4], [1, -1, 1])
    assert a.dtype == float and set(np.abs(a)) == {1.0}                   # real weights: a binary pair
    assert not golay.is_complementary(a, np.roll(b, 1))                    # the property is not trivial
    with pytest.raises(ValueError, match="permutation"):
        golay.golay_pair([1, 2, 2], [1, 1, 1])
    with pytest.raises(ValueError, match="±1 or ±j"):
        golay.golay_pair([1, 2], [1, 0.5])


def test_sc_numerology_refuses_a_rotation_that_breaks_the_cyclic_guard():
    assert sc.ScNumerology(block=128, guard=16, fs_hz=FS, rotation_rad=np.pi / 2).data_per_block == 112
    with pytest.raises(ValueError, match="multiple of 2π"):
        sc.ScNumerology(block=130, guard=16, fs_hz=FS, rotation_rad=np.pi / 2)
    with pytest.raises(ValueError, match="guard"):
        sc.ScNumerology(block=16, guard=16, fs_hz=FS)


def test_the_guard_is_a_cyclic_prefix_up_to_its_length():
    """A channel no longer than the guard: the pair-based estimate is exact
    and zero forcing returns the symbols to numerical precision (with the
    π/2 rotation on).  Longer than the guard: inter-block interference."""
    rng = np.random.default_rng(1)
    num, sym, frm = _sc_setup(rng)
    h = _channel(rng, num.guard, 4.0)
    rx = np.convolve(frm.samples, h)[:frm.samples.size]
    est = sc.channel_estimate(rx, frm)
    assert np.max(np.abs(est - np.fft.fft(h, num.block))) < 1e-12
    assert evm(sc.equalize(rx, frm, est).reshape(-1), sym).db < -200
    h_long = _channel(rng, 3 * num.guard, 12.0)
    rx_l = np.convolve(frm.samples, h_long)[:frm.samples.size]
    assert evm(sc.equalize(rx_l, frm, sc.channel_estimate(rx_l, frm)).reshape(-1), sym).db > -40


def test_sc_mmse_equaliser_is_unbiased_and_reads_the_snr_on_a_flat_channel():
    rng = np.random.default_rng(2)
    num, sym, frm = _sc_setup(rng, n_blocks=60)
    for snr_db in (10.0, 20.0):
        s2 = 10 ** (-snr_db / 10)
        noise = np.sqrt(s2 / 2) * (rng.standard_normal(frm.samples.size) + 1j * rng.standard_normal(frm.samples.size))
        z = sc.equalize(frm.samples + noise, frm, np.ones(num.block), noise_var=s2, track_phase=False)
        assert abs(np.mean(z.reshape(-1) / sym) - 1.0) < 0.01             # the MMSE bias is removed
        assert evm(z.reshape(-1), sym).db == pytest.approx(-snr_db, abs=0.3)


def test_the_tail_guard_tracks_a_phase_drift_block_by_block():
    rng = np.random.default_rng(3)
    num, sym, frm = _sc_setup(rng)
    n = np.arange(frm.samples.size)
    rx = frm.samples * np.exp(1j * (0.7 + 2 * np.pi * 200e3 * n / FS))   # offset + residual CFO
    tracked = evm(sc.equalize(rx, frm, np.ones(num.block)).reshape(-1), sym).db
    untracked = evm(sc.equalize(rx, frm, np.ones(num.block), track_phase=False).reshape(-1), sym).db
    assert tracked < -25 and untracked > 0


def test_a_repeated_sequence_gives_the_cfo_over_half_its_repetition_rate():
    """``stf_coarse_cfo`` at a lag of one sequence length L: unbiased inside
    ±fs/(2L), aliased by fs/L outside — the range ay's preamble gives once
    its L and chip rate are known."""
    seq, _ = golay.golay_pair([1, 2, 4, 8, 16], [1, 1, 1, -1, 1])
    stf = golay.repeated(seq, 16)
    lim = FS / (2 * len(seq))
    for cfo in (1e6, 0.9 * lim, -0.9 * lim):
        r = stf * np.exp(2j * np.pi * cfo * np.arange(stf.size) / FS)
        assert stf_coarse_cfo(r, len(seq), 16, FS) == pytest.approx(cfo, rel=1e-9)
    r = stf * np.exp(2j * np.pi * 1.1 * lim * np.arange(stf.size) / FS)
    assert stf_coarse_cfo(r, len(seq), 16, FS) == pytest.approx(1.1 * lim - 2 * lim, rel=1e-9)


def _ofdm_num(n_fft=128, cp=16, edge=50, pilots=(-30, -10, 10, 30)):
    data = tuple(k for k in range(-edge, edge + 1) if k not in (-1, 0, 1) and k not in pilots)
    return ofdm.OfdmNumerology(n_fft=n_fft, cp=cp, fs_hz=FS, data_tones=data, pilot_tones=pilots)


def test_ofdm_numerology_checks_and_derived_quantities():
    num = _ofdm_num()
    assert num.scs_hz == FS / 128 and len(num.used_tones) == 98 and num.symbol_samples == 144
    assert num.occupied_bandwidth_hz == pytest.approx(101 * FS / 128)
    with pytest.raises(ValueError, match="twice"):
        ofdm.OfdmNumerology(n_fft=64, cp=16, fs_hz=FS, data_tones=(1, 2), pilot_tones=(2,))
    with pytest.raises(ValueError, match="lie in"):
        ofdm.OfdmNumerology(n_fft=64, cp=16, fs_hz=FS, data_tones=(1, 32))
    with pytest.raises(ValueError, match="one pilot value"):
        ofdm.OfdmNumerology(n_fft=64, cp=16, fs_hz=FS, data_tones=(1,), pilot_tones=(2, 3), pilot_values=(1,))


def test_ofdm_on_an_arbitrary_plan_round_trips_multipath_and_a_common_phase():
    rng = np.random.default_rng(4)
    num = _ofdm_num()
    tr = rng.choice([-1.0, 1.0], len(num.used_tones))
    d = _qam(rng, len(num.data_tones) * 30).reshape(30, -1)
    x = ofdm.modulate(num, d, tr)
    assert np.mean(np.abs(x) ** 2) == pytest.approx(1.0, abs=0.02)
    rx = np.convolve(x, _channel(rng, num.cp, 4.0))[:x.size]
    assert evm(ofdm.receive(num, rx, tr, 30), d).db < -200
    phase = np.repeat(np.concatenate([[0.0, 0.0], rng.uniform(-np.pi, np.pi, 30)]), num.symbol_samples)
    rot = rx * np.exp(1j * phase)
    assert evm(ofdm.receive(num, rot, tr, 30), d).db < -200
    assert evm(ofdm.receive(num, rot, tr, 30, cpe=False), d).db > -5


def test_ideal_interpolation_and_the_rrc_pair_are_transparent():
    rng = np.random.default_rng(5)
    x = rng.standard_normal(1000) + 1j * rng.standard_normal(1000)
    assert np.max(np.abs(papr.decimate(papr.interpolate(x, 4), 4) - x)) < 1e-12
    taps = papr.rrc_taps(4, 0.25, 16)
    assert np.sum(taps ** 2) == pytest.approx(1.0)
    s = _qam(rng, 4000)
    y = papr.shape(s, 4, taps)
    assert np.mean(np.abs(y) ** 2) == pytest.approx(1.0, abs=0.03)
    assert evm(papr.matched(y, 4, taps, s.size), s).db < -50               # truncated-pulse ISI only


def test_ofdm_papr_is_the_gaussian_envelope_and_single_carrier_sits_well_below():
    """Many tones: |x|² is exponential, P(|x|²/mean > γ) = e^−γ, so the
    1e-3 level is 10·log10(ln 1000) = 8.39 dB.  Single carrier with a
    root-raised-cosine pulse is ≥ 3 dB below (the milestone-3 acceptance
    line); the π/2 rotation brings BPSK down further still."""
    rng = np.random.default_rng(6)
    num = ofdm.OfdmNumerology(n_fft=512, cp=128, fs_hz=FS,
                              data_tones=tuple(k for k in range(-170, 171) if k not in (-1, 0, 1)))
    d = _qam(rng, len(num.data_tones) * 150).reshape(150, -1)
    xo = papr.interpolate(ofdm.modulate(num, d, np.ones(len(num.used_tones)), n_training=0), 4)
    p_ofdm = papr.papr_db(xo, 1e-3)
    assert p_ofdm == pytest.approx(10 * np.log10(np.log(1e3)), abs=0.3)
    assert papr.ccdf(xo, [p_ofdm])[0] == pytest.approx(1e-3, rel=0.1)
    taps = papr.rrc_taps(4, 0.25, 16)
    n, cut = 40000, len(taps)

    def sc_papr(order, rotation=0.0):
        return papr.papr_db(papr.shape(_qam(rng, n, order, rotation), 4, taps)[cut:-cut], 1e-3)

    p_qpsk, p_64 = sc_papr(4), sc_papr(64)
    p_bpsk, p_rot = sc_papr(2), sc_papr(2, np.pi / 2)
    assert p_ofdm - p_64 >= 2.0 and p_ofdm - p_qpsk >= 3.0, (p_ofdm, p_qpsk, p_64)
    assert p_rot < p_bpsk - 2.0 and p_qpsk < p_64, (p_bpsk, p_rot, p_qpsk, p_64)


def test_single_carrier_needs_less_back_off_than_ofdm_on_the_shared_pa():
    """The milestone-3 question on the preset front end's PA instance: the
    back-off from P_sat at which EVM after the PA reaches −20 dB.  The same
    16-QAM points need less back-off on single carrier than on OFDM, by
    about their PAPR difference at 1e-3 (not ≥ 3 dB: that holds for QPSK);
    the search lands on the target; a target under the waveform's own floor
    reads None.  Both sides are isolation readings (scalar gain only), so the
    difference is the waveforms' and not their training fields'."""
    from mmw60.config import zero_if_60ghz
    from mmw60.frontend import Frontend60
    pa = Frontend60.from_config(zero_if_60ghz(k=8)).pa_model
    rng = np.random.default_rng(7)
    taps, n = papr.rrc_taps(4, 0.25, 16), 8000
    s = _qam(rng, n, 16)
    xs = papr.shape(s, 4, taps)
    m_sc = lambda y: evm(papr.matched(y, 4, taps, n), s).db              # noqa: E731
    num = ofdm.OfdmNumerology(n_fft=256, cp=32, fs_hz=FS,
                              data_tones=tuple(k for k in range(-84, 85) if k not in (-1, 0, 1)))
    d = _qam(rng, len(num.data_tones) * 40, 16).reshape(40, -1)
    xo = papr.interpolate(ofdm.modulate(num, d, None, n_training=0), 4)
    flat = np.ones(len(num.used_tones))                # the PA alone: no training field through it (see ofdm.receive)
    m_ofdm = lambda y: evm(ofdm.receive(num, papr.decimate(y, 4), None, 40, n_training=0, h=flat), d).db   # noqa: E731
    o_sc = papr.obo_for_evm(pa, xs, m_sc, -20.0, hi_db=30.0)
    o_ofdm = papr.obo_for_evm(pa, xo, m_ofdm, -20.0, hi_db=30.0)
    assert o_sc is not None and o_ofdm is not None and o_ofdm - o_sc >= 2.0, (o_sc, o_ofdm)
    # the back-off gap is the PAPR gap (2.59 against 2.76 dB at 1e-3 on 2026-11-16)
    gap = papr.papr_db(xo, 1e-3) - papr.papr_db(xs[len(taps):-len(taps)], 1e-3)
    assert abs((o_ofdm - o_sc) - gap) < 0.6, (o_sc, o_ofdm, gap)
    from mmw60.pa.rapp import apply_pa_at_obo
    assert m_ofdm(apply_pa_at_obo(pa, xo, o_ofdm)[0]) == pytest.approx(-20.0, abs=0.1)
    assert papr.obo_for_evm(pa, xs, m_sc, -80.0, hi_db=10.0) is None
