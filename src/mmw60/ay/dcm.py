"""Dual-carrier modulation of the EDMG OFDM payload (MCS 1-10): two points
of every pair of data tones carry the same bits, spread by a 2 x 2 matrix
(edmg.ofdm_modulation_mapping, spec_sources#43; 17/1170r2, renamed by
18/0331r2 from SQPSK / QPSK).

* DCM BPSK (n_bpsc 1): bits c_2k, c_2k+1 -> x = 2c - 1;
  [d(k), d(P(k))] = (1/sqrt(2)) [[1, j], [1, -j]] [x_2k, x_2k+1];
* DCM QPSK (n_bpsc 2): bits c_4k .. c_4k+3 -> two QPSK points
  x_2k = ((2c_4k - 1) + j(2c_4k+2 - 1))/sqrt(2),
  x_2k+1 = ((2c_4k+1 - 1) + j(2c_4k+3 - 1))/sqrt(2);
  [d(k), d(P(k))] = (1/sqrt(5)) [[1, 2], [-2, 1]] [x_2k, x_2k+1];
* the static pairing P(k) = k + N_SD/2, k = 0 ... N_SD/2 - 1 (every mode
  supports it; the dynamic one is fed back by the receiver and not built);
* data index k on the data tones in ascending order (the mapping's
  tone_placement).

Both matrices are unitary, so every pair carries unit power and the tone
constellations are QPSK (DCM BPSK) and 16-QAM (DCM QPSK), the ``tone_order``
of the MCS table.  The demapper is the joint max-log over the pair's
2^(2 n_bpsc) hypotheses, so a pair whose two tones see different noise
(``weight`` per tone) is combined as it should be.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np

from .. import spec

#: the mapping's spec key (spec_sources#43)
DCM_KEY = "edmg.ofdm_modulation_mapping"


def pairs(n_sd: int) -> tuple[np.ndarray, np.ndarray]:
    """The static pairing: data indices k and P(k) = k + N_SD/2."""
    spec.value(DCM_KEY)  # the rule is read from there; fail loudly if the key goes
    n = int(n_sd)
    if n % 2:
        raise ValueError(f"DCM pairs the data tones: N_SD must be even, got {n}")
    k = np.arange(n // 2)
    return k, k + n // 2


def _pair_points(bits: np.ndarray, n_bpsc: int) -> tuple[np.ndarray, np.ndarray]:
    """(n_pairs, 2 n_bpsc) bits -> (d(k), d(P(k))) for every pair."""
    b = np.asarray(bits, dtype=np.int64)
    s = 2.0 * b - 1.0
    if n_bpsc == 1:
        x0, x1 = s[:, 0], s[:, 1]
        return (x0 + 1j * x1) / np.sqrt(2), (x0 - 1j * x1) / np.sqrt(2)
    if n_bpsc == 2:
        x0 = (s[:, 0] + 1j * s[:, 2]) / np.sqrt(2)
        x1 = (s[:, 1] + 1j * s[:, 3]) / np.sqrt(2)
        return (x0 + 2 * x1) / np.sqrt(5), (-2 * x0 + x1) / np.sqrt(5)
    raise ValueError(f"DCM is BPSK (n_bpsc 1) or QPSK (2), not n_bpsc {n_bpsc}")


def map_bits(bits: np.ndarray, n_bpsc: int, n_sd: int) -> np.ndarray:
    """Coded bits, symbol after symbol (N_SD * n_bpsc per symbol, pair k
    taking bits 2 n_bpsc k ... 2 n_bpsc (k + 1) - 1 of its symbol) ->
    (n_symbols, N_SD) data-tone points."""
    b = np.asarray(bits, dtype=np.int64).reshape(-1)
    per_sym = int(n_sd) * int(n_bpsc)
    if b.size % per_sym:
        raise ValueError(f"DCM carries {per_sym} bits per symbol; {b.size} is not a whole number of symbols")
    n_sym = b.size // per_sym
    k, pk = pairs(n_sd)
    dk, dp = _pair_points(b.reshape(n_sym * k.size, 2 * int(n_bpsc)), int(n_bpsc))
    out = np.empty((n_sym, int(n_sd)), dtype=complex)
    out[:, k] = dk.reshape(n_sym, -1)
    out[:, pk] = dp.reshape(n_sym, -1)
    return out


@lru_cache(maxsize=None)
def _hypotheses(n_bpsc: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    m = 2 * int(n_bpsc)
    hb = (np.arange(2 ** m)[:, None] >> (m - 1 - np.arange(m))[None, :]) & 1
    dk, dp = _pair_points(hb, int(n_bpsc))
    return hb.astype(bool), dk, dp


def llr(points: np.ndarray, n_bpsc: int, n_sd: int, weight: np.ndarray | float = 1.0) -> np.ndarray:
    """Max-log LLRs of the bits ``map_bits`` sent, positive = bit 0 likely
    (``phy.mapper.llr``'s convention), from the equalised data-tone points
    (n_symbols, N_SD).  ``weight``: the inverse noise variance, a scalar or
    one per data tone (n_symbols, N_SD) or (N_SD,)."""
    z = np.asarray(points, dtype=complex).reshape(-1, int(n_sd))
    k, pk = pairs(n_sd)
    w = (np.broadcast_to(np.asarray(weight, dtype=float), z.shape) if np.ndim(weight)
         else np.full(z.shape, float(weight)))
    zk, zp = z[:, k].reshape(-1), z[:, pk].reshape(-1)
    wk, wp = w[:, k].reshape(-1), w[:, pk].reshape(-1)
    hb, dk, dp = _hypotheses(int(n_bpsc))
    metric = (wk[:, None] * np.abs(zk[:, None] - dk[None, :]) ** 2
              + wp[:, None] * np.abs(zp[:, None] - dp[None, :]) ** 2)       # (n_pairs, 2^m)
    m = hb.shape[1]
    out = np.empty((zk.size, m))
    for i in range(m):
        d0 = np.where(hb[None, :, i], np.inf, metric).min(axis=1)
        d1 = np.where(hb[None, :, i], metric, np.inf).min(axis=1)
        out[:, i] = d1 - d0
    return out.reshape(-1)


__all__ = ["DCM_KEY", "pairs", "map_bits", "llr"]
