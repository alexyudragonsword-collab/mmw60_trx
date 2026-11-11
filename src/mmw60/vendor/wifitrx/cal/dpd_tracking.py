# Vendored from wifi_trx_cal@96078aa9438c590a24d13959472263ec5f9ab623: src/wifitrx/cal/dpd_tracking.py
# Adapted-copy policy: see src/mmw60/vendor/__init__.py
"""Background DPD tracking against a drifting PA (temperature/aging).

The one-shot ILA (``dpd_cal``) freezes coefficients at calibration time; a
field unit's PA drifts underneath them.  ``track_dpd`` runs the vendored
RLS ``AdaptiveDPD`` (plain LMS diverges on the |x|^k basis, see
dpd/adaptive.py) in a periodic capture -> update loop while the PA drift
state advances, and records EVM/ACLR over the schedule for both the
tracking DPD and a frozen-DPD control.
"""
from __future__ import annotations

import numpy as np

from ..chain.agc import CAL_OBSERVATION_STATE
from ..chain.loopback import LoopbackPath, run_loopback
from ..chain.rx import RxChain
from ..chain.tx import TxChain
from ..dpd.adaptive import AdaptiveDPD
from ..metrics import evm
from ..metrics.cpe import correct_cpe
from ..pa.gmp import GMPModel
from ..waveform.ofdm import OFDMWaveform, demodulate_ofdm
from .base import CalResult
from .sync import align_delay, compensate_delay


def _tx_evm_now(tx: TxChain, wf: OFDMWaveform, drive_scale: float,
                n_warmup: int = 512, n_guard: int = 64) -> float:
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
    syms = correct_cpe(syms, ref)
    return evm(syms, ref, equalize="per_tone").db


def _observation_fn(tx: TxChain, rx: RxChain, path: LoopbackPath,
                    n_warmup: int = 512):
    """Raw chain (DPD bypassed) as the callable AdaptiveDPD adapts against."""

    def pa_fn(u: np.ndarray) -> np.ndarray:
        saved = tx.dpd
        tx.dpd = None
        try:
            up = np.concatenate([u[-n_warmup:], u, u[:64]])
            cap = run_loopback(tx, rx, up, path)
            _, _, info = align_delay(up, cap, max_lag=32)
            cap = compensate_delay(cap, info["lag_total"], n_warmup, len(u))
        finally:
            tx.dpd = saved
        return cap

    return pa_fn


def _pin_observation(tx: TxChain, rx: RxChain, x: np.ndarray,
                     path: LoopbackPath) -> tuple:
    """Set the receiver to the calibration observation state for the
    coupled level of ``x``, as the DPD step does, and return the AGC
    state to restore.  Without it the tracker observes in whatever gain
    state the previous measurement left: the first version did, inherited
    the receive figures' high-gain states 7 and 3 instead of 4, and
    learned a 20 MHz part to -14.9 dB EVM at 85 degC from a clipped
    capture."""
    from ..units import power_dbm
    saved = (rx.lna_idx, rx.vga_db)
    rx.agc_pinned(power_dbm(tx(x)) - path.atten_db, CAL_OBSERVATION_STATE)
    return saved


def tracking_adapter(tx: TxChain, rx: RxChain, x: np.ndarray,
                     path: LoopbackPath, order: int = 7,
                     memory_depth: int = 5, forget: float = 0.4,
                     warm_blocks: int = 3) -> AdaptiveDPD:
    """An RLS tracker converged on the chain as it is now.

    This is the runtime loop a part runs when DPD tracking is enabled:
    warm-started from pass-through against the raw chain (the programmed
    predistorter bypassed), at the GMP order and memory of the one-shot
    ILA, with the per-block forgetting ``track_dpd`` uses.  The receive
    LPF is lifted for the wideband observation and put back, as in
    ``track_dpd``.  Does not touch ``tx.dpd``.
    """
    agc = _pin_observation(tx, rx, x, path)
    lpf_was = rx.params.lpf.enabled
    rx.params.lpf.enabled = False
    try:
        adpd = AdaptiveDPD(model_factory=lambda: GMPModel(
            order=order, memory_depth=memory_depth), forget=forget,
            method="rls")
        adpd.warm_start(_observation_fn(tx, rx, path), x, blocks=warm_blocks)
    finally:
        rx.params.lpf.enabled = lpf_was
        rx.lna_idx, rx.vga_db = agc
    return adpd


