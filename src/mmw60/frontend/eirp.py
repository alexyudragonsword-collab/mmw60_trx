"""Regulatory EIRP ceiling (data/spec: fcc15255.*, source survey) as one shared object."""
from __future__ import annotations

from dataclasses import dataclass

from .. import spec


@dataclass(frozen=True)
class EirpLimit:
    avg_dbm: float
    peak_dbm: float
    band_low_hz: float
    band_high_hz: float
    source: str = "survey"

    @classmethod
    def fcc_15_255(cls) -> "EirpLimit":
        return cls(avg_dbm=float(spec.value("fcc15255.eirp_avg_dbm")),
                   peak_dbm=float(spec.value("fcc15255.eirp_peak_dbm")),
                   band_low_hz=float(spec.value("fcc15255.band_low_hz")),
                   band_high_hz=float(spec.value("fcc15255.band_high_hz")))

    def check(self, pout_avg_dbm: float, antenna_gain_dbi: float, papr_db: float = 10.0) -> dict:
        eirp = pout_avg_dbm + antenna_gain_dbi
        return {"eirp_avg_dbm": eirp, "margin_avg_db": self.avg_dbm - eirp,
                "eirp_peak_dbm": eirp + papr_db, "margin_peak_db": self.peak_dbm - (eirp + papr_db),
                "ok": eirp <= self.avg_dbm and eirp + papr_db <= self.peak_dbm}

    def in_band(self, f_low_hz: float, f_high_hz: float) -> bool:
        return self.band_low_hz <= f_low_hz and f_high_hz <= self.band_high_hz
