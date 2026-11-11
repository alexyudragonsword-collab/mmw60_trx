# Vendored from wifi_trx_cal@7b8d08eb9f11e426f9c99e079ebcbe06c2c64a02: src/wifitrx/pa/memory_polynomial.py
# Adapted-copy policy: see src/mmw60/vendor/__init__.py
# Vendored from PA_DPD:src/padpd/pa/memory_polynomial.py (internal sibling
# repo), adapted for wifitrx.
# Upstream changes should be ported manually; see PROVENANCE.md.
"""Memory Polynomial (MP) model with least-squares fitting.

Basis functions: phi_{k,m}(n) = x(n-m*s) * |x(n-m*s)|^k
for k = 0..order-1, m = 0..memory_depth-1 and tap spacing s.

``tap_spacing`` (default 1) puts the memory taps s samples apart, so the
memory span stays fixed in seconds when the sampling rate rises. A PA
whose memory is defined in time (``ReferencePA(fs=..., fir_fs=...)``)
needs it. Measured on an 80 MHz signal at 320 MS/s against a PA whose
taps sit 12.5 ns (4 samples) apart (PA_DPD issue #4): MP order 7, memory 4
fits to -27.3 dB with sample-spaced taps and -36.4 dB with
tap_spacing 4; a GMP-ILA DPD reaches an EVM of -28.6 dB and -46.4 dB.
"""

from __future__ import annotations

import numpy as np

from .base import PAModel, lstsq_fit


def delayed(x: np.ndarray, m: int) -> np.ndarray:
    """Shift x by m samples (positive m = delay/lag), zero-padded."""
    if m == 0:
        return x
    out = np.zeros_like(x)
    if m > 0:
        out[m:] = x[:-m]
    else:
        out[:m] = x[-m:]
    return out


def check_tap_spacing(tap_spacing) -> int:
    if int(tap_spacing) != tap_spacing or tap_spacing < 1:
        raise ValueError("tap_spacing must be an integer >= 1")
    return int(tap_spacing)


class MemoryPolynomialModel(PAModel):
    def __init__(self, order: int = 7, memory_depth: int = 4,
                 tap_spacing: int = 1):
        if order < 1 or memory_depth < 1:
            raise ValueError("order and memory_depth must be >= 1")
        self.order = order
        self.memory_depth = memory_depth
        self.tap_spacing = check_tap_spacing(tap_spacing)
        self.coeffs: np.ndarray | None = None

    def get_config(self) -> dict:
        cfg = {"order": self.order, "memory_depth": self.memory_depth}
        # only when it is not the default, so a sample-spaced model saves
        # exactly as before and older readers can still load it
        if self.tap_spacing != 1:
            cfg["tap_spacing"] = self.tap_spacing
        return cfg

    @property
    def n_coeffs(self) -> int:
        return self.order * self.memory_depth

    def basis_matrix(self, x: np.ndarray) -> np.ndarray:
        cols = []
        for m in range(self.memory_depth):
            xm = delayed(x, m * self.tap_spacing)
            am = np.abs(xm)
            for k in range(self.order):
                cols.append(xm * am**k)
        return np.stack(cols, axis=1)

    def branch_delays(self) -> list[tuple[int, int]]:
        """(carrier delay, envelope delay) per branch — LUT metadata."""
        return [(m * self.tap_spacing, m * self.tap_spacing)
                for m in range(self.memory_depth)]

    def gain_curve(self, r: np.ndarray) -> np.ndarray:
        """Complex gain of each memory tap vs envelope: sum_k c_km r^k."""
        if self.coeffs is None:
            raise RuntimeError("model is not fitted; call fit(x, y) first")
        r = np.asarray(r, dtype=float)
        powers = np.stack([r**k for k in range(self.order)], axis=1)
        return np.stack([powers @ self.coeffs[m * self.order:
                                              (m + 1) * self.order]
                         for m in range(self.memory_depth)])

    def fit(self, x: np.ndarray, y: np.ndarray,
            regularization: float = 0.0) -> MemoryPolynomialModel:
        self.coeffs = lstsq_fit(self.basis_matrix(x), y, regularization)
        return self

    def __call__(self, x: np.ndarray) -> np.ndarray:
        if self.coeffs is None:
            raise RuntimeError("model is not fitted; call fit(x, y) first")
        return self.basis_matrix(x) @ self.coeffs
