# Vendored from wifi_trx_cal@7b8d08eb9f11e426f9c99e079ebcbe06c2c64a02: src/wifitrx/pa/scaled.py
# Adapted-copy policy: see src/mmw60/vendor/__init__.py
"""dBm-scaled PA wrapper around the unit-power-normalized padpd PA models.

The vendored PA models (Saleh, GMP, ReferencePA...) operate on dimensionless
drive levels with an internal saturation point.  ``ScaledPA`` maps that
normalized domain to physical units: input/output in sqrt(mW) so that

* small-signal power gain equals ``gain_db``
* peak envelope output power saturates at ``psat_dbm``

P1dB is a derived quantity (the underlying model's AM-AM shape fixes the
Psat-to-P1dB relation).  PAE follows a class-AB-like square-root law
``pae(p) = pae_max * sqrt(p/psat)``, from which DC power and average PAE
for modulated signals are reported.
"""
from __future__ import annotations

import numpy as np

from ..units import dbm_to_mw, mw_to_dbm, db_to_amp
from .base import PAModel


def _is_memoryless(model, r: np.ndarray, a_out: np.ndarray) -> bool:
    """Whether ``model`` treats every sample on its own: the ramp sent
    backwards must come back as the same numbers, reversed.  Elementwise
    models (Saleh, a LUT without filters) do so exactly; anything with a
    filter in it does not."""
    back = np.abs(model(r[::-1].astype(complex)))[::-1]
    # elementwise ==, not array_equal: the Android call-surface allow-list
    # holds names verified against numpy 1.19.5
    return bool(back.shape == a_out.shape and np.all(back == a_out))


