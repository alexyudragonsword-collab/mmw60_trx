"""End-to-end carrier frequency offset: crystal error × carrier (iron rule 3).

Each topology must say how it catches ``(ppm_tx + ppm_rx) × f_c``; this is
the term itself.  wifitrx's ``ClockError`` has the same convention
(CFO = ppm·1e-6·f_carrier) but lives inside its RX chain and is RX-only;
here the TX and RX crystals are separate so the two topologies can report
the pre-compensated and residual parts separately (milestone 1, topology A).
With both ppm at zero the offset is exactly ``0.0`` and the signal is
returned bit for bit (``tests/test_laws.py::test_law3_*``).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class CfoModel:
    carrier_hz: float
    ppm_tx: float = 0.0
    ppm_rx: float = 0.0
    #: sign of the net offset as seen by the receiver (+1: the received
    #: baseband is rotated by +2π·Δf·t).  Liu 2025 gives "up to ±2.94 MHz";
    #: the worst case either sign is the same for an autocorrelation
    #: estimator, so +1 is taken.
    sign: float = 1.0

    @property
    def total_ppm(self) -> float:
        return float(self.ppm_tx) + float(self.ppm_rx)

    @property
    def cfo_hz(self) -> float:
        if self.total_ppm == 0.0:
            return 0.0
        return self.sign * self.total_ppm * 1e-6 * float(self.carrier_hz)

    def apply(self, x: np.ndarray, fs: float) -> np.ndarray:
        x = np.asarray(x, dtype=complex)
        f = self.cfo_hz
        if f == 0.0:
            return x
        t = np.arange(x.size) / fs
        return x * np.exp(2j * np.pi * f * t)

    def in_subcarriers(self, scs_hz: float) -> float:
        return self.cfo_hz / scs_hz
