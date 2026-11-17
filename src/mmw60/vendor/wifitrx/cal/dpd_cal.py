# Vendored from wifi_trx_cal@a8edf503df74cf11d6069a6354c4c0ddbf6e82d1: src/wifitrx/cal/dpd_cal.py
# Adapted-copy policy: see src/mmw60/vendor/__init__.py
"""DPD calibration through the TX -> loopback -> RX observation path.

Runs LAST in the sequence: the ILA identification would otherwise learn
residual observation-path impairments (IQ image, DC, delay) into the
predistorter coefficients.  The RX channel filter is opened up during the
capture (wideband observation mode, standard practice for DPD receivers —
the adjacent-channel regrowth must be visible to the identification).

Flow per iteration: transmit reference -> capture -> delay-align ->
gain-normalize -> single-shot ILA fit on the measured pair -> apply.

The step then programs the BEST candidate as the observation path reads
it, not the last one (B40).  Each iteration's capture is the previous
candidate seen through the loopback, so candidate k -- no predistorter
for k = 0, the k-th fit otherwise -- is scored on capture k at no extra
cost, and one capture after the loop scores the last.  Iterating is not
monotone: on this library's own PA the second ILA pass reads 0.6-0.9 dB
worse than the first at 80 / 160 / 320 MHz, and past saturation later
passes diverge (80 MHz at drive 0.3: -34.7 dB after one pass, -19.8
after three); a soft-compression PA (mmw60_trx, issue #5) loses the
first pass's gain in the second.  The observation picks the same pass
as the PA output in 10 of 12 parts measured, and where it does not the
two passes differ by <= 0.12 dB.  Keeping candidate 0 is allowed: a
predistorter the observation reads worse than none is not programmed.
"""
from __future__ import annotations

import numpy as np

from ..chain.agc import CAL_OBSERVATION_STATE
from ..chain.loopback import LoopbackPath
from ..chain.rx import RxChain
from ..chain.tx import TxChain
from ..metrics import aclr, evm
from ..metrics.cpe import correct_cpe_equalized
from ..pa.gmp import GMPModel
from ..dpd.bounded import BoundedDPD
from ..waveform.ofdm import OFDMWaveform, demodulate_ofdm
from .base import CalResult
from .sync import align_delay, compensate_delay, loopback_capture_aligned


def _capture(tx: TxChain, rx: RxChain, path: LoopbackPath,
             x: np.ndarray, n_warmup: int = 512,
             n_guard: int = 64) -> np.ndarray:
    """Delay-aligned loopback capture with a cyclic warm-up prefix that
    settles the IIR baseband filters and a cyclic guard tail that keeps
    delay compensation inside the frame (not gain-normalized); the delay
    search widens itself when needed (``sync.loopback_capture_aligned``)."""
    return loopback_capture_aligned(tx, rx, path, x, n_warmup=n_warmup,
                                    n_guard=n_guard)


