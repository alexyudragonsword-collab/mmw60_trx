"""The comparison table (同台表): every scheme — topology × waveform — on one
front end, one LO chain, one channel, one EIRP ceiling (iron rule 2), with
the K = 1 baseline row, and its budget report (d2d_link's ``report`` method).

``scheme_matrix`` names **every** cell of ``TOPOLOGIES × WAVEFORMS``: the
built ones get a config and numbers (topology B's two waveforms; topology A
with the WiFi 7 waveform, ``mmw60.ifext``), the unbuilt ones a row that says
which milestone brings them (802.11ay: milestone 3) or that the pair is not
a scheme (A keeps the waveform; ay is B's hardware).
A table that silently left a scheme out would not be the comparison the
rules ask for, so ``tests/test_compare.py`` checks the matrix is complete.

Per built row, all from the same objects (``Frontend60`` built once and
handed to every ``LinkSim``):

- numerology after upclocking, the CFO in Hz and in subcarriers and whether
  the L-STF range catches it;
- the analytic EVM floor and its terms (``frontend/grid.py``), the MCS it
  allows, the same with the IQ image at the residual example 03 **measured**
  after calibration (``derived.irr_after_cal_measured_db``), the data rate
  and spectral efficiency at the cap;
- the time-domain EVM of the same cell on the wifitrx chain (flat channel,
  no noise) — the cross-check of the analytic floor;
- wifitrx's own ``EvmBudget`` fed the same terms (the "对账" of ROADMAP A3):
  it integrates the LO over 10 kHz – 100 MHz and removes the per-symbol
  CPE share, this library integrates the ICI weight up to fs_eff / 2; the
  two phase-noise terms are printed side by side and their gap explained;
- the PA operating point against the shared EIRP ceiling (57–71 GHz rows);
- the power blocks of :mod:`mmw60.power` per bit at the cap.

``sensitivity`` reruns the analytic side with every coefficient and
assumption the column leans on at its range ends and lists which rows'
MCS cap or pJ/bit ranking move (d2d's "which guesses decide the verdict").
"""
from __future__ import annotations

import dataclasses as dc
import math
from dataclasses import dataclass, field

import numpy as np

from . import spec
from .config import (TOPOLOGIES, WAVEFORMS, ChannelConfig, Mmw60Config, if_extender_60ghz, wifi7_chain_k1,
                     zero_if_60ghz)
from .frontend.frontend import Frontend60
from .frontend.grid import (REASON_ZH, analytic_floors, data_rate_bps, decoder_cap, decoder_floor_db,
                            max_mcs_for_floor, pa_isolated_evm_db)
from .power import PowerCoefficients, PowerReport, power_report
from .vendor.wifitrx.impairments.phase_noise import cpe_partition
from .vendor.wifitrx.link.evm_budget import PN_BAND_HZ, EvmBudget

#: why a (topology, waveform) cell has no numbers yet
PENDING = {
    ("upclock_zero_if", "ay_ofdm"): "pending: milestone 3 (802.11ay OFDM on the zero-IF hardware)",
    ("upclock_zero_if", "ay_sc"): "pending: milestone 3 (802.11ay single carrier)",
}
NOT_A_SCHEME = "n/a: topology A keeps the WiFi 7 waveform; the ay waveforms are topology B's hardware"


@dataclass
class Scheme:
    label: str
    topology: str
    waveform: str
    cfg: Mmw60Config | None = None
    status: str = "built"            # built | pending | n/a
    reason: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return (self.topology, self.waveform)


