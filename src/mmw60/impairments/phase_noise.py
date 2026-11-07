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
from pathlib import Path

import numpy as np
import yaml

from ..vendor.wifitrx.impairments.phase_noise import (DEFAULT_WIFI7_LO_PROFILE, NoiseSource,
                                                      TabulatedPhase, sphi_from_ldbc, synth_from_psd)


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


# ------------------------------------------------------------ other LO profiles
CLOCK_PROFILES_DIR = Path(__file__).resolve().parent.parent / "data" / "clock_profiles"


def load_clock_profile(path: str | Path) -> dict:
    """A pllsim clock phase-noise profile (``pllsim.export.clock_profile``
    format, the file Halo_Serdes consumes): ``f0_hz``, ``f_hz``, ``l_dbc_hz``
    (single-sideband L(f) in dBc/Hz), ``spurs``, ``source``.  A relative
    path is looked up in ``mmw60/data/clock_profiles``."""
    p = Path(path)
    if not p.is_absolute() and not p.exists():
        p = CLOCK_PROFILES_DIR / p
    d = yaml.safe_load(p.read_text(encoding="utf-8"))
    for key in ("f0_hz", "f_hz", "l_dbc_hz"):
        if key not in d:
            raise ValueError(f"{p}: not a clock profile (missing {key!r})")
    if len(d["f_hz"]) != len(d["l_dbc_hz"]):
        raise ValueError(f"{p}: f_hz and l_dbc_hz differ in length")
    d["path"] = str(p)
    return d


def profile_at_carrier(prof: dict, carrier_hz: float, name: str = "clock_profile") -> TabulatedPhase:
    """The profile's L(f) moved from its own carrier ``f0_hz`` to ``carrier_hz``
    by 20·log10(f_c / f0): an ideal frequency multiplier / divider, no
    multiplier floor and no harmonic-selection spurs (data/spec:
    assumed.lo_multiplier_law; the real ×N block is ROADMAP D2).  wifitrx's
    ``TabulatedPhase`` interpolates linearly in (log f, dB) and holds the end
    values flat outside the table."""
    n_db = 20.0 * np.log10(float(carrier_hz) / float(prof["f0_hz"]))
    l_dbc = tuple(float(v) + n_db for v in prof["l_dbc_hz"])
    return TabulatedPhase(name, f_pts=tuple(float(f) for f in prof["f_hz"]), l_dbc_pts=l_dbc)


def make_profile(pn_cfg, carrier_hz: float) -> NoiseSource | None:
    """The ``NoiseSource`` a ``PhaseNoiseConfig`` names, or None when it is
    off.  ``pole_zero`` returns the same ``PoleZeroPhase`` the milestone-0
    path always built (the fingerprint does not move)."""
    if not pn_cfg.enabled:
        return None
    m = pn_cfg.model
    if m == "pole_zero":
        return PoleZeroPhase(psd0_dbchz=pn_cfg.psd0_dbchz, f_pole_hz=pn_cfg.f_pole_hz,
                             f_zero_hz=pn_cfg.f_zero_hz)
    if m == "wifitrx_wifi7":
        return DEFAULT_WIFI7_LO_PROFILE
    if m == "profile":
        prof = load_clock_profile(pn_cfg.profile_path)
        return profile_at_carrier(prof, carrier_hz, name=f"profile:{Path(prof['path']).stem}")
    raise ValueError(f"unknown phase-noise model {m!r}")
