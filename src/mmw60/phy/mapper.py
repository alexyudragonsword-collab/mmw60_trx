"""Bit ↔ constellation mapping with max-log LLRs.

QAM orders 4 and up use wifitrx's Gray constellation (``waveform/qam.py``,
unit average power, the first bit of a group being the MSB of the label,
which is the 802.11 bit order: b0 b1 → I, b2 b3 → Q for 16-QAM).  BPSK,
which wifitrx does not have, is ``2b − 1``.  ``tests/test_phy.py`` checks
the QPSK / 16-QAM points are wifitrx's exactly.
"""
from __future__ import annotations

import numpy as np

from ..vendor.wifitrx.waveform.qam import qam_constellation

_CACHE: dict[int, tuple[np.ndarray, np.ndarray]] = {}


def constellation(order: int) -> tuple[np.ndarray, np.ndarray]:
    """(points indexed by label, bits[label, position]) — position 0 is the
    first transmitted bit of the group (the MSB of the label).  Orders 4 …
    4096 are wifitrx's (``qam._SUPPORTED``), 2 is BPSK."""
    if order not in _CACHE:
        if order == 2:
            pts = np.array([-1.0 + 0j, 1.0 + 0j])
        else:
            pts = qam_constellation(order)
        m = int(round(np.log2(order)))
        labels = np.arange(order)
        bits = ((labels[:, None] >> (m - 1 - np.arange(m))[None, :]) & 1).astype(np.uint8)
        _CACHE[order] = (pts, bits)
    return _CACHE[order]


def bits_per_symbol(order: int) -> int:
    return int(round(np.log2(order)))


def map_bits(bits: np.ndarray, order: int) -> np.ndarray:
    """Groups of log2(order) bits → complex points (first bit = MSB)."""
    m = bits_per_symbol(order)
    b = np.asarray(bits, dtype=np.int64).reshape(-1, m)
    labels = (b << (m - 1 - np.arange(m))[None, :]).sum(axis=1)
    pts, _ = constellation(order)
    return pts[labels]


#: orders whose LLRs are computed over the full 2-D constellation (the
#: milestone-0 arithmetic, kept bit for bit); above it the axis-separable form
SEPARABLE_ABOVE = 256


def llr(points: np.ndarray, order: int, weight: np.ndarray | float = 1.0) -> np.ndarray:
    """Max-log LLRs, positive = bit 0 likely; shape (n_points, m) flattened
    in transmission order.  ``weight`` scales each point's LLRs (use
    |H|²/σ² after zero-forcing: the per-tone inverse noise variance).

    For 1024- / 4096-QAM the search is done per axis: wifitrx's Gray square
    constellation puts the first m/2 bits on I and the rest on Q, so the
    max-log metric of an I bit is min over the I levels alone (the Q term
    is common to both hypotheses and cancels) — exact, and (n × 64) instead
    of (n × 4096) distances."""
    pts, bits = constellation(order)
    y = np.asarray(points, dtype=complex).reshape(-1)
    m = bits.shape[1]
    out = np.empty((y.size, m))
    big = np.inf
    if order > SEPARABLE_ABOVE:
        side = int(round(np.sqrt(order)))
        lev_i = pts[np.arange(side) * side].real            # label = i_idx * side + q_idx
        lev_q = pts[np.arange(side)].imag
        bits_i = bits[np.arange(side) * side, :m // 2]
        bits_q = bits[np.arange(side), m // 2:]
        for axis, (yy, lev, bb, off) in enumerate(((y.real, lev_i, bits_i, 0), (y.imag, lev_q, bits_q, m // 2))):
            d2 = (yy[:, None] - lev[None, :]) ** 2         # (n, side)
            for i in range(m // 2):
                is1 = bb[:, i].astype(bool)
                d0 = np.where(is1[None, :], big, d2).min(axis=1)
                d1 = np.where(is1[None, :], d2, big).min(axis=1)
                out[:, off + i] = d1 - d0
    else:
        d2 = np.abs(y[:, None] - pts[None, :]) ** 2        # (n, order)
        for i in range(m):
            is1 = bits[:, i].astype(bool)
            d0 = np.where(is1[None, :], big, d2).min(axis=1)
            d1 = np.where(is1[None, :], d2, big).min(axis=1)
            out[:, i] = d1 - d0
    w = np.asarray(weight, dtype=float).reshape(-1, 1) if np.ndim(weight) else float(weight)
    return (out * w).reshape(-1)


def llr_full_search(points: np.ndarray, order: int, weight: np.ndarray | float = 1.0) -> np.ndarray:
    """The 2-D form for any order (the reference the separable form is tested against)."""
    pts, bits = constellation(order)
    y = np.asarray(points, dtype=complex).reshape(-1)
    d2 = np.abs(y[:, None] - pts[None, :]) ** 2
    m = bits.shape[1]
    out = np.empty((y.size, m))
    for i in range(m):
        is1 = bits[:, i].astype(bool)
        d0 = np.where(is1[None, :], np.inf, d2).min(axis=1)
        d1 = np.where(is1[None, :], d2, np.inf).min(axis=1)
        out[:, i] = d1 - d0
    w = np.asarray(weight, dtype=float).reshape(-1, 1) if np.ndim(weight) else float(weight)
    return (out * w).reshape(-1)


def hard_bits(points: np.ndarray, order: int) -> np.ndarray:
    pts, bits = constellation(order)
    y = np.asarray(points, dtype=complex).reshape(-1)
    lab = np.abs(y[:, None] - pts[None, :]).argmin(axis=1)
    return bits[lab].reshape(-1)
