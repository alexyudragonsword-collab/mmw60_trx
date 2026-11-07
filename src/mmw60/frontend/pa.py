"""The modified Rapp PA in wifitrx's physical (sqrt(mW)) domain, for ``TxChain(pa=…)``.

wifitrx's ``ScaledPA`` finds a model's saturation as the argmax of its AM/AM,
which a monotonic Rapp never has, and reads the small-signal gain at
r_sat/100 — deep in compression for this curve.  This wrapper fixes the two
anchors analytically instead: small-signal power gain ``gain_db`` and
saturated output power ``psat_dbm`` (A_sat² of the normalised model), and
keeps the ``__call__`` / ``average_pae`` / ``am_am`` surface ``TxChain``
and the calibration steps use.
"""
from __future__ import annotations

import numpy as np

from ..pa.rapp import ModifiedRappPA
from ..vendor.wifitrx.units import db_to_amp, dbm_to_mw, mw_to_dbm


class ScaledRappPA:
    def __init__(self, pa_model: ModifiedRappPA | None = None, gain_db: float = 20.0,
                 psat_dbm: float = 15.0, pae_max: float = 0.20):
        self.pa_model = pa_model or ModifiedRappPA()
        self.gain_db = float(gain_db)
        self.psat_dbm = float(psat_dbm)
        self.pae_max = float(pae_max)
        self._k_out = float(np.sqrt(dbm_to_mw(psat_dbm)) / self.pa_model.a_sat)
        self._k_in = float(db_to_amp(gain_db) / (self._k_out * self.pa_model.small_signal_gain))

    def __call__(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=complex)
        return self.pa_model(x * self._k_in) * self._k_out

    def am_am(self, p_in_dbm) -> np.ndarray:
        a_in = np.sqrt(dbm_to_mw(np.asarray(p_in_dbm, dtype=float)))
        a_out = self.pa_model.am_am(a_in * self._k_in) * self._k_out
        return mw_to_dbm(a_out ** 2)

    @property
    def p1db_out_dbm(self) -> float:
        return float(mw_to_dbm(self.pa_model.p1db * self._k_out ** 2))

    def pae(self, p_out_dbm):
        p = dbm_to_mw(np.asarray(p_out_dbm, dtype=float))
        return self.pae_max * np.sqrt(np.minimum(p / dbm_to_mw(self.psat_dbm), 1.0))

    def average_pae(self, y: np.ndarray) -> float:
        return float(self.pae(mw_to_dbm(np.mean(np.abs(y) ** 2))))

    def dc_power_w(self, y: np.ndarray) -> float:
        p_out_mw = float(np.mean(np.abs(y) ** 2))
        return p_out_mw / max(self.average_pae(y), 1e-6) / 1e3

    def obo_from_psat_db(self, y: np.ndarray) -> float:
        return float(self.psat_dbm - mw_to_dbm(np.mean(np.abs(y) ** 2)))