def scheme_matrix(ks=(1, 4, 8, 16, 32), standard: str = "11ac", bandwidth_hz: float = 20e6,
                  carrier_hz: float = 60.48e9, k1_carrier_hz: float = 6.0e9, mcs: int = 0) -> list[Scheme]:
    """One ``Scheme`` per built configuration plus one per unbuilt cell, so
    that every ``(topology, waveform)`` pair appears at least once."""
    rows: list[Scheme] = []
    for topo in TOPOLOGIES:
        for wf in WAVEFORMS:
            if (topo, wf) == ("upclock_zero_if", "be"):
                cfg = wifi7_chain_k1(mcs=mcs, standard=standard, bandwidth_hz=bandwidth_hz, carrier_hz=k1_carrier_hz)
                rows.append(Scheme(f"be {standard} {bandwidth_hz / 1e6:g}M K=1 @{k1_carrier_hz / 1e9:g} GHz (WiFi 7 chain)",
                                   topo, wf, cfg))
            elif (topo, wf) == ("upclock_zero_if", "be_upclocked"):
                for k in ks:
                    cfg = zero_if_60ghz(k=k, mcs=mcs, standard=standard, bandwidth_hz=bandwidth_hz, carrier_hz=carrier_hz)
                    rows.append(Scheme(f"be_upclocked {standard} {bandwidth_hz / 1e6:g}M K={k} @{carrier_hz / 1e9:g} GHz",
                                       topo, wf, cfg))
            elif (topo, wf) == ("if_extender", "be"):
                cfg = if_extender_60ghz(mcs=mcs, standard=standard, bandwidth_hz=bandwidth_hz, carrier_hz=carrier_hz)
                rows.append(Scheme(f"be {standard} {bandwidth_hz / 1e6:g}M IF extender @{carrier_hz / 1e9:g} GHz",
                                   topo, wf, cfg))
            elif (topo, wf) in PENDING:
                rows.append(Scheme(f"{wf} on {topo}", topo, wf, None, "pending", PENDING[(topo, wf)]))
            else:
                rows.append(Scheme(f"{wf} on {topo}", topo, wf, None, "n/a", NOT_A_SCHEME))
    return rows


def measured_irr_after_cal_db(bw_eff_hz: float) -> tuple[float, float]:
    """Example 03's calibrated IRR at the largest measured bandwidth not
    above ``bw_eff_hz`` (the residual only gets worse with bandwidth);
    returns (irr_db, bandwidth it was measured at)."""
    table = {float(k): float(v) for k, v in spec.value("derived.irr_after_cal_measured_db").items()}
    below = [b for b in table if b <= bw_eff_hz * (1 + 1e-9)]
    b = max(below) if below else min(table)
    return table[b], b


# ------------------------------------------------------------------ one row
@dataclass
class Row:
    scheme: Scheme
    k: int
    standard: str
    base_bw_hz: float
    bw_eff_hz: float
    fs_eff_hz: float
    scs_eff_hz: float
    t_symbol_eff_s: float
    carrier_hz: float
    cfo_hz: float
    cfo_subcarriers: float
    cfo_captured: bool
    stf_capture_hz: float
    terms_db: dict
    floor_db: float
    dominant: str | None
    max_mcs: int | None
    irr_cal_db: float
    irr_cal_measured_at_hz: float
    floor_cal_db: float
    max_mcs_cal: int | None
    rate_mbps: float | None
    rate_cal_mbps: float | None
    bits_per_s_per_hz: float | None
    plan_ok: bool | None            # None = sub-7 carrier, the 57–71 GHz plan does not apply
    verdict: str
    reason: str
    td_evm_db: float | None = None
    evm_budget: dict = field(default_factory=dict)
    eirp: dict | None = None
    power: dict | None = None
    pout_dbm: float | None = None
    #: the decoder's cap (``frontend/grid.py::decoder_cap``): uncalibrated, at
    #: the calibrated IRR, the SNR it needs there and what the floor costs
    dec_mcs: int | None = None
    dec_mcs_cal: int | None = None
    dec_required_snr_db: float | None = None
    dec_penalty_db: float | None = None
    dec_rate_mbps: float | None = None
    dec_rate_cal_mbps: float | None = None
    power_dec: dict | None = None
    dec_floor_db: float | None = None       # analytic floor, or the time-domain EVM when that reads worse

    @property
    def label(self) -> str:
        return self.scheme.label


