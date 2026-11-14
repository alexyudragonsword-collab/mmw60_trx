# Vendored from array_tx@5815c5a7ea43143fd58502d4894ac840b5b5fb86: src/arraytx/loadpull.py
# Adapted-copy policy: see src/mmw60/vendor/__init__.py
"""Load modulation of the digital PA (ROADMAP A2; model in
``cairn/load-pull-proposal.md``).

Milestone 1's coupling is a linear leakage r_k = y_k + sum_j S_kj y_j, and a
phase-covariant DPA turns that into a linear combination of the elements'
nonlinear outputs -- which is why per-element and array DPD could not be
told apart.  For the coupled wave to reach the NONLINEARITY it has to move
the PA's operating point.  First-order, voltage-mode reading:

* the active reflection coefficient at port k is
  Gamma_k(t) = sum_j S_kj (*) y_j / y_k -- the leakage ``apply_coupling``
  already computes, divided by the element's own wave;
* a switched-capacitor / class-D DPA is a voltage source whose swing is
  limited by its supply rail, and the swing at the port is v_fwd (1 +
  Gamma).  So compression acts on the TOTAL swing: the Rapp law is fed
  ``drive * |1 + kappa_a Gamma| * r`` and the result is divided by
  |1 + kappa_a Gamma| again, because ``apply_coupling`` adds the coupled
  wave afterwards.  In the linear region this cancels (the gain does not
  move); at the knee the compression starts earlier when |1 + Gamma| > 1.
  AM-PM is read at the same total swing, ``r * |1 + kappa_p Gamma|``.
  kappa = 1 is the ideal voltage-source reading (source: assumed); a
  measured load-pull table would replace this mapping (source: measured).

An ``"ideal"`` AM-AM has no knee, so it has no load dependence here, and
the RF-DAC (no compression) and the outphasing combiner are not touched
(``element.py`` reports the switch as inert for them).

``LoadPulledDPA`` is an arraytx-side subclass of polar_tx's ``DPA``: the
chain keeps calling ``dpa(code, phase)``; ``set_load(gamma)`` (one complex
value per sample, or None) is what ``sim.ArraySim.radiate`` sets between
its fixed-point rounds.  With no load set it IS the vendored DPA, bit for
bit (the table path is untouched).
"""
from __future__ import annotations

import numpy as np


from .vendor.polartx.dpa.characteristics import ampm_curve, efficiency_curve
from .vendor.polartx.dpa.combiner import OutphasingCombiner
from .vendor.polartx.dpa.dpa import DPA, DPAConfig
from .vendor.polartx.dpa.mismatch import code_amplitude_table

#: smallest |1 + kappa Gamma| / |1 - Gamma| the load model divides by (Gamma = -1 / +1 exactly)
G_FLOOR = 1e-12


def amam_loaded(amam, r: np.ndarray, g: np.ndarray) -> np.ndarray:
    """Normalised AM-AM of the FORWARD wave under a load factor
    g = |1 + kappa Gamma| per sample: the device saturates on g * r, and
    the forward wave is that output divided by g.  g = 1 reproduces
    ``characteristics.amam_curve`` (same expression, same order)."""
    r = np.asarray(r, dtype=float)
    # g = 0 is Gamma = -1 exactly (reachable at the total-reflection clip): the
    # forward wave's limit there is finite (the small-signal gain), but the
    # expression below would be 0 / 0.  A floor far below any physical g keeps
    # every other sample bit for bit.
    g = np.maximum(np.asarray(g, dtype=float), G_FLOOR)
    if amam == "ideal":
        return r
    kind = amam[0]
    if kind == "rapp":
        _, p, drive = amam
        x = drive * (g * r)
        y = x / (1.0 + x ** (2.0 * p)) ** (1.0 / (2.0 * p))
        y_fs = drive / (1.0 + drive ** (2.0 * p)) ** (1.0 / (2.0 * p))
        return y / y_fs / g
    if kind == "lut":
        _, r_in, r_out = amam
        r_in = np.asarray(r_in, float)
        r_out = np.asarray(r_out, float)
        y = np.interp(g * r, r_in, r_out)
        return y / np.interp(1.0, r_in, r_out) / g
    raise ValueError(f"unknown amam spec: {amam!r}")


