"""ROADMAP C1–C3: the cross-symbol CPE combiner, the automatic channel-estimate
smoothing span, and the PER-threshold refinement and confidence interval."""
import dataclasses as dc

import numpy as np
import pytest

from mmw60.config import ChannelConfig, RxConfig, improved_rx, liu2025_table2, zero_if_60ghz
from mmw60.rx.tracking import auto_smooth_span, pilot_phasors, smoothed_cpe, tone_autocorrelation
from mmw60.sim.curves import CurveSpec, ci_text, run_curves
from mmw60.sim.link import LinkSim, _bracket, per_sweep, snr_at_per, snr_at_per_ci
from mmw60.vendor.wifitrx.metrics.cpe import correct_cpe_pilots

FLAT = ChannelConfig(model="flat")


def _symbols(n_sym, n_tones, cols, rng, snr_db=None, phase=None):
    """Unit-power QPSK symbols with BPSK pilots, rotated by ``phase[n]`` and noised."""
    tx = (rng.choice([-1, 1], (n_sym, n_tones)) + 1j * rng.choice([-1, 1], (n_sym, n_tones))) / np.sqrt(2)
    pil = rng.choice([-1.0, 1.0], (n_sym, cols.size)).astype(complex)
    tx[:, cols] = pil
    rx = tx.copy()
    if phase is not None:
        rx = rx * np.exp(1j * np.asarray(phase))[:, None]
    if snr_db is not None:
        s = 10 ** (-snr_db / 20) / np.sqrt(2)
        rx = rx + s * (rng.standard_normal(rx.shape) + 1j * rng.standard_normal(rx.shape))
    return tx, rx, pil


# ---------------------------------------------------------------- C1
def test_window_of_one_is_wifitrx_per_symbol_cpe_bit_for_bit():
    rng = np.random.default_rng(0)
    cols = np.array([7, 21, 34, 48])
    _, rx, pil = _symbols(40, 56, cols, rng, snr_db=10.0, phase=0.3 * rng.standard_normal(40))
    assert np.array_equal(smoothed_cpe(rx, cols, pil, 1), correct_cpe_pilots(rx, cols, pil))
    a = pilot_phasors(rx, cols, pil)
    assert np.allclose(rx * (a / np.abs(a))[:, None], correct_cpe_pilots(rx, cols, pil))
    # the default receiver config is that estimator, and the Liu preset keeps it
    assert RxConfig().cpe_window_symbols == 1 and liu2025_table2().rx.cpe_window_symbols == 1
    assert not liu2025_table2().rx.ce_smooth_auto
    z = zero_if_60ghz()
    assert z.rx.cpe_window_symbols == 17 and z.rx.ce_smooth_auto and z.rx == improved_rx(dc.replace(z.rx))


def test_low_snr_the_combiner_smooths_and_beats_per_symbol():
    """4 pilots at 2 dB: one symbol's own estimate has σ ≈ 16°, the true
    common phase here is a slow 2° wander plus a CFO ramp.  The combiner
    must put its weight on the smooth estimate and leave less phase error."""
    rng = np.random.default_rng(1)
    cols = np.array([7, 21, 34, 48])
    n = 400
    true = 0.004 * np.arange(n) + np.deg2rad(2.0) * np.sin(2 * np.pi * np.arange(n) / 150)
    tx, rx, pil = _symbols(n, 56, cols, rng, snr_db=2.0, phase=true)
    out, info = smoothed_cpe(rx, cols, pil, 17, return_info=True)
    assert info["g"] < 0.15 and info["window"] == 17
    assert info["ramp_rad_per_symbol"] == pytest.approx(-0.004, abs=0.003)        # correction ramp = −(true ramp)
    data = np.setdiff1d(np.arange(56), cols)
    def phase_err(y):
        return np.angle(np.sum(y[:, data] * np.conj(tx[:, data]), axis=1))
    e_smooth = np.sqrt(np.mean(phase_err(out) ** 2))
    e_own = np.sqrt(np.mean(phase_err(correct_cpe_pilots(rx, cols, pil)) ** 2))
    assert e_smooth < 0.45 * e_own, (e_smooth, e_own)


