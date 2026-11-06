"""Binary convolutional code of 802.11 (K = 7, g0 = 133₈, g1 = 171₈), puncturing and a
soft-decision Viterbi decoder.

Two decoder kernels compute the same add-compare-select in the same
floating-point order: a numpy one (vectorised over the 64 states per trellis
step) and a numba one (scalar loops).  numba is a performance layer, not a
correctness layer — with ``MMW60_NO_JIT=1`` or without numba installed the
numpy kernel runs and the decoded bits are identical (``tests/test_phy.py``).

LLR convention: positive means bit 0 is more likely.  The path cost of a
coded bit ``c`` with LLR ``l`` is ``c * l`` (max-log ML); punctured
positions carry ``l = 0``.
"""
from __future__ import annotations

import os

import numpy as np

G0, G1 = 0o133, 0o171
K = 7
N_STATES = 1 << (K - 1)
N_TAIL = K - 1

PUNCTURE = {
    (1, 2): np.array([1, 1], dtype=bool),
    (2, 3): np.array([1, 1, 1, 0], dtype=bool),
    (3, 4): np.array([1, 1, 1, 0, 0, 1], dtype=bool),
    (5, 6): np.array([1, 1, 1, 0, 0, 1, 1, 0, 0, 1], dtype=bool),
}


def jit_enabled() -> bool:
    if os.environ.get("MMW60_NO_JIT", "") not in ("", "0"):
        return False
    try:
        import numba  # noqa: F401
    except Exception:
        return False
    return True


def _parity(x: int) -> int:
    return bin(x).count("1") & 1


def _tables():
    """Predecessor tables: for new state ``ns`` and branch ``j`` the previous
    state and the two coded bits of that transition.  State = the last six
    input bits, newest in the MSB; the input bit of a transition into ``ns``
    is ``ns >> 5``."""
    prev = np.zeros((N_STATES, 2), dtype=np.int64)
    out_a = np.zeros((N_STATES, 2), dtype=np.float64)
    out_b = np.zeros((N_STATES, 2), dtype=np.float64)
    for ns in range(N_STATES):
        u = ns >> 5
        for j in (0, 1):
            s = ((ns & 0x1F) << 1) | j
            w = (u << 6) | s
            prev[ns, j] = s
            out_a[ns, j] = _parity(w & G0)
            out_b[ns, j] = _parity(w & G1)
    return prev, out_a, out_b


PREV, OUT_A, OUT_B = _tables()
_TAPS0 = np.array([(G0 >> (6 - i)) & 1 for i in range(7)], dtype=np.int64)
_TAPS1 = np.array([(G1 >> (6 - i)) & 1 for i in range(7)], dtype=np.int64)


def encode(bits: np.ndarray) -> np.ndarray:
    """Rate-1/2 BCC; output interleaved A0 B0 A1 B1 ... (the input must already
    end in the six tail zeros that return the encoder to state 0)."""
    x = np.asarray(bits, dtype=np.int64)
    a = np.convolve(x, _TAPS0)[:x.size] & 1
    b = np.convolve(x, _TAPS1)[:x.size] & 1
    return np.stack([a, b], axis=1).reshape(-1).astype(np.uint8)


