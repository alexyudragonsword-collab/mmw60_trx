"""Propagation channel at the effective rate (data/spec: assumed.cr_rms_delay_ns).

Three implementations behind one ``apply(x, fs, rng) -> (y, taps)`` protocol:

* ``FlatChannel`` — the identity (AWGN-only reference row);
* ``ExponentialTdl`` — wifitrx's ``TDLChannel`` (exponential PDP, one
  Rayleigh / Rician realisation per packet, total power 1), the stand-in for
  the 802.11ad conference-room model whose tap table this repository does
  not hold;
* ``TapTableChannel`` — explicit (delay, power, phase) taps, for the day a
  real table arrives (``cairn/Reference/``); it bins the delays onto the
  ``fs`` grid and keeps the total power at 1.

All delays are physical seconds: at ``fs_eff = K·fs_base`` the same channel
spans K times more samples relative to the (K times shorter) guard interval,
which is one of the things upclocking is supposed to show.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from .vendor.wifitrx.link.channel import TDLChannel


class Channel(Protocol):
    name: str

    def apply(self, x: np.ndarray, fs: float,
              rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]: ...


@dataclass(frozen=True)
class FlatChannel:
    name: str = "flat"

    def apply(self, x, fs, rng):
        return np.asarray(x, dtype=complex), np.ones(1, dtype=complex)


@dataclass(frozen=True)
class ExponentialTdl:
    """wifitrx's exponential-PDP Rayleigh TDL for the diffuse part, plus an
    optional line-of-sight tap: ``los_k_db`` is the LOS-to-total-diffuse
    power ratio (a conference-room LOS link), None is Rayleigh throughout.
    (wifitrx's own ``k_db`` makes only the *first tap* Rician and leaves the
    tail power unchanged, which is not the same thing.)"""
    rms_delay_ns: float = 7.0
    los_k_db: float | None = None
    name: str = "tdl_exp"

    def tdl(self) -> TDLChannel:
        return TDLChannel(rms_delay_ns=self.rms_delay_ns)

    def realize(self, fs: float, rng: np.random.Generator) -> np.ndarray:
        diffuse = self.tdl().realize(fs, rng)
        if self.los_k_db is None:
            return diffuse
        k = 10.0 ** (self.los_k_db / 10.0)
        taps = diffuse * np.sqrt(1.0 / (k + 1.0))
        taps[0] += np.sqrt(k / (k + 1.0))
        return taps

    def apply(self, x, fs, rng):
        x = np.asarray(x, dtype=complex)
        if self.rms_delay_ns <= 0.0:
            return x, np.ones(1, dtype=complex)
        taps = self.realize(fs, rng)
        return np.convolve(x, taps)[:x.size], taps

    def realized_rms_delay_s(self, fs: float) -> float:
        return self.tdl().realized_rms_delay_s(fs)


@dataclass(frozen=True)
class TapTableChannel:
    delays_ns: tuple
    powers_db: tuple
    phases_deg: tuple | None = None
    name: str = "tap_table"

    def taps(self, fs: float) -> np.ndarray:
        d = np.asarray(self.delays_ns, dtype=float) * 1e-9
        p = 10.0 ** (np.asarray(self.powers_db, dtype=float) / 10.0)
        ph = (np.zeros_like(p) if self.phases_deg is None
              else np.deg2rad(np.asarray(self.phases_deg, dtype=float)))
        idx = np.round(d * fs).astype(int)
        taps = np.zeros(int(idx.max()) + 1, dtype=complex)
        np.add.at(taps, idx, np.sqrt(p) * np.exp(1j * ph))
        return taps / np.sqrt(np.sum(np.abs(taps) ** 2))

    def apply(self, x, fs, rng):
        x = np.asarray(x, dtype=complex)
        taps = self.taps(fs)
        return np.convolve(x, taps)[:x.size], taps


def make_channel(model: str, rms_delay_ns: float = 7.0, los_k_db: float | None = None,
                 taps: dict | None = None) -> Channel:
    if model == "flat":
        return FlatChannel()
    if model == "tdl_exp":
        return ExponentialTdl(rms_delay_ns=float(rms_delay_ns), los_k_db=los_k_db)
    if model == "tap_table":
        if not taps:
            raise ValueError("tap_table channel needs taps: {delays_ns, powers_db[, phases_deg]}")
        return TapTableChannel(tuple(taps["delays_ns"]), tuple(taps["powers_db"]),
                               tuple(taps["phases_deg"]) if taps.get("phases_deg") else None)
    raise ValueError(f"unknown channel model {model!r}; use flat | tdl_exp | tap_table")