def test_high_snr_the_combiner_keeps_each_symbols_own_phase():
    """Independent 3° common phase per symbol at 35 dB: the deviation from
    the window mean is real, g → 1, and the result matches per-symbol CPE."""
    rng = np.random.default_rng(2)
    cols = np.arange(4, 240, 15)                                  # 16 pilots
    n = 200
    true = np.deg2rad(3.0) * rng.standard_normal(n)
    tx, rx, pil = _symbols(n, 242, cols, rng, snr_db=35.0, phase=true)
    out, info = smoothed_cpe(rx, cols, pil, 17, return_info=True)
    assert info["g"] > 0.9
    ref = correct_cpe_pilots(rx, cols, pil)
    evm = lambda y: 10 * np.log10(np.mean(np.abs(y - tx) ** 2))           # noqa: E731
    assert evm(out) < evm(ref) + 0.5 and evm(out) < -30
    # short packets fall back to the per-symbol estimator
    assert np.array_equal(smoothed_cpe(rx[:2], cols, pil[:2], 17), correct_cpe_pilots(rx[:2], cols, pil[:2]))


def test_improved_receiver_moves_the_mcs0_threshold_left():
    """ROADMAP C1's own measure: Liu K = 8 MCS0 on a flat channel.  At 3 dB
    the milestone-0 receiver still loses most packets, the improved one
    hardly any."""
    base = dc.replace(liu2025_table2(k=8, mcs=0), channel=FLAT)
    old = per_sweep(base, [3.0], max_packets=40, min_errors=40, seed=4)["per"][0]
    new = per_sweep(dc.replace(base, rx=improved_rx(base.rx)), [3.0], max_packets=40, min_errors=40, seed=4)["per"][0]
    assert old > 0.4 and new < 0.1, (old, new)


# ---------------------------------------------------------------- C2
def _lorentz_channel(n, a2, rng, n_real=200):
    """Per-tone channels whose tone autocorrelation is 1 / (1 + j·a·d): an
    exponential delay profile sampled at the tone spacing."""
    a = np.sqrt(a2)
    taps = 60
    pdp = np.exp(-np.arange(taps) / (a * taps / (2 * np.pi) if a > 0 else 1e9))
    k = np.arange(n)[:, None] * np.arange(taps)[None, :]
    out = []
    for _ in range(n_real):
        g = (rng.standard_normal(taps) + 1j * rng.standard_normal(taps)) * np.sqrt(pdp / pdp.sum() / 2)
        out.append(np.exp(-2j * np.pi * k / taps) @ g)
    return np.array(out)


def test_span_is_the_ceiling_on_a_flat_channel_and_one_on_a_selective_one():
    rng = np.random.default_rng(3)
    flat_h = np.ones(242) * np.exp(1j * 0.4)
    noisy = flat_h + 0.2 * (rng.standard_normal(242) + 1j * rng.standard_normal(242))
    s, info = auto_smooth_span(noisy, None, 9, return_info=True)
    assert s == 9 and info["white_power"] == pytest.approx(0.08, rel=0.4) and info["a2"] < 0.01
    assert auto_smooth_span(noisy, None, 5) == 5 and auto_smooth_span(noisy, None, 1) == 1
    # white error that is not thermal (an LTF-pattern share of an IQ image) is averaged down as well
    assert auto_smooth_span(flat_h * (1 + 0.1 * rng.choice([-1, 1], 242)), None, 9) == 9
    # few tones: three is taken, wider only when the gain clears the estimate's own scatter
    few = np.ones(56) + 0.2 * (rng.standard_normal(56) + 1j * rng.standard_normal(56))
    assert auto_smooth_span(few, None, 9) in (3, 5, 7, 9) and auto_smooth_span(few, None, 3) == 3
    # a smooth roll-off the model does not know: the measured bias stops the span short of the ceiling
    k = np.arange(996)
    rolloff = (1.0 - 0.5 * (k / 995.0) ** 8) * np.exp(1j * 2e-5 * (k - 498.0) ** 2)
    clean = rolloff + 1e-3 * (rng.standard_normal(996) + 1j * rng.standard_normal(996))
    s_roll, info_roll = auto_smooth_span(clean, None, 9, return_info=True)
    assert s_roll < 9, info_roll
    # a channel that decorrelates over a few tones: no smoothing when the estimate is clean
    spans = [auto_smooth_span(h, None, 9) for h in _lorentz_channel(242, 0.25, rng, 40)]
    assert np.mean(np.array(spans) == 1) >= 0.7, spans         # one realisation's acf is itself noisy
    # tone_autocorrelation stays inside the frequency-contiguous runs
    h = np.concatenate([np.ones(10), -np.ones(10)])
    whole = tone_autocorrelation(h, None, 1)
    split = tone_autocorrelation(h, [np.arange(10), np.arange(10, 20)], 1)
    assert whole[1] < 1.0 and split[1] == pytest.approx(1.0)