def tracked_update(adpd: AdaptiveDPD, tx: TxChain, rx: RxChain,
                   x: np.ndarray, path: LoopbackPath,
                   updates: int = 3) -> dict:
    """Let the tracker follow the chain for ``updates`` blocks, then
    program it: ``tx.dpd`` becomes the tracker's predistorter.  Returns
    the last block's metrics (``resid_db`` is the post-inverse fit
    residual)."""
    # the level moves with the driver-gain drift, so the pin is re-taken
    # at every temperature rather than inherited from the warm start
    agc = _pin_observation(tx, rx, x, path)
    lpf_was = rx.params.lpf.enabled
    rx.params.lpf.enabled = False
    info: dict = {}
    try:
        pa_fn = _observation_fn(tx, rx, path)
        for _ in range(int(updates)):
            info = adpd.update(pa_fn, x)
    finally:
        rx.params.lpf.enabled = lpf_was
        rx.lna_idx, rx.vga_db = agc
    tx.dpd = adpd.predistort
    return info


def track_dpd(tx: TxChain, rx: RxChain, wf: OFDMWaveform,
              drift_schedule: np.ndarray, path: LoopbackPath | None = None,
              drive_scale: float = 0.15, order: int = 7,
              memory_depth: int = 5, forget: float = 0.4,
              updates_per_state: int = 3, warm_blocks: int = 3,
              compare_frozen: bool = True) -> CalResult:
    # forget is applied per BLOCK (thousands of samples each), not per
    # sample: aggressive forgetting is statistically safe and necessary,
    # otherwise stale pre-drift data dominates the RLS covariance and the
    # tracker lags the PA by tens of dB.  Raise it toward ~0.9 only if the
    # observation path is very noisy (coefficient noise averaging).
    """Advance ``tx.pa`` through ``drift_schedule`` (states in [0,1]),
    updating the RLS DPD each step; returns per-step EVM traces.

    Requires ``tx.pa`` to expose ``set_state`` (DriftingScaledPA).
    """
    if path is None:
        path = LoopbackPath(atten_db=40.0, delay_ns=6.0)
    if not hasattr(tx.pa, "set_state"):
        raise TypeError("track_dpd needs a drifting PA (DriftingScaledPA)")
    x = wf.x * drive_scale

    # wideband observation for DPD adaptation
    lpf_was = rx.params.lpf.enabled
    rx.params.lpf.enabled = False
    pa_fn = _observation_fn(tx, rx, path)

    tx.pa.set_state(float(drift_schedule[0]))
    adpd = AdaptiveDPD(model_factory=lambda: GMPModel(order=order,
                                                      memory_depth=memory_depth),
                       forget=forget, method="rls")
    adpd.warm_start(pa_fn, x, blocks=warm_blocks)
    tx.dpd = adpd.predistort
    frozen = adpd.as_model() if compare_frozen else None

    evm_track, evm_frozen, resid = [], [], []
    for state in drift_schedule:
        tx.pa.set_state(float(state))
        for _ in range(updates_per_state):
            info = adpd.update(pa_fn, x)
        resid.append(info["resid_db"])
        tx.dpd = adpd.predistort
        evm_track.append(_tx_evm_now(tx, wf, drive_scale))
        if frozen is not None:
            tx.dpd = frozen
            evm_frozen.append(_tx_evm_now(tx, wf, drive_scale))
            tx.dpd = adpd.predistort

    # Oracle: a freshly converged DPD at the final state — the achievable
    # floor there.  The PA genuinely gets harder as it drifts (compression
    # point moves at fixed drive), so absolute EVM degradation is physics;
    # tracking quality = staying close to this floor.
    oracle = AdaptiveDPD(model_factory=lambda: GMPModel(order=order,
                                                        memory_depth=memory_depth),
                         forget=forget, method="rls")
    oracle.warm_start(pa_fn, x, blocks=warm_blocks)
    tx.dpd = oracle.predistort
    evm_oracle_final = _tx_evm_now(tx, wf, drive_scale)
    tx.dpd = adpd.predistort

    rx.params.lpf.enabled = lpf_was
    metrics_after = {
        "evm_track_final_db": float(evm_track[-1]),
        "evm_oracle_final_db": float(evm_oracle_final),
        "track_vs_oracle_db": float(evm_track[-1] - evm_oracle_final),
        "evm_track_worst_db": float(np.max(evm_track)),
    }
    if evm_frozen:
        metrics_after["evm_frozen_worst_db"] = float(np.max(evm_frozen))
    return CalResult(
        name="dpd_tracking",
        estimated={"order": order, "memory_depth": memory_depth,
                   "forget": forget},
        trace=[{"state": float(s), "evm_track_db": float(et),
                "evm_frozen_db": (float(ef) if evm_frozen else None),
                "resid_db": float(r)}
               for s, et, ef, r in zip(
                   drift_schedule, evm_track,
                   evm_frozen or [np.nan] * len(evm_track), resid)],
        metrics_before={"evm_at_state0_db": float(evm_track[0])},
        metrics_after=metrics_after,
        passed=metrics_after["track_vs_oracle_db"] < 2.0,
    )
