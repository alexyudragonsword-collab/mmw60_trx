"""Law 4 on topology B: the scoring waveform of the calibration check at
bandwidths wifitrx has no standard pilot table for (wifi_trx_cal#4)."""
from __future__ import annotations

import numpy as np
import pytest

from mmw60 import spec
from mmw60.calcheck import FINAL_VIEWS, run_cal_at, scoring_config, upclocked_scoring_config
from mmw60.config import zero_if_60ghz
from mmw60.frontend import Frontend60
from mmw60.vendor.wifitrx.waveform.pilots import generate_ofdm_with_pilots, pilot_positions


@pytest.mark.parametrize("base_bw, k, standard, n_active, n_pilots", [
    (20e6, 32, "11ac", 52, 4), (80e6, 32, "11be", 996, 16), (20e6, 1, "11ac", 52, 4)])
def test_upclocked_scoring_waveform_is_the_base_waveform_k_times_faster(base_bw, k, standard, n_active, n_pilots):
    base, _ = upclocked_scoring_config(base_bw, 1, standard=standard)
    cfg, label = upclocked_scoring_config(base_bw, k, standard=standard)
    assert cfg.bandwidth_hz == base_bw * k and cfg.subcarrier_spacing_hz == base.subcarrier_spacing_hz * k
    assert cfg.n_active == base.n_active == n_active and cfg.fft_size == base.fft_size
    assert cfg.sample_rate_hz == pytest.approx(base.sample_rate_hz * k)
    assert np.array_equal(cfg.active_tone_indices(), base.active_tone_indices())
    # the pilots are the base standard's own, carried by the tone plan (wifitrx >= 96078aa)
    assert np.array_equal(pilot_positions(cfg), pilot_positions(base)) and pilot_positions(cfg).size == n_pilots
    std, _ = scoring_config(base_bw)
    if standard == "11ac":
        assert np.array_equal(cfg.active_tone_indices()[pilot_positions(cfg)],
                              std.active_tone_indices()[pilot_positions(std)])
    wf_base, cols_base = generate_ofdm_with_pilots(base)
    wf_k, cols_k = generate_ofdm_with_pilots(cfg)
    assert np.array_equal(cols_base, cols_k)
    assert np.array_equal(wf_base.x, wf_k.x)                 # the same samples: only the clock differs
    assert f"x{k} upclocked" in label and str(n_pilots) in label


def test_no_standard_scoring_waveform_above_320mhz_and_unknown_base_is_refused():
    assert scoring_config(640e6)[0] is None and scoring_config(2.56e9)[0] is None
    assert upclocked_scoring_config(30e6, 4)[0] is None
    assert upclocked_scoring_config(20e6, 4, standard="11be")[0].subcarrier_spacing_hz == 4 * 78.125e3


def test_law4_final_evm_is_scored_at_640mhz_not_skipped():
    """K = 32 on the 11ac 20 MHz base: every step of wifitrx's sequence runs,
    the last one included (it was 'skipped' before the upclocked waveform)."""
    fe = Frontend60.from_config(zero_if_60ghz(k=8))
    run = run_cal_at(fe, 32, 20e6, with_dpd=False, standard="11ac")
    by = {r.step: r for r in run.rows}
    assert "upclocked" in run.waveform and not [r.step for r in run.rows if r.status in ("skipped", "failed")]
    last = by["final_loopback_evm"]
    assert last.metric and np.isfinite(last.value) and np.isfinite(run.evm_before_db)
    assert run.evm_after_db < run.evm_before_db
    assert run.n_symbols == spec.value("assumed.cal_capture_symbols") == 8 and run.capture_samples == 1280
    assert run_cal_at(fe, 32, 20e6, with_dpd=False, standard="11ac", n_symbols=16).capture_samples == 2560
    assert set(run.final_views) == set(FINAL_VIEWS) and all(np.isfinite(v) for v in run.final_views.values())


def test_waveform_seed_changes_the_training_data_and_zero_is_the_default():
    """ROADMAP C7 (overturned 2026-11-14): whether the DPD step writes a
    predistorter at the preset back-off depends on the training waveform's
    random data, so the check can be run on other data; seed 0 is wifitrx's
    default and every earlier reading."""
    a0, _ = upclocked_scoring_config(20e6, 32, standard="11ac")
    a0s, _ = upclocked_scoring_config(20e6, 32, standard="11ac", seed=0)
    a3, _ = upclocked_scoring_config(20e6, 32, standard="11ac", seed=3)
    assert a0.seed == a0s.seed == 0 and a3.seed == 3
    x0, x0s, x3 = (generate_ofdm_with_pilots(c)[0].x for c in (a0, a0s, a3))
    assert np.array_equal(x0, x0s) and x0.shape == x3.shape and not np.allclose(x0, x3)
    s0, _ = scoring_config(80e6)
    assert s0.seed == 0 and scoring_config(80e6, seed=5)[0].seed == 5
    fe = Frontend60.from_config(zero_if_60ghz(k=8))
    runs = [run_cal_at(fe, 1, 20e6, standard="11ac", obo_db=fe.obo_db, waveform_seed=s) for s in (0, 1)]
    for r in runs:
        assert r.dpd_kept in (0, 1, 2) and r.dpd_before_db is not None and r.dpd_after_db is not None
        same = r.dpd_after_db == pytest.approx(r.dpd_before_db)
        assert (r.dpd_after_db < r.dpd_before_db) == bool(r.dpd_kept) or same
    assert runs[0].rows[-1].value != runs[1].rows[-1].value             # different data, different final reading
