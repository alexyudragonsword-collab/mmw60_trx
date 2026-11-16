"""Golay complementary pairs.

The recursive construction (Budisin; the form 802.11ad writes its Ga / Gb
sequences in):

    a_0(n) = b_0(n) = δ(n)
    a_k(n) = W_k · a_{k-1}(n) + b_{k-1}(n − D_k)
    b_k(n) = W_k · a_{k-1}(n) − b_{k-1}(n − D_k)

with D a permutation of 1, 2, 4, …, 2^(K−1) and W_k ∈ {±1, ±j}.  The pair
(a_K, b_K) has length 2^K and aperiodic autocorrelations that sum to
2·2^K at lag 0 and to zero elsewhere — the property the guard interval, the
channel estimate and the CFO estimate lean on.  Which D / W the standard
uses is a spec number (spec_sources#29); this module takes them as given.
"""
from __future__ import annotations

import numpy as np


def golay_pair(delays, weights) -> tuple[np.ndarray, np.ndarray]:
    """(a, b), each of length 2^K, K = len(delays)."""
    d = [int(x) for x in delays]
    w = [complex(x) for x in weights]
    if len(d) != len(w) or not d:
        raise ValueError("delays and weights must be non-empty and of the same length")
    k = len(d)
    if sorted(d) != [1 << i for i in range(k)]:
        raise ValueError(f"delays must be a permutation of 1, 2, …, 2^{k - 1}; got {d}")
    if any(abs(abs(x) - 1.0) > 1e-12 or min(abs(x.real), abs(x.imag)) > 1e-12 for x in w):
        raise ValueError(f"weights must be ±1 or ±j; got {w}")
    n = 1 << k
    a = np.zeros(n, dtype=complex)
    b = np.zeros(n, dtype=complex)
    a[0] = b[0] = 1.0
    for dk, wk in zip(d, w):
        shifted = np.roll(b, dk)          # b_{k-1}(n − D_k); support ⊂ [0, ΣD] = [0, 2^K − 1]: no wrap
        a, b = wk * a + shifted, wk * a - shifted
    if all(x.imag == 0 for x in w):
        return a.real.copy(), b.real.copy()
    return a, b


def aperiodic_autocorr(x: np.ndarray) -> np.ndarray:
    """R(τ) = Σ_n x(n + τ)·conj(x(n)) for τ = −(N−1) … N−1."""
    x = np.asarray(x)
    return np.correlate(x, x, mode="full")


def is_complementary(a: np.ndarray, b: np.ndarray, atol: float = 1e-9) -> bool:
    """True when R_a + R_b is 2N at lag 0 and zero at every other lag."""
    s = aperiodic_autocorr(a) + aperiodic_autocorr(b)
    n = len(a)
    want = np.zeros_like(s)
    want[n - 1] = 2 * n
    return len(a) == len(b) and bool(np.allclose(s, want, atol=atol))


def repeated(seq: np.ndarray, n: int) -> np.ndarray:
    """``seq`` repeated n times — a training field whose lag-len(seq)
    autocorrelation gives the CFO over ±fs / (2·len(seq))
    (``rx.cfo.stf_coarse_cfo`` with ``period = len(seq)``)."""
    return np.tile(np.asarray(seq), int(n))
