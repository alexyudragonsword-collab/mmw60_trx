"""The "base bandwidth × K" grid: for every (standard, base bandwidth, K) cell,
can the upclocked zero-IF link carry a given MCS, and if not, why.

Analytic side (closed forms, all from the same objects the time-domain run
uses): CFO capture (L-STF range vs the crystal offset), phase-noise ICI left
after per-symbol CPE (wifitrx ``cpe_partition`` at T_FFT/K, TX + RX),
uncorrected IQ image (wifitrx ``FreqDepIQImbalance.irr_db`` averaged over the
occupied tones at fs_eff, TX + RX), converter quantisation at ENOB(fs_eff)
(DAC + ADC, in-band share), PA compression (the Rapp at its OBO, isolated,
gain-equalised), guard-interval overflow of the channel's diffuse tail.
Power-summed into a floor, compared with the MCS's TX-EVM requirement less
a margin (data/spec: assumed.mcs_evm_margin_db).  Time-domain side: the
same cell through ``LinkSim`` (zero-IF chain, no noise, flat channel), all
impairments on and each alone — the isolation method of wifitrx's
AGENTS.md, never "all minus one".
"""
from __future__ import annotations

import dataclasses as dc
from dataclasses import dataclass

import numpy as np

from .. import spec
from ..config import ChannelConfig, Mmw60Config
from ..pa.rapp import ModifiedRappPA, drive_for_obo
from ..vendor.wifitrx.impairments.phase_noise import cpe_partition
from ..vendor.wifitrx.link.mcs import MCS_TABLE
from .dpd_cost import dsp_ip_models
from .freqplan import zero_if_plan
from .frontend import Frontend60

MAX_MCS = {"11ac": 9, "11be": 13}


def _db(p: float) -> float:
    return float(10 * np.log10(max(p, 1e-30)))


def pa_isolated_evm_db(pa: ModifiedRappPA, obo_db: float, reference: str, seed: int = 3,
                       n: int = 1 << 15) -> float:
    """EVM of the Rapp alone at its OBO on a Gaussian-like OFDM envelope after
    the LS complex gain is removed (what an equaliser takes out)."""
    rng = np.random.default_rng(seed)
    x = (rng.standard_normal(n) + 1j * rng.standard_normal(n)) / np.sqrt(2)
    d = drive_for_obo(pa, x, obo_db, reference=reference)
    y = pa(d * x)
    g = np.vdot(x, y) / np.vdot(x, x)
    return _db(np.mean(np.abs(y - g * x) ** 2) / np.mean(np.abs(g * x) ** 2))


def obo_for_isolated_evm(pa: ModifiedRappPA, evm_limit_db: float, reference: str = "psat",
                         seed: int = 3, lo_db: float = 1.0, hi_db: float = 20.0) -> float:
    """The smallest back-off at which the Rapp alone meets ``evm_limit_db``
    (``pa_isolated_evm_db`` falls monotonically with the back-off): the
    operating point a transmitter is rated at when its output is quoted
    "at the TX EVM limit" (data/spec: assumed.pa60_operating_rule).  The
    search starts 1 dB from the reference: a Rapp never reaches its Psat."""
    from scipy.optimize import brentq
    f = lambda o: pa_isolated_evm_db(pa, o, reference, seed=seed) - float(evm_limit_db)   # noqa: E731
    if f(hi_db) > 0:
        raise ValueError(f"the PA does not reach {evm_limit_db} dB within {hi_db} dB of back-off")
    if f(lo_db) <= 0:
        return float(lo_db)
    return float(brentq(f, lo_db, hi_db, xtol=1e-4))