def _steady_response(model, r: np.ndarray, block: int = 64,
                     max_block: int = 1 << 16) -> np.ndarray:
    """|output| of ``model`` for a constant-amplitude input at each level
    of ``r``, read once the model's memory has settled.

    Each level is held for ``block`` samples (a staircase, one call) and
    read at the block's middle, so that neither a causal filter's start-up
    nor a centred (non-causal) filter's look-ahead into the next level
    reaches it.  The block doubles until the read stops changing: equality
    of two samples inside one block is not enough, because taps spaced
    exactly one block apart see the same neighbouring levels at both.
    """
    prev = None
    while True:
        # each level held for `block` samples (np.tile, not np.repeat:
        # see the allow-list note above)
        stair = np.tile(r[:, None], (1, block)).ravel()
        y = np.abs(model(stair.astype(complex)))
        read = y.reshape(r.size, block)[:, block // 2]
        if prev is not None and np.all(
                np.abs(read - prev) <= 1e-9 * np.maximum(read, 1e-300)):
            return read
        prev = read
        block *= 2
        if block > max_block:
            raise ValueError(
                f"the PA model has not settled within {max_block} samples "
                "at a constant input; its memory is too long to calibrate "
                "a gain and saturation point from")


class ScaledPA:
    def __init__(self, pa_model: PAModel, gain_db: float = 30.0,
                 psat_dbm: float = 28.0, pae_max: float = 0.35):
        self.pa_model = pa_model
        self.gain_db = float(gain_db)
        self.psat_dbm = float(psat_dbm)
        self.pae_max = float(pae_max)

        # Native-domain saturation amplitude and small-signal gain, found
        # numerically so any PAModel works — unit-normalized analytic models
        # (Saleh/GMP) and physical-amplitude LUT models (HB imports) alike.
        # Log sweep locates the AM-AM peak wherever the model's scale sits;
        # the small-signal gain is read at r_sat/100 (on the flat region,
        # not at the sweep bottom, which may be outside a LUT's table).
        r = np.logspace(-3, 3, 6000)
        a_out = np.abs(self.pa_model(r.astype(complex)))
        # The sweep is one signal.  A model with memory reads it through
        # its own start-up transient: the first samples see only the
        # filters' leading taps, the gain is flat there, and the plateau
        # search below takes it -- a ReferencePA whose taps are spread
        # (fs / fir_fs >= 2) got its small-signal gain 1.80 dB high (B41,
        # reported by mmw60_trx in issue #5; sample-spaced taps escaped
        # with 0.004 dB).  Such a model is read level by level in steady
        # state instead; an elementwise one keeps the sweep, so its
        # scaling is bit-identical to what it always was.
        self._memoryless = _is_memoryless(self.pa_model, r, a_out)
        if not self._memoryless:
            r = np.logspace(-3, 3, 600)
            a_out = _steady_response(self.pa_model, r)
        i_sat = int(np.argmax(a_out))
        self._r_sat = float(r[i_sat])
        self._a_sat = float(a_out[i_sat])
        # Small-signal gain = the gain plateau (d log(gain) / d log(r) ~ 0)
        # below saturation.  Neither end of the sweep is safe: LUT models
        # clamp below their table (slope -1 there) and everything
        # compresses near r_sat.
        gains = a_out / r
        slope = np.gradient(np.log(np.maximum(gains, 1e-300)), np.log(r))
        mask = r < self._r_sat / 3.0
        idx = int(np.argmin(np.abs(np.where(mask, slope, np.inf))))
        self._g0 = float(gains[idx])

        # |y_norm| = a_sat maps to sqrt(psat_mw)
        self._k_out = np.sqrt(dbm_to_mw(self.psat_dbm)) / self._a_sat
        # overall small-signal amplitude gain k_out * g0 * k_in = 10^(gain/20)
        self._k_in = db_to_amp(self.gain_db) / (self._k_out * self._g0)

    def __call__(self, x: np.ndarray) -> np.ndarray:
        """sqrt(mW) in -> sqrt(mW) out."""
        return self._k_out * self.pa_model(self._k_in * np.asarray(x, dtype=complex))

    # ------------------------------------------------------------ metrics
    def am_am(self, p_in_dbm: np.ndarray) -> np.ndarray:
        """Output power (dBm) vs input power (dBm) for a CW tone (in steady
        state: a model with memory is read level by level, not as one
        swept signal)."""
        a_in = np.sqrt(dbm_to_mw(np.asarray(p_in_dbm, dtype=float)))
        if getattr(self, "_memoryless", True):
            a_out = np.abs(self(a_in.astype(complex)))
        else:
            a_out = self._k_out * _steady_response(self.pa_model,
                                                   self._k_in * a_in)
        return mw_to_dbm(a_out ** 2)

    @property
    def p1db_out_dbm(self) -> float:
        """Output-referred 1 dB compression point."""
        p_in = np.linspace(self.psat_dbm - self.gain_db - 40.0,
                           self.psat_dbm - self.gain_db + 10.0, 4000)
        p_out = self.am_am(p_in)
        comp = (p_in + self.gain_db) - p_out
        idx = np.argmax(comp >= 1.0)
        if comp[idx] < 1.0:
            return float(p_out[-1])
        return float(np.interp(1.0, comp[max(idx - 1, 0):idx + 1],
                               p_out[max(idx - 1, 0):idx + 1]))

    def pae(self, p_out_dbm) -> np.ndarray | float:
        """Instantaneous PAE at envelope power p_out_dbm (square-root law)."""
        p = dbm_to_mw(p_out_dbm)
        psat = dbm_to_mw(self.psat_dbm)
        return self.pae_max * np.sqrt(np.minimum(p / psat, 1.0))

    def dc_power_w(self, y: np.ndarray) -> float:
        """Average DC power consumption for output waveform y [sqrt(mW)].

        P_dc,inst = p_inst / pae(p_inst) = sqrt(psat * p_inst) / pae_max.
        """
        p_inst = np.abs(np.asarray(y)) ** 2  # mW
        psat = dbm_to_mw(self.psat_dbm)
        p_dc_mw = np.sqrt(psat * p_inst) / self.pae_max
        return float(np.mean(p_dc_mw)) * 1e-3

    def average_pae(self, y: np.ndarray) -> float:
        p_out_w = float(np.mean(np.abs(np.asarray(y)) ** 2)) * 1e-3
        p_dc = self.dc_power_w(y)
        return p_out_w / p_dc if p_dc > 0 else 0.0


class DriftingScaledPA:
    """dBm-scaled wrapper around a drifting PA (temperature/aging scenario).

    The dBm mapping (k_in/k_out) is frozen at drift state 0 — advancing the
    state then genuinely changes gain and compression at the chain level,
    which is what an adaptive DPD has to track.  Duck-types ScaledPA for
    TxChain use (__call__, average_pae, pae, dc_power_w).
    """

    def __init__(self, drift, gain_db: float = 26.0, psat_dbm: float = 28.0,
                 pae_max: float = 0.35):
        self.drift = drift
        self.scaled = ScaledPA(drift.pa(), gain_db=gain_db,
                               psat_dbm=psat_dbm, pae_max=pae_max)

    def set_state(self, state: float) -> None:
        self.drift.set_state(state)
        # swap only the inner model; keep the state-0 dBm scaling
        self.scaled.pa_model = self.drift.pa()

    @property
    def state(self) -> float:
        return self.drift.state

    def __call__(self, x: np.ndarray) -> np.ndarray:
        return self.scaled(x)

    def __getattr__(self, name):
        return getattr(self.scaled, name)
