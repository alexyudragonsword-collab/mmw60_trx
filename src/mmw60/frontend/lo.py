"""The 60 GHz LO as the chains see it: phase-noise profile, TX leakage, RX self-mixing DC.

Zero-IF (topology B): LO leakage lands at DC, the band centre; after the
receiver's CFO correction it sits at −Δf, i.e. 2.94 MHz / SCS_eff tones off
centre, inside the data (upclocking.md).  Topology A's fixed ×N LO reuses
``profile`` with its own multiplication (the other session).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..impairments.phase_noise import PoleZeroPhase
from ..vendor.wifitrx.impairments.phase_noise import LOModel, NoiseSource


@dataclass(frozen=True)
class Lo60:
    carrier_hz: float = 60e9
    profile: NoiseSource | None = None          # None = ideal LO
    tx_leak_dbc: float | None = None            # leak power relative to the modulator's signal
    rx_dc_dbc: float | None = None              # RX self-mixing DC relative to the signal at baseband

    @classmethod
    def from_pole_zero(cls, carrier_hz, psd0_dbchz, f_pole_hz, f_zero_hz, enabled=True, **kw):
        prof = PoleZeroPhase(psd0_dbchz=psd0_dbchz, f_pole_hz=f_pole_hz,
                             f_zero_hz=f_zero_hz) if enabled else None
        return cls(carrier_hz=carrier_hz, profile=prof, **kw)

    def lo_model(self, seed_profile: bool = True) -> LOModel:
        """A wifitrx ``LOModel`` for ``TxParams.lo`` / ``RxParams.lo``."""
        if self.profile is None:
            return LOModel(freq_hz=self.carrier_hz, enabled=False)
        return LOModel(freq_hz=self.carrier_hz, profile=self.profile, enabled=True)

    def tx_leak_dbm(self, signal_dbm: float) -> float | None:
        return None if self.tx_leak_dbc is None else signal_dbm + self.tx_leak_dbc

    def rx_dc(self, signal_rms_sqrt_mw: float, phase_deg: float = 37.0) -> complex:
        if self.rx_dc_dbc is None:
            return 0.0 + 0.0j
        amp = signal_rms_sqrt_mw * 10.0 ** (self.rx_dc_dbc / 20.0)
        return complex(amp * np.exp(1j * np.deg2rad(phase_deg)))

    def ipn_dbc(self, f1: float = 1e4, f2: float = 1e8) -> float | None:
        return None if self.profile is None else self.lo_model().ipn_dbc(f1, f2)