def analytic_floors(cfg: Mmw60Config, fe: Frontend60, pa_evm_db: float | None = None,
                    irr_after_cal_db: float | None = None) -> dict:
    """``irr_after_cal_db``: replace the uncorrected IQ image by the residual a
    calibrated chain leaves (per side), i.e. the grid "after wifitrx IQ
    calibration"; example 03 measures what that residual actually is at K."""
    sim_phy = cfg.upclocked()
    fs, scs, t_fft = sim_phy.fs_eff, sim_phy.scs_eff, sim_phy.t_fft_eff
    base = sim_phy.base
    tones = base.active_tone_indices() * scs
    occupied = base.n_active * scs
    out: dict = {}
    # CFO capture
    cfo = abs(cfg.cfo_hz)
    out["cfo_hz"] = cfo
    topo_a = cfg.topology == "if_extender"
    seen = cfo
    if topo_a:
        # what reaches the chip's estimators after the multi-link pre-compensation
        # (iron rule 3): the sub-7 estimate's error × f_c / f_sub7, measured
        from ..impairments.cfo import MloCfo
        mlo = MloCfo(cfg.carrier_hz, cfg.xo_ppm_tx, cfg.xo_ppm_rx, sub7_hz=cfg.ifext.mlo_sub7_hz,
                     sub7_snr_db=cfg.ifext.mlo_sub7_snr_db, enabled=cfg.ifext.mlo_enabled)
        st = mlo.residual_stats(n=100, seed=cfg.seed)
        out["cfo_residual_rms_hz"], out["cfo_residual_max_hz"] = st["rms_hz"], st["max_abs_hz"]
        out["cfo_precompensation"] = "mlo" if cfg.ifext.mlo_enabled else "off"
        seen = st["max_abs_hz"]
    out["cfo_captured"] = seen <= sim_phy.stf_capture_hz if cfg.rx.cfo_estimation == "stf_ltf" else (
        seen <= sim_phy.ltf_capture_hz if cfg.rx.cfo_estimation == "ltf" else True)
    terms = {}
    # phase noise: ICI after CPE, both LOs
    if fe.lo.profile is not None and cfg.lo.phase_noise.enabled:
        part = cpe_partition(fe.lo.profile.psd, t_fft, 1e3, fs / 2)
        n_lo = {"both": 2, "tx": 1, "rx": 1}.get(cfg.lo.phase_noise.apply, 0)
        terms["phase_noise"] = n_lo * part["ici_rad2"]
    # topology A: the chip's own share — its residual after its calibration (measured:
    # the sequence's final loopback EVM, once per link end) and its two synthesizers
    if topo_a and cfg.ifext.chip == "wifitrx":
        from ..ifext import chip_facts
        facts = chip_facts(cfg, sim_phy.bandwidth_eff, fs)
        out["chip"] = {k: v for k, v in facts.items() if k != "lo_profile"}
        if facts["residual_evm_db"] is not None:
            terms["chip"] = 10 ** (facts["residual_evm_db"] / 10)
        if facts["lo_profile"] is not None:
            terms["chip_lo"] = 2 * cpe_partition(facts["lo_profile"].psd, t_fft, 1e3, fs / 2)["ici_rad2"]
    # IQ image, TX and RX, averaged over the occupied tones (uncalibrated)
    if cfg.frontend.iq.enabled:
        if irr_after_cal_db is not None:
            terms["iq_image"] = 2 * 10 ** (-irr_after_cal_db / 10)
        else:
            e = 0.0
            for iq in (fe.tx_iq.model(), fe.rx_iq.model()):
                irr = iq.irr_db(tones, fs)
                e += float(np.mean(10 ** (-irr / 10)))
            terms["iq_image"] = e
    # converters: DAC + ADC at ENOB(fs), in-band share of the quantisation noise
    if cfg.frontend.converters.enabled:
        sq = fe.converters.in_band_sqnr_db(fs, occupied)
        terms["converters"] = 2 * 10 ** (-sq / 10)
    # PA
    if cfg.frontend.pa.enabled:
        if pa_evm_db is None:
            pa_evm_db = pa_isolated_evm_db(fe.pa_model or ModifiedRappPA(), fe.obo_db, fe.obo_reference)
        terms["pa"] = 10 ** (pa_evm_db / 10)
    # channel tail beyond the guard interval
    ch = cfg.channel
    if ch.model == "tdl_exp" and ch.rms_delay_ns > 0:
        tail = np.exp(-sim_phy.t_gi_eff / (ch.rms_delay_ns * 1e-9))
        share = 1.0 / (10 ** (ch.los_k_db / 10) + 1.0) if ch.los_k_db is not None else 1.0
        terms["isi"] = tail * share
    out["terms_db"] = {k: _db(v) for k, v in terms.items()}
    total = sum(terms.values())
    out["floor_db"] = _db(total) if total > 0 else -np.inf
    no_pa = sum(v for k, v in terms.items() if k != "pa")
    out["floor_no_pa_db"] = _db(no_pa) if no_pa > 0 else -np.inf
    out["dominant"] = max(terms, key=terms.get) if terms else None
    if topo_a:
        from ..ifext import if_plan
        out["plan"] = if_plan(cfg.carrier_hz, cfg.lo.if_hz, cfg.lo.n_mult, sim_phy.bandwidth_eff)
    else:
        out["plan"] = zero_if_plan(cfg.carrier_hz, sim_phy.bandwidth_eff, fs, scs, cfg.cfo_hz)
    return out


