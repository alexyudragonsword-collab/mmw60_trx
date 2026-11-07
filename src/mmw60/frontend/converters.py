"""DAC / ADC resolution as a function of sample rate (data/spec: assumed.converter_*).

Upclocking by K multiplies the converter rate by K.  At a fixed power and
architecture the achievable ENOB falls with rate; the law used here is a
straight line in log2(fs):

    ENOB(fs) = ENOB_ref − bits_per_octave · log2(fs / fs_ref)

with ``bits_per_octave = 0.5`` (a constant Schreier figure of merit: SNDR
falls 3 dB per doubling of bandwidth) as the default and 1.0 (constant
Walden FoM at constant power) as the pessimistic end.  wifitrx's converters
take integer bits, so ``bits(fs)`` rounds; the SQNR floor the grid quotes
uses the unrounded ENOB.  Nothing here is a measured part: every number is
``source: assumed`` and the grid prints the floor it produces.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ConverterLaw:
    enob_ref: float = 10.0
    fs_ref_hz: float = 1.0e9
    bits_per_octave: float = 0.5
    enob_min: float = 4.0
    #: rms of the OFDM signal below converter full scale (PAPR headroom)
    backoff_db: float = 12.0

    def enob(self, fs_hz: float) -> float:
        e = self.enob_ref - self.bits_per_octave * np.log2(fs_hz / self.fs_ref_hz)
        return float(max(e, self.enob_min))

    def bits(self, fs_hz: float) -> int:
        return int(round(self.enob(fs_hz)))

    def sqnr_db(self, fs_hz: float, backoff_db: float | None = None) -> float:
        """Signal-to-quantisation-noise of an OFDM signal ``backoff_db`` below
        full scale, in the Nyquist band: 6.02·ENOB + 1.76 − backoff."""
        b = self.backoff_db if backoff_db is None else backoff_db
        return 6.02 * self.enob(fs_hz) + 1.76 - b

    def in_band_sqnr_db(self, fs_hz: float, occupied_bw_hz: float,
                        backoff_db: float | None = None) -> float:
        """The same with the oversampling gain: quantisation noise is spread
        over fs/2 … only the occupied band's share lands on the tones."""
        return self.sqnr_db(fs_hz, backoff_db) + 10 * np.log10(fs_hz / max(occupied_bw_hz, 1.0))

    def describe(self, fs_hz: float) -> dict:
        return {"fs_hz": fs_hz, "enob": self.enob(fs_hz), "bits": self.bits(fs_hz),
                "sqnr_db": self.sqnr_db(fs_hz)}
