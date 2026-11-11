"""The PA-memory study (ROADMAP D3): the reference PA with memory in the
topology-B chain, and wifitrx's DPD tap spacing passed through to its step."""
from __future__ import annotations

import numpy as np
import pytest

from mmw60 import pamemory, spec
from mmw60.calcheck import run_cal_at
from mmw60.config import zero_if_60ghz
from mmw60.frontend import Frontend60
from mmw60.vendor.wifitrx.pa import ReferencePA
from mmw60.vendor.wifitrx.units import power_dbm


@pytest.fixture(scope="module")
def fe():
    return Frontend60.from_config(zero_if_60ghz(k=8))


def test_memory_pa_keeps_the_front_ends_anchors_and_its_taps_in_seconds(fe):
    fir = pamemory.default_fir_fs_hz()
    assert fir == spec.value("assumed.pa_memory_fir_fs_hz") == 80e6
    assert pamemory.memory_stride(640e6, None) == 1 and pamemory.memory_stride(640e6, fir) == 8
    assert pamemory.memory_stride(5.12e9, fir) == 64
    with pytest.raises(ValueError, match="not a positive integer"):
        pamemory.memory_stride(40e6, fir)                       # K = 1 at 2x: fs below the PA's own tap rate
    with pytest.raises(ValueError, match="not a positive integer"):
        pamemory.memory_pa(fe, 200e6, fir)
    for fs in (160e6, 640e6, 5.12e9):
        pa = pamemory.memory_pa(fe, fs, fir)
        assert (pa.gain_db, pa.psat_dbm, pa.pae_max) == (fe.pa_gain_db, fe.psat_dbm, fe.pa_pae_max)
        stride = int(fs / fir)
        taps = np.flatnonzero(pa.pa_model.fir_in)
        assert list(taps) == [0, stride, 2 * stride]             # 0 / 12.5 / 25 ns whatever the clock
        assert np.allclose(taps / fs, np.arange(3) / fir)
        assert np.array_equal(pa.pa_model.fir_in[taps], ReferencePA().fir_in)
    scales = pamemory.memory_pa(fe, 5.12e9, None)
    assert np.array_equal(scales.pa_model.fir_in, ReferencePA().fir_in)   # one sample apart at any clock
    # the same small-signal gain and saturated power as the front end's Rapp (wifitrx ScaledPA's anchors),
    # at either memory law
    for pa in (scales, pamemory.memory_pa(fe, 5.12e9, fir)):
        x = np.full(8192, 1e-3 + 0j)
        assert power_dbm(pa(x)[512:]) - power_dbm(x) == pytest.approx(fe.pa_gain_db, abs=0.1)
        peak = max(power_dbm(pa(np.full(8192, g + 0j))[512:]) for g in np.logspace(-1, 1.5, 80))
        assert peak == pytest.approx(fe.psat_dbm, abs=0.5)


def test_candidate_spacings_always_include_sample_spaced_and_matched():
    listed = spec.value("assumed.pa_memory_dpd_candidates")
    assert pamemory.candidate_spacings(64) == tuple(sorted({1, 64, *listed}))
    assert pamemory.candidate_spacings(2) == (1, 2) and pamemory.candidate_spacings(1) == (1,)
    for f in spec.value("assumed.pa_memory_fir_fs_sensitivity_hz"):
        assert pamemory.memory_stride(80e6 * 32 * 2, f) >= 1     # each divides the K = 32 clock of example 07