def max_mcs_for_floor(floor_db: float, standard: str, margin_db: float | None = None) -> int | None:
    m = float(spec.value("assumed.mcs_evm_margin_db")) if margin_db is None else margin_db
    best = None
    for row in MCS_TABLE[:MAX_MCS[standard] + 1]:
        if floor_db <= row.tx_evm_limit_db - m:
            best = row.index
    return best


def decoder_cap(floor_db: float, standard: str, bandwidth_hz: float, margin_db: float | None = None) -> dict:
    """The highest MCS the **decoder** can carry over an EVM floor: the floor
    is one more noise term, so an MCS whose ideal-chain threshold is ``T``
    (``data/spec/per_thresholds.yaml``, measured) needs

        SNR_req = −10·log10( 10^(−T/10) − 10^(floor/10) )

    and is counted reachable while the floor sits at least ``margin_db``
    (data/spec: assumed.decoder_cap_margin_db) under the noise it tolerates,
    i.e. −floor ≥ T + margin — at a 3 dB margin the floor costs 3.0 dB of
    sensitivity.  This is the receiver's question; ``max_mcs_for_floor`` is
    the transmitter-conformance one (floor against the standard's TX-EVM
    limit) and sits about two MCS lower (example 05; cairn/comparison-table.md §6).

    Returns ``{"mcs", "threshold_db", "required_snr_db", "penalty_db"}``;
    ``mcs`` is None when no MCS is reachable or the base has no coded data
    field (11ac 40 / 80 / 160 MHz: no thresholds to compare with)."""
    m = float(spec.value("assumed.decoder_cap_margin_db")) if margin_db is None else float(margin_db)
    best = {"mcs": None, "threshold_db": None, "required_snr_db": None, "penalty_db": None}
    for idx in range(MAX_MCS[standard] + 1):
        t = spec.per_threshold_db(standard, bandwidth_hz, idx)
        if t is None or not (-floor_db >= t + m):
            continue
        lin = 10 ** (-t / 10) - 10 ** (floor_db / 10)
        if lin <= 0:
            continue
        req = -10 * np.log10(lin)
        best = {"mcs": idx, "threshold_db": float(t), "required_snr_db": float(req), "penalty_db": float(req - t)}
    return best


def decoder_floor_db(analytic_floor_db: float, td_evm_db: float | None, cfo_captured: bool = True) -> float:
    """The EVM floor the decoder cap is computed from: the analytic floor, or
    the time-domain EVM of the same cell when that was run and reads worse.
    The analytic power sum is optimistic once the IQ image stops being a
    small perturbation (+1 dB at 1.28 GHz, +1.7 dB at 2.56 GHz); example 05
    shows the decoder following the time-domain number.  With the CFO not
    captured the time-domain reading is no floor at all and is ignored."""
    if td_evm_db is None or not cfo_captured:
        return float(analytic_floor_db)
    return float(max(analytic_floor_db, td_evm_db))