def puncture(coded: np.ndarray, rate) -> np.ndarray:
    mask = PUNCTURE[tuple(rate)]
    n = coded.size
    reps = -(-n // mask.size)
    keep = np.tile(mask, reps)[:n]
    return coded[keep]


def depuncture(llr: np.ndarray, rate, n_coded: int) -> np.ndarray:
    """Insert zero LLRs at the punctured positions; returns ``n_coded`` values."""
    mask = PUNCTURE[tuple(rate)]
    reps = -(-n_coded // mask.size)
    keep = np.tile(mask, reps)[:n_coded]
    if int(keep.sum()) != llr.size:
        raise ValueError(f"expected {int(keep.sum())} LLRs for {n_coded} coded bits at rate "
                         f"{rate[0]}/{rate[1]}, got {llr.size}")
    out = np.zeros(n_coded, dtype=np.float64)
    out[keep] = llr
    return out


def n_coded_bits(n_info: int, rate) -> int:
    """Coded bits after puncturing for ``n_info`` encoder input bits."""
    mask = PUNCTURE[tuple(rate)]
    n = 2 * n_info
    reps = -(-n // mask.size)
    return int(np.tile(mask, reps)[:n].sum())


# ---------------------------------------------------------------- decoders
def _viterbi_numpy(llr2: np.ndarray) -> np.ndarray:
    n = llr2.shape[0]
    big = 1e30
    metric = np.full(N_STATES, big)
    metric[0] = 0.0
    dec = np.zeros((n, N_STATES), dtype=np.uint8)
    p0, p1 = PREV[:, 0], PREV[:, 1]
    a0, a1, b0, b1 = OUT_A[:, 0], OUT_A[:, 1], OUT_B[:, 0], OUT_B[:, 1]
    for t in range(n):
        la = llr2[t, 0]
        lb = llr2[t, 1]
        c0 = metric[p0] + (a0 * la + b0 * lb)
        c1 = metric[p1] + (a1 * la + b1 * lb)
        sel = c1 < c0
        metric = np.where(sel, c1, c0)
        dec[t] = sel
    return _traceback(dec)


def _traceback(dec: np.ndarray) -> np.ndarray:
    n = dec.shape[0]
    bits = np.empty(n, dtype=np.uint8)
    s = 0
    for t in range(n - 1, -1, -1):
        j = int(dec[t, s])
        bits[t] = s >> 5
        s = int(PREV[s, j])
    return bits


_viterbi_numba = None
if jit_enabled():
    try:
        import numba

        @numba.njit(cache=True)
        def _acs_numba(llr2, prev, out_a, out_b, dec):     # pragma: no cover (jit)
            n = llr2.shape[0]
            big = 1e30
            metric = np.full(N_STATES, big)
            metric[0] = 0.0
            new = np.empty(N_STATES)
            for t in range(n):
                la = llr2[t, 0]
                lb = llr2[t, 1]
                for ns in range(N_STATES):
                    c0 = metric[prev[ns, 0]] + (out_a[ns, 0] * la + out_b[ns, 0] * lb)
                    c1 = metric[prev[ns, 1]] + (out_a[ns, 1] * la + out_b[ns, 1] * lb)
                    if c1 < c0:
                        new[ns] = c1
                        dec[t, ns] = 1
                    else:
                        new[ns] = c0
                        dec[t, ns] = 0
                for ns in range(N_STATES):
                    metric[ns] = new[ns]
            # traceback
            bits = np.empty(n, dtype=np.uint8)
            s = 0
            for t in range(n - 1, -1, -1):
                j = dec[t, s]
                bits[t] = s >> 5
                s = prev[s, j]
            return bits

        def _viterbi_numba(llr2: np.ndarray) -> np.ndarray:
            dec = np.zeros((llr2.shape[0], N_STATES), dtype=np.uint8)
            return _acs_numba(np.ascontiguousarray(llr2, dtype=np.float64), PREV, OUT_A,
                              OUT_B, dec)
    except Exception:          # numba present but unusable: fall back silently
        _viterbi_numba = None


def viterbi_decode(llr_coded: np.ndarray, kernel: str | None = None) -> np.ndarray:
    """Decode rate-1/2 coded LLRs (A0 B0 A1 B1 ..., punctured positions already
    zero) into the input bits, tail included.  ``kernel`` forces
    ``"numpy"`` / ``"numba"``; default picks numba when available."""
    llr2 = np.asarray(llr_coded, dtype=np.float64).reshape(-1, 2)
    if kernel is None:
        kernel = "numba" if _viterbi_numba is not None else "numpy"
    if kernel == "numba":
        if _viterbi_numba is None:
            raise RuntimeError("numba kernel requested but not available")
        return _viterbi_numba(llr2)
    if kernel == "numpy":
        return _viterbi_numpy(llr2)
    raise ValueError(f"unknown kernel {kernel!r}")


def active_kernel() -> str:
    return "numba" if _viterbi_numba is not None else "numpy"
