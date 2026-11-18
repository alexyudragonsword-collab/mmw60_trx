"""The training fields of a single-channel, single-stream EDMG OFDM PPDU.

An EDMG OFDM PPDU sends its legacy part (L-STF, L-CEF, the headers) at the
1.76 GHz chip rate and everything from the EDMG-STF on at the 2.64 GHz OFDM
rate; the data's channel is estimated on the EDMG-CEF (spec_sources#48:
``edmg.ofdm_ppdu_ncb1``).  This module builds the two OFDM-rate fields from
the standard's sequences and estimates the channel on the second:

* EDMG-STF (``edmg.ofdm_stf_ncb1``): 88 tones, every fourth one, so the
  field repeats every 128 samples; 30 periods, no guard interval;
* EDMG-CEF (``edmg.ofdm_cef_ncb1``): the same unit-modulus sequence on all
  352 used tones, sent twice with the signs of the mapping matrix
  P = [+1, −1], each symbol behind the long guard interval.

Both are scaled like the data symbols (``ay.ofdm``): unit average power per
sample, a tone value of 1 after ``_time_to_bins``.

The estimate: least squares per tone on the two symbols, then — the
receiver's own noise reduction, assumed.ay_receiver — the impulse response
held to the guard interval plus an eighth of pre-cursor.  The response is
only seen on 352 of the 512 bins, so "held to L taps" is a least-squares
fit of L taps to the used tones, and that fit is ill-conditioned: L taps
seen through 352 / 512 of the band span about L·352/512 directions, the
rest are combinations of taps with almost no response in band.  The fit
keeps the directions whose singular value is above ``rcond`` of the
largest (the spectrum falls a decade every two directions there, so the
count hardly depends on it) and drops the others.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np

from .. import spec
from .ofdm import OfdmNumerology

_SYMBOL = {"0": 0.0, "+1": 1.0, "-1": -1.0, "+j": 1j, "-j": -1j}


def sequence(key: str) -> tuple[np.ndarray, np.ndarray]:
    """(k, value) of a field's frequency-domain sequence: k = k_first … k_last,
    [left 176 | three zeros | right 176] (spec_sources#48)."""
    e = spec.value(key)
    left = [_SYMBOL[t] for t in str(e["seq1_left"]).split()]
    right = [_SYMBOL[t] for t in str(e["seq1_right"]).split()]
    k = np.arange(int(e["k_first"]), int(e["k_last"]) + 1)
    v = np.array(left + [0.0] * (k.size - len(left) - len(right)) + right, dtype=complex)
    if (len(left), len(right), k.size - len(left) - len(right)) != (176, 176, 3):
        raise ValueError(f"{key}: expected 176 values, three zeros and 176 values")
    return k, v


def cef_values(num: OfdmNumerology) -> np.ndarray:
    """The EDMG-CEF value of each used tone, in ``num.used_tones`` order."""
    k, v = sequence("edmg.ofdm_cef_ncb1")
    if not np.array_equal(k[v != 0], num.used_tones):
        raise ValueError("the EDMG-CEF is not on this numerology's used tones")
    return v[v != 0]


def _long_gi() -> int:
    return int(spec.ref("edmg.ofdm_ppdu_ncb1#n_gi@gi_order=long"))


def _cef_signs() -> np.ndarray:
    p = np.asarray(spec.value("edmg.ofdm_cef_ncb1")["p_matrix_nsts1"], dtype=float)
    if p.size != int(spec.ref("edmg.ofdm_ppdu_ncb1#n_edmg_cef_symbols@n_sts=1")):
        raise ValueError("the EDMG-CEF mapping matrix and its symbol count disagree")
    return p


def cef_field(num: OfdmNumerology) -> np.ndarray:
    """The EDMG-CEF in time: one symbol per entry of P, each [long GI | n_fft]."""
    f = np.zeros(num.n_fft, dtype=complex)
    f[num.bins(num.used_tones)] = cef_values(num)
    t = np.fft.ifft(f) * num.n_fft / np.sqrt(len(num.used_tones))
    gi = _long_gi()
    sym = np.concatenate([t[num.n_fft - gi:], t])
    if sym.size != int(spec.value("edmg.ofdm_ppdu_ncb1")["edmg_cef_samples_per_symbol"]):
        raise ValueError("the EDMG-CEF symbol is not the length edmg.ofdm_ppdu_ncb1 gives")
    return np.concatenate([s * sym for s in _cef_signs()])


def stf_field(num: OfdmNumerology) -> tuple[np.ndarray, int, int]:
    """(samples, period, periods) of the EDMG-STF."""
    e = spec.value("edmg.ofdm_stf_ncb1")
    k, v = sequence("edmg.ofdm_stf_ncb1")
    on = k[v != 0]
    step = int(np.gcd.reduce(on))
    if on.size != int(e["n_tone"]) or num.n_fft % step:
        raise ValueError("the EDMG-STF tones are not the comb edmg.ofdm_stf_ncb1 describes")
    f = np.zeros(num.n_fft, dtype=complex)
    f[num.bins(k)] = v
    t = np.fft.ifft(f) * num.n_fft / np.sqrt(on.size)
    period, n = num.n_fft // step, int(e["n_periods"])
    if period * n != int(spec.value("edmg.ofdm_ppdu_ncb1")["edmg_stf_samples"]):
        raise ValueError("the EDMG-STF is not the length edmg.ofdm_ppdu_ncb1 gives")
    return np.tile(t[:period], n), period, n


@lru_cache(maxsize=8)
def _basis(n_fft: int, tones: tuple, keep: int, pre: int, rcond: float) -> np.ndarray:
    taps = np.concatenate([np.arange(keep), np.arange(-pre, 0)])
    a = np.exp(-2j * np.pi * np.outer(np.asarray(tones), taps) / n_fft)
    u, s, _ = np.linalg.svd(a, full_matrices=False)
    return u[:, s > rcond * s[0]]


def window_basis(num: OfdmNumerology, keep: int, pre: int, rcond: float) -> np.ndarray:
    """Orthonormal columns spanning, on the used tones, the responses of the
    first ``keep`` and last ``pre`` taps that the band can tell apart
    (singular value above ``rcond`` of the largest)."""
    return _basis(num.n_fft, tuple(int(k) for k in num.used_tones), int(keep), int(pre), float(rcond))


def cef_least_squares(num: OfdmNumerology, rx: np.ndarray, start: int = 0) -> np.ndarray:
    """H per used tone from the EDMG-CEF starting at ``start``: Σ P_i·Y_i / (n·CEF)."""
    gi, p = _long_gi(), _cef_signs()
    step = num.n_fft + gi
    idx = int(start) + np.arange(p.size)[:, None] * step + gi + np.arange(num.n_fft)[None, :]
    y = np.fft.fft(np.asarray(rx)[idx], axis=1) * np.sqrt(len(num.used_tones)) / num.n_fft
    return (p[:, None] * y[:, num.bins(num.used_tones)]).mean(axis=0) / cef_values(num)


def cef_estimate(num: OfdmNumerology, rx: np.ndarray, start: int = 0, keep: int | None = None, pre: int = 0,
                 rcond: float = 1e-3) -> np.ndarray:
    """H per used tone (``num.used_tones`` order).  ``keep`` None = the
    per-tone least squares as it is; otherwise its fit by ``window_basis``."""
    h = cef_least_squares(num, rx, start)
    if keep is None:
        return h
    u = window_basis(num, keep, pre, rcond)
    return u @ (u.conj().T @ h)


def estimate_noise_gain(num: OfdmNumerology, keep: int | None, pre: int = 0, rcond: float = 1e-3) -> np.ndarray:
    """Per used tone, the estimate's noise power over the noise power of one
    data tone of one symbol (the two CEF symbols halve it; the fit leaves
    each tone the diagonal of its projector)."""
    n_sym = _cef_signs().size
    if keep is None:
        return np.full(len(num.used_tones), 1.0 / n_sym)
    u = window_basis(num, keep, pre, rcond)
    return np.sum(np.abs(u) ** 2, axis=1) / n_sym


__all__ = ["sequence", "cef_values", "cef_field", "stf_field", "window_basis", "cef_least_squares",
           "cef_estimate", "estimate_noise_gain"]
