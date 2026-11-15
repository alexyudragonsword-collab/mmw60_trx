# Vendored from array_tx@5815c5a7ea43143fd58502d4894ac840b5b5fb86: src/arraytx/guiutil.py
# Adapted-copy policy: see src/mmw60/vendor/__init__.py
"""What the page computes, behind plain functions returning JSON-ready
dicts.  Nothing here is physics: every number comes from ``ArraySim`` and
the same metric functions the examples use; this module only arranges them
for a renderer and adds the plot data (downsampled where a page would choke
on 140k samples).

``run_report`` is the unit: one config, one scan angle, one DPD scheme ->
the OTA metrics at the beam and the highest sidelobe (acceptance), the
conducted metrics per element (diagnostic, labelled so), three plots, the
engine line, timing and a reproducibility card (seed, config hash, vendored
pins, the equivalent two lines of Python).  ``scan_report`` is that over
``scan_deg x schemes`` on ONE ArraySim (one waveform, one set of element
draws), which is what the page's main table shows.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

import numpy as np

from .beam import beamwidth_3db_deg, squint_analytic_deg
from .config import ArrayConfig, config_from_dict
from .guispec import to_yaml, values_from_config
from .metrics import SEM_TX_POWER_DBM, ota_metrics
from .sim import ArrayResult, ArraySim
from .vendor.polartx.metrics.masks import default_mask_spec
from .vendor.polartx.metrics.sem import check_sem
from .vendor.polartx.vendor.padpd.metrics import psd
from .vendor.polartx.vendor.padpd.waveform.ofdm import demodulate_ofdm

VENDOR = Path(__file__).resolve().parent / "vendor"
_PIN_FILES = {"polar_tx": "polartx/chain.py", "PA_DPD": "polartx/vendor/padpd/pa/thermal.py",
              "pll_simulator": "polartx/vendor/pllsim/export/clock_profile.py"}
_HDR = re.compile(r"#\s*Vendored from (\w+)@([0-9a-f]{7,40})")

#: directions the ACLR-vs-direction plot reports (1 deg grid, as ex04)
DIRECTION_STEP_DEG = 1.0
#: the pattern level below which a direction is a null: ACLR there is real but
#: nobody transmits into it (ex04 greys it out and does not report it)
NULL_BELOW_DB = -15.0
#: constellation points sent to the page (of n_symbols x 3168)
MAX_CONSTELLATION = 4000
#: Welch size for the plotted spectrum (the SEM margin number itself comes
#: from metrics.py's 4096-point PSD; the plot is a lighter copy)
PLOT_NFFT = 2048


def pins() -> dict[str, str]:
    """``{repo: sha}`` of the vendored trees, read from the files' own headers."""
    out = {}
    for repo, rel in _PIN_FILES.items():
        try:
            head = (VENDOR / rel).read_text(encoding="utf-8").splitlines()[0]
        except OSError:
            continue
        m = _HDR.search(head)
        if m and m.group(1) == repo:
            out[repo] = m.group(2)
    return out


