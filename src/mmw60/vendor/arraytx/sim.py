# Vendored from array_tx@5815c5a7ea43143fd58502d4894ac840b5b5fb86: src/arraytx/sim.py
# Adapted-copy policy: see src/mmw60/vendor/__init__.py
"""ArraySim: one config in, far-field metrics out.

Data flow for one run (one scan angle, one DPD scheme)::

    standard -> waveform x (unit power) -> CFR (common) -> [DPD] -> steer
      -> element k chain -> y_k (conducted, diagnostic)
      -> apply_coupling -> r_k (radiated)
      -> far_field(theta) for theta in {beam, sidelobe} -> OTA metrics

Everything random comes from ``SeedTree(cfg.seed)``; nothing here draws.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .beam import far_field, far_field_many, highest_sidelobe_direction
from .config import ArrayConfig
from .coupling import CouplingMatrix, apply_coupling, build_coupling
from .dpd import DPDBank, predistort_drives, train
from .element import ElementChain, ElementResult, build_elements
from .geometry import ArrayGeometry
from .loadpull import active_reflection
from .metrics import DirectionMetrics, conducted_metrics, ota_metrics
from .report import engine_line
from .seeds import SeedTree
from .standards import Standard, get_standard
from .vendor.polartx.vendor.padpd.cfr import cfr_clip_filter
from .vendor.polartx.waveforms.base import Waveform


def smoke() -> bool:
    return os.environ.get("ARRAYTX_SMOKE", "") not in ("", "0")


@dataclass
class ArrayResult:
    theta0_deg: float
    scheme: str
    sidelobe_deg: float | None
    drives: list[np.ndarray]
    element_results: list[ElementResult]
    ys: np.ndarray                      # (n, N) conducted
    rs: np.ndarray                      # (n, N) radiated (after coupling)
    far: dict[str, tuple[float, np.ndarray]]     # label -> (theta, far-field burst)
    ota: dict[str, DirectionMetrics]             # label -> metrics (acceptance)
    conducted: list[DirectionMetrics]            # per element (diagnostic)
    dpd: DPDBank
    engine_modes: list[str]
    seconds: float
    info: dict[str, Any] = field(default_factory=dict)

    @property
    def beam(self) -> DirectionMetrics:
        return self.ota["beam"]

    @property
    def sidelobe(self) -> DirectionMetrics | None:
        return self.ota.get("sidelobe")


class ArraySim:
    def __init__(self, cfg: ArrayConfig, *, n_symbols: int | None = None):
        self.cfg = cfg
        self.standard: Standard = get_standard(cfg.standard)
        if cfg.sim.oversampling:
            self.standard = self.standard.with_oversampling(cfg.sim.oversampling)
        self.tree = SeedTree(cfg.seed, cfg.array.n_elements * cfg.array.n_rows)
        self.geom = ArrayGeometry(cfg.array.n_elements, cfg.array.n_rows, cfg.array.spacing_lambda,
                                  cfg.array.spacing_y_lambda, float(self.standard.carrier_hz.value),
                                  cfg.array.element_pattern, cfg.beam.plane_phi_deg)
        if n_symbols is None:
            n_symbols = cfg.sim.smoke_n_symbols if smoke() else cfg.sim.n_symbols
        self.n_symbols = int(n_symbols)
        self.wf: Waveform = self.standard.make_waveform(self.n_symbols, self.tree.int_seed("waveform"))
        x = self.wf.x
        if cfg.sim.cfr_papr_db is not None:
            x = cfr_clip_filter(x, cfg.sim.cfr_papr_db, self.wf.fs, self.wf.bw)
        self.x = x
        self.coupling: CouplingMatrix = build_coupling(cfg, self.geom, self.wf.fs)
        self.elements: list[ElementChain] = build_elements(cfg, self.standard, self.tree, self.x, self.wf)
        #: the last ``radiate`` with load modulation: iterations, deltas, |1+Gamma| stats (None otherwise)
        self.last_load_pull: dict[str, Any] | None = None
        #: banks trained jointly over dpd.train_angles_deg do not depend on the
        #: beam angle: one per scheme for the life of this ArraySim
        self._joint_banks: dict[tuple, DPDBank] = {}

    # ------------------------------------------------------------- pieces
    @property
    def fs(self) -> float:
        return self.wf.fs

    @property
    def f0(self) -> float:
        return self.geom.f0_hz

    def sidelobe_direction(self, theta0_deg: float) -> float | None:
        if self.cfg.beam.sidelobe == "auto":
            return highest_sidelobe_direction(self.geom, theta0_deg, self.cfg.beam.steering)
        return float(self.cfg.beam.sidelobe)

    @property
    def load_pull_active(self) -> bool:
        """Load modulation runs when it is switched on, at least one element
        has something for the load to act on (a polar DPA with a knee, or an
        outphasing combiner with a source impedance), and there is coupling to
        pull with (S = 0 leaves Gamma = 0, and the plain path, bit for bit)."""
        return (self.cfg.element.pa.load_pull.enabled and not self.coupling.is_zero
                and any(getattr(e, "load_pull_effective", False) for e in self.elements))

    def _run_all(self, drives):
        res = [el.run(d, self.wf, noise=self.cfg.sim.noise) for el, d in zip(self.elements, drives)]
        return res, np.stack([r.y for r in res])

    def radiate(self, drives: list[np.ndarray]) -> tuple[list[ElementResult], np.ndarray, np.ndarray]:
        """Element outputs and the radiated (coupled) waves for these drives.

        With load modulation: start from the matched-load PAs, compute each
        element's active reflection coefficient from the leakage, re-run
        the PAs under that load, ``iterations`` times (the fixed point of
        Gamma -> PA -> Gamma); the elements keep the last load, which is
        the operating point a per-element DPD then trains against."""
        if not self.load_pull_active:
            res, ys = self._run_all(drives)
            return res, ys, apply_coupling(ys, self.coupling, self.fs, self.f0)
        lp = self.cfg.element.pa.load_pull
        for el in self.elements:
            el.set_load(None)
        res, ys = self._run_all(drives)
        # the floor follows each element's own signal scale (full scale x the per-element output gain)
        floors = [lp.floor * (el.fs_scale * el.out_gain if el.fs_scale else float(np.abs(y).max()))
                  for el, y in zip(self.elements, ys)]
        deltas = []
        clip = np.zeros(len(self.elements))
        for _ in range(int(lp.iterations)):
            rs = apply_coupling(ys, self.coupling, self.fs, self.f0)
            gamma = active_reflection(ys, rs, floors, lp.gamma_max)
            # how often the guard acted, among the samples it can act on (above the
            # floor), in the round where it acted most: a clip in round 1 moves ys
            # even if round 2 sits just under the limit
            live = np.abs(ys) > np.asarray(floors).reshape(-1, 1)
            hit = (np.abs(gamma) >= lp.gamma_max * (1 - 1e-12)) & live
            clip = np.maximum(clip, hit.sum(axis=1) / np.maximum(live.sum(axis=1), 1))
            for el, g in zip(self.elements, gamma):
                el.set_load(g)
            res, ys_new = self._run_all(drives)
            deltas.append(float(np.linalg.norm(ys_new - ys) / max(np.linalg.norm(ys), 1e-300)))
            ys = ys_new
        rs = apply_coupling(ys, self.coupling, self.fs, self.f0)
        ga = np.abs(1.0 + gamma)
        lg = np.stack([el.load_gain(g) for el, g in zip(self.elements, gamma)])
        self.last_load_pull = {"iterations": int(lp.iterations), "deltas": deltas,
                               "abs_1pg_mean": ga.mean(axis=1).tolist(), "abs_1pg_std": ga.std(axis=1).tolist(),
                               "load_gain_mean": lg.mean(axis=1).tolist(), "load_gain_std": lg.std(axis=1).tolist(),
                               "abs_gamma_max": np.abs(gamma).max(axis=1).tolist(),
                               # how often the |Gamma| guard acted (a guard, not physics: if this is not
                               # ~0 the numbers depend on gamma_max -- cairn/load-pull-proposal.md)
                               "clip_fraction": clip.tolist()}
        return res, ys, rs

    def far_field(self, rs: np.ndarray, theta_deg: float) -> np.ndarray:
        return far_field(rs, self.geom, theta_deg, self.fs)

    def far_field_many(self, rs: np.ndarray, thetas_deg) -> np.ndarray:
        return far_field_many(rs, self.geom, thetas_deg, self.fs)

    # ---------------------------------------------------------------- run
    def run(self, theta0_deg: float | None = None, scheme: str | None = None,
            *, extra_directions: dict[str, float] | None = None,
            conducted_diagnostics: bool = True) -> ArrayResult:
        t0 = time.time()
        cfg = self.cfg
        theta0 = float(cfg.beam.scan_deg[0] if theta0_deg is None else theta0_deg)
        scheme = scheme or cfg.dpd.scheme
        self.last_load_pull = None
        # a bank trained jointly over dpd.train_angles_deg does not depend on the
        # beam angle: train once, keyed on everything training reads from the config
        joint_key = (scheme, repr(cfg.dpd), cfg.beam.steering, cfg.sim.noise) if cfg.dpd.train_angles_deg and scheme != "none" else None
        if joint_key is not None and joint_key in self._joint_banks:
            bank = self._joint_banks[joint_key]
        else:
            bank = train(cfg, scheme, elements=self.elements, x=self.x, wf=self.wf, geom=self.geom,
                         coupling=self.coupling, theta0_deg=theta0, radiate=self.radiate)
            if joint_key is not None:
                self._joint_banks[joint_key] = bank
        drives = predistort_drives(bank, self.x, self.geom, theta0, self.fs, cfg.beam.steering)
        res, ys, rs = self.radiate(drives)
        sl = self.sidelobe_direction(theta0)
        dirs: dict[str, float] = {"beam": theta0}
        if sl is not None:
            dirs["sidelobe"] = sl
        if extra_directions:
            dirs.update(extra_directions)
        far = {k: (th, self.far_field(rs, th)) for k, th in dirs.items()}
        offsets = tuple(cfg.metrics.aclr_offsets)
        ota = {k: ota_metrics(e, self.wf, th, k, offsets=offsets, equalize=cfg.metrics.evm_equalize)
               for k, (th, e) in far.items()}
        cond = []
        if conducted_diagnostics:
            cond = [conducted_metrics(ys[k], self.wf, k, offsets=offsets, equalize=cfg.metrics.evm_equalize)
                    for k in range(self.geom.n)]
        modes = [r.phasemod_mode for r in res]
        # efficiency once, here: every element still holds the load of this final run
        effs = []
        for el, r in zip(self.elements, res):
            e = el.efficiency(r)
            if e is not None:
                r.info["element"]["efficiency"] = e
                effs.append(e)
        efficiency = None
        if effs:
            etas = [e["eta_avg"] for e in effs]
            lo = [e["eta_loaded"] for e in effs]
            efficiency = {"eta_avg_mean": float(np.mean(etas)), "eta_avg_min": float(min(etas)), "eta_avg_max": float(max(etas)),
                          "eta_loaded_mean": float(np.mean(lo)), "eta_loaded_min": float(min(lo)), "eta_loaded_max": float(max(lo)),
                          "eta_loaded_per_element": [float(v) for v in lo], "law": effs[0]["law"],
                          "note": "eta_avg_*: polar_tx DPA law on the matched-load table; eta_loaded_*: net port power "
                                  "|a|^2 (1 - |Gamma|^2) over net + switching loss (cairn/loaded-efficiency-proposal.md)"}
            # the array: total radiated power (= the sum of net port powers, lossless
            # antennas) over total DC; the matched figure the same way, for comparison
            pn, pl, pm = (sum(e[k] for e in effs) for k in ("p_net", "p_loss", "p_matched"))
            efficiency["eta_array_loaded"] = pn / (pn + pl) if pn + pl > 0 else 0.0
            efficiency["eta_array_matched"] = pm / (pm + pl) if pm + pl > 0 else 0.0
            efficiency["n_backflow"] = int(sum(e["n_backflow"] for e in effs))
        return ArrayResult(theta0, scheme, sl, drives, res, ys, rs, far, ota, cond, bank, modes,
                           time.time() - t0,
                           info={"coupling_source": self.coupling.source,
                                 "coupling_max_offdiag_db": self.coupling.max_offdiag_db(),
                                 "n_symbols": self.n_symbols, "fs": self.fs,
                                 "load_pull": self.last_load_pull,
                                 "efficiency": efficiency,
                                 "engine_line": engine_line(modes, cfg.element.topology,
                                                              int(self.standard.oversampling.value))})

    def run_matrix(self, scan_deg=None, schemes=None) -> dict[tuple[float, str], ArrayResult]:
        scan = list(self.cfg.beam.scan_deg if scan_deg is None else scan_deg)
        schemes = list(schemes or ("none", "per_element", "array"))
        return {(float(th), s): self.run(th, s) for th in scan for s in schemes}