def _pn_terms(cfg: Mmw60Config, fe: Frontend60, phy) -> dict:
    """This library's ICI term (to fs/2) next to wifitrx EvmBudget's
    (10 kHz–100 MHz IPN less the CPE-tracked share), both for the sides on."""
    out = {"n_lo": {"both": 2, "tx": 1, "rx": 1}.get(cfg.lo.phase_noise.apply, 0)}
    if fe.lo.profile is None or not cfg.lo.phase_noise.enabled:
        out.update(ici_rad2=0.0, budget_rad2=0.0, tracked_fraction=None, ipn_dbc=None)
        return out
    t_fft, fs = phy.t_fft_eff, phy.fs_eff
    part = cpe_partition(fe.lo.profile.psd, t_fft, 1e3, fs / 2)
    band = cpe_partition(fe.lo.profile.psd, t_fft, PN_BAND_HZ[0], PN_BAND_HZ[1])
    # wifitrx's ipn_dbc is the single-sideband convention (phase power / 2): the phase
    # variance EvmBudget takes is twice 10^(dBc/10).  (Until A1 this line left the 2 out
    # and the budget's phase-noise term read 3.0 dB low — cairn/comparison-table.md §3.)
    ipn_rad2 = 2 * 10 ** (fe.lo.lo_model().ipn_dbc(*PN_BAND_HZ) / 10)
    out.update(ici_rad2=out["n_lo"] * part["ici_rad2"],
               budget_rad2=out["n_lo"] * ipn_rad2 * (1 - band["tracked_fraction"]),
               tracked_fraction=float(band["tracked_fraction"]),
               ipn_dbc=float(fe.lo.lo_model().ipn_dbc(*PN_BAND_HZ)), ipn_rad2=ipn_rad2)
    return out


def evm_budget_reconciliation(cfg: Mmw60Config, fe: Frontend60, a: dict, pa_evm_db: float | None, phy) -> dict:
    """wifitrx's ``EvmBudget`` fed this row's terms; what it predicts and
    where it parts from the analytic floor (only the phase-noise term can)."""
    pn = _pn_terms(cfg, fe, phy)
    t = a["terms_db"]
    kw = dict(lo_profile=fe.lo.profile if fe.lo.profile is not None else EvmBudget().lo_profile,
              t_fft_s=phy.t_fft_eff, pn_band_hz=PN_BAND_HZ)
    if "iq_image" in t:
        kw["irr_db"] = -t["iq_image"]
    if "converters" in t:
        kw["sqnr_db"] = -t["converters"]
    if "pa" in t:
        kw["pa_nmse_db"] = t["pa"]
    if pn["n_lo"] and pn.get("ipn_rad2"):
        kw["ipn_rad2"] = pn["n_lo"] * pn["ipn_rad2"]
    extra = {k: v for k, v in t.items() if k not in ("phase_noise", "iq_image", "converters", "pa")}
    if extra:
        kw["extra_db"] = extra        # GI-tail ISI; topology A's chip residual and chip-LO ICI
    b = EvmBudget(**kw)
    rep = b.report()
    return {"predicted_evm_db": rep["predicted_evm_db"], "components_db": rep["components_db"],
            "cpe_tracked_fraction": rep["cpe_tracked_fraction"],
            "pn_ici_db": 10 * np.log10(max(pn["ici_rad2"], 1e-30)) if pn["n_lo"] else None,
            "pn_budget_db": 10 * np.log10(max(pn["budget_rad2"], 1e-30)) if pn["n_lo"] else None,
            "ipn_dbc_10k_100m": pn["ipn_dbc"], "delta_vs_floor_db": rep["predicted_evm_db"] - a["floor_db"]}


