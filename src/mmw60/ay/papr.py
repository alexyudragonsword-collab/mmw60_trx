"""Peak-to-average power, interpolation, and the back-off a waveform needs.

PAPR is a property of the analog envelope, so the samples are interpolated
first: :func:`interpolate` is the ideal (band-limited, periodic) one, the
right reading for OFDM, whose spectrum ends at its outer tones; a
single-carrier waveform's envelope depends on its pulse, so :func:`shape`
upsamples with a root-raised-cosine and :func:`matched` undoes it at the
receiver.  The roll-off is not in the standard (only the spectral mask is):
the caller passes it, and when the ay rows are built it is an ``assumed``
entry with a sensitivity line (iron rule "assumptions visible").

:func:`obo_for_evm` answers the milestone-3 question on the shared PA: the
output back-off (from P_sat, ``pa.rapp.apply_pa_at_obo``) at which a
waveform's EVM after the PA meets a target.  The single-carrier waveform's
lower PAPR shows up as a smaller back-off, i.e. more average power out of
the same PA under the same EIRP cap.
"""
from __future__ import annotations

from typing import Callable

import numpy as np


def interpolate(x: np.ndarray, factor: int) -> np.ndarray:
    """Ideal band-limited interpolation by ``factor`` (zero-padding the
    spectrum of the whole record; treats the record as periodic)."""
    x = np.asarray(x, dtype=complex)
    n = x.size
    if factor == 1:
        return x.copy()
    f = np.fft.fft(x)
    half = n // 2
    out = np.zeros(n * factor, dtype=complex)
    out[:half] = f[:half]
    out[-(n - half):] = f[half:]
    return np.fft.ifft(out) * factor


def decimate(y: np.ndarray, factor: int) -> np.ndarray:
    """Inverse of :func:`interpolate`: keep the central 1/factor of the
    spectrum (an ideal low-pass at the original rate) and resample."""
    y = np.asarray(y, dtype=complex)
    if factor == 1:
        return y.copy()
    n = y.size // factor
    f = np.fft.fft(y[:n * factor])
    half = n // 2
    keep = np.concatenate([f[:half], f[-(n - half):]])
    return np.fft.ifft(keep) / factor


def rrc_taps(sps: int, rolloff: float, span: int) -> np.ndarray:
    """Root-raised-cosine taps over ``span`` symbols at ``sps`` samples per
    symbol, unit energy."""
    if not (0.0 < rolloff <= 1.0):
        raise ValueError("rolloff must be in (0, 1]")
    t = (np.arange(span * sps + 1) - span * sps / 2) / sps
    h = np.empty_like(t)
    b = rolloff
    for i, ti in enumerate(t):
        if abs(ti) < 1e-12:
            h[i] = 1.0 - b + 4 * b / np.pi
        elif abs(abs(ti) - 1 / (4 * b)) < 1e-9:
            h[i] = b / np.sqrt(2) * ((1 + 2 / np.pi) * np.sin(np.pi / (4 * b))
                                     + (1 - 2 / np.pi) * np.cos(np.pi / (4 * b)))
        else:
            h[i] = ((np.sin(np.pi * ti * (1 - b)) + 4 * b * ti * np.cos(np.pi * ti * (1 + b)))
                    / (np.pi * ti * (1 - (4 * b * ti) ** 2)))
    return h / np.sqrt(np.sum(h ** 2))


def shape(symbols: np.ndarray, sps: int, taps: np.ndarray) -> np.ndarray:
    """Upsample by ``sps`` and filter; unit average power for unit-power symbols."""
    s = np.asarray(symbols, dtype=complex).reshape(-1)
    up = np.zeros(s.size * sps, dtype=complex)
    up[::sps] = s
    return np.convolve(up, taps) * np.sqrt(sps)


def matched(y: np.ndarray, sps: int, taps: np.ndarray, n_symbols: int) -> np.ndarray:
    """Matched filter and symbol-rate sampling: the inverse of :func:`shape`
    for a waveform that went through it unchanged (up to the truncated
    pulse's own inter-symbol interference)."""
    z = np.convolve(np.asarray(y, dtype=complex), taps) / np.sqrt(sps)
    delay = len(taps) - 1
    return z[delay:delay + n_symbols * sps:sps]


def _power_ratio(x: np.ndarray) -> np.ndarray:
    p = np.abs(np.asarray(x)) ** 2
    return p / p.mean()


def ccdf(x: np.ndarray, levels_db) -> np.ndarray:
    """P(|x|² / mean |x|² > level) for each level (dB)."""
    r = _power_ratio(x)
    lv = 10.0 ** (np.asarray(levels_db, dtype=float) / 10.0)
    return np.array([np.mean(r > v) for v in np.atleast_1d(lv)])


def papr_db(x: np.ndarray, prob: float) -> float:
    """The instantaneous-to-mean power level (dB) exceeded by a fraction
    ``prob`` of the samples (prob → 0: the peak)."""
    r = _power_ratio(x)
    return float(10 * np.log10(np.quantile(r, 1.0 - prob)))


def obo_for_evm(pa, x: np.ndarray, measure: Callable[[np.ndarray], float], target_db: float,
                lo_db: float = 0.0, hi_db: float = 20.0, tol_db: float = 0.01,
                reference: str = "psat") -> float | None:
    """Output back-off (dB from ``reference``) at which ``measure(PA output)``
    — an EVM in dB — equals ``target_db``; ``lo_db`` when the PA already
    meets it there, None when not even ``hi_db`` does.  The PA output is
    ``apply_pa_at_obo``'s (renormalised by the drive and small-signal gain,
    so ``measure`` sees the waveform at its own scale)."""
    from ..pa.rapp import apply_pa_at_obo

    def at(obo):
        try:
            y = apply_pa_at_obo(pa, x, obo, reference=reference)[0]
        except RuntimeError:          # the PA cannot put out that mean power at any drive
            return np.inf
        return measure(y)

    if at(lo_db) <= target_db:
        return float(lo_db)
    if at(hi_db) > target_db:
        return None
    lo, hi = float(lo_db), float(hi_db)
    while hi - lo > tol_db:
        mid = 0.5 * (lo + hi)
        if at(mid) > target_db:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


__all__ = ["interpolate", "decimate", "rrc_taps", "shape", "matched", "ccdf", "papr_db", "obo_for_evm"]