def pa_out_evm_db(tx: TxChain, wf: OFDMWaveform, drive_scale: float,
                  n_warmup: int = 512, n_guard: int = 64) -> float:
    """PA-output EVM of ``wf`` at ``drive_scale``, in the isolation view
    the closure target uses (``sequence.tx_snapshot``): a cyclic warm-up
    settles the TX filters, the capture is delay-aligned, the edge
    symbol is dropped, and each symbol's common phase is removed against
    the reference (genie CPE) before the per-tone equaliser scores it.

    The DPD step's ``evm_db`` and the temperature study's re-read of it
    are measured here, and so is the RLS tracker's.  Until 0.7.42 the
    step scored the raw PA output with the per-tone equaliser alone, so
    its number kept the TX LO phase noise's per-symbol common phase that
    the closure target removes: on 2.5 MHz subcarriers (0.4 us symbols)
    that read -42.3 dB where the same chain measured -45.9 at the final
    step, and the replay's TX view over-explained by +4.6 dB (B38).
    With the LO noise off the two conventions agree within 0.12 dB.
    """
    x = wf.x * drive_scale
    xp = np.concatenate([x[-n_warmup:], x, x[:n_guard]])
    y = tx(xp)
    _, _, info = align_delay(xp, y, max_lag=n_guard // 2)
    y = compensate_delay(y, info["lag_total"], n_warmup, len(x))
    g = np.vdot(x, y) / np.vdot(x, x)
    # score interior symbols only: the burst's final symbol is
    # edge-contaminated once delay compensation advances its FFT window
    # past the burst end (see cal.sequence.tx_evm)
    syms = demodulate_ofdm(y / g / drive_scale, wf)[:-1]
    ref = wf.tx_symbols[:-1]
    syms = correct_cpe_equalized(syms, ref)       # as score_views (B46)
    return float(evm(syms, ref, equalize="per_tone").db)


def calibrate_dpd(tx: TxChain, rx: RxChain, wf: OFDMWaveform,
                  path: LoopbackPath | None = None, n_iter: int = 2,
                  order: int = 7, memory_depth: int = 5,
                  drive_scale: float = 0.25, seed: int = 17,
                  tap_spacing: int = 1) -> CalResult:
    """``drive_scale`` sets the digital rms level (unit-power reference times
    drive_scale) so the OFDM peaks stay inside DAC full scale and the PA
    runs at a sane backoff — ILA diverges if driven past saturation.

    ``tap_spacing`` puts the GMP basis's memory taps that many samples
    apart (see :mod:`wifitrx.pa.memory_polynomial`).  1 is the historical
    sample-spaced basis; a PA whose memory is fixed in seconds
    (``ReferencePA(fs=..., fir_fs=...)``) run at ``fs`` needs ``fs /
    fir_fs`` here, or the predistorter's memory shrinks with the sampling
    rate while the PA's does not (issue #5)."""
    if path is None:
        path = LoopbackPath(atten_db=40.0, delay_ns=6.0)
    fs = tx.fs
    bw = wf.config.bandwidth_hz
    x = wf.x * drive_scale

    # wideband observation mode for the RX channel filter
    lpf_was_enabled = rx.params.lpf.enabled
    rx.params.lpf.enabled = False

    # AGC for the actual coupled level (the observation ADC must not clip)
    from ..units import power_dbm
    rx.agc_pinned(power_dbm(tx(x)) - path.atten_db, CAL_OBSERVATION_STATE)

    def pa_out_metrics() -> dict:
        y = tx(x)
        if fs >= 3.0 * bw:
            ac = aclr(y, fs, bw)
            ac_worst = max(ac["lower_dbc"], ac["upper_dbc"])
        else:
            ac_worst = float("nan")  # adjacent channel outside Nyquist
        # in the closure target's convention (B38): this number is the
        # in-band term the replay injects
        return {"evm_db": pa_out_evm_db(tx, wf, drive_scale),
                "aclr_worst_dbc": ac_worst}

    def observed_evm_db(cap: np.ndarray) -> float:
        # the same per-tone isolation EVM, read through the observation
        # receiver instead of at the PA output (a part cannot do that)
        g = np.vdot(x, cap) / np.vdot(x, x)
        return float(evm(demodulate_ofdm(cap / g, wf), wf.tx_symbols,
                         equalize="per_tone").db)

    before = pa_out_metrics()
    trace = [before["aclr_worst_dbc"]]

    # Iterated indirect learning: fit the post-inverse on (capture/G0 -> u)
    # where u is the ACTUAL predistorted drive of the current iteration and
    # G0 is the composite linear gain frozen at iteration 0 (a drifting
    # normalization would fold gain error into the coefficients).
    dpd_model = None
    g0 = None
    x_max = float(np.max(np.abs(x)))
    candidates: list = [None]        # k-th: the predistorter after k passes
    observed: list[float] = []       # k-th: candidate k through the loopback
    for it in range(n_iter):
        u = x if dpd_model is None else dpd_model(x)
        cap = _capture(tx, rx, path, x)
        observed.append(observed_evm_db(cap))
        if g0 is None:
            g0 = np.vdot(x, cap) / np.vdot(x, x)
        model = GMPModel(order=order, memory_depth=memory_depth,
                         tap_spacing=tap_spacing)
        model.fit(cap / g0, u)
        dpd_model = model
        # programmed envelope-bounded: the polynomial is a model of the
        # PA only up to the training peak; beyond it the correction gain
        # holds its edge value (see dpd/bounded.py for the -3.8 dB
        # symbol that motivated this)
        tx.dpd = BoundedDPD(dpd_model, x_max)
        candidates.append(tx.dpd)
        trace.append(pa_out_metrics()["aclr_worst_dbc"])
    observed.append(observed_evm_db(_capture(tx, rx, path, x)))
    kept = int(np.argmin(observed))
    tx.dpd = candidates[kept]

    after = pa_out_metrics()
    rx.params.lpf.enabled = lpf_was_enabled
    return CalResult(
        name="dpd",
        estimated={"order": order, "memory_depth": memory_depth,
                   "tap_spacing": int(tap_spacing), "x_max": x_max,
                   "kept_iteration": kept,
                   "observed_evm_db": [round(v, 3) for v in observed]},
        corrections={"dpd": (
            f"GMP ILA predistorter after pass {kept} of {n_iter} (the best "
            "the observation path read) programmed on TxChain, "
            "envelope-bounded at the training peak" if kept else
            "none programmed: the observation path read every fitted pass "
            "worse than no predistorter")},
        trace=trace,
        metrics_before=before,
        metrics_after=after,
        # ACLR may be phase-noise-limited rather than distortion-limited, so
        # the pass gate is EVM-driven with ACLR required not to regress
        # (ACLR is NaN when fs < 3*bw and then only the EVM gate applies).
        # A PA already linear enough (post EVM <= -40 dB, beyond MCS13
        # needs) passes even without a 3 dB improvement to show.  The
        # regression check only bites while ACLR is shallower than
        # -45 dBc: a ~1 dB wobble on an already phase-noise-limited -48
        # (highly linear imported PA) is measurement noise, not learned
        # distortion regrowth.
        passed=((after["evm_db"] < before["evm_db"] - 3.0
                 or after["evm_db"] <= -40.0)
                and not (after["aclr_worst_dbc"]
                         > before["aclr_worst_dbc"] + 1.0
                         and after["aclr_worst_dbc"] > -45.0)),
        cost={"captures": n_iter + 1,
              "samples": (n_iter + 1) * (x.size + 512)},
    )