def test_dpd_tap_spacing_reaches_wifitrx_dpd_step(fe):
    """wifi_trx_cal#5: the spacing asked for is the one the DPD step records
    having used, and it changes the fitted predistorter."""
    pa = pamemory.memory_pa(fe, 20e6 * 8 * 2, 80e6)
    runs = {ts: run_cal_at(fe, 8, 20e6, standard="11be", pa=pa, dpd_tap_spacing=ts) for ts in (1, 4)}
    assert runs[1].dpd_tap_spacing == 1 and runs[4].dpd_tap_spacing == 4
    dpd = {ts: next(r.value for r in run.rows if r.step == "dpd") for ts, run in runs.items()}
    assert np.isfinite(list(dpd.values())).all() and dpd[1] != dpd[4]
    off = run_cal_at(fe, 8, 20e6, standard="11be", pa=pa, with_dpd=False)
    assert off.dpd_tap_spacing is None and "dpd" not in [r.step for r in off.rows]
    assert off.pout_dbm == pytest.approx(runs[1].pout_dbm, abs=1.0) and 5 < fe.psat_dbm - off.pout_dbm < 15
    row = pamemory.run_row(fe, 8, 20e6, "11be", fir_fs_hz=80e6, tap_spacing=4)
    assert row.stride == 4 and row.law == pamemory.FIXED and row.tx_evm_db == runs[4].final_views["tx_evm_modem_db"]
    assert "12.5 ns" in row.label and not row.failed
    rapp = pamemory.run_row(fe, 8, 20e6, "11be", pa="rapp")
    assert rapp.law is None and rapp.stride == 1 and rapp.label.startswith("Rapp")
    assert rapp.tx_evm_db == run_cal_at(fe, 8, 20e6, standard="11be").final_views["tx_evm_modem_db"]


@pytest.mark.slow
def test_fixed_memory_costs_the_sample_spaced_basis_most_at_the_widest_clock(fe):
    """Example 07's headline at K = 32 (2.56 GHz): memory fixed in seconds
    costs the sample-spaced DPD several dB against memory that scales with
    the signal, and the matched spacing wins most of it back."""
    kw = dict(k=32, base_bw_hz=80e6, standard="11be")
    scales = pamemory.run_row(fe, **kw, tap_spacing=1)
    sample = pamemory.run_row(fe, **kw, fir_fs_hz=80e6, tap_spacing=1)
    matched = pamemory.run_row(fe, **kw, fir_fs_hz=80e6, tap_spacing=64)
    assert sample.tx_evm_db - scales.tx_evm_db > 3.0
    assert sample.tx_evm_db - matched.tx_evm_db > 2.5
    assert matched.tx_evm_db - scales.tx_evm_db < 2.5
    assert pamemory.best_spacing([scales, sample, matched]) is matched


def test_every_row_lands_on_the_asked_back_off(fe):
    """The two memory laws give different output power at the same drive
    (taps spread over the band average to less in-band gain), so the study
    reruns the sequence until the final check sits at the asked back-off."""
    pa = pamemory.memory_pa(fe, 20e6 * 8 * 2, 80e6)
    free = run_cal_at(fe, 8, 20e6, standard="11be", pa=pa)
    assert free.passes == 1 and abs(fe.psat_dbm - free.pout_dbm - fe.obo_db) > 0.5      # wifitrx's own drive
    for obo in (fe.obo_db, 12.0):
        run = run_cal_at(fe, 8, 20e6, standard="11be", pa=pa, obo_db=obo)
        assert fe.psat_dbm - run.pout_dbm == pytest.approx(obo, abs=0.1) and 1 <= run.passes <= 4
    rows = pamemory.cost_rows(fe, 8, 20e6, "11be", fe.obo_db)
    assert [r.law for r in rows] == [pamemory.SCALES, pamemory.FIXED, pamemory.FIXED]
    assert [r.tap_spacing for r in rows] == [1, 1, 4]
    assert all(r.obo_db == pytest.approx(fe.obo_db, abs=0.1) for r in rows)


@pytest.mark.slow
def test_fixed_memory_defeats_the_dpd_at_the_preset_back_off(fe):
    """Example 07 at K = 8 and the preset 8 dB back-off: memory that scales
    with the signal is linearised, memory fixed at 12.5 ns is not, at either
    tap spacing."""
    scales, sample, matched = pamemory.cost_rows(fe, 8, 80e6, "11be", fe.obo_db)
    off = pamemory.run_row(fe, 8, 80e6, "11be", fir_fs_hz=80e6, tap_spacing=None, obo_db=fe.obo_db)
    assert scales.tx_evm_db < -25.0
    assert min(sample.tx_evm_db, matched.tx_evm_db) - scales.tx_evm_db > 4.0
    assert min(sample.tx_evm_db, matched.tx_evm_db) > off.tx_evm_db - 1.5      # the DPD buys about nothing