class LoadPulledDPA(DPA):
    """polar_tx's DPA with a per-sample load factor on its nonlinearity."""

    def __init__(self, cfg: DPAConfig, kappa_amam: float = 1.0, kappa_ampm: float = 1.0):
        super().__init__(cfg)
        # the same normalised code amplitudes the base class built its
        # tables from (same seed, same draw)
        rng = np.random.default_rng(cfg.seed)
        raw = code_amplitude_table(cfg.n_bits, min(cfg.n_thermo, cfg.n_bits), cfg.sigma_cell, cfg.gradient, rng)
        self.r = raw / raw[-1]
        self.kappa_amam = float(kappa_amam)
        self.kappa_ampm = float(kappa_ampm)
        self.gamma: np.ndarray | None = None

    def set_load(self, gamma) -> None:
        """Active reflection coefficient per sample (complex), or None for
        the matched load (the plain table path)."""
        self.gamma = None if gamma is None else np.asarray(gamma, dtype=complex)

    @property
    def load_factors(self) -> tuple[np.ndarray, np.ndarray] | None:
        if self.gamma is None:
            return None
        return np.abs(1.0 + self.kappa_amam * self.gamma), np.abs(1.0 + self.kappa_ampm * self.gamma)

    def forward_amplitude(self, code: np.ndarray) -> np.ndarray:
        """|forward wave| per sample of the code stream under the current load
        (the matched table with no load set)."""
        code = np.asarray(code, dtype=np.int64)
        if self.gamma is None:
            return self.amp_table[code]
        return amam_loaded(self.cfg.amam, self.r[code], self.load_factors[0])

    def __call__(self, code: np.ndarray, phase: np.ndarray) -> np.ndarray:
        if self.gamma is None:
            return super().__call__(code, phase)
        code = np.asarray(code, dtype=np.int64)
        if self.gamma.shape[0] != code.shape[0]:
            raise ValueError(f"load has {self.gamma.shape[0]} samples, the code stream {code.shape[0]}")
        r = self.r[code]
        ga, gp = self.load_factors
        amp = amam_loaded(self.cfg.amam, r, ga)
        r_pm = r * gp
        if self.cfg.ampm_lut is not None:
            r_in, deg = self.cfg.ampm_lut
            ph = np.deg2rad(np.interp(r_pm, np.asarray(r_in, float), np.asarray(deg, float)))
        else:
            ph = ampm_curve(self.cfg.ampm_deg_poly, r_pm)
        return amp * np.exp(1j * (np.asarray(phase, float) + ph))


def loaded_power_terms(amp_matched: np.ndarray, amp_fwd: np.ndarray, gamma, eff_spec) -> dict:
    """The two terms of the loaded efficiency (cairn/loaded-efficiency-proposal.md).

    * switching loss per sample, from the SCPA law on the MATCHED amplitude
      of the code: P_loss = a_m^2 (1 / eta(a_m) - 1).  The cell-capacitor
      charging C V^2 f is set by the code, not by the load (source: assumed,
      the Yoo & Walling derivation's premise);
    * net power out of the port, P_net = |a|^2 (1 - |Gamma|^2), a the forward
      wave the loaded DPA produces: port voltage a (1 + Gamma), current
      a (1 - Gamma), real part of their product.  Samples at |Gamma| >= 1
      (total reflection, or power flowing INTO the PA, clipped to 1 upstream)
      count 0 and are reported as ``n_backflow``.

    Returns the sums, so an element and the whole array combine the same
    way: eta = sum P_net / sum (P_net + P_loss)."""
    a_m = np.asarray(amp_matched, dtype=float)
    a = np.asarray(amp_fwd, dtype=float)
    eta = efficiency_curve(eff_spec, a_m)
    p_m = a_m * a_m
    loss = np.zeros_like(p_m)
    on = eta > 0
    loss[on] = p_m[on] / eta[on] - p_m[on]
    g2 = np.zeros_like(a) if gamma is None else np.abs(np.asarray(gamma)) ** 2
    # |Gamma| >= 1: as much (or more) power comes back as goes out.  active_reflection
    # clips at gamma_max <= 1, so a true |Gamma| > 1 arrives here AT the clip; these
    # samples deliver nothing (net 0) and are what n_backflow counts
    back = g2 >= 1.0 - 1e-12
    net = np.where(back, 0.0, a * a * (1.0 - g2))
    return {"p_net": float(net.sum()), "p_loss": float(loss.sum()), "p_matched": float(p_m.sum()),
            "n_backflow": int(back.sum()), "n": int(a.size)}


