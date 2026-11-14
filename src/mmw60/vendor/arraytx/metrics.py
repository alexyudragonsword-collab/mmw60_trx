# Vendored from array_tx@5815c5a7ea43143fd58502d4894ac840b5b5fb86: src/arraytx/metrics.py
# Adapted-copy policy: see src/mmw60/vendor/__init__.py
"""Metrics in two domains (invariant 2).

``ota``        measured on a far-field signal in a stated direction: the
               acceptance metrics.  EVM, ACLR (1st and 2nd adjacent), SEM.
``conducted``  measured at an element's PA output: a DIAGNOSTIC.  The
               functions are named ``conducted_*`` and the result carries
               ``domain="conducted"`` so a table cannot quietly present one
               as the other.

The metric functions themselves are polar_tx's (``PolarResult.evm``'s
``evm_of_signal``, ``aclr_multi``, ``check_sem``): same conventions as a single chain, applied to a different
signal.  Every function here expects the signal sample-aligned with the
waveform reference, which the far-field synthesis guarantees in the beam
direction (array phase centre at the origin, steering compensated).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .vendor.polartx.metrics.aclr_ext import aclr_multi
from .vendor.polartx.metrics.masks import default_mask_spec
from .vendor.polartx.metrics.sem import check_sem
from .vendor.polartx.vendor.padpd.metrics import evm_of_signal, psd
from .vendor.polartx.waveforms.base import Waveform

#: the reference transmit power the stylized spectral-emission mask is drawn
#: against (polar_tx's check_sem convention); the page's mask line uses the
#: same constant so the plot and the SEM margin number cannot diverge
SEM_TX_POWER_DBM = 23.0


@dataclass
class DirectionMetrics:
    domain: str                 # "ota" | "conducted"
    where: str                  # e.g. "beam 30.0 deg", "sidelobe -17.2 deg", "element 2 PA output"
    theta_deg: float | None
    evm_db: float
    evm_pct: float
    aclr_db: dict[str, float]   # aclr1_lower_dbc, aclr1_upper_dbc, aclr2_...
    sem: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def aclr1_db(self) -> float:
        """Worst (highest) first-adjacent ACLR, dBc."""
        return max(self.aclr_db["aclr1_lower_dbc"], self.aclr_db["aclr1_upper_dbc"])

    @property
    def aclr2_db(self) -> float | None:
        if "aclr2_lower_dbc" not in self.aclr_db:
            return None
        return max(self.aclr_db["aclr2_lower_dbc"], self.aclr_db["aclr2_upper_dbc"])

    def row(self) -> dict[str, Any]:
        d = {"domain": self.domain, "where": self.where, "evm_db": self.evm_db,
             "evm_pct": self.evm_pct, "aclr1_dbc": self.aclr1_db}
        if self.aclr2_db is not None:
            d["aclr2_dbc"] = self.aclr2_db
        if self.sem:
            d["sem_margin_db"] = self.sem.get("worst_margin_db")
        return d


def _measure(y: np.ndarray, wf: Waveform, *, offsets, equalize: str, with_sem: bool,
             domain: str, where: str, theta: float | None) -> DirectionMetrics:
    y = np.asarray(y)
    if y.shape != wf.x.shape:
        raise ValueError(f"signal {y.shape} does not match the waveform {wf.x.shape}")
    # polar_tx's PolarResult.evm convention: scalar | per_tone equalisation
    e = evm_of_signal(y, wf.require_ofdm_ref(), equalize=equalize)
    ac = aclr_multi(y, wf.fs, wf.bw, offsets=tuple(int(o) for o in offsets))
    sem: dict[str, Any] = {}
    if with_sem:
        f, p = psd(y, wf.fs, nfft=4096)
        spec = default_mask_spec(wf)
        sem = check_sem(f, p, spec, channel_bw_hz=wf.bw, tx_power_dbm=SEM_TX_POWER_DBM)
        sem["spec_source"] = spec.source
    return DirectionMetrics(domain, where, theta, float(e.db), float(e.percent),
                            {k: float(v) for k, v in ac.items()}, sem)


def ota_metrics(e_theta: np.ndarray, wf: Waveform, theta_deg: float, label: str, *,
                offsets=(1, 2), equalize: str = "scalar", with_sem: bool = True) -> DirectionMetrics:
    """Acceptance metrics on the far-field signal in direction theta."""
    return _measure(e_theta, wf, offsets=offsets, equalize=equalize, with_sem=with_sem,
                    domain="ota", where=f"{label} {theta_deg:+.1f} deg", theta=theta_deg)


def conducted_metrics(y_k: np.ndarray, wf: Waveform, k: int, *, offsets=(1, 2),
                      equalize: str = "scalar") -> DirectionMetrics:
    """DIAGNOSTIC: the same metrics at element k's PA output.  Not an
    acceptance number (AGENTS.md invariant 2); examples print it under a
    'diagnostic' heading only."""
    return _measure(y_k, wf, offsets=offsets, equalize=equalize, with_sem=False,
                    domain="conducted", where=f"element {k} PA output (diagnostic)", theta=None)


def aclr1_vs_direction(e_many: np.ndarray, wf: Waveform, thetas_deg) -> np.ndarray:
    """Worst first-adjacent ACLR (dBc) for each row of ``e_many`` (one far-field
    burst per direction) — the 'where does the distortion radiate' curve."""
    out = np.empty(len(thetas_deg))
    for i in range(len(thetas_deg)):
        ac = aclr_multi(e_many[i], wf.fs, wf.bw, offsets=(1,))
        out[i] = max(ac["aclr1_lower_dbc"], ac["aclr1_upper_dbc"])
    return out


def power_vs_direction_db(e_many: np.ndarray) -> np.ndarray:
    p = np.mean(np.abs(e_many) ** 2, axis=1)
    return 10 * np.log10(np.maximum(p, 1e-300))
