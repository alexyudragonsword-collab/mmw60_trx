"""Upclocking (IMMW topology B): the PHY untouched, the clock × K.

Liu 2025 §III-B: "increasing the subcarrier spacing and channel bandwidth of
IEEE 802.11ac by a specific multiple ... the OFDM symbol time is also
reduced, but the baseband processing remains unchanged."  That is exactly a
sample-clock reinterpretation, and that is how this library models it:
the waveform is generated and demodulated by the vendored wifitrx at the
**base** numerology (312.5 kHz / 20 MHz / 64-point, which its pilot and
tone tables know), and every physical quantity — CFO in Hz, phase-noise PSD
in Hz, channel delays in seconds, noise density — is applied at the
effective rate ``fs_eff = fs_base * K``.  ``K = 1`` is therefore the
unmodified wifitrx chain bit for bit (iron rule 2's regression anchor).

Scaling the wifitrx config's ``subcarrier_spacing_hz`` instead would break
its exact-match pilot tables (``pilots._tables``) and tone plans; see
cairn/engineering-pitfalls.md.
"""
from __future__ import annotations

from dataclasses import dataclass

from .vendor.wifitrx.waveform.ofdm import OFDMConfig
from .vendor.wifitrx.waveform.preamble import STF_PERIOD_S


@dataclass(frozen=True)
class UpclockedPhy:
    """A base wifitrx ``OFDMConfig`` plus the clock multiple ``k``."""

    base: OFDMConfig
    k: int = 1

    def __post_init__(self):
        if int(self.k) < 1 or int(self.k) != self.k:
            raise ValueError(f"upclock factor must be a positive integer, got {self.k!r}")

    # --- the base (what the digital PHY sees) -------------------------------
    @property
    def fs_base(self) -> float:
        return float(self.base.sample_rate_hz)

    @property
    def scs_base(self) -> float:
        return float(self.base.subcarrier_spacing_hz)

    # --- the effective (what the air sees) ----------------------------------
    @property
    def fs_eff(self) -> float:
        """Sample rate the impairments and the channel are applied at."""
        return self.fs_base * self.k

    @property
    def scs_eff(self) -> float:
        return self.scs_base * self.k

    @property
    def bandwidth_eff(self) -> float:
        return float(self.base.bandwidth_hz) * self.k

    @property
    def t_fft_eff(self) -> float:
        """FFT (useful symbol) duration [s] after upclocking: 3.2 µs / K at 11ac."""
        return 1.0 / self.scs_eff

    @property
    def t_gi_eff(self) -> float:
        return self.base.cp_len / self.fs_base / self.k * self.base.oversampling

    @property
    def t_symbol_eff(self) -> float:
        return self.t_fft_eff + self.t_gi_eff

    @property
    def stf_period_samples(self) -> int:
        """Samples per L-STF period (0.8 µs at the base clock); unchanged by K."""
        return int(round(STF_PERIOD_S * self.fs_base))

    @property
    def stf_period_eff(self) -> float:
        return self.stf_period_samples / self.fs_eff

    @property
    def stf_capture_hz(self) -> float:
        """Unambiguous range of an L-STF autocorrelation CFO estimate: ±1/(2·T_stf)."""
        return 0.5 / self.stf_period_eff

    @property
    def ltf_capture_hz(self) -> float:
        """Unambiguous range of the two-repeat L-LTF estimate: ±SCS_eff/2."""
        return 0.5 * self.scs_eff

    def cfo_in_subcarriers(self, cfo_hz: float) -> float:
        return cfo_hz / self.scs_eff

    def summary(self) -> dict:
        return {"k": self.k, "fs_eff_hz": self.fs_eff, "scs_eff_hz": self.scs_eff,
                "bandwidth_eff_hz": self.bandwidth_eff, "t_fft_eff_s": self.t_fft_eff,
                "t_gi_eff_s": self.t_gi_eff, "stf_capture_hz": self.stf_capture_hz,
                "ltf_capture_hz": self.ltf_capture_hz}