def evaluate_scheme(s: Scheme, fe: Frontend60, coeffs: PowerCoefficients | None = None,
                    pa_evm_db: float | None = None, time_domain: bool = True,
                    irr_cal_db: float | None = None, dec_margin_db: float | None = None) -> Row:
    from .sim.link import evm_at
    cfg = s.cfg
    assert cfg is not None
    phy = cfg.upclocked()
    if pa_evm_db is None and fe.pa_enabled and cfg.frontend.pa.enabled:
        pa_evm_db = pa_isolated_evm_db(fe.pa_model, fe.obo_db, fe.obo_reference)
    a = analytic_floors(cfg, fe, pa_evm_db)
    mcs = max_mcs_for_floor(a["floor_db"], cfg.phy.standard)
    if irr_cal_db is None:
        irr_cal_db, meas_at = measured_irr_after_cal_db(phy.bandwidth_eff)
    else:
        meas_at = float("nan")
    a_cal = analytic_floors(cfg, fe, pa_evm_db, irr_cal_db)
    mcs_cal = max_mcs_for_floor(a_cal["floor_db"], cfg.phy.standard)
    mmwave = fe.eirp is not None and fe.eirp.in_band(cfg.carrier_hz - phy.bandwidth_eff / 2,
                                                     cfg.carrier_hz + phy.bandwidth_eff / 2)
    plan_ok = a["plan"]["ok"] if cfg.carrier_hz >= 50e9 else None
    reasons = []
    if not a["cfo_captured"]:
        reasons.append(REASON_ZH["cfo"])
    if plan_ok is False:
        reasons.append(REASON_ZH["plan"])
    ok = a["cfo_captured"] and plan_ok is not False and mcs is not None
    if mcs is None and a["dominant"]:
        reasons.append(REASON_ZH[a["dominant"]])
    reason = ", ".join(reasons) if reasons else (REASON_ZH.get(a["dominant"], "") + " 限 MCS")
    rate = rate_cal = None
    if mcs is not None:
        rate = data_rate_bps(cfg.phy.standard, cfg.phy.bandwidth_hz, mcs, phy.t_symbol_eff)
    if mcs_cal is not None:
        rate_cal = data_rate_bps(cfg.phy.standard, cfg.phy.bandwidth_hz, mcs_cal, phy.t_symbol_eff)
    row = Row(scheme=s, k=cfg.upclock_k, standard=cfg.phy.standard, base_bw_hz=cfg.phy.bandwidth_hz,
              bw_eff_hz=phy.bandwidth_eff, fs_eff_hz=phy.fs_eff, scs_eff_hz=phy.scs_eff,
              t_symbol_eff_s=phy.t_symbol_eff, carrier_hz=cfg.carrier_hz, cfo_hz=cfg.cfo_hz,
              cfo_subcarriers=cfg.cfo_hz / phy.scs_eff, cfo_captured=bool(a["cfo_captured"]),
              stf_capture_hz=phy.stf_capture_hz, terms_db=a["terms_db"], floor_db=a["floor_db"],
              dominant=a["dominant"], max_mcs=mcs, irr_cal_db=irr_cal_db, irr_cal_measured_at_hz=meas_at,
              floor_cal_db=a_cal["floor_db"], max_mcs_cal=mcs_cal,
              rate_mbps=None if rate is None else rate / 1e6,
              rate_cal_mbps=None if rate_cal is None else rate_cal / 1e6,
              bits_per_s_per_hz=None if rate is None else rate / phy.bandwidth_eff,
              plan_ok=plan_ok, verdict="能" if ok else "不能", reason=reason)
    row.evm_budget = evm_budget_reconciliation(cfg, fe, a, pa_evm_db, phy)
    if fe.pa_enabled and cfg.frontend.pa.enabled:
        row.pout_dbm = fe.target_pout_dbm()
        if mmwave:
            row.eirp = fe.eirp.check(row.pout_dbm, fe.antenna_gain_dbi)
    if rate is not None:
        row.power = power_report(cfg, fe, rate, coeffs, phy, mcs_index=mcs).as_dict()
    if time_domain:
        flat = dc.replace(cfg, channel=ChannelConfig(model="flat"))
        row.td_evm_db = evm_at(flat, None, n_packets=1, frontend=fe)["evm_db"]
    if cfg.coded:
        row.dec_floor_db = decoder_floor_db(a["floor_db"], row.td_evm_db, bool(a["cfo_captured"]))
        d = decoder_cap(row.dec_floor_db, cfg.phy.standard, cfg.phy.bandwidth_hz, dec_margin_db)
        d_cal = decoder_cap(a_cal["floor_db"], cfg.phy.standard, cfg.phy.bandwidth_hz, dec_margin_db)
        row.dec_mcs, row.dec_mcs_cal = d["mcs"], d_cal["mcs"]
        row.dec_required_snr_db, row.dec_penalty_db = d["required_snr_db"], d["penalty_db"]
        if d["mcs"] is not None:
            r_dec = data_rate_bps(cfg.phy.standard, cfg.phy.bandwidth_hz, d["mcs"], phy.t_symbol_eff)
            row.dec_rate_mbps = r_dec / 1e6
            row.power_dec = power_report(cfg, fe, r_dec, coeffs, phy, mcs_index=d["mcs"]).as_dict()
        if d_cal["mcs"] is not None:
            row.dec_rate_cal_mbps = data_rate_bps(cfg.phy.standard, cfg.phy.bandwidth_hz, d_cal["mcs"],
                                                  phy.t_symbol_eff) / 1e6
    return row


