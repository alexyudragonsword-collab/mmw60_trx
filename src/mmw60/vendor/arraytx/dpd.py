# Vendored from array_tx@5815c5a7ea43143fd58502d4894ac840b5b5fb86: src/arraytx/dpd.py
# Adapted-copy policy: see src/mmw60/vendor/__init__.py
"""The three DPD schemes, side by side (milestone 1).

``none``         the drives go to the elements as steered.
``per_element``  one ILA-GMP per element, trained at that element's
                 CONDUCTED port — by default its own PA forward output
                 (``per_element_observe: pa_output``: a forward coupler
                 does not see the wave coupled back from the neighbours),
                 optionally the antenna port including the leakage.
``array``        one ILA-GMP for the whole array, trained on the OTA
                 observation in the beam direction: the far-field burst at
                 theta0 after coupling.  Every element then transmits the
                 same predistorted signal, steered.

The predistorter is PA_DPD's ``ILAPredistorter`` over its ``GMPModel``
(vendored through polar_tx), untouched: the "PA" it sees is a callable that
runs the element chain(s) and, for the array scheme, the far-field
synthesis.  ``dpd.train_angles_deg`` fits either scheme jointly over several
scan angles (one least-squares problem over all of them) instead of at the
beam; the bank then does not depend on the angle it is used at.
Nothing in the chain moves between training and use: the
envelope full scale is pinned (element.py) and each element's run seed is
fixed, so the ILA iterates against one deterministic device.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from .beam import far_field, steer
from .config import ArrayConfig
from .coupling import CouplingMatrix, apply_coupling
from .element import ElementChain
from .geometry import ArrayGeometry
from .vendor.polartx.vendor.padpd.dpd import ILAPredistorter
from .vendor.polartx.vendor.padpd.pa.base import lstsq_fit
from .vendor.polartx.vendor.padpd.pa.gmp import GMPModel
from .vendor.polartx.waveforms.base import Waveform

SCHEMES = ("none", "per_element", "array")


def make_ila(cfg: ArrayConfig) -> ILAPredistorter:
    g = cfg.dpd.gmp
    kw = dict(order=g.order, memory_depth=g.memory_depth,
              lag_order=g.lag_order, lag_memory=g.lag_memory, lag_span=g.lag_span,
              lead_order=g.lead_order, lead_memory=g.lead_memory, lead_span=g.lead_span)
    return ILAPredistorter(model_factory=lambda: GMPModel(**kw),
                           n_iterations=cfg.dpd.n_iterations,
                           fit_kwargs={"regularization": cfg.dpd.regularization})


@dataclass
class DPDBank:
    scheme: str
    per_element: list[ILAPredistorter] = field(default_factory=list)
    array: ILAPredistorter | None = None
    info: dict[str, Any] = field(default_factory=dict)

    def n_coeffs(self) -> int:
        if self.scheme == "per_element":
            return sum(d.dpd_model.n_coeffs for d in self.per_element)
        if self.scheme == "array" and self.array is not None:
            return int(self.array.dpd_model.n_coeffs)
        return 0


def _run_all(elements: list[ElementChain], drives: list[np.ndarray], wf: Waveform, noise: bool) -> np.ndarray:
    return np.stack([el.run(d, wf, noise=noise).y for el, d in zip(elements, drives)])


def train(cfg: ArrayConfig, scheme: str, *, elements: list[ElementChain], x: np.ndarray,
          wf: Waveform, geom: ArrayGeometry, coupling: CouplingMatrix, theta0_deg: float,
          radiate=None) -> DPDBank:
    """Train the scheme's predistorter(s) for the beam at theta0, or jointly
    over ``dpd.train_angles_deg`` when that is set (one path: a single angle
    is the joint fit over one pair, the same least-squares problem as
    ``ILAPredistorter.fit``, bit for bit -- tests/test_loadpull.py).

    ``radiate(drives) -> (results, ys, rs)`` is the simulator's own path
    (``ArraySim.radiate``); with load modulation on it iterates the PAs'
    operating points, so the array DPD and the antenna-port observation
    see the same PAs the final run uses.  Without it the plain chain +
    coupling is used (identical when load modulation is off)."""
    def _radiate(drives):
        if radiate is not None:
            return radiate(drives)
        ys = _run_all(elements, drives, wf, noise)
        return None, ys, apply_coupling(ys, coupling, fs, f0)
    if scheme not in SCHEMES:
        raise ValueError(f"unknown DPD scheme {scheme!r}; one of {SCHEMES}")
    noise = cfg.sim.noise
    fs, f0 = wf.fs, geom.f0_hz
    bank = DPDBank(scheme)
    if scheme == "none":
        return bank
    joint = bool(cfg.dpd.train_angles_deg)
    angles = list(cfg.dpd.train_angles_deg) if joint else [theta0_deg]
    return _train_joint(cfg, scheme, elements=elements, x=x, wf=wf, geom=geom, coupling=coupling,
                        angles=angles, joint=joint, _radiate=_radiate)


def _joint_ila(cfg: ArrayConfig, pas: list[Callable[[np.ndarray], np.ndarray]], xs: list[np.ndarray]) -> ILAPredistorter:
    """ILA over several (PA, input) pairs at once: the same loop as
    ``ILAPredistorter.fit`` (target gain from the first pass, post-inverse
    fitted on y/G -> u, then u = DPD(x)), with the GMP basis matrices of
    all pairs stacked into ONE least-squares problem.  Stacking the bases
    instead of concatenating the signals keeps the memory taps from
    reaching across from one angle's burst into the next.  Each pair keeps
    its own target gain (the gain at 0 deg and at 60 deg need not agree);
    the predistorter's ``target_gain`` is the first pair's."""
    ila = make_ila(cfg)
    us = list(xs)
    gains: list[complex] = []
    for it in range(ila.n_iterations):
        ys = [pa(u) for pa, u in zip(pas, us)]
        if it == 0:
            gains = [complex(np.vdot(x, y) / np.vdot(x, x)) for x, y in zip(xs, ys)]
        model = ila.model_factory()
        phi = np.vstack([model.basis_matrix(y / g) for y, g in zip(ys, gains)])
        model.coeffs = lstsq_fit(phi, np.concatenate(us), **ila.fit_kwargs)
        ila.dpd_model = model
        if it < ila.n_iterations - 1:
            # the array scheme hands the SAME x for every angle: evaluate it once
            done: dict[int, np.ndarray] = {}
            for xi in xs:
                if id(xi) not in done:
                    done[id(xi)] = model(xi)
            us = [done[id(xi)] for xi in xs]
    ila.target_gain = gains[0]
    return ila


def _train_joint(cfg: ArrayConfig, scheme: str, *, elements, x, wf, geom, coupling, angles, joint, _radiate) -> DPDBank:
    """One predistorter (per element, or for the array) fitted over ``angles``
    (one angle: the beam).  The per-element PAs need an operating point per
    angle when load modulation is on, and the antenna-port observation needs
    the neighbours' outputs: for those, the undistorted steered drives are
    radiated once per angle and the loads it leaves are set again before
    every PA call made for that angle.  The array scheme radiates inside
    every ILA pass and needs neither."""
    noise = cfg.sim.noise
    fs, f0 = wf.fs, geom.f0_hz
    bank = DPDBank(scheme)
    angles = [float(a) for a in angles]
    drives = {th: steer(x, geom, th, fs, cfg.beam.steering) for th in angles}
    tag = {"train_angles_deg": angles} if joint else {}
    if scheme == "per_element":
        observe = cfg.dpd.per_element_observe
        need = observe == "antenna_port" or any(getattr(el, "load_pull_effective", False) for el in elements)
        loads, ys_fixed = {}, {}
        for th in angles:
            if need:
                ys_fixed[th] = _radiate(drives[th])[1]
            loads[th] = [el.load for el in elements]
        for k, el in enumerate(elements):
            def make_pa(th, k=k, el=el):
                def pa(u):
                    el.set_load(loads[th][k])
                    y = el.run(u, wf, noise=noise).y
                    if observe == "pa_output":
                        return y
                    ys = ys_fixed[th].copy()      # neighbours fixed while element k trains: O(n), not O(n^2)
                    ys[k] = y
                    return apply_coupling(ys, coupling, fs, f0)[k]
                return pa
            bank.per_element.append(_joint_ila(cfg, [make_pa(th) for th in angles], [drives[th][k] for th in angles]))
        bank.info = {"observe": observe, **tag, "target_gain": [complex(d.target_gain) for d in bank.per_element]}
        return bank

    def make_pa_array(th):
        def pa(u):
            rs = _radiate(steer(u, geom, th, fs, cfg.beam.steering))[2]
            return far_field(rs, geom, th, fs)
        return pa
    bank.array = _joint_ila(cfg, [make_pa_array(th) for th in angles], [x for _ in angles])
    observe = ("far field, jointly at " + ", ".join(f"{a:+.1f}" for a in angles) + " deg") if joint else f"far field {angles[0]:+.1f} deg"
    bank.info = {"observe": observe, **tag, "target_gain": complex(bank.array.target_gain)}
    return bank


def blend_banks(a: DPDBank, b: DPDBank, w) -> DPDBank:
    """A bank whose GMP coefficients are (1 - w) a + w b -- the in-between
    entry of a predistorter table (GMP is linear in its parameters).  Both
    banks must be the same scheme and model structure; w in [0, 1], one
    number, or (per-element scheme) one per element -- each element then
    interpolates by its own operating point."""
    import copy
    if a.scheme != b.scheme or a.scheme == "none":
        raise ValueError(f"blend needs two trained banks of one scheme, got {a.scheme!r} and {b.scheme!r}")
    ws = np.atleast_1d(np.asarray(w, dtype=float))
    if ws.size > 1 and (a.scheme != "per_element" or ws.size != len(a.per_element)):
        raise ValueError(f"per-element weights need the per_element scheme and one weight per element, got {ws.size}")
    # written so NaN fails it too (a NaN weight would put NaN coefficients into the drives)
    if ws.size == 0 or not np.all((ws >= 0.0) & (ws <= 1.0)):
        raise ValueError(f"blend weight must be in [0, 1] (finite, at least one), got {w}")
    if a.scheme == "per_element" and len(a.per_element) != len(b.per_element):
        raise ValueError(f"blend needs the same element count, got {len(a.per_element)} and {len(b.per_element)}")
    out = copy.deepcopy(a)
    pairs = list(zip(out.per_element, b.per_element)) if a.scheme == "per_element" else [(out.array, b.array)]
    for i, (d, e) in enumerate(pairs):
        # same basis, not just the same number of coefficients
        if d.dpd_model.get_config() != e.dpd_model.get_config() or d.dpd_model.coeffs.shape != e.dpd_model.coeffs.shape:
            raise ValueError("blend needs the same model structure in both banks")
        wi = float(ws[i] if ws.size > 1 else ws[0])
        d.dpd_model.coeffs = (1.0 - wi) * d.dpd_model.coeffs + wi * e.dpd_model.coeffs
        d.target_gain = complex((1.0 - wi) * d.target_gain + wi * e.target_gain)
    out.info = {"observe": f"blend of [{a.info.get('observe')}] and [{b.info.get('observe')}]",
                "blend": float(ws[0]) if ws.size == 1 else ws.tolist(), "a": a.info, "b": b.info}
    return out


def predistort_drives(bank: DPDBank, x: np.ndarray, geom: ArrayGeometry, theta0_deg: float,
                      fs: float, steering: str) -> list[np.ndarray]:
    """The element drives for the common signal ``x`` under the bank's scheme."""
    if bank.scheme == "none":
        return steer(x, geom, theta0_deg, fs, steering)
    if bank.scheme == "per_element":
        drives = steer(x, geom, theta0_deg, fs, steering)
        return [d(dr) for d, dr in zip(bank.per_element, drives)]
    assert bank.array is not None
    return steer(bank.array(x), geom, theta0_deg, fs, steering)