def active_reflection(ys: np.ndarray, rs: np.ndarray, floors, gamma_max: float) -> np.ndarray:
    """Gamma_k(t) = (r_k - y_k) / y_k per element and sample, with the two
    guards: 0 where |y_k| is below the element's floor (the ratio means
    nothing near an envelope zero), magnitude clipped to ``gamma_max``."""
    ys = np.asarray(ys)
    leak = np.asarray(rs) - ys
    mag = np.abs(ys)
    floors = np.asarray(floors, dtype=float).reshape(-1, 1)
    safe = np.where(mag > floors, ys, 1.0)
    gamma = np.where(mag > floors, leak / safe, 0.0 + 0.0j)
    g = np.abs(gamma)
    over = g > gamma_max
    gamma = np.where(over, gamma * (gamma_max / np.where(over, g, 1.0)), gamma)
    return gamma


class SourceImpedanceCombiner(OutphasingCombiner):
    """polar_tx's outphasing combiner with a finite branch source impedance
    (ROADMAP B3; cairn/outphasing-load-proposal.md, option A).

    Each branch PA is a voltage source v_k behind rho (relative to the
    branch load); the Chireix compensation sits at the branch node as a
    susceptance +-jB (polar_tx's b = 1/2 sin 2 theta_c; 0 in isolated mode);
    the branches combine in series into Z_L = 2 (1 + Gamma) / (1 - Gamma).
    Solving that linear network (Thevenin at the load port):

        y = [sum_k y_k / (1 + j rho B_k)] / (S / 2)  x  F(Gamma),
        S = sum_k 1 / (1 + j rho B_k),
        F = [Z_L / (Z_L + rho S)] / [Z_0 / (Z_0 + rho S)],  Z_0 = 2,

    normalised so that Gamma = 0, theta = 0 is the ideal sum.  The first
    factor carries the distortion (cos theta + rho B sin theta at small
    rho: the output does not reach zero at theta = 90 deg) and does NOT
    depend on Gamma; the array's load enters only through F, a complex
    gain per sample.  rho = 0 is the parent's ``combine``, bit for bit.
    ``tests/test_outphasing_load.py`` checks the closed form against a
    numerical solve of the series and the lambda/4-line networks."""

    def __init__(self, *args, source_impedance_rel: float, **kw):
        super().__init__(*args, **kw)
        self.rho = float(source_impedance_rel)
        self.gamma: np.ndarray | None = None

    @classmethod
    def from_combiner(cls, c: OutphasingCombiner, source_impedance_rel: float) -> "SourceImpedanceCombiner":
        """The same combiner (mode, compensation angle, loss, imbalance -- whatever
        polar_tx's preset built) with a branch source impedance added."""
        from dataclasses import fields
        return cls(**{f.name: getattr(c, f.name) for f in fields(c)}, source_impedance_rel=source_impedance_rel)

    @property
    def susceptances(self) -> tuple[float, float]:
        b = float(self._b) if self.mode == "chireix" else 0.0
        return b, -b

    def set_load(self, gamma) -> None:
        self.gamma = None if gamma is None else np.asarray(gamma, dtype=complex)

    def load_factor(self, gamma) -> np.ndarray | complex:
        """F(Gamma): the array's load at the combiner output as a complex gain."""
        b1, b2 = self.susceptances
        S = 1.0 / (1.0 + 1j * self.rho * b1) + 1.0 / (1.0 + 1j * self.rho * b2)
        g = np.asarray(gamma, dtype=complex)
        den = 1.0 - g
        # Gamma = +1 exactly (an open, reachable at the total-reflection clip): Z_L
        # would be inf and F = inf / inf; F's limit there is 1 / [Z_0 / (Z_0 + rho S)]
        den = np.where(np.abs(den) < G_FLOOR, G_FLOOR, den)
        zl = 2.0 * (1.0 + g) / den
        return (zl / (zl + self.rho * S)) / (2.0 / (2.0 + self.rho * S))

    def combine(self, y1: np.ndarray, y2: np.ndarray) -> np.ndarray:
        if self.rho == 0.0:
            return super().combine(y1, y2)
        b1, b2 = self.susceptances
        d1, d2 = 1.0 + 1j * self.rho * b1, 1.0 + 1j * self.rho * b2
        half_s = 0.5 * (1.0 / d1 + 1.0 / d2)
        y = super().combine(np.asarray(y1) / d1, np.asarray(y2) / d2) / half_s
        if self.gamma is not None:
            if self.gamma.shape[0] != y.shape[0]:
                raise ValueError(f"load has {self.gamma.shape[0]} samples, the branches {y.shape[0]}")
            y = y * self.load_factor(self.gamma)
        return y
