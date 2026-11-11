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

    def apply(self, x: np.ndarray, fs: float, rng: np.random.Generator | None = None) -> np.ndarray:
        x = np.asarray(x, dtype=complex)
        f = self.cfo_hz
        if f == 0.0:
            return x
        t = np.arange(x.size) / fs
        return x * np.exp(2j * np.pi * f * t)

    def in_subcarriers(self, scs_hz: float) -> float:
        return self.cfo_hz / scs_hz


# ---------------------------------------------------------------- topology A: MLO pre-compensation
_SUB7_CACHE: dict = {}


def _sub7_preamble():
    """The legacy 20 MHz preamble (10 L-STF periods + L-LTF) the sub-7 GHz link
    estimates its CFO on, at 2× oversampling: (samples, frame, phy)."""
    if "f" not in _SUB7_CACHE:
        from ..config import Mmw60Config, PhyConfig
        from ..vendor.wifitrx.waveform.ofdm import generate_ofdm
        from ..vendor.wifitrx.waveform.preamble import build_frame
        cfg = Mmw60Config(carrier_hz=6e9, phy=PhyConfig(standard="11ac", bandwidth_hz=20e6))
        phy = cfg.upclocked(1)
        frame = build_frame(phy.base, data=generate_ofdm(phy.base), stf_periods=cfg.phy.stf_periods)
        _SUB7_CACHE["f"] = (frame.x[:frame.preamble_len].copy(), frame, phy)
    return _SUB7_CACHE["f"]


@dataclass(frozen=True)
class MloCfo:
    """How topology A catches (ppm_tx + ppm_rx) × f_c (iron rule 3).

    The chip's own L-STF / L-LTF estimators reach ±625 kHz; 40 ppm at
    60.48 GHz is 2.42 MHz.  A multi-link device has a sub-7 GHz link on the
    same crystals: its CFO there, (ppm_tx + ppm_rx) × f_sub7, is inside the
    estimators' range, and the 60 GHz offset is that times f_c / f_sub7
    (data/spec: assumed.mlo_common_reference).  The 60 GHz link is
    pre-compensated with the scaled estimate; what is left is the sub-7
    estimate's error × the frequency ratio, which the chip's own estimators
    then take out like any small offset.

    The sub-7 estimate is run, not assumed: the legacy preamble with the
    sub-7 offset and AWGN at ``sub7_snr_db`` through this library's
    L-STF coarse + L-LTF fine estimators, one draw per packet.  With both
    ppm at zero the term — offset, estimate and pre-compensation — is
    switched off and the signal is returned bit for bit.
    """
    carrier_hz: float
    ppm_tx: float = 0.0
    ppm_rx: float = 0.0
    sub7_hz: float = 5.5e9
    sub7_snr_db: float = 20.0
    enabled: bool = True
    sign: float = 1.0

    @property
    def total_ppm(self) -> float:
        return float(self.ppm_tx) + float(self.ppm_rx)

    @property
    def cfo_hz(self) -> float:
        """The raw offset at the 60 GHz carrier (what would hit the receiver without MLO)."""
        if self.total_ppm == 0.0:
            return 0.0
        return self.sign * self.total_ppm * 1e-6 * float(self.carrier_hz)

    @property
    def ratio(self) -> float:
        return float(self.carrier_hz) / float(self.sub7_hz)

    @property
    def sub7_cfo_hz(self) -> float:
        return 0.0 if self.total_ppm == 0.0 else self.cfo_hz / self.ratio

    def sub7_estimate_hz(self, rng: np.random.Generator) -> float:
        """One sub-7 GHz CFO estimate [Hz at f_sub7]: preamble + offset + noise → estimators."""
        from ..impairments.noise import add_awgn_per_tone
        from ..rx import cfo as est
        x, frame, phy = _sub7_preamble()
        fs = phy.fs_eff
        t = np.arange(x.size) / fs
        y = x * np.exp(2j * np.pi * self.sub7_cfo_hz * t)
        base = phy.base
        y, _ = add_awgn_per_tone(y, self.sub7_snr_db, base.fft_size, base.oversampling, base.n_active, rng)
        f_stf = est.stf_coarse_cfo(y, phy.stf_period_samples, frame.stf_len // phy.stf_period_samples, fs)
        y = est.correct(y, f_stf, fs)
        return float(f_stf + est.ltf_fine_cfo(y, frame, fs))

    def residual_hz(self, rng: np.random.Generator | None = None) -> float:
        """What reaches the 60 GHz receiver: 0.0 at zero ppm; the raw offset with
        MLO off; (true − estimate) × f_c / f_sub7 with it on."""
        if self.total_ppm == 0.0:
            return 0.0
        if not self.enabled:
            return self.cfo_hz
        rng = np.random.default_rng(0) if rng is None else rng
        return (self.sub7_cfo_hz - self.sub7_estimate_hz(rng)) * self.ratio

    def apply(self, x: np.ndarray, fs: float, rng: np.random.Generator | None = None) -> np.ndarray:
        x = np.asarray(x, dtype=complex)
        f = self.residual_hz(rng)
        if f == 0.0:
            return x
        t = np.arange(x.size) / fs
        return x * np.exp(2j * np.pi * f * t)

    def in_subcarriers(self, scs_hz: float) -> float:
        return self.cfo_hz / scs_hz

    def residual_stats(self, n: int = 200, seed: int = 0) -> dict:
        rng = np.random.default_rng(seed)
        r = np.array([self.residual_hz(rng) for _ in range(n)])
        return {"rms_hz": float(np.sqrt(np.mean(r ** 2))), "max_abs_hz": float(np.max(np.abs(r))),
                "mean_hz": float(np.mean(r)), "n": int(n)}