# ------------------------------------------------------------------ the report
def build(schemes: list[Scheme], fe: Frontend60 | None = None, coeffs: PowerCoefficients | None = None,
          time_domain: bool = True, progress=None) -> dict:
    built = [s for s in schemes if s.status == "built"]
    labels = [s.label for s in built]
    if len(set(labels)) != len(labels):
        raise ValueError(f"scheme labels must be unique (they key the report): {labels}")
    if fe is None:
        fe = Frontend60.from_config(built[0].cfg)
    coeffs = coeffs or PowerCoefficients.from_spec()
    pa_evm = pa_isolated_evm_db(fe.pa_model, fe.obo_db, fe.obo_reference) if fe.pa_enabled else None
    rows = []
    for s in built:
        rows.append(evaluate_scheme(s, fe, coeffs, pa_evm, time_domain))
        if progress:
            progress(rows[-1])
    rep = {"frontend": fe.describe(), "frontend_ids": {"frontend": id(fe), "lo": id(fe.lo), "eirp": id(fe.eirp),
                                                       "converters": id(fe.converters)},
           "pa_isolated_evm_db": pa_evm, "coefficients": coeffs.describe(),
           "rows": [row_dict(r) for r in rows],
           "pending": [{"label": s.label, "topology": s.topology, "waveform": s.waveform, "status": s.status,
                        "reason": s.reason} for s in schemes if s.status != "built"],
           "matrix": sorted({(s.topology, s.waveform) for s in schemes}),
           "cross_checks": cross_checks(rows)}
    rep["_rows"] = rows
    return rep


def row_dict(r: Row) -> dict:
    d = {k: v for k, v in dc.asdict(r).items() if k != "scheme"}
    d.update(label=r.label, topology=r.scheme.topology, waveform=r.scheme.waveform)
    return d


def cross_checks(rows: list[Row], td_tol_db: float = 2.0, linear_limit_db: float = -8.0) -> list[dict]:
    """Per row: analytic floor vs time-domain EVM (within ``td_tol_db`` while
    the floor is below ``linear_limit_db``; above it the IQ image is no
    longer a small perturbation and the linear sum is not expected to
    hold) and EvmBudget vs floor (the phase-noise term's two conventions)."""
    out = []
    for r in rows:
        c = {"label": r.label, "floor_db": r.floor_db, "td_evm_db": r.td_evm_db,
             "budget_db": r.evm_budget.get("predicted_evm_db")}
        if r.td_evm_db is not None:
            c["td_delta_db"] = r.td_evm_db - r.floor_db
            # an uncaught CFO makes the time-domain reading meaningless (the
            # floor assumes a locked receiver): no verdict on that row
            c["td_ok"] = (abs(c["td_delta_db"]) <= td_tol_db
                          if (r.floor_db <= linear_limit_db and r.cfo_captured) else None)
        c["budget_delta_db"] = r.evm_budget.get("delta_vs_floor_db")
        out.append(c)
    return out


_HDR = ("| scheme | K | BW_eff | SCS | T_sym | CFO | STF catches | floor | TD EVM | EvmBudget | max MCS | "
        "IQcal (meas.) | rate @cap | b/s/Hz | Pout / EIRP margin | pJ/bit | verdict |")


def _f(v, fmt="{:.1f}", none="—"):
    if v is None or (isinstance(v, float) and (not math.isfinite(v) or v < -150)):
        return none            # −300 dB is a term that is zero to double precision
    return fmt.format(v)