def config_sha(cfg: ArrayConfig) -> str:
    """sha256 of the config's leaves (canonical JSON of the flat values)."""
    flat = values_from_config(cfg)
    s = json.dumps({k: _json(v) for k, v in flat.items()}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _json(v):
    if isinstance(v, (np.floating, np.integer)):
        return v.item()
    if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
        return str(v)
    if isinstance(v, (list, tuple)):
        return [_json(x) for x in v]
    return v


def _cfg(cfg: ArrayConfig | dict) -> ArrayConfig:
    return cfg if isinstance(cfg, ArrayConfig) else config_from_dict(cfg)


def _metrics_row(m, extra: dict | None = None) -> dict[str, Any]:
    d = {"domain": m.domain, "where": m.where, "theta_deg": m.theta_deg,
         "evm_db": m.evm_db, "evm_pct": m.evm_pct, "aclr1_dbc": m.aclr1_db, "aclr2_dbc": m.aclr2_db}
    if m.sem:
        d["sem_margin_db"] = m.sem.get("worst_margin_db")
        d["sem_passes"] = m.sem.get("passes")
        d["sem_source"] = m.sem.get("source")
        d["sem_is_conformance"] = m.sem.get("is_conformance")
    if extra:
        d.update(extra)
    return d


def direction_scan(sim: ArraySim, rs: np.ndarray, thetas_deg, *, nperseg: int = 4096) -> tuple[np.ndarray, np.ndarray]:
    """ACLR1 (dBc, worst side) and radiated power (dB) per direction, from
    Welch segments of the ELEMENT signals combined per direction.

    ``metrics.aclr1_vs_direction`` synthesises the full-length far field in
    every direction (181 inverse FFTs of the whole burst plus 181 Welch
    PSDs: 10 s at 8 symbols), which a page cannot wait for after every run.
    Welch is linear in the signal, so the far field's Welch PSD is the
    per-segment combination  E_seg(f) = sum_k g/n exp(j 2 pi (f0+f) tau_k) X_k,seg(f)
    of the elements' segment FFTs, taken once: same window, same segment
    length and overlap, same band sums as ``aclr_multi``.  The one
    approximation is the delay applied per segment instead of over the
    whole burst (tau_k is ~0.01 sample: an edge effect below 1e-4);
    ``tests/test_guiutil.py`` holds it to 0.05 dB against the exact path."""
    rs = np.asarray(rs)
    n, N = rs.shape
    fs, bw = sim.fs, sim.wf.bw
    nperseg = min(nperseg, N)
    step = nperseg // 2                                      # welch default noverlap
    if n * ((N - nperseg) // step + 1) * nperseg > 40_000_000:   # > ~640 MB of segment FFTs: no overlap
        step = nperseg
    k_seg = (N - nperseg) // step + 1
    idx = np.arange(nperseg)[None, :] + step * np.arange(k_seg)[:, None]
    win = np.hanning(nperseg + 1)[:-1]                        # scipy's periodic 'hann'
    X = np.fft.fft(rs[:, idx] * win, axis=2)                 # (n, K, F)
    f = np.fft.fftfreq(nperseg, 1.0 / fs)
    scale = 1.0 / (fs * np.sum(win ** 2))
    meas = 0.9 * bw
    band = lambda fc: (f >= fc - meas / 2) & (f < fc + meas / 2)    # noqa: E731
    b0, bl, bu = band(0.0), band(-bw), band(bw)
    thetas = np.atleast_1d(np.asarray(thetas_deg, dtype=float))
    aclr = np.empty(thetas.size)
    power = np.empty(thetas.size)
    for i, th in enumerate(thetas):
        tau = sim.geom.delays_s(th)
        g = sim.geom.element_gain(th) / n
        ph = g * np.exp(1j * 2 * np.pi * np.outer(tau, sim.f0 + f))        # (n, F)
        E = np.einsum("kf,ksf->sf", ph, X)
        pxx = np.mean(np.abs(E) ** 2, axis=0) * scale
        p0 = pxx[b0].sum()
        aclr[i] = 10 * np.log10(max(pxx[bl].sum(), pxx[bu].sum()) / p0) if p0 > 0 else np.nan
        power[i] = 10 * np.log10(max(pxx.sum() * fs / nperseg, 1e-300))
    return aclr, power


def _plots(sim: ArraySim, r: ArrayResult) -> dict[str, Any]:
    th = np.arange(-90.0, 90.0 + DIRECTION_STEP_DEG / 2, DIRECTION_STEP_DEG)
    aclr, patt = direction_scan(sim, r.rs, th)
    patt = patt - patt.max()
    null = patt < NULL_BELOW_DB
    direction = {"theta_deg": th.tolist(), "aclr1_dbc": [None if n else float(a) for a, n in zip(aclr, null)],
                 "pattern_db": patt.tolist(), "beam_deg": r.theta0_deg, "sidelobe_deg": r.sidelobe_deg,
                 "null_below_db": NULL_BELOW_DB}
    e_beam = r.far["beam"][1]
    f, p = psd(e_beam, sim.fs, nfft=PLOT_NFFT)
    spec = default_mask_spec(sim.wf)
    sem = check_sem(f, p, spec, channel_bw_hz=sim.wf.bw, tx_power_dbm=SEM_TX_POWER_DBM)
    spectrum = {"f_mhz": (f / 1e6).tolist(), "psd_db": p.tolist(), "mask_db": np.asarray(sem["limit_db"]).tolist(),
                "mask_source": spec.source, "mask_is_conformance": bool(spec.is_conformance),
                "bw_mhz": sim.wf.bw / 1e6, "rbw_hz": sem.get("rbw_hz")}
    ref = sim.wf.require_ofdm_ref()
    rx = demodulate_ofdm(e_beam, ref)
    g = np.vdot(ref.tx_symbols, rx) / np.vdot(ref.tx_symbols, ref.tx_symbols)
    pts = (rx / g).ravel()
    if pts.size > MAX_CONSTELLATION:
        pts = pts[np.linspace(0, pts.size - 1, MAX_CONSTELLATION).astype(int)]
    constellation = {"i": pts.real.round(4).tolist(), "q": pts.imag.round(4).tolist(),
                     "equalize": "scalar", "qam": int(getattr(ref.config, "qam_order", 0))}
    return {"direction": direction, "spectrum": spectrum, "constellation": constellation}


def report_from_result(sim: ArraySim, r: ArrayResult, *, with_plots: bool = True) -> dict[str, Any]:
    """The JSON-ready report of one ``ArraySim.run`` result."""
    cfg = sim.cfg
    bw2 = sim.wf.bw / 2
    beam_pt = ota_metrics(r.far["beam"][1], sim.wf, r.theta0_deg, "beam", offsets=(1,),
                          equalize="per_tone", with_sem=False).evm_db
    ota = {"beam": _metrics_row(r.beam, {"evm_per_tone_db": beam_pt})}
    if r.sidelobe is not None:
        ota["sidelobe"] = _metrics_row(r.sidelobe)
    diag = [{"element": k, "conducted_evm_db": c.evm_db, "conducted_aclr1_dbc": c.aclr1_db,
             "conducted_aclr2_dbc": c.aclr2_db,
             "errors": {"gain_db": e.errors.gain_db, "phase_deg": e.errors.phase_deg,
                        "delay_ps": e.errors.delay_s * 1e12, "pa_dev": e.errors.pa_dev}}
            for k, (c, e) in enumerate(zip(r.conducted, sim.elements))]
    squint = squint_analytic_deg(r.theta0_deg, sim.f0, bw2)
    out = {
        "theta0_deg": r.theta0_deg, "scheme": r.scheme, "steering": cfg.beam.steering,
        "sidelobe_deg": r.sidelobe_deg, "ota": ota, "diagnostic": diag,
        "info": {"squint_deg": squint, "beamwidth_deg": beamwidth_3db_deg(sim.geom, r.theta0_deg, cfg.beam.steering),
                 "n_elements": sim.geom.n, "n_x": sim.geom.n_x, "n_rows": sim.geom.n_y, "plane_phi_deg": sim.geom.plane_phi_deg,
                 "f0_ghz": sim.f0 / 1e9, "bw_mhz": sim.wf.bw / 1e6,
                 "fs_gsps": sim.fs / 1e9, "n_symbols": sim.n_symbols, "n_samples": int(sim.wf.n),
                 "coupling_source": sim.coupling.source, "coupling_max_offdiag_db": sim.coupling.max_offdiag_db(),
                 "evm_equalize": cfg.metrics.evm_equalize,
                 "eta_array_pct": None if r.info.get("efficiency") is None else 100.0 * r.info["efficiency"]["eta_array_loaded"],
                 "eta_array_matched_pct": None if r.info.get("efficiency") is None else 100.0 * r.info["efficiency"]["eta_array_matched"],
                 "backoff_db": cfg.element.pa.backoff_db,
                 "backoff_per_element_db": list(cfg.element.pa.backoff_per_element_db) or None,
                 # what the PAs saw (load pull on): the |1 + Gamma_k| the per-element means span
                 "load_pull": _load_pull_stats(r)},
        "engine_line": r.info["engine_line"], "engine_modes": sorted(set(r.engine_modes)),
        "seconds": r.seconds,
        "repro": {"seed": cfg.seed, "config_sha256": config_sha(cfg), "pins": pins(),
                  "source_path": cfg.source_path,
                  "call": (f"sim = ArraySim(load_config({cfg.source_path!r}))\n"
                           f"r = sim.run(theta0_deg={r.theta0_deg}, scheme={r.scheme!r})")},
    }
    if with_plots:
        out["plots"] = _plots(sim, r)
    return out


def _load_pull_stats(r: ArrayResult) -> dict[str, float] | None:
    lp = r.info.get("load_pull")
    if not lp or not lp.get("abs_1pg_mean"):
        return None
    m = np.asarray(lp["abs_1pg_mean"], dtype=float)
    return {"abs_1pg_mean": float(m.mean()), "abs_1pg_min": float(m.min()), "abs_1pg_max": float(m.max()),
            "clip_fraction_max": float(max(lp.get("clip_fraction") or [0.0]))}


def run_report(cfg: ArrayConfig | dict, theta0_deg: float | None = None, scheme: str | None = None,
               *, n_symbols: int | None = None, with_plots: bool = True) -> dict[str, Any]:
    """One run -> one report (see the module docstring)."""
    sim = ArraySim(_cfg(cfg), n_symbols=n_symbols)
    r = sim.run(theta0_deg, scheme)
    return report_from_result(sim, r, with_plots=with_plots)


def scan_report(cfg: ArrayConfig | dict, scan_deg=None, schemes=None, *, n_symbols: int | None = None,
                with_plots: bool = True, progress=None) -> dict[str, Any]:
    """``scan_deg x schemes`` on one ArraySim.  ``progress(i, n, row)`` is
    called after each run (the host streams rows to the page as they land)."""
    c = _cfg(cfg)
    sim = ArraySim(c, n_symbols=n_symbols)
    scan = [float(t) for t in (c.beam.scan_deg if scan_deg is None else scan_deg)]
    schemes = list(schemes or ("none", "per_element", "array"))
    rows = []
    t0 = time.time()
    n = len(scan) * len(schemes)
    for th in scan:
        for s in schemes:
            rep = report_from_result(sim, sim.run(th, s), with_plots=with_plots)
            rows.append(rep)
            if progress is not None:
                progress(len(rows), n, rep)
    return {"rows": rows, "scan_deg": scan, "schemes": schemes, "seconds": time.time() - t0,
            "engine_line": rows[0]["engine_line"] if rows else "", "repro": rows[0]["repro"] if rows else {}}


def sweep_report(cfg: ArrayConfig | dict, path: str, points, theta0_deg: float | None = None,
                 scheme: str | None = None, *, n_symbols: int | None = None, with_plots: bool = True,
                 progress=None, group_path: str | None = None, group_values=None) -> dict[str, Any]:
    """One control, many values: the page's form of ex05 (clock profile),
    ex06 (element count) and ex07 (spurs on / off).  Every point is a fresh
    ArraySim built from the config with that one leaf changed through
    ``values_to_config`` (so the YAML the point would save is what ran),
    everything else -- seed, waveform, draws of the elements that still
    exist -- unchanged (invariant 5).  Rows carry ``sweep`` = {path, value}.

    ``group_path`` / ``group_values`` repeat the sweep for each value of a
    SECOND leaf (ex06's two lines: steering phase vs ttd); the rows then also
    carry ``group_path`` / ``group_value`` and the page draws one line per
    group.  The groups run in order, points within a group in order."""
    from .guispec import values_to_config
    base = _cfg(cfg)
    flat0 = values_from_config(base)
    rows = []
    t0 = time.time()
    pts = list(points)
    groups = [None] if not group_path else list(group_values or [])
    n_total = len(pts) * len(groups)
    for gi, gv in enumerate(groups):
        for i, v in enumerate(pts):
            flat = dict(flat0)
            if group_path:
                flat[group_path] = gv
            flat[path] = v
            c = values_to_config(flat, base)
            sim = ArraySim(c, n_symbols=n_symbols)
            rep = report_from_result(sim, sim.run(theta0_deg, scheme), with_plots=with_plots)
            rep["sweep"] = {"path": path, "value": _json(v), "index": i, "n": len(pts)}
            if group_path:
                rep["sweep"].update({"group_path": group_path, "group_value": _json(gv), "group_index": gi, "n_groups": len(groups)})
            rows.append(rep)
            if progress is not None:
                progress(len(rows), n_total, rep)
    return {"rows": rows, "path": path, "points": [_json(v) for v in pts], "group_path": group_path,
            "group_values": [_json(g) for g in groups] if group_path else None, "seconds": time.time() - t0,
            "engine_line": rows[0]["engine_line"] if rows else "", "repro": rows[0]["repro"] if rows else {}}


def rule_report(cfg: ArrayConfig | dict, scan_deg, backoffs, *, aclr_target_dbc: float, evm_target_db: float,
                margin_db: float = 0.0, scheme: str = "per_element", n_symbols: int | None = None,
                with_plots: bool = True, progress=None) -> dict[str, Any]:
    """The page's form of ex19 Part 1: every scan angle x output backoff
    (``element.pa.backoff_db``, one fresh ArraySim per backoff, everything
    else unchanged), then per angle the least backoff meeting the targets and
    the mean |1 + Gamma| there, and the rule backoff(|1 + Gamma|) they make
    (``design.backoff_rule``).  The targets are design choices the caller
    passes (source: assumed), not config.  Rows are ordinary reports carrying
    ``sweep`` (path = backoff, group = the angle) so the page draws them as a
    grouped study; the table is in the summary."""
    from .design import backoff_rule, meets
    from .guispec import values_to_config
    base = _cfg(cfg)
    flat0 = values_from_config(base)
    scan = [float(t) for t in scan_deg]
    bos = sorted(float(b) for b in backoffs)
    sims: dict[float, ArraySim] = {}
    rows = []
    t0 = time.time()
    n_total = len(scan) * len(bos)
    for gi, th in enumerate(scan):
        for i, b in enumerate(bos):
            if b not in sims:
                flat = dict(flat0)
                flat["element.pa.backoff_db"] = b
                sims[b] = ArraySim(values_to_config(flat, base), n_symbols=n_symbols)
            sim = sims[b]
            rep = report_from_result(sim, sim.run(th, scheme), with_plots=with_plots)
            rep["sweep"] = {"path": "element.pa.backoff_db", "value": b, "index": i, "n": len(bos),
                            "group_path": "theta0_deg", "group_value": th, "group_index": gi, "n_groups": len(scan)}
            rows.append(rep)
            if progress is not None:
                progress(len(rows), n_total, rep)
    table = []
    for th in scan:
        here = [r for r in rows if r["theta0_deg"] == th]
        ok = [r["sweep"]["value"] for r in here
              if meets(r["ota"]["beam"]["aclr1_dbc"], r["ota"]["beam"]["evm_db"], margin_db, aclr_target_dbc, evm_target_db)]
        lp = here[0]["info"]["load_pull"]                         # at the least backoff swept
        table.append({"theta_deg": th, "abs_1pg_mean": None if lp is None else lp["abs_1pg_mean"],
                      "abs_1pg_min": None if lp is None else lp["abs_1pg_min"], "abs_1pg_max": None if lp is None else lp["abs_1pg_max"],
                      "least_backoff_db": min(ok) if ok else None,
                      "eta_pct": next((r["info"]["eta_array_pct"] for r in here if ok and r["sweep"]["value"] == min(ok)), None)})
    pairs = [(t["abs_1pg_mean"], t["least_backoff_db"]) for t in table
             if t["abs_1pg_mean"] is not None and t["least_backoff_db"] is not None]
    rule = None
    if pairs:
        _, m_sorted, b_mono, slope = backoff_rule([m for m, _ in pairs], [b for _, b in pairs])
        rule = {"abs_1pg": [float(m) for m in m_sorted], "backoff_db": [float(b) for b in b_mono], "slope_db_per_unit": slope}
    return {"rows": rows, "table": table, "rule": rule, "scan_deg": scan, "backoffs": bos, "scheme": scheme,
            "targets": {"aclr1_dbc": aclr_target_dbc, "evm_db": evm_target_db, "margin_db": margin_db, "source": "assumed"},
            "seconds": time.time() - t0, "engine_line": rows[0]["engine_line"] if rows else "",
            "repro": rows[0]["repro"] if rows else {}}


def yaml_text(cfg: ArrayConfig | dict) -> str:
    return to_yaml(_cfg(cfg))
