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
    """Example 07's K = 32 (2.56 GHz) reading at the preset back-off: memory
    fixed in seconds costs the sample-spaced DPD dB against memory that scales
    with the signal, and the matched spacing wins nearly all of it back
    (example 07's sweep at 8 dB: -25.3 / -22.8 / -25.2 dB).

    The rows sit on the preset back-off, as example 07's do.  Until
    2026-11-12 this test ran them at wifitrx's default drive; that drive
    lands wherever the PA's gain puts it (it moved by 3.8 dB when the presets
    took the measured PA), and the two memory laws landed on different
    back-offs (7.1 / 8.2 dB) — the single-operating-point comparison the
    third reading of example 07 had already given up."""
    kw = dict(k=32, base_bw_hz=80e6, standard="11be", obo_db=fe.obo_db)
    scales = pamemory.run_row(fe, **kw, tap_spacing=1)
    sample = pamemory.run_row(fe, **kw, fir_fs_hz=80e6, tap_spacing=1)
    matched = pamemory.run_row(fe, **kw, fir_fs_hz=80e6, tap_spacing=64)
    assert all(abs(r.obo_db - fe.obo_db) < 0.1 for r in (scales, sample, matched))
    assert sample.tx_evm_db - scales.tx_evm_db > 2.0
    assert sample.tx_evm_db - matched.tx_evm_db > 2.0
    assert matched.tx_evm_db - scales.tx_evm_db < 1.0
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


def test_backoff_for_evm_reads_the_first_crossing():
    obo = [7.0, 8.0, 9.0, 10.0]
    evm = [-20.0, -22.0, -26.0, -28.0]
    assert pamemory.backoff_for_evm(obo, evm, -24.0) == (pytest.approx(8.5), True)
    assert pamemory.backoff_for_evm(obo, evm, -22.0) == (pytest.approx(8.0), True)
    assert pamemory.backoff_for_evm(obo[::-1], evm[::-1], -27.0) == (pytest.approx(9.5), True)   # order does not matter
    assert pamemory.backoff_for_evm(obo, evm, -19.0) == (7.0, False)       # there at the first point: an upper bound
    assert pamemory.backoff_for_evm(obo, evm, -30.0) == (None, False)      # never reached inside the sweep
    # a dip that comes back: the first crossing counts
    dip = pamemory.backoff_for_evm([7.0, 8.0, 9.0, 10.0], [-20.0, -26.0, -23.0, -27.0], -25.0)
    assert dip == (pytest.approx(7.0 + 5 / 6), True)


def test_rows_do_not_depend_on_the_worker_count_and_duplicates_run_once(fe):
    keys = [*pamemory.cost_keys(8, 20e6, "11be", 10.0), *pamemory.cost_keys(8, 20e6, "11be", 10.0),
            pamemory.row_key(8, 20e6, "11be", "rapp", obo_db=10.0)]
    serial = pamemory.run_many(fe, keys, jobs=1)
    pooled = pamemory.run_many(fe, keys, jobs=2)
    assert list(serial) == list(pooled) and len(serial) == 4                 # three cost rows + the Rapp, once each
    for key in serial:
        assert serial[key] == pooled[key], key                               # the dataclass compares every field
    pts = pamemory.sweep_points(serial, 8, 20e6, "11be", [10.0])
    assert len(pts) == 1 and pts[0].fixed_best_evm_db == min(pts[0].fixed_x1.tx_evm_db, pts[0].fixed_matched.tx_evm_db)
    pen = pamemory.backoff_penalty(pts, -10.0)
    assert pen["scales"] == 10.0 and not pen["scales_exact"] and pen["cost"] is None    # one point: no crossing
    assert fe.obo_db in spec.value("assumed.pa_memory_obo_sweep_db")                    # the preset is on the grid
    assert set(spec.value("assumed.pa_memory_obo_sweep_coarse_db")) <= set(spec.value("assumed.pa_memory_obo_sweep_db"))


@pytest.mark.slow
def test_the_preset_back_off_sits_on_the_dpd_cliff_and_the_cost_is_read_in_back_off(fe):
    """Example 07 at K = 8: between 7 and 8 dB of back-off the predistorter
    on the scales-with-the-signal PA goes from useless to 6 dB of gain; the
    fixed-memory PA gets there 1–3 dB of back-off later.  The EVM gap read
    at the preset 8 dB (several dB) is that offset between the two cliffs,
    not the price of the memory."""
    obos = (7.0, 8.0, 9.0, 10.0, 12.0)
    done = pamemory.run_many(fe, pamemory.sweep_keys(8, 80e6, "11be", obos), jobs=2)
    pts = {p.obo_db: p for p in pamemory.sweep_points(done, 8, 80e6, "11be", obos)}
    assert pts[7.0].scales.tx_evm_db - pts[8.0].scales.tx_evm_db > 4.0               # the cliff, inside one dB
    assert pts[8.0].fixed_best_evm_db - pts[8.0].scales.tx_evm_db > 4.0              # the gap read on it
    assert pts[12.0].fixed_best_evm_db - pts[12.0].scales.tx_evm_db < 1.5            # and gone off it
    pen = pamemory.backoff_penalty(list(pts.values()), -25.0)
    assert pen["scales_exact"] and pen["fixed_exact"] and 0.8 < pen["cost"] < 3.0
    assert 7.0 < pen["scales"] < 8.0 < pen["fixed"] < 10.0