def to_markdown(rep: dict) -> str:
    fe = rep["frontend"]
    lines = ["# 同台表 / comparison table", "",
             f"front end (one instance for every row): PA {fe['pa']} Psat {fe['psat_dbm']:g} dBm OBO {fe['obo_db']:g} dB "
             f"from {fe['obo_reference']} → Pout {_f(fe['pout_dbm'])} dBm; LO profile {fe.get('lo_profile')} "
             f"IPN {_f(fe['lo_ipn_dbc'])} dBc (10 kHz–100 MHz); TX leak {fe['tx_leak_dbc']} dBc; RX DC {fe['rx_dc_dbc']} dBc; "
             f"PA isolated EVM {_f(rep['pa_isolated_evm_db'])} dB. The LO chain is part of that instance: every row, "
             f"the sub-7 GHz K = 1 row included, runs on the same profile (its own ``lo.phase_noise`` setting is used "
             f"only when it is simulated on its own — example 04's LO section).", "",
             _HDR, "|" + "---|" * (_HDR.count("|") - 1)]
    for r in rep["rows"]:
        eirp = "—" if not r["eirp"] else f"{r['pout_dbm']:.0f} dBm / {r['eirp']['margin_avg_db']:+.0f} dB"
        pj = "—" if not r["power"] else f"{r['power']['pj_per_bit']:.0f}"
        lines.append(
            f"| {r['label']} | {r['k']} | {r['bw_eff_hz'] / 1e6:g} MHz | {r['scs_eff_hz'] / 1e6:g} MHz | "
            f"{r['t_symbol_eff_s'] * 1e9:.0f} ns | {r['cfo_hz'] / 1e6:.2f} MHz = {r['cfo_subcarriers']:.2f} sc | "
            f"{'yes' if r['cfo_captured'] else 'NO'} (±{r['stf_capture_hz'] / 1e6:.2f} MHz) | {r['floor_db']:.1f} | "
            f"{_f(r['td_evm_db'])} | {_f(r['evm_budget'].get('predicted_evm_db'))} | {_f(r['max_mcs'], 'MCS{}')} | "
            f"{_f(r['max_mcs_cal'], 'MCS{}')} ({r['irr_cal_db']:.0f} dB) | {_f(r['rate_mbps'], '{:.0f} Mb/s')} | "
            f"{_f(r['bits_per_s_per_hz'], '{:.2f}')} | {eirp} | {pj} | {r['verdict']} {r['reason']} |")
    lines += ["", "## the decoder's cap (EVM floor as a noise term against the measured ideal thresholds)", "",
              "| scheme | floor used (worse of analytic / time-domain) | conformance cap | decoder cap | SNR needed there | floor costs | decoder cap, IQ calibrated | rate @dec cap | pJ/bit @dec cap |",
              "|---|---|---|---|---|---|---|---|---|"]
    for r in rep["rows"]:
        pjd = "—" if not r["power_dec"] else f"{r['power_dec']['pj_per_bit']:.0f}"
        lines.append(f"| {r['label']} | {_f(r['dec_floor_db'])} | {_f(r['max_mcs'], 'MCS{}')} | {_f(r['dec_mcs'], 'MCS{}')} | "
                     f"{_f(r['dec_required_snr_db'], '{:.1f} dB')} | {_f(r['dec_penalty_db'], '{:.1f} dB')} | "
                     f"{_f(r['dec_mcs_cal'], 'MCS{}')} | {_f(r['dec_rate_mbps'], '{:.0f} Mb/s')} | {pjd} |")
    lines += ["", "## rows without numbers yet", ""]
    for p in rep["pending"]:
        lines.append(f"- **{p['label']}** — {p['reason']}")
    lines += ["", "## analytic terms [dB] and the EvmBudget reconciliation", "",
              "| scheme | pn (ICI to fs/2) | pn (EvmBudget: IPN 10k–100M × (1−tracked)) | tracked share | iq | conv | pa | isi | floor | EvmBudget | Δ |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rep["rows"]:
        t, b = r["terms_db"], r["evm_budget"]
        lines.append(f"| {r['label']} | {_f(b.get('pn_ici_db'))} | {_f(b.get('pn_budget_db'))} | "
                     f"{_f(b.get('cpe_tracked_fraction'), '{:.1%}')} | {_f(t.get('iq_image'))} | {_f(t.get('converters'))} | "
                     f"{_f(t.get('pa'))} | {_f(t.get('isi'))} | {r['floor_db']:.1f} | {_f(b.get('predicted_evm_db'))} | "
                     f"{_f(b.get('delta_vs_floor_db'), '{:+.1f}')} |")
    lines += ["", "## power blocks per bit at the MCS cap [pJ/bit] (ratios, not totals)", "",
              "| scheme | rate | pa | lo | converters | dpd | fft | decoder | total | not counted |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rep["rows"]:
        p = r["power"]
        if not p:
            lines.append(f"| {r['label']} | — | | | | | | | — | no MCS reachable |")
            continue
        bl = p["blocks"]
        cell = lambda n: _f(bl[n]["pj_per_bit"], "{:.0f}") if n in bl else "—"  # noqa: E731
        lines.append(f"| {r['label']} | {p['bit_rate_bps'] / 1e6:.0f} Mb/s | {cell('pa')} | {cell('lo')} | {cell('converters')} | "
                     f"{cell('dpd')} | {cell('fft')} | {cell('decoder')} | {p['pj_per_bit']:.0f} | {'; '.join(p['omitted']) or '—'} |")
    c = rep["coefficients"]
    lines += ["", f"coefficients: Walden {c['walden_fom_fj']:.0f} fJ/step, Horowitz {c['mult32_pj']:g} / {c['add32_pj']:g} pJ "
              f"(32-bit mult / add, 45 nm) × node scale {c['node_scale']:g}, {c['word_bits']} bit; synthesizers "
              f"{c['pll60_mw']:g} mW (60 GHz) / {c['pll_sub7_mw']:g} mW (sub-7); DPD {c['dpd_model']}", ""]
    if rep.get("sensitivity"):
        lines += sensitivity_markdown(rep["sensitivity"]).splitlines()
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ sensitivity
def sensitivity_knobs() -> list[dict]:
    """Every number the power column and the MCS cap lean on, with the ends
    it is moved to; ``kind`` says what is changed (coefficient, front end,
    or the calibrated-IRR source)."""
    lo, hi = (float(v) for v in spec.value("adc_survey.walden_fom_range_fj"))
    return [
        {"name": "Walden FoM", "kind": "coeff", "field": "walden_fom_j", "values": (lo * 1e-15, hi * 1e-15),
         "source": "adc_survey.walden_fom_range_fj"},
        {"name": "digital node 45 → 7 nm", "kind": "coeff", "field": "node_scale",
         "values": (float(spec.value("deepscale.node_scale_45_to_7nm")),), "source": "deepscale.node_scale_45_to_7nm"},
        {"name": "synthesizer power", "kind": "coeff_scale", "field": ("pll60_w", "pll_sub7_w"), "values": (0.5, 2.0),
         "source": "assumed.pll60_power_mw / assumed.pll_sub7_power_mw"},
        {"name": "PA peak PAE", "kind": "frontend", "field": "pa_pae_max", "values": (0.10, 0.30),
         "source": "assumed.pa60_pae_max"},
        {"name": "PA back-off", "kind": "frontend", "field": "obo_db", "values": ("-2", "+2"), "source": "liu2025.pa_obo_db"},
        {"name": "converter ENOB law", "kind": "converters", "field": "bits_per_octave", "values": (1.0,),
         "source": "assumed.converter_bits_per_octave"},
        {"name": "calibrated IRR", "kind": "irr", "field": "irr_after_cal_db",
         "values": (float(spec.value("assumed.irr_after_cal_db")),), "source": "assumed.irr_after_cal_db (vs measured)"},
        {"name": "decoder-cap margin", "kind": "dec_margin", "field": "decoder_cap_margin_db", "values": (1.0, 6.0),
         "source": "assumed.decoder_cap_margin_db"},
    ]


def _variant(fe: Frontend60, coeffs: PowerCoefficients, knob: dict, v):
    irr = margin = None
    if knob["kind"] == "dec_margin":
        margin = v
    if knob["kind"] == "coeff":
        coeffs = coeffs.with_(**{knob["field"]: v})
    elif knob["kind"] == "coeff_scale":
        coeffs = coeffs.with_(**{f: getattr(coeffs, f) * v for f in knob["field"]})
    elif knob["kind"] == "frontend":
        cur = getattr(fe, knob["field"])
        val = cur + float(v) if isinstance(v, str) else v
        fe = dc.replace(fe, **{knob["field"]: val})
    elif knob["kind"] == "converters":
        fe = dc.replace(fe, converters=dc.replace(fe.converters, **{knob["field"]: v}))
    elif knob["kind"] == "irr":
        irr = v
    return fe, coeffs, irr, margin


def sensitivity(schemes: list[Scheme], fe: Frontend60, coeffs: PowerCoefficients | None = None,
                progress=None) -> dict:
    """The analytic side rerun at every knob end; per knob the rows whose MCS
    cap changed and whether the pJ/bit ranking of the rows changed."""
    coeffs = coeffs or PowerCoefficients.from_spec()
    built = [s for s in schemes if s.status == "built"]

    def run(fe_, co_, irr_, margin_=None):
        pa_evm = pa_isolated_evm_db(fe_.pa_model, fe_.obo_db, fe_.obo_reference) if fe_.pa_enabled else None
        return [evaluate_scheme(s, fe_, co_, pa_evm, time_domain=False, irr_cal_db=irr_, dec_margin_db=margin_)
                for s in built]

    base = run(fe, coeffs, None)
    base_dec = {r.label: r.dec_mcs for r in base}
    base_dec_cal = {r.label: r.dec_mcs_cal for r in base}
    base_pj = {r.label: (r.power or {}).get("pj_per_bit") for r in base}
    base_mcs = {r.label: r.max_mcs for r in base}
    base_rank = _rank(base_pj)
    out = {"base": {"mcs": base_mcs, "dec_mcs": base_dec, "pj_per_bit": base_pj, "ranking": base_rank}, "knobs": []}
    for knob in sensitivity_knobs():
        for v in knob["values"]:
            fe_, co_, irr_, margin_ = _variant(fe, coeffs, knob, v)
            rows = run(fe_, co_, irr_, margin_)
            dec = {r.label: (r.dec_mcs_cal if knob["kind"] == "irr" else r.dec_mcs) for r in rows}
            ref_dec = base_dec_cal if knob["kind"] == "irr" else base_dec
            dec_moved = {lab: (ref_dec[lab], dec[lab]) for lab in dec if dec[lab] != ref_dec[lab]}
            pj = {r.label: (r.power or {}).get("pj_per_bit") for r in rows}
            mcs = {r.label: (r.max_mcs_cal if knob["kind"] == "irr" else r.max_mcs) for r in rows}
            ref_mcs = {r.label: r.max_mcs_cal for r in base} if knob["kind"] == "irr" else base_mcs
            moved = {lab: (ref_mcs[lab], mcs[lab]) for lab in mcs if mcs[lab] != ref_mcs[lab]}
            entry = {"knob": knob["name"], "value": v, "source": knob["source"], "mcs_moved": moved,
                     "dec_mcs_moved": dec_moved,
                     "pj_per_bit": pj, "ranking": _rank(pj), "ranking_changed": _rank(pj) != base_rank,
                     "pj_ratio_max": max((pj[lab] / base_pj[lab] for lab in pj if pj[lab] and base_pj[lab]), default=None),
                     "pj_ratio_min": min((pj[lab] / base_pj[lab] for lab in pj if pj[lab] and base_pj[lab]), default=None)}
            out["knobs"].append(entry)
            if progress:
                progress(entry)
    return out


def _rank(pj: dict) -> list[str]:
    return [lab for lab, v in sorted(pj.items(), key=lambda kv: (kv[1] is None, kv[1] or 0))]


def sensitivity_markdown(sens: dict) -> str:
    lines = ["## sensitivity: which guesses decide the verdict", "",
             "base pJ/bit ranking (best first): " + " < ".join(sens["base"]["ranking"]), "",
             "| knob (source) | at | conformance cap moved | decoder cap moved | pJ/bit × (min … max over rows) | ranking changed |",
             "|---|---|---|---|---|---|"]
    for e in sens["knobs"]:
        moved = ", ".join(f"{lab}: {a}→{b}" for lab, (a, b) in e["mcs_moved"].items()) or "none"
        dmoved = ", ".join(f"{lab}: {a}→{b}" for lab, (a, b) in e["dec_mcs_moved"].items()) or "none"
        ratio = ("—" if e["pj_ratio_min"] is None else f"{e['pj_ratio_min']:.2f} … {e['pj_ratio_max']:.2f}")
        lines.append(f"| {e['knob']} ({e['source']}) | {e['value']} | {moved} | {dmoved} | {ratio} | "
                     f"{'YES' if e['ranking_changed'] else 'no'} |")
    return "\n".join(lines) + "\n"


def report_json(rep: dict) -> dict:
    """The report without the live ``Row`` objects."""
    return {k: v for k, v in rep.items() if not k.startswith("_")}


__all__ = ["Scheme", "Row", "PENDING", "NOT_A_SCHEME", "scheme_matrix", "measured_irr_after_cal_db",
           "evaluate_scheme", "build", "to_markdown", "cross_checks", "sensitivity", "sensitivity_knobs",
           "sensitivity_markdown", "report_json", "PowerReport"]