def data_rate_bps(standard: str, bandwidth_hz: float, mcs_index: int, t_symbol_s: float) -> float:
    table = spec.value("ieee80211ac.n_sd" if standard == "11ac" else "ieee80211be.n_sd")
    n_sd = int(table[float(bandwidth_hz)])
    row = MCS_TABLE[mcs_index]
    num, den = (int(v) for v in row.coding_rate.split("/"))
    return n_sd * row.bits_per_symbol * num / den / t_symbol_s


REASON_ZH = {"cfo": "CFO 捕获", "phase_noise": "相噪", "iq_image": "IQ 不平衡", "converters": "转换器",
             "pa": "PA", "isi": "GI 外 ISI", "plan": "频率规划", "chip": "芯片残差", "chip_lo": "芯片 LO 相噪"}


@dataclass
class Cell:
    standard: str
    base_bw_hz: float
    k: int
    bw_eff_hz: float
    fs_eff_hz: float
    scs_eff_hz: float
    t_fft_eff_s: float
    cfo_captured: bool
    terms_db: dict
    floor_db: float
    dominant: str | None
    max_mcs: int | None
    verdict: str
    reason: str
    floor_cal_db: float | None = None
    max_mcs_cal: int | None = None
    floor_no_pa_db: float | None = None
    max_mcs_no_pa: int | None = None
    td_evm_db: float | None = None
    td_isolated_db: dict | None = None
    data_rate_mbps: float | None = None
    dpd_pj_per_bit: float | None = None
    plan_ok: bool = True
    #: the decoder's cap (floor as a noise term against the measured ideal
    #: thresholds), uncalibrated and with the IQ image at the calibrated residual
    dec_mcs: int | None = None
    dec_mcs_cal: int | None = None
    dec_required_snr_db: float | None = None
    dec_rate_mbps: float | None = None
    dec_coded: bool = True
    dec_floor_db: float | None = None       # the floor the cap was computed from (analytic or time-domain)

    def row(self) -> str:
        iso = "" if not self.td_isolated_db else " ".join(
            f"{k}:{v:.0f}" for k, v in self.td_isolated_db.items())
        td = "   —  " if self.td_evm_db is None else f"{self.td_evm_db:6.1f}"
        cal = "  —  " if self.max_mcs_cal is None else f"MCS{self.max_mcs_cal}"
        nopa = "  —  " if self.max_mcs_no_pa is None else f"MCS{self.max_mcs_no_pa}"
        def dec(v):
            return " n/a " if not self.dec_coded else ("  —  " if v is None else f"MCS{v}")
        return (f"{self.standard:<5} {self.base_bw_hz / 1e6:5.0f} x{self.k:<3} {self.bw_eff_hz / 1e9:6.2f} "
                f"{self.scs_eff_hz / 1e6:6.2f} {self.floor_db:7.1f} {td} "
                f"{'MCS' + str(self.max_mcs) if self.max_mcs is not None else '  —  ':>6} {cal:>6} "
                f"{self.floor_no_pa_db:7.1f} {nopa:>6} {dec(self.dec_mcs):>6} {dec(self.dec_mcs_cal):>6} "
                f"{self.verdict:<4} {self.reason:<22} {iso}")


