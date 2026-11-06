"""Modified Rapp PA (AM/AM Rapp + AM/PM of the 11ad evaluation methodology).

    G(A)   = g·A / (1 + (g·A / A_sat)^(2p))^(1/(2p))           (AM/AM, V → V)
    Φ(A)   = α·A^q1 / (1 + (A/β)^q2)                             (AM/PM, degrees)
    y      = G(|x|) · exp(j(∠x + Φ(|x|)·π/180))

Default parameters are the TGad EM CMOS PA (``tgad_em.pa_rapp_*`` in
``data/spec/survey.yaml``, source survey): g = 4.65, A_sat = 0.58, p = 0.81,
α = 2560, β = 0.114, q1 = 2.4, q2 = 2.3.  A ``wifitrx.pa.base.PAModel``, so
``ScaledPA`` and ``TxChain(pa=…)`` take it unchanged.

Output back-off is average output power below the saturated output power
``P_sat = A_sat²``: ``drive_for_obo`` finds the input scale by bisection
(the mapping drive → mean output power is monotonic), and
``apply_pa_at_obo`` returns the PA output renormalised by the small-signal
gain so the downstream SNR definition still sees a unit-power signal.
"""
from __future__ import annotations

import numpy as np

from .. import spec
from ..vendor.wifitrx.pa.base import PAModel


def _p(key: str) -> float:
    return float(spec.value(key))


class ModifiedRappPA(PAModel):
    def __init__(self, g: float | None = None, a_sat: float | None = None,
                 p: float | None = None, alpha: float | None = None,
                 beta: float | None = None, q1: float | None = None,
                 q2: float | None = None, ampm: bool = True):
        self.g = _p("tgad_em.pa_rapp_g") if g is None else float(g)
        self.a_sat = _p("tgad_em.pa_rapp_asat") if a_sat is None else float(a_sat)
        self.p = _p("tgad_em.pa_rapp_p") if p is None else float(p)
        self.alpha = _p("tgad_em.pa_ampm_alpha") if alpha is None else float(alpha)
        self.beta = _p("tgad_em.pa_ampm_beta") if beta is None else float(beta)
        self.q1 = _p("tgad_em.pa_ampm_q1") if q1 is None else float(q1)
        self.q2 = _p("tgad_em.pa_ampm_q2") if q2 is None else float(q2)
        self.ampm = bool(ampm)

    # --- the curves ---------------------------------------------------------
    def am_am(self, a: np.ndarray) -> np.ndarray:
        a = np.asarray(a, dtype=float)
        ga = self.g * a
        return ga / (1.0 + (ga / self.a_sat) ** (2 * self.p)) ** (1.0 / (2 * self.p))

    def am_pm_deg(self, a: np.ndarray) -> np.ndarray:
        a = np.asarray(a, dtype=float)
        if not self.ampm:
            return np.zeros_like(a)
        return self.alpha * a ** self.q1 / (1.0 + (a / self.beta) ** self.q2)

    def __call__(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=complex)
        a = np.abs(x)
        out_amp = self.am_am(a)
        phase = np.angle(x) + np.deg2rad(self.am_pm_deg(a))
        return out_amp * np.exp(1j * phase)

    @property
    def small_signal_gain(self) -> float:
        return self.g

    @property
    def p_sat(self) -> float:
        """Saturated output power (|y|² as A → ∞) in the model's normalised units."""
        return self.a_sat ** 2

    @property
    def p1db(self) -> float:
        """Output power at 1 dB gain compression (found on a log sweep)."""
        a = np.logspace(-4, 2, 60001)
        comp_db = 20 * np.log10(self.am_am(a) / (self.g * a))
        i = int(np.argmin(np.abs(comp_db + 1.0)))
        return float(self.am_am(a[i]) ** 2)

    def reference_power(self, reference: str) -> float:
        if reference == "psat":
            return self.p_sat
        if reference == "p1db":
            return self.p1db
        raise ValueError("reference must be psat | p1db")

    def get_config(self) -> dict:
        return {"g": self.g, "a_sat": self.a_sat, "p": self.p, "alpha": self.alpha,
                "beta": self.beta, "q1": self.q1, "q2": self.q2, "ampm": self.ampm}


def mean_output_power(pa: ModifiedRappPA, x: np.ndarray, drive: float) -> float:
    return float(np.mean(pa.am_am(drive * np.abs(x)) ** 2))


def drive_for_obo(pa: ModifiedRappPA, x: np.ndarray, obo_db: float,
                  tol_db: float = 1e-4, reference: str = "psat") -> float:
    """Input scale so that mean |y|² = P_ref · 10^(−OBO/10) for this waveform,
    P_ref being P_sat (the literal OBO) or P1dB."""
    x = np.asarray(x, dtype=complex)
    target = pa.reference_power(reference) * 10.0 ** (-obo_db / 10.0)
    lo, hi = 1e-6, 1.0
    while mean_output_power(pa, x, hi) < target:
        hi *= 2.0
        if hi > 1e6:
            raise RuntimeError("OBO target unreachable")
    for _ in range(200):
        mid = np.sqrt(lo * hi)
        p = mean_output_power(pa, x, mid)
        if abs(10 * np.log10(p / target)) < tol_db:
            return float(mid)
        if p < target:
            lo = mid
        else:
            hi = mid
    return float(np.sqrt(lo * hi))


def apply_pa_at_obo(pa: ModifiedRappPA, x: np.ndarray, obo_db: float,
                    reference: str = "psat") -> tuple[np.ndarray, dict]:
    """PA output for ``x`` at the given OBO, divided by (drive · g) so a
    linear PA would return ``x`` exactly.  Also reports the drive, the
    realised OBO from Psat and from P1dB, and the compression (NMSE of y vs x)."""
    x = np.asarray(x, dtype=complex)
    d = drive_for_obo(pa, x, obo_db, reference=reference)
    y = pa(d * x) / (d * pa.small_signal_gain)
    p_out = mean_output_power(pa, x, d)
    e = y - x
    nmse_db = 10 * np.log10(np.mean(np.abs(e) ** 2) / np.mean(np.abs(x) ** 2))
    info = {"drive": d, "obo_psat_db": float(10 * np.log10(pa.p_sat / p_out)),
            "obo_p1db_db": float(10 * np.log10(pa.p1db / p_out)),
            "nmse_db": float(nmse_db),
            "peak_in_v": float(d * np.abs(x).max()),
            "ampm_at_peak_deg": float(pa.am_pm_deg(d * np.abs(x).max()))}
    return y, info
