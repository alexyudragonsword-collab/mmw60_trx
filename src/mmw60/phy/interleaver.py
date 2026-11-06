"""802.11n/ac block interleaver, 20 MHz, one spatial stream (N_COL = 13, N_ROW = 4·N_BPSCS).

Two permutations (the third, the frequency rotation, applies only to
N_SS > 1).  ``permutation(n_bpscs)`` returns ``perm`` with the meaning
"input bit k goes to output position perm[k]".
"""
from __future__ import annotations

import numpy as np

N_COL_20 = 13


def permutation(n_bpscs: int, n_sd: int = 52, n_col: int = N_COL_20) -> np.ndarray:
    n_cbps = n_sd * n_bpscs
    n_row = n_cbps // n_col
    if n_row * n_col != n_cbps:
        raise ValueError("N_CBPS must be a multiple of N_COL")
    k = np.arange(n_cbps)
    i = n_row * (k % n_col) + k // n_col
    s = max(n_bpscs // 2, 1)
    j = s * (i // s) + (i + n_cbps - (n_col * i) // n_cbps) % s
    perm = np.asarray(j, dtype=np.int64)
    if np.unique(perm).size != n_cbps:
        raise AssertionError("interleaver permutation is not a bijection")
    return perm


def interleave(bits: np.ndarray, n_bpscs: int, n_sd: int = 52) -> np.ndarray:
    """Per-symbol interleave of a (n_symbols, N_CBPS) array (or flat multiple)."""
    perm = permutation(n_bpscs, n_sd)
    b = np.asarray(bits).reshape(-1, perm.size)
    out = np.empty_like(b)
    out[:, perm] = b
    return out.reshape(np.shape(bits))


def deinterleave(values: np.ndarray, n_bpscs: int, n_sd: int = 52) -> np.ndarray:
    perm = permutation(n_bpscs, n_sd)
    v = np.asarray(values).reshape(-1, perm.size)
    return v[:, perm].reshape(np.shape(values))
