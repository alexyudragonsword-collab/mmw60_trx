"""The array layer (milestone 2): N elements of the shared front end behind
arraytx's linear array model.

arraytx (vendored @5815c5a, used as is) gives the geometry — element
positions, the far-field delays tau_k(theta), the element factor — and the
beam functions (squint, beamwidth).  It has no phase-shifter quantisation,
no codebook, no absolute power and no receive array, so those are here.

Every element is the shared ``Frontend60``'s (iron rule 2): the same PA at
the same per-element output, the same receive face, the same antenna
element gain.  Both topologies get the same ``Array60`` instance.

Conventions (one carrier, CW at f_c; the wideband squint is arraytx's):

* weights w_k: the steering phase (``beam.steering_phase_weights``),
  quantised to ``phase_bits``, times the static element error a_k;
* array factor AF(theta) = sum_k w_k exp(+j 2 pi f_c tau_k(theta)) — |AF| = N
  at the beam with ideal weights;
* transmit: N copies of the PA at P_e each; the fields add coherently:
  EIRP(theta) = P_e + 20 log10 |AF(theta)| + G_e(theta);
* receive: the signal adds coherently, the N element noises incoherently:
  G_rx(theta) = 20 log10 |AF(theta)| - 10 log10 N + G_e(theta) (10 log10 N + G_e
  at the beam);
* G_e(theta) = the front end's element gain (dBi, boresight) plus arraytx's
  element factor, a field amplitude: 20 log10 g(theta) (cos: 3 dB at 45 deg).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..vendor.arraytx.beam import steering_phase_weights
from ..vendor.arraytx.geometry import ArrayGeometry

SIDES = ("tx", "rx")


def quantise_phase(w: np.ndarray, bits: int | None) -> np.ndarray:
    """Unit-modulus weights with their phase rounded to a ``bits``-bit phase
    shifter (2**bits states); unchanged when ``bits`` is None.  The phases
    are taken relative to the first element (a common phase does not move
    the beam, and arraytx's arrays are centred, which puts the raw phases on
    the half-step at some angles), rounded half up."""
    w = np.asarray(w, dtype=complex)
    if bits is None:
        return w
    step = 2.0 * np.pi / 2 ** int(bits)
    rel = np.angle(w * np.conj(w[0]))
    return np.exp(1j * step * np.floor(rel / step + 0.5))


@dataclass
class Array60:
    """One link end's transmit array and receive array (shapes may differ)."""
    tx: ArrayGeometry
    rx: ArrayGeometry
    phase_bits: int | None = None
    steering: str = "phase"
    element_gain_tx_dbi: float = 0.0
    element_gain_rx_dbi: float = 0.0
    scan_max_deg: float = 60.0
    sector_oversampling: float = 1.0
    #: static per-element errors a_k (complex, unit mean), one draw per side
    err: dict = field(default_factory=dict)

    @classmethod
    def from_config(cls, cfg, fe) -> "Array60":
        a = cfg.frontend.array
        geo = lambda nx, ny: ArrayGeometry(int(nx), int(ny), spacing_lambda=float(a.spacing_lambda),  # noqa: E731
                                           spacing_y_lambda=float(a.spacing_lambda), f0_hz=float(cfg.carrier_hz),
                                           element_pattern=a.element_pattern)
        tx, rx = geo(a.tx_nx, a.tx_ny), geo(a.rx_nx, a.rx_ny)
        rng = np.random.default_rng(int(a.error_seed))
        err = {}
        for side, g in (("tx", tx), ("rx", rx)):
            gain = 10.0 ** (rng.normal(0.0, float(a.gain_err_db_rms), g.n) / 20.0)
            phase = np.deg2rad(rng.normal(0.0, float(a.phase_err_deg_rms), g.n))
            # one element is the front end itself: its gain is the operating point, nothing to mismatch
            err[side] = gain * np.exp(1j * phase) if g.n > 1 else np.ones(1, dtype=complex)
        return cls(tx=tx, rx=rx, phase_bits=a.phase_bits, steering=a.steering,
                   element_gain_tx_dbi=fe.antenna_gain_tx_dbi, element_gain_rx_dbi=fe.antenna_gain_rx_resolved_dbi,
                   scan_max_deg=float(a.scan_max_deg), sector_oversampling=float(a.sector_oversampling), err=err)

    # ------------------------------------------------------------ geometry
    def geom(self, side: str) -> ArrayGeometry:
        if side not in SIDES:
            raise ValueError(f"side must be one of {SIDES}")
        return self.tx if side == "tx" else self.rx

    def n(self, side: str) -> int:
        return int(self.geom(side).n)

    # ------------------------------------------------------------ weights and gain
    def weights(self, side: str, theta0_deg: float, ideal: bool = False) -> np.ndarray:
        """The programmed weights steering ``side`` to ``theta0_deg``: the
        steering phase, quantised, times the static element errors (``ideal``:
        neither)."""
        w = steering_phase_weights(self.geom(side), float(theta0_deg))
        if ideal:
            return w
        return quantise_phase(w, self.phase_bits) * self.err[side]

    def af(self, side: str, w: np.ndarray, thetas_deg) -> np.ndarray:
        """|AF(theta)| = |sum_k w_k exp(+j 2 pi f_c tau_k(theta))| (N at a perfect beam)."""
        g = self.geom(side)
        th = np.atleast_1d(np.asarray(thetas_deg, dtype=float))
        out = np.empty(th.size)
        for i, t in enumerate(th):
            out[i] = abs(np.sum(np.asarray(w) * np.exp(2j * np.pi * g.f0_hz * g.delays_s(float(t)))))
        return out

    def element_factor_db(self, side: str, thetas_deg) -> np.ndarray:
        g = self.geom(side)
        th = np.atleast_1d(np.asarray(thetas_deg, dtype=float))
        v = np.array([g.element_gain(float(t)) for t in th])
        with np.errstate(divide="ignore"):
            return 20.0 * np.log10(v)

    def tx_gain_db(self, thetas_deg, theta0_deg: float, ideal: bool = False) -> np.ndarray:
        """EIRP above one element's conducted output (dB): 20 log10|AF| + G_e(theta)."""
        af = self.af("tx", self.weights("tx", theta0_deg, ideal), thetas_deg)
        with np.errstate(divide="ignore"):
            return 20.0 * np.log10(af) + self.element_factor_db("tx", thetas_deg) + self.element_gain_tx_dbi

    def rx_gain_db(self, thetas_deg, theta0_deg: float, ideal: bool = False) -> np.ndarray:
        """The receive array's SNR gain over an isotropic antenna (dB):
        20 log10|AF| - 10 log10 N + G_e(theta)."""
        af = self.af("rx", self.weights("rx", theta0_deg, ideal), thetas_deg)
        with np.errstate(divide="ignore"):
            return (20.0 * np.log10(af) - 10.0 * np.log10(self.n("rx"))
                    + self.element_factor_db("rx", thetas_deg) + self.element_gain_rx_dbi)

    def quantisation_loss_db(self, side: str, theta0_deg: float) -> float:
        """Gain lost at the beam to the phase shifters and the element errors."""
        w_ideal, w = self.weights(side, theta0_deg, ideal=True), self.weights(side, theta0_deg)
        return float(20.0 * np.log10(self.af(side, w_ideal, theta0_deg)[0] / self.af(side, w, theta0_deg)[0]))

    # ------------------------------------------------------------ power
    def eirp_dbm(self, p_elem_dbm: float, theta0_deg: float = 0.0) -> float:
        """EIRP at the beam from N elements each at ``p_elem_dbm`` average output."""
        return float(p_elem_dbm + self.tx_gain_db(theta0_deg, theta0_deg)[0])

    def element_pout_dbm(self, p_target_dbm: float, eirp_limit_dbm: float, theta0_deg: float = 0.0,
                         margin_db: float = 0.0) -> float:
        """The per-element output: the front end's operating point, or lower
        when N of them at that point would exceed the EIRP limit (minus
        ``margin_db``) at the beam."""
        g = float(self.tx_gain_db(theta0_deg, theta0_deg)[0])
        return float(min(p_target_dbm, eirp_limit_dbm - margin_db - g))

    # ------------------------------------------------------------ the training codebook
    def codebook_deg(self, side: str = "tx") -> np.ndarray:
        """Sector centres, uniform in sin(theta) over +-scan_max_deg:
        ``sector_oversampling`` x the array's columns of them (one sector at n_x = 1)."""
        g = self.geom(side)
        s = max(1, int(np.ceil(g.n_x * self.sector_oversampling))) if g.n_x > 1 else 1
        if s == 1:
            return np.array([0.0])
        u = np.linspace(-np.sin(np.deg2rad(self.scan_max_deg)), np.sin(np.deg2rad(self.scan_max_deg)), s)
        return np.rad2deg(np.arcsin(u))

    def sector_gains_db(self, side: str, theta_user_deg: float) -> np.ndarray:
        """Each sector beam's gain toward a station at ``theta_user_deg``
        (transmit: EIRP over one element's output; receive: SNR gain)."""
        f = self.tx_gain_db if side == "tx" else self.rx_gain_db
        return np.array([f(theta_user_deg, s)[0] for s in self.codebook_deg(side)])

    def describe(self) -> dict:
        return {"tx_shape": (int(self.tx.n_x), int(self.tx.n_y)), "rx_shape": (int(self.rx.n_x), int(self.rx.n_y)),
                "n_tx": self.n("tx"), "n_rx": self.n("rx"), "phase_bits": self.phase_bits, "steering": self.steering,
                "element_gain_tx_dbi": self.element_gain_tx_dbi, "element_gain_rx_dbi": self.element_gain_rx_dbi,
                "element_pattern": self.tx.element_pattern, "spacing_lambda": float(self.tx.spacing_lambda),
                "sectors_tx": int(self.codebook_deg("tx").size), "sectors_rx": int(self.codebook_deg("rx").size)}


__all__ = ["Array60", "quantise_phase", "SIDES"]
