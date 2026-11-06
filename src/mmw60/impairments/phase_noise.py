"""The 1-pole / 1-zero LO phase-noise profile of the 11ad evaluation methodology.

    L(f) = PSD0 + 10·log10( (1 + (f/f_z)²) / (1 + (f/f_p)²) )   [dBc/Hz]

flat at PSD0 below the pole, −20 dB/decade between pole and zero, flat
again at PSD0 − 20·log10(f_z/f_p) above the zero (Liu 2025: f_p = 1 MHz,
f_z = 100 MHz, PSD0 = −93 dBc/Hz; the formula shape is ``tgad_em.pn_model_shape``
in ``data/spec/survey.yaml``, source survey).

It is a wifitrx ``NoiseSource`` so the vendored ``synth_from_psd`` /
``ipn_dbc`` / ``cpe_partition`` all take it unchanged; the PSD convention is
wifitrx's (``psd`` returns S_φ = 2·10^(L/10) rad²/Hz, one-sided in the real
phase process).  Time-domain synthesis runs at ``fs_eff``: the profile is in
absolute Hz and does not scale with K — that is the physics of upclocking.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..vendor.wifitrx.impairments.phase_noise import (NoiseSource, sphi_from_ldbc,
                                                      synth_from_psd)


@dataclass
class PoleZeroPhase(NoiseSource):
    """Single-pole single-zero LO phase-noise PSD."""

    name: str = "pole_zero"
    unit: str = "rad^2/Hz"
    psd0_dbchz: float = -93.0
    f_pole_hz: float = 1.0e6
    f_zero_hz: float = 100.0e6

    def l_dbc(self, f) -> np.ndarray:
        f = np.asarray(f, dtype=float)
        return (self.psd0_dbchz
                + 10.0 * np.log10((1.0 + (f / self.f_zero_hz) ** 2)
                                  / (1.0 + (f / self.f_pole_hz) ** 2)))

    def psd(self, f: np.ndarray) -> np.ndarray:
        return sphi_from_ldbc(self.l_dbc(f))

    @property
    def floor_dbchz(self) -> float:
        """The high-offset floor: PSD0 − 20·log10(f_z / f_p)."""
        return self.psd0_dbchz - 20.0 * np.log10(self.f_zero_hz / self.f_pole_hz)

    def integrated_rad2(self, f1: float = 1e3, f2: float = 1e10) -> float:
        """∫ S_φ df between f1 and f2 (both sidebands), closed form of the
        Lorentzian part plus the floor: used as a check on the synthesis."""
        f = np.logspace(np.log10(f1), np.log10(f2), 4000)
        s = self.psd(f)
        return float(np.trapezoid(s, f) if hasattr(np, "trapezoid") else np.trapz(s, f))


def lo_phase(profile: NoiseSource | None, n: int, fs: float,
             rng: np.random.Generator) -> np.ndarray:
    """Phase deviation φ[n] [rad] at rate ``fs``; zeros when ``profile`` is None."""
    if profile is None:
        return np.zeros(n)
    return synth_from_psd(profile.psd, fs, n, rng)