def test_auto_span_matches_the_better_fixed_span_on_the_roadmap_case():
    """ROADMAP C2's reproduction: K = 16, 15 ns rms Rayleigh.  A fixed 3-tone
    boxcar wrecks the estimate (EVM −4 dB against −14 dB unsmoothed); the
    automatic span follows the unsmoothed one.  On the flat impaired chain
    it takes the ceiling and reads the fixed-3 EVM or better."""
    c = dc.replace(liu2025_table2(k=16, mcs=4).ideal(),
                   channel=ChannelConfig(model="tdl_exp", rms_delay_ns=15.0, los_k_db=None))
    def evm(cfg, n=6):
        sim, rng = LinkSim(cfg), np.random.default_rng(5)
        rs = [sim.packet(None, rng) for _ in range(n)]
        return 10 * np.log10(np.mean([10 ** (r.rx.evm_db / 10) for r in rs])), [r.rx.ce_span for r in rs]
    e1, _ = evm(dc.replace(c, rx=dc.replace(c.rx, ce_smooth_tones=1)))
    e3, s3 = evm(c)
    ea, sa = evm(dc.replace(c, rx=dc.replace(c.rx, ce_smooth_auto=True)))
    assert s3 == [3] * 6 and e3 > e1 + 6 and ea < e1 + 3 and np.median(sa) == 1, (e1, e3, ea, sa)
    z = dc.replace(zero_if_60ghz(k=4, standard="11be", bandwidth_hz=80e6), channel=FLAT)
    r_auto = LinkSim(z).packet(None, np.random.default_rng(0))
    r_3 = LinkSim(dc.replace(z, rx=dc.replace(z.rx, ce_smooth_auto=False))).packet(None, np.random.default_rng(0))
    assert r_auto.rx.ce_span == 9 and r_3.rx.ce_span == 3 and r_auto.rx.evm_db < r_3.rx.evm_db + 0.1


# ---------------------------------------------------------------- C3
def test_interval_narrows_with_the_error_count_and_brackets_the_point():
    snr = [1.0, 2.0, 3.0, 4.0]
    few = {"snr_db": snr, "per": [1.0, 0.2, 0.004, 0.0], "n_packets": [10, 50, 250, 250], "n_errors": [10, 10, 1, 0]}
    many = {"snr_db": snr, "per": [1.0, 0.2, 0.004, 0.0], "n_packets": [100, 500, 25000, 2500],
            "n_errors": [100, 100, 100, 0]}
    a, b = snr_at_per_ci(few), snr_at_per_ci(many)
    assert a["snr_db"] == pytest.approx(snr_at_per(few)) and a["lo_db"] < a["snr_db"] < a["hi_db"]
    assert (b["hi_db"] - b["lo_db"]) < 0.35 * (a["hi_db"] - a["lo_db"])
    assert a["errors_at_bracket"] == [10, 1] and b["errors_at_bracket"] == [100, 100]
    assert snr_at_per_ci(few, seed=1)["lo_db"] == snr_at_per_ci(few, seed=1)["lo_db"]      # deterministic
    never = {"snr_db": [1.0, 2.0], "per": [1.0, 1.0], "n_packets": [10, 10], "n_errors": [10, 10]}
    n = snr_at_per_ci(never)
    assert n["snr_db"] is None and n["lo_db"] is None and n["never_fraction"] == 1.0
    assert ci_text({"ci": n}).count("—") == 2 and "errors" in ci_text({"ci": b})
    assert _bracket([1.0, 0.2, 0.004, 0.0], 1e-2) == [1, 2] and _bracket([1.0, 1.0], 1e-2) == []


