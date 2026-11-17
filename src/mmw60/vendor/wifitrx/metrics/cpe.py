# Vendored from wifi_trx_cal@a8edf503df74cf11d6069a6354c4c0ddbf6e82d1: src/wifitrx/metrics/cpe.py
# Adapted-copy policy: see src/mmw60/vendor/__init__.py
"""Per-symbol common phase error (CPE) removal for EVM measurement.

Modems track the common phase rotation of each OFDM symbol from pilot
tones; EVM against the standard is therefore measured after CPE removal.

Two estimators live here.  ``correct_cpe`` is a genie: it fits the
rotation on every subcarrier against the ideal reference, so its own
estimation noise is negligible and what it leaves behind is the ICI
floor of the phase noise itself.  ``correct_cpe_pilots`` is the modem's
form — N_p known pilots only — and carries the pilot estimator's noise
onto every data subcarrier as a common-mode error.  The gap between the
two is a mechanism, not a bug; the phase-noise/CPE study measures it.

The genie's "negligible" holds only on a flat channel.  It weights each
subcarrier by |X_k|^2, so where the channel phase varies across the band
the estimate moves with the constellation amplitudes, which differ from
symbol to symbol; a per-tone equaliser fitted over all symbols cannot
take that back out.  ``correct_cpe_equalized`` equalises each tone first
and is what every isolation reading uses since 0.7.45 (B46).
"""
from __future__ import annotations

import numpy as np


def correct_cpe(rx_symbols: np.ndarray, ref_symbols: np.ndarray) -> np.ndarray:
    """Rotate each OFDM symbol by its LS common phase vs the reference."""
    rx = np.asarray(rx_symbols, dtype=complex)
    ref = np.asarray(ref_symbols, dtype=complex)
    out = rx.copy()
    for i in range(rx.shape[0]):
        acc = np.vdot(rx[i], ref[i])
        if abs(acc) > 0:
            out[i] = rx[i] * (acc / abs(acc))
    return out


def correct_cpe_equalized(rx_symbols: np.ndarray,
                          ref_symbols: np.ndarray) -> np.ndarray:
    """Per-tone LS equalisation over all symbols, then each symbol's common
    phase against the reference.

    The order matters (B46): estimating the common phase on unequalised
    symbols weights each tone's channel phase by |X_k|^2, so a channel
    whose phase is not flat across the band -- the RX and TX channel
    filters' band edges, a residual delay -- makes the estimate jitter
    with the constellation amplitudes from symbol to symbol.  On a
    constant-modulus constellation, or a flat channel, the two orders give
    the same answer bit for bit; with 256-QAM on 108 tones behind the
    loopback's two filters the old order read 2.6-2.7 dB worse.
    """
    rx = np.asarray(rx_symbols, dtype=complex)
    ref = np.asarray(ref_symbols, dtype=complex)
    h = (np.sum(rx * np.conj(ref), axis=0)
         / np.maximum(np.sum(np.abs(ref) ** 2, axis=0), 1e-300))
    h = np.where(np.abs(h) > 0, h, 1.0)
    return correct_cpe(rx / h, ref)


def correct_cpe_pilots(rx_symbols: np.ndarray, pilot_cols: np.ndarray,
                       pilots: np.ndarray) -> np.ndarray:
    """Rotate each OFDM symbol by the LS common phase of its pilots only.

    ``pilot_cols`` index the pilot tones along the n_active axis and
    ``pilots`` (n_symbols, n_pilots) are their known values — the same
    inputs the tracking loop reads.  Same arithmetic as ``correct_cpe``
    restricted to the pilot set, so the two differ only by how many
    tones the estimate averages over.
    """
    rx = np.asarray(rx_symbols, dtype=complex)
    pil = np.asarray(pilots, dtype=complex)
    cols = np.asarray(pilot_cols, dtype=int)
    out = rx.copy()
    for i in range(rx.shape[0]):
        acc = np.vdot(rx[i, cols], pil[i])
        if abs(acc) > 0:
            out[i] = rx[i] * (acc / abs(acc))
    return out