def evaluate_cell(cfg: Mmw60Config, fe: Frontend60, time_domain: bool = True,
                  isolate: bool = True, pa_evm_db: float | None = None,
                  target_mcs: int | None = None, irr_after_cal_db: float | None = None) -> Cell:
    from ..sim.link import evm_at
    phy = cfg.upclocked()
    a = analytic_floors(cfg, fe, pa_evm_db)
    mcs = max_mcs_for_floor(a["floor_db"], cfg.phy.standard)
    if irr_after_cal_db is None:
        irr_after_cal_db = float(spec.value("assumed.irr_after_cal_db"))
    a_cal = analytic_floors(cfg, fe, pa_evm_db, irr_after_cal_db)
    mcs_cal = max_mcs_for_floor(a_cal["floor_db"], cfg.phy.standard)
    mcs_no_pa = max_mcs_for_floor(a["floor_no_pa_db"], cfg.phy.standard)
    reasons = []
    if not a["cfo_captured"]:
        reasons.append(REASON_ZH["cfo"])
    if not a["plan"]["ok"]:
        reasons.append(REASON_ZH["plan"])
    want = 0 if target_mcs is None else target_mcs
    ok = a["cfo_captured"] and a["plan"]["ok"] and mcs is not None and mcs >= want
    if (mcs is None or mcs < want) and a["dominant"]:
        reasons.append(REASON_ZH[a["dominant"]])
    cell = Cell(cfg.phy.standard, cfg.phy.bandwidth_hz, cfg.upclock_k, phy.bandwidth_eff, phy.fs_eff,
                phy.scs_eff, phy.t_fft_eff, a["cfo_captured"], a["terms_db"], a["floor_db"],
                a["dominant"], mcs, "能" if ok else "不能",
                ", ".join(reasons) if reasons else (REASON_ZH.get(a["dominant"], "") + " 限 MCS"),
                floor_cal_db=a_cal["floor_db"], max_mcs_cal=mcs_cal,
                floor_no_pa_db=a["floor_no_pa_db"], max_mcs_no_pa=mcs_no_pa, plan_ok=a["plan"]["ok"])
    cell.dec_coded = cfg.coded
    if mcs is not None:
        rate = data_rate_bps(cfg.phy.standard, cfg.phy.bandwidth_hz, mcs, phy.t_symbol_eff)
        cell.data_rate_mbps = rate / 1e6
        cell.dpd_pj_per_bit = dsp_ip_models()["ddr_r1_w16"].pj_per_bit(
            float(spec.value("assumed.dpd_rate_over_bw")) * phy.bandwidth_eff, rate)
    if time_domain:
        flat = dc.replace(cfg, channel=ChannelConfig(model="flat"))
        cell.td_evm_db = evm_at(flat, None, n_packets=1, frontend=fe)["evm_db"]
        if isolate:
            ideal = flat.ideal()
            iso = {}
            f = cfg.frontend
            variants = {
                "pn": dc.replace(ideal, lo=cfg.lo),
                "iq": dc.replace(ideal, frontend=dc.replace(ideal.frontend, iq=f.iq)),
                "conv": dc.replace(ideal, frontend=dc.replace(ideal.frontend, converters=f.converters)),
                "pa": dc.replace(ideal, frontend=dc.replace(ideal.frontend, pa=f.pa)),
                "cfo": dc.replace(ideal, xo_ppm_tx=cfg.xo_ppm_tx, xo_ppm_rx=cfg.xo_ppm_rx),
            }
            for name, v in variants.items():
                on = {"pn": cfg.lo.phase_noise.enabled, "iq": f.iq.enabled, "conv": f.converters.enabled,
                      "pa": f.pa.enabled, "cfo": cfg.cfo_hz != 0}[name]
                if on:
                    iso[name] = evm_at(v, None, n_packets=1)["evm_db"]
            cell.td_isolated_db = iso
    if cfg.coded:
        cell.dec_floor_db = decoder_floor_db(a["floor_db"], cell.td_evm_db, a["cfo_captured"])
        d = decoder_cap(cell.dec_floor_db, cfg.phy.standard, cfg.phy.bandwidth_hz)
        cell.dec_mcs, cell.dec_required_snr_db = d["mcs"], d["required_snr_db"]
        cell.dec_mcs_cal = decoder_cap(a_cal["floor_db"], cfg.phy.standard, cfg.phy.bandwidth_hz)["mcs"]
        if d["mcs"] is not None:
            cell.dec_rate_mbps = data_rate_bps(cfg.phy.standard, cfg.phy.bandwidth_hz, d["mcs"],
                                               phy.t_symbol_eff) / 1e6
    return cell


HEADER = ("std    base   K    BW[GHz] SCS[MHz] floor   TD-EVM  maxMCS IQcal  no-PA   maxMCS    dec dec-cal "
          "verdict reason                 isolated TD EVM [dB]")