def test_refinement_adds_errors_at_the_bracket_only_and_stays_deterministic():
    cfg = dc.replace(liu2025_table2(k=8, mcs=4).ideal(), channel=FLAT)
    grid = [13.0, 14.0, 15.0, 16.0, 17.0]
    plain = per_sweep(cfg, grid, max_packets=30, min_errors=4, seed=2)
    fine = per_sweep(cfg, grid, max_packets=30, min_errors=4, seed=2, refine_errors=12, refine_max_packets=120)
    again = per_sweep(cfg, grid, max_packets=30, min_errors=4, seed=2, refine_errors=12, refine_max_packets=120)
    assert fine == again
    idx = _bracket(fine["per"], 1e-2)
    assert idx, fine
    grew = [i for i in range(len(plain["snr_db"])) if fine["n_packets"][i] > plain["n_packets"][i]]
    assert grew and len(grew) <= 4          # the bracket, and the one it may shift to on the second pass
    for i in idx:
        assert fine["n_errors"][i] >= 12 or fine["n_packets"][i] == 120
    rs = run_curves([CurveSpec("x", cfg, grid, 30, 4, refine_errors=12, refine_max_packets=120)], 1e-2, 1,
                    log=lambda s: None)
    assert rs[0]["ci"]["lo_db"] <= rs[0]["snr_at_target"] <= rs[0]["ci"]["hi_db"]
    assert rs[0]["ci"]["hi_db"] - rs[0]["ci"]["lo_db"] < 2.0


def test_external_check_verdict_has_three_states(capsys):
    """ROADMAP C3: a difference is OUTSIDE only if its whole interval (our
    bootstrap interval widened by the figure's reading precision) is; an
    interval straddling the tolerance is reported as undecided, not as a miss."""
    import sys

    from conftest import REPO
    sys.path.insert(0, str(REPO / "tools"))
    import external_check

    from mmw60 import spec
    results = []
    for c in spec.fig4_readings()["curves"]:
        paper = c["per_at_1e-2_snr_db"]
        tags = {"k": c["k"], "mcs": c["mcs"], "set": "impaired"}
        if paper is None:
            results.append({"tags": tags, "snr_at_target": None, "sweep": {"per": [1.0, 1.0]}, "ci": {}})
            continue
        delta, half = {(8, 1): (1.2, 0.5), (8, 4): (2.5, 0.2)}.get((c["k"], c["mcs"]), (0.2, 0.1))
        results.append({"tags": tags, "snr_at_target": paper + delta, "sweep": {"per": [1.0, 0.0]},
                        "ci": {"lo_db": paper + delta - half, "hi_db": paper + delta + half}})
    code = external_check.compare(results, "impaired")
    out = capsys.readouterr().out
    assert code == 1 and out.count("OUTSIDE 1 dB") == 1 and out.count("cannot tell") == 1
    assert out.count("within 1 dB") == 4 and "1 cannot be told" in out and "1 to investigate" in out
    # without the one clear miss the check passes, undecided curves included
    ok = [r for r in results if (r["tags"]["k"], r["tags"]["mcs"]) != (8, 4)]
    ok.append({"tags": {"k": 8, "mcs": 4, "set": "impaired"}, "snr_at_target": 19.9, "sweep": {"per": [1.0, 0.0]},
               "ci": {"lo_db": 19.8, "hi_db": 20.0}})
    assert external_check.compare(ok, "impaired") == 0
