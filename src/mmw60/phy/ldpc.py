"""The 802.11 quasi-cyclic LDPC codes (n = 648 / 1296 / 1944, R = 1/2, 2/3, 3/4, 5/6):
parity-check matrices from the base matrices in ``data/spec/ldpc_80211.yaml``
(source survey: two independent public transcriptions of IEEE 802.11-2020
Annex F, identical entry for entry — :func:`mmw60.spec.ldpc_base_matrices`),
a systematic encoder, and a normalised min-sum decoder.

The same twelve codes serve 11n, 11ac, 11ax and 11be; 11be (EHT) carries
LDPC only, which is why the 11be bases of this library are coded with them
(``phy/eht.py``) and the 11ac 20 MHz base keeps its BCC.

Encoder: ``H = [H_s | H_p]`` with ``H_p`` the square parity part; the
parity bits are ``p = H_p^{-1} · H_s · s`` over GF(2), ``H_p^{-1}`` computed
once per code by Gaussian elimination and cached — the dual-diagonal
back-substitution the standard's structure allows is faster in hardware
but not needed here, and this form holds for any full-rank ``H_p``.
``tests/test_ldpc.py`` checks ``H · c = 0`` for every code.

Decoder: flooding normalised min-sum (scale ``alpha``, data/spec:
assumed.ldpc_minsum_scale), early stop on a zero syndrome.  Two kernels,
numpy (vectorised over codewords × check rows) and numba (scalar loops),
compute every operation in the same order — the variable-node total is a
sequential sum over a node's edges in both, the check node uses exact
min / second-min and a sign product, the only rounding is the one
``alpha × magnitude`` multiply — so the decoded bits are identical
(``MMW60_NO_JIT=1``; iron rule: numba is a performance layer, not a
correctness layer).  LLR convention is the library's: positive = bit 0.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from .. import spec

RATES = ("1/2", "2/3", "3/4", "5/6")
LENGTHS = (648, 1296, 1944)
#: known (shortened) bits enter the decoder with this magnitude (finite so
#: that inf − inf never appears in the extrinsic subtraction)
KNOWN_LLR = 1.0e6


def jit_enabled() -> bool:
    if os.environ.get("MMW60_NO_JIT", "") not in ("", "0"):
        return False
    try:
        import numba  # noqa: F401
    except Exception:
        return False
    return True


def _gf2_inverse(a: np.ndarray) -> np.ndarray:
    """Inverse of a square binary matrix over GF(2) (Gauss–Jordan)."""
    m = a.shape[0]
    aug = np.concatenate([a.astype(np.uint8) % 2, np.eye(m, dtype=np.uint8)], axis=1)
    for col in range(m):
        piv = col + np.flatnonzero(aug[col:, col])
        if piv.size == 0:
            raise ValueError("parity part of H is singular over GF(2)")
        p = int(piv[0])
        if p != col:
            aug[[col, p]] = aug[[p, col]]
        rows = np.flatnonzero(aug[:, col])
        rows = rows[rows != col]
        aug[rows] ^= aug[col]
    return aug[:, m:].copy()


@dataclass(frozen=True)
class LdpcCode:
    n: int
    rate: str
    z: int
    base: np.ndarray            # (m_b, 24) base matrix, -1 = zero block
    edge_row: np.ndarray        # (E,) check-node index of every edge, sorted by row
    edge_col: np.ndarray        # (E,) variable-node index of every edge
    row_edges: np.ndarray       # (m, dc_max) edge indices per check node, -1 padded
    col_edges: np.ndarray       # (n, dv_max) edge indices per variable node, -1 padded
    hs: np.ndarray              # (m, k) dense systematic part of H
    hp_inv: np.ndarray          # (m, m) inverse of the parity part over GF(2)

    @property
    def m(self) -> int:
        return self.n - self.k

    @property
    def k(self) -> int:
        num, den = (int(v) for v in self.rate.split("/"))
        return self.n * num // den

    @property
    def n_edges(self) -> int:
        return int(self.edge_row.size)

    # ------------------------------------------------------------ encode
    def encode(self, info: np.ndarray) -> np.ndarray:
        """(n_cw, k) information bits → (n_cw, n) systematic codewords."""
        s = np.asarray(info, dtype=np.uint8).reshape(-1, self.k)
        t = (s.astype(np.int64) @ self.hs.T.astype(np.int64)) % 2          # H_s · s
        p = (t @ self.hp_inv.T.astype(np.int64)) % 2                        # H_p^{-1} · t
        return np.concatenate([s, p.astype(np.uint8)], axis=1)

    def syndrome(self, bits: np.ndarray) -> np.ndarray:
        """(n_cw, m) parity checks of (n_cw, n) hard bits (0 = satisfied)."""
        b = np.asarray(bits, dtype=np.int64).reshape(-1, self.n)
        acc = np.zeros((b.shape[0], self.m), dtype=np.int64)
        np.add.at(acc.T, self.edge_row, b[:, self.edge_col].T)
        return (acc % 2).astype(np.uint8)

    # ------------------------------------------------------------ decode
    def decode(self, llr: np.ndarray, max_iter: int | None = None, alpha: float | None = None,
               kernel: str | None = None) -> tuple[np.ndarray, int]:
        """(n_cw, n) LLRs → ((n_cw, n) hard bits, iterations run)."""
        max_iter = int(spec.value("assumed.ldpc_max_iterations")) if max_iter is None else int(max_iter)
        alpha = float(spec.value("assumed.ldpc_minsum_scale")) if alpha is None else float(alpha)
        llr = np.ascontiguousarray(np.asarray(llr, dtype=np.float64).reshape(-1, self.n))
        k = kernel or ("numba" if jit_enabled() else "numpy")
        if k == "numba":
            fn = _numba_kernel()
            if fn is None:
                raise RuntimeError("numba kernel requested but numba is not available / disabled")
            return fn(llr, self.edge_row, self.edge_col, self.row_edges, self.col_edges, max_iter, alpha)
        if k != "numpy":
            raise ValueError("kernel must be numpy | numba")
        return _decode_numpy(llr, self.edge_row, self.edge_col, self.row_edges, self.col_edges, max_iter, alpha)


def _sign(x: np.ndarray) -> np.ndarray:
    """−1 where x < 0, +1 otherwise (zero counts as positive, like the scalar kernel)."""
    return np.where(x < 0, -1.0, 1.0)


def _decode_numpy(llr, edge_row, edge_col, row_edges, col_edges, max_iter, alpha):
    n_cw, n = llr.shape
    e_count = edge_row.size
    c2v = np.zeros((n_cw, e_count))
    row_mask = row_edges >= 0                        # (m, dc_max)
    re = np.where(row_mask, row_edges, 0)
    col_mask = col_edges >= 0                        # (n, dv_max)
    ce = np.where(col_mask, col_edges, 0)
    tot = llr.copy()
    hard = (tot < 0).astype(np.uint8)
    it = 0
    for it in range(1, max_iter + 1):
        # variable → check: extrinsic LLR per edge
        v2c = tot[:, edge_col] - c2v                 # (n_cw, E)
        # check nodes: min / second-min of magnitudes and the sign product per row
        mag = np.abs(v2c)[:, re]                     # (n_cw, m, dc_max)
        mag = np.where(row_mask[None], mag, np.inf)
        sg = _sign(v2c)[:, re]
        sg = np.where(row_mask[None], sg, 1.0)
        amin = mag.argmin(axis=2)                                               # (n_cw, m)
        min1 = np.take_along_axis(mag, amin[..., None], axis=2)[..., 0]
        mag2 = mag.copy()
        np.put_along_axis(mag2, amin[..., None], np.inf, axis=2)
        min2 = mag2.min(axis=2)
        prod = sg.prod(axis=2)                                                  # (n_cw, m)
        j = np.arange(row_edges.shape[1])[None, None, :]
        excl_min = np.where(j == amin[..., None], min2[..., None], min1[..., None])  # (n_cw, m, dc_max)
        excl_sign = prod[..., None] * sg
        new = alpha * excl_min
        new = np.where(excl_sign < 0, -new, new)
        c2v_new = np.empty_like(c2v)
        c2v_new[:, re[row_mask]] = new[:, row_mask]
        c2v = c2v_new
        # variable nodes: sequential sum over the node's edges (same order as the scalar kernel)
        tot = llr.copy()
        for d in range(col_edges.shape[1]):
            idx = ce[:, d]
            contrib = np.where(col_mask[:, d][None, :], c2v[:, idx], 0.0)
            tot = tot + contrib
        hard = (tot < 0).astype(np.uint8)
        # syndrome check
        acc = np.zeros((n_cw, row_edges.shape[0]), dtype=np.int64)
        np.add.at(acc.T, edge_row, hard[:, edge_col].T)
        if not (acc % 2).any():
            break
    return hard, it


_NUMBA_FN = None


def _numba_kernel():
    global _NUMBA_FN
    if _NUMBA_FN is not None:
        return _NUMBA_FN
    if not jit_enabled():
        return None
    import numba

    # the scratch buffer is allocated per call through a closure-free wrapper
    @numba.njit(cache=True)
    def _kern_alloc(llr, edge_row, edge_col, row_edges, col_edges, max_iter, alpha):
        return _kern_impl(llr, edge_row, edge_col, row_edges, col_edges, max_iter, alpha,
                          np.zeros(row_edges.shape))

    @numba.njit(cache=True)
    def _kern_impl(llr, edge_row, edge_col, row_edges, col_edges, max_iter, alpha, row_edges_scratch):
        n_cw, n = llr.shape
        m, dc_max = row_edges.shape
        dv_max = col_edges.shape[1]
        E = edge_row.size
        hard = np.zeros((n_cw, n), dtype=np.uint8)
        c2v = np.zeros(E)
        tot = np.zeros(n)
        it_max = 0
        for w in range(n_cw):
            for e in range(E):
                c2v[e] = 0.0
            for v in range(n):
                tot[v] = llr[w, v]
                hard[w, v] = 1 if tot[v] < 0 else 0
            it = 0
            for it in range(1, max_iter + 1):
                for r in range(m):
                    min1 = np.inf
                    min2 = np.inf
                    amin = -1
                    prod = 1.0
                    for d in range(dc_max):
                        e = row_edges[r, d]
                        if e < 0:
                            continue
                        v = tot[edge_col[e]] - c2v[e]
                        mag = abs(v)
                        if v < 0:
                            prod = -prod
                        if mag < min1:
                            min2 = min1
                            min1 = mag
                            amin = d
                        elif mag < min2:
                            min2 = mag
                    for d in range(dc_max):
                        e = row_edges[r, d]
                        if e < 0:
                            continue
                        v = tot[edge_col[e]] - c2v[e]
                        s = -1.0 if v < 0 else 1.0
                        mag = min2 if d == amin else min1
                        val = alpha * mag
                        if prod * s < 0:
                            val = -val
                        row_edges_scratch[r, d] = val
                for r in range(m):
                    for d in range(dc_max):
                        e = row_edges[r, d]
                        if e >= 0:
                            c2v[e] = row_edges_scratch[r, d]
                for v in range(n):
                    t = llr[w, v]
                    for d in range(dv_max):
                        e = col_edges[v, d]
                        if e >= 0:
                            t = t + c2v[e]
                    tot[v] = t
                    hard[w, v] = 1 if t < 0 else 0
                ok = True
                for r in range(m):
                    par = 0
                    for d in range(dc_max):
                        e = row_edges[r, d]
                        if e >= 0:
                            par ^= hard[w, edge_col[e]]
                    if par:
                        ok = False
                        break
                if ok:
                    break
            if it > it_max:
                it_max = it
        return hard, it_max

    _NUMBA_FN = _kern_alloc
    return _NUMBA_FN


def active_kernel() -> str:
    return "numba" if jit_enabled() else "numpy"


# ---------------------------------------------------------------- construction
@lru_cache(maxsize=None)
def code(n: int, rate: str) -> LdpcCode:
    """The 802.11 code of length ``n`` and rate ``rate`` ("1/2" … "5/6")."""
    if n not in LENGTHS or rate not in RATES:
        raise ValueError(f"802.11 LDPC: n in {LENGTHS}, rate in {RATES}; got {n}, {rate!r}")
    base = np.asarray(spec.ldpc_base_matrices()[n][rate], dtype=np.int64)
    z = n // 24
    m_b = base.shape[0]
    rows, cols = [], []
    for i in range(m_b):
        for j in range(24):
            s = int(base[i, j])
            if s < 0:
                continue
            r = np.arange(z)
            rows.append(i * z + r)
            cols.append(j * z + (r + s) % z)          # identity cyclically shifted right by s
    edge_row = np.concatenate(rows)
    edge_col = np.concatenate(cols)
    order = np.lexsort((edge_col, edge_row))
    edge_row, edge_col = edge_row[order], edge_col[order]
    m = m_b * z
    k = n - m
    row_edges = _padded_groups(edge_row, m)
    col_edges = _padded_groups(edge_col, n)
    h = np.zeros((m, n), dtype=np.uint8)
    h[edge_row, edge_col] = 1
    hs, hp = h[:, :k], h[:, k:]
    return LdpcCode(n=n, rate=rate, z=z, base=base, edge_row=edge_row, edge_col=edge_col,
                    row_edges=row_edges, col_edges=col_edges, hs=hs, hp_inv=_gf2_inverse(hp))


def _padded_groups(keys: np.ndarray, n_groups: int) -> np.ndarray:
    """(n_groups, max count) edge indices grouped by ``keys``, −1 padded, in edge order."""
    counts = np.bincount(keys, minlength=n_groups)
    out = np.full((n_groups, int(counts.max())), -1, dtype=np.int64)
    fill = np.zeros(n_groups, dtype=np.int64)
    for e, g in enumerate(keys):
        out[g, fill[g]] = e
        fill[g] += 1
    return out


def rate_fraction(rate: str) -> float:
    num, den = (int(v) for v in rate.split("/"))
    return num / den
