"""Milestone 2: the array's link budget and the beam-training SNR budget.

The data link: N_tx elements of the shared PA, each at the front end's
operating point unless N of them would exceed the EIRP limit at the beam
(then every element backs off together — the PA gets more linear), and an
N_rx receive array whose SNR gain is 10 log10 N_rx + G_e.  The range of an
MCS is where the received power falls to the receiver's own sensitivity for
that MCS's required SNR (the decoder threshold over the link's EVM floor),
over a line-of-sight path at the carrier: the topology's own noise figure
and occupied bandwidth come from its ``LinkSim`` (topology A's 60 GHz LNA
cascade included), the floor from ``analytic_floors`` at the per-element
back-off.  The budget's answer is the path loss it takes; the distance that
means adds the oxygen absorption (data/spec: assumed.oxygen_absorption, an
estimate) to free space.

The training (data/spec: assumed.array_training): 802.11be has no mmWave
beam training, so it is MLO-triggered — the sub-7 GHz link schedules the
sweep, so its timing is known — and each sector sends the base PHY's L-LTF
(GI2 + 2 symbols) upclocked.  First the transmit sweep, the far end on one
element (no receive array gain yet: the bottleneck), then the receive sweep
behind the chosen transmit beam.  The receiver estimates each sector's power
from the known LTF — two symbols coherently per tone, tones non-coherently —
and keeps the strongest; a pick within ``success_within_db`` of the best
sector counts.

For a flat channel with known timing the per-tone statistic is exact in
closed form: tone k of sector s reads Y = sqrt(rho_s) X + N (|X| = 1,
N ~ CN(0, 1), rho_s the per-tone SNR), and over n tones and two symbols

    T_s = sum_k |Y_k1 X* + Y_k2 X*|^2 ~ chi'^2(2n, 4 n rho_s)   (non-coherent)
    T_s = |sum_k (...)|^2            ~ (n) chi'^2(2, 4 n rho_s) (coherent)

so a sweep is sampled from the non-central chi-square directly
(``tests/test_arraylink.py`` checks it against tone-by-tone noise).

Where the transmit sweep falls short of the MCS0 edge, each sector repeats
the training field R times (data/spec: assumed.array_training_repetition,
the user's pick 2026-11-15): summing the R powers non-coherently is the
same statistic over n R tones, chi'^2(2nR, 4nR rho); summing them
coherently (a sensitivity: it needs the phase to hold across repetitions)
is 2R symbols per tone, chi'^2(2n, 4nR rho).  The sweep lasts R times as
long.

The array's power (``array_power_report``): the single-element power
column with the PA taken N_tx times at the per-element output the EIRP
limit leaves, and one phase shifter per element on each side (data/spec:
assumed.array_phase_shifter_power_mw; none at N = 1, where the element is
the front end itself) — the user's pick 2026-11-15.  The LNA / mixer stay
uncounted as in the single-element column.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import brentq

from . import spec
from .frontend.array60 import Array60
from .frontend.grid import analytic_floors, data_rate_bps, decoder_cap, pa_isolated_evm_db
from .power import PowerBlock, PowerCoefficients, PowerReport, power_report
from .vendor.wifitrx.units import KT_DBM_HZ, dbm_to_mw

C0 = 299_792_458.0


def fspl_db(d_m, f_hz: float):
    """Free-space path loss 20 log10(4 pi d f / c)."""
    return 20.0 * np.log10(4.0 * np.pi * np.asarray(d_m, dtype=float) * float(f_hz) / C0)


def oxygen_db_per_km() -> float:
    """The oxygen absorption the distances use (data/spec: assumed.oxygen_absorption)."""
    return float(spec.value("assumed.oxygen_absorption"))


def path_loss_db(d_m, f_hz: float, oxygen_db_km: float | None = None):
    """Free space plus the oxygen absorption over ``d_m``."""
    a = oxygen_db_per_km() if oxygen_db_km is None else float(oxygen_db_km)
    d = np.asarray(d_m, dtype=float)
    return fspl_db(d, f_hz) + a * d / 1000.0


def range_m(link_db: float, f_hz: float, oxygen_db_km: float | None = None) -> float:
    """The distance at which the path (free space plus oxygen) eats ``link_db``
    (EIRP + G_rx - sensitivity); ``oxygen_db_km=0`` is free space alone."""
    d_fs = float(10.0 ** (link_db / 20.0) * C0 / (4.0 * np.pi * float(f_hz)))
    a = oxygen_db_per_km() if oxygen_db_km is None else float(oxygen_db_km)
    if a == 0.0:
        return d_fs
    # the loss rises with d and the absorption only shortens the free-space distance
    return float(brentq(lambda d: float(path_loss_db(d, f_hz, a)) - link_db, d_fs * 1e-12, d_fs,
                        xtol=1e-12 * d_fs, rtol=1e-14))


def required_snr_db(threshold_db: float, floor_db: float) -> float | None:
    """SNR the decoder needs over an EVM floor: -10 log10(10^(-T/10) - 10^(floor/10))."""
    lin = 10.0 ** (-threshold_db / 10.0) - 10.0 ** (floor_db / 10.0)
    return None if lin <= 0 else float(-10.0 * np.log10(lin))


# ---------------------------------------------------------------- the training statistic
def sweep_statistic(rho_lin: np.ndarray, n_tones: int, rng: np.random.Generator, trials: int,
                    estimator: str = "noncoherent_tones", n_sym: int = 2) -> np.ndarray:
    """(trials, S) samples of each sector's power statistic for per-tone
    SNRs ``rho_lin`` (one per sector), from its closed form."""
    rho = np.asarray(rho_lin, dtype=float)
    if estimator == "noncoherent_tones":
        return rng.noncentral_chisquare(2 * n_tones, 2 * n_sym * n_tones * rho, size=(trials, rho.size))
    if estimator == "coherent":
        return rng.noncentral_chisquare(2, 2 * n_sym * n_tones * rho, size=(trials, rho.size))
    raise ValueError(f"unknown estimator {estimator!r}")


def selection_success(gains_db: np.ndarray, snr_best_db: float, n_tones: int, rng: np.random.Generator,
                      trials: int = 2000, estimator: str = "noncoherent_tones", within_db: float = 1.0,
                      n_sym: int = 2) -> float:
    """P(the sweep keeps a sector within ``within_db`` of the best) when the
    best sector arrives at ``snr_best_db`` per tone and the others at their
    gain differences below it."""
    g = np.asarray(gains_db, dtype=float)
    rho = 10.0 ** ((snr_best_db + g - g.max()) / 10.0)
    t = sweep_statistic(rho, n_tones, rng, trials, estimator, n_sym)
    pick = np.argmax(t, axis=1)
    return float(np.mean(g[pick] >= g.max() - within_db))


def required_training_snr_db(array: Array60, side: str, n_tones: int, seed: int = 0, trials: int = 2000,
                             estimator: str | None = None, within_db: float | None = None,
                             p_target: float | None = None, n_users: int = 25,
                             grid_db=None, repetitions: int = 1, combining: str | None = None,
                             candidates: int | None = None) -> dict:
    """The lowest per-tone SNR of the best sector at which a sweep of
    ``side``'s codebook picks a good sector with probability ``p_target``,
    averaged over stations spread uniformly in sin(theta) across the scan.
    ``repetitions`` R > 1 repeats the training field per sector, combined
    ``combining`` = "noncoherent" (powers summed: n R tones) or "coherent"
    (2 R symbols per tone); default assumed.array_training_repetition.
    ``candidates`` restricts each station's sweep to the sectors with the
    highest gain toward it (a refining stage inside a chosen wide sector)."""
    tr = spec.value("assumed.array_training")
    est = tr["estimator"] if estimator is None else estimator
    within = float(tr["success_within_db"]) if within_db is None else float(within_db)
    p_t = float(tr["p_target"]) if p_target is None else float(p_target)
    reps = int(repetitions)
    if reps < 1:
        raise ValueError("repetitions must be >= 1")
    comb = spec.value("assumed.array_training_repetition")["combining"] if combining is None else combining
    if comb == "noncoherent":
        n_eff, n_sym = n_tones * reps, 2
    elif comb == "coherent":
        n_eff, n_sym = n_tones, 2 * reps
    else:
        raise ValueError(f"unknown combining {comb!r}")
    if grid_db is None:
        # R repetitions buy up to 10 log10 R dB: start the walk that much lower (R = 1: the original grid)
        grid_db = np.arange(-20.0 - 0.5 * np.ceil(20.0 * np.log10(reps)), 20.01, 0.5)
    smax = np.sin(np.deg2rad(array.scan_max_deg))
    users = np.rad2deg(np.arcsin(np.linspace(-smax, smax, n_users)))
    gains = [array.sector_gains_db(side, float(u)) for u in users]
    if candidates is not None:
        gains = [np.sort(g)[::-1][:int(candidates)] for g in gains]
    rng = np.random.default_rng(seed)
    curve = []
    for snr in grid_db:
        p = float(np.mean([selection_success(g, float(snr), n_eff, rng, trials, est, within, n_sym) for g in gains]))
        curve.append((float(snr), p))
        if p >= p_t:
            if len(curve) == 1:
                raise ValueError(f"the sweep already succeeds at the grid's first point ({float(snr):g} dB): "
                                 "start the grid lower")
            return {"snr_db": float(snr), "p": p, "curve": curve, "sectors": int(gains[0].size), "estimator": est,
                    "repetitions": reps, "combining": comb}
    return {"snr_db": None, "p": curve[-1][1], "curve": curve, "sectors": int(gains[0].size), "estimator": est,
            "repetitions": reps, "combining": comb}


# ---------------------------------------------------------------- one scheme's budget
@dataclass
class ArrayBudget:
    label: str
    n_tx: int
    n_rx: int
    p_elem_dbm: float
    obo_db: float
    pa_evm_db: float
    eirp_dbm: float
    g_rx_db: float
    floor_db: float
    dec_mcs: int | None
    occupied_bw_hz: float
    nf_db: float
    sens_by_mcs: dict = field(default_factory=dict)      # MCS -> receiver input [dBm] at its required SNR
    range_by_mcs: dict = field(default_factory=dict)     # MCS -> metres (free space + oxygen), beams aligned
    noise_dbm: float = 0.0                               # per-tone SNR = P_rx - noise_dbm
    #: the 802.11ay rows (``ay_array_budget``): the floor of each payload constellation on the chain
    #: calibrated at the per-element back-off, and each MCS's rate (the be rows read data_rate_bps)
    floor_by_order: dict = field(default_factory=dict)
    rate_by_mcs: dict = field(default_factory=dict)

    def snr_tone_db(self, p_rx_dbm: float) -> float:
        return float(p_rx_dbm - self.noise_dbm)


def array_budget(cfg, fe, array: Array60, label: str = "", theta0_deg: float = 0.0) -> ArrayBudget:
    """The data link of ``cfg`` with ``array`` at both ends, steered to
    ``theta0_deg`` (the same array at each end: a TDD link)."""
    from .sim.link import LinkSim
    eirp_cap = float(fe.eirp.avg_dbm)
    p_target = float(fe.target_pout_dbm())
    p_e = array.element_pout_dbm(p_target, eirp_cap, theta0_deg)
    obo = float(fe.obo_db + (p_target - p_e))
    pa_evm = pa_isolated_evm_db(fe.pa_model, obo, fe.obo_reference)
    floors = analytic_floors(cfg, fe, pa_evm)
    std, bw = cfg.phy.standard, cfg.phy.bandwidth_hz
    cap = decoder_cap(floors["floor_db"], std, bw)
    sim = LinkSim(cfg, frontend=fe)
    sens0 = sim.rx_input_dbm_for_snr(0.0)
    eirp = array.eirp_dbm(p_e, theta0_deg)
    g_rx = float(array.rx_gain_db(theta0_deg, theta0_deg)[0])
    out = ArrayBudget(label=label, n_tx=array.n("tx"), n_rx=array.n("rx"), p_elem_dbm=p_e, obo_db=obo,
                      pa_evm_db=pa_evm, eirp_dbm=eirp, g_rx_db=g_rx, floor_db=floors["floor_db"],
                      dec_mcs=cap["mcs"], occupied_bw_hz=float(sim.occupied_bw_hz), nf_db=float(sim._rx_nf_db()),
                      noise_dbm=float(sens0))
    if cap["mcs"] is not None:
        for m in range(cap["mcs"] + 1):
            t = spec.per_threshold_db(std, bw, m)
            req = None if t is None else required_snr_db(t, floors["floor_db"])
            if req is None:
                continue
            s = sim.rx_input_dbm_for_snr(req)
            out.sens_by_mcs[m] = float(s)
            out.range_by_mcs[m] = range_m(eirp + g_rx - s, cfg.carrier_hz)
    return out


def training_ranges(budget: ArrayBudget, array: Array60, req_tx_db: float | None, req_rx_db: float | None,
                    f_hz: float, theta_deg: float = 0.0) -> dict:
    """How far each sweep reaches: the transmit sweep with the far end on one
    element, the receive sweep behind the chosen transmit beam (EIRP at the
    beam, receive sector gain at the station)."""
    g_one = float(array.element_factor_db("rx", theta_deg)[0] + array.element_gain_rx_dbi)
    out = {}
    if req_tx_db is not None:
        out["txss_m"] = range_m(budget.eirp_dbm + g_one - (budget.noise_dbm + req_tx_db), f_hz)
    if req_rx_db is not None:
        out["rxss_m"] = range_m(budget.eirp_dbm + budget.g_rx_db - (budget.noise_dbm + req_rx_db), f_hz)
    return out


def sweep_time_s(array: Array60, phy, side: str = "tx", repetitions: int = 1) -> float:
    """One sweep: every sector sends the training field (GI2 + 2 LTF symbols
    of the base PHY at the upclocked rate) ``repetitions`` times, plus the
    sector switch."""
    tr = spec.value("assumed.array_training")
    return float(array.codebook_deg(side).size * (int(repetitions) * _ltf_field_s(phy) + float(tr["sector_switch_s"])))


def ssw_frame_s() -> float:
    """One SSW frame of the 802.11ay sector sweep in the DMG control PHY
    (assumed.ay_sector_sweep): the control PHY's preamble
    (dmg.phy_timing.control_preamble_s, STF + CEF) plus the header and the
    frame's octets (dmg.control_phy.header_bits, dmg.ssw_frame) at the control
    PHY's rate (dmg.control_phy_rate_bps, effective code rate 1/2).  A lower
    bound: every LDPC codeword is counted as full, so a partly filled one's
    parity is not."""
    cp = spec.value("dmg.control_phy")
    bits = int(cp["header_bits"]) + 8 * int(spec.value("dmg.ssw_frame")["ssw_frame_octets"])
    rate = float(spec.value("dmg.control_phy_rate_bps"))
    return float(spec.value("dmg.phy_timing")["control_preamble_s"]) + bits / rate


def ay_sweep_time_s(array: Array60, side: str = "tx") -> float:
    """One 802.11ay sector sweep: every sector sends one SSW frame, the frames
    SBIFS apart (dmg.phy_timing.sbifs_s)."""
    gap = float(spec.value("dmg.phy_timing")["sbifs_s"])
    return float(array.codebook_deg(side).size * (ssw_frame_s() + gap))


def transmit_sweep_reach_db(budget: "ArrayBudget", array: Array60, req_db: float, theta_deg: float = 0.0) -> float:
    """The path loss the transmit sweep takes (far end on one element) at a
    required per-tone SNR ``req_db``."""
    g_one = float(array.element_factor_db("rx", theta_deg)[0] + array.element_gain_rx_dbi)
    return float(budget.eirp_dbm + g_one - (budget.noise_dbm + req_db))


def repetitions_to_reach(budget: "ArrayBudget", array: Array60, n_tones: int, target_pl_db: float,
                         combining: str | None = None, max_repetitions: int | None = None, **kw) -> dict:
    """The smallest R (a power of two, up to ``max_repetitions``) at which
    the transmit sweep takes at least ``target_pl_db`` of path loss (the MCS0
    edge of the data link): ``{"repetitions", "req_db", "pl_db", "margin_db"}``,
    ``repetitions`` None when even the largest R falls short."""
    rep = spec.value("assumed.array_training_repetition")
    r_max = int(rep["max_repetitions"]) if max_repetitions is None else int(max_repetitions)
    r, last = 1, None
    while r <= r_max:
        rt = required_training_snr_db(array, "tx", n_tones, repetitions=r, combining=combining, **kw)
        if rt["snr_db"] is not None:
            pl = transmit_sweep_reach_db(budget, array, rt["snr_db"])
            last = {"repetitions": r, "req_db": rt["snr_db"], "pl_db": pl, "margin_db": pl - target_pl_db}
            if pl >= target_pl_db:
                return last
        r *= 2
    return {**(last or {"req_db": None, "pl_db": None, "margin_db": None}), "repetitions": None}


def hierarchical_training(cfg, fe, n: int, m: int, n_tones: int, target_pl_db: float,
                          combining: str | None = None, max_repetitions: int | None = None, **kw) -> dict:
    """A two-stage transmit sweep toward ``target_pl_db`` of path loss, the
    far end on one element as in the flat sweep (ROADMAP B, user's pick
    2026-11-16): first the first ``m`` elements of the ``n``-element array as
    an m-element sub-array at its own per-element output (the EIRP limit for
    m elements), sweeping its m wide sectors; then the full array inside the
    chosen wide sector, over the ``ceil(n / m)`` narrow sectors with the
    highest gain toward the station.  Each stage gets the fewest
    repetitions (a power of two) that reach the target on its own.  Returns
    both stages and the flat sweep for comparison: sectors, repetitions,
    EIRP, required per-tone SNR, path loss reached and sweep time."""
    from .config import array_frontend
    from .frontend.array60 import Array60
    phy = cfg.upclocked()
    out = {}
    stages = (("wide", m, None), ("narrow", n, int(np.ceil(n / m))), ("flat", n, None))
    rep_cfg = spec.value("assumed.array_training_repetition")
    r_max = int(rep_cfg["max_repetitions"]) if max_repetitions is None else int(max_repetitions)
    tr = spec.value("assumed.array_training")
    for name, size, cand in stages:
        c = array_frontend(cfg, size)
        ar = Array60.from_config(c, fe)
        b = array_budget(c, fe, ar)
        sectors = int(ar.codebook_deg("tx").size) if cand is None else cand
        r, got = 1, None
        while r <= r_max:
            rt = required_training_snr_db(ar, "tx", n_tones, repetitions=r, combining=combining, candidates=cand,
                                          **kw)
            if rt["snr_db"] is not None:
                pl = transmit_sweep_reach_db(b, ar, rt["snr_db"])
                got = {"repetitions": r, "req_db": rt["snr_db"], "pl_db": pl}
                if pl >= target_pl_db:
                    break
            r *= 2
        reached = got is not None and got["pl_db"] >= target_pl_db
        reps = got["repetitions"] if reached else None
        t = None if reps is None else sectors * (reps * _ltf_field_s(phy) + float(tr["sector_switch_s"]))
        out[name] = {"elements": size, "sectors": sectors, "eirp_dbm": b.eirp_dbm, "repetitions": reps,
                     "req_db": None if got is None else got["req_db"], "pl_db": None if got is None else got["pl_db"],
                     "time_s": t}
    w, nr = out["wide"], out["narrow"]
    out["hierarchical_time_s"] = (None if w["time_s"] is None or nr["time_s"] is None
                                  else w["time_s"] + nr["time_s"])
    return out


def _ay_cfg_at(cfg, mcs: int | None = None, pa_only: bool = False):
    """``cfg`` on a flat channel with payload ``mcs``; ``pa_only`` = the ideal chain with only the PA on."""
    import dataclasses as dc

    from .config import ChannelConfig
    c = dc.replace(cfg, channel=ChannelConfig(model="flat"))
    if mcs is not None:
        c = dc.replace(c, ay=dc.replace(c.ay, mcs=int(mcs)))
    if pa_only:
        ideal = c.ideal()
        c = dc.replace(ideal, frontend=dc.replace(ideal.frontend, pa=cfg.frontend.pa))
    return c


def _ay_rule_payload(waveform: str) -> int:
    """The payload the operating rule is measured on: the fastest 16-QAM MCS (the rule's limit is the
    802.11ad 16-QAM 3/4 one)."""
    from .ay import edmg
    return max((e for e in edmg.mcs_table(waveform) if e.order == 16), key=lambda e: e.mcs).mcs


def ay_pa_alone_evm_db(cfg, obo_db: float, mcs: int | None = None) -> float:
    """The PA alone on an 802.11ay waveform's own payload (the ideal chain with only the PA on, flat, no
    noise) at ``obo_db`` from the PA's reference: the preset rule's measurement (data/spec:
    assumed.pa60_operating_rule) made on this waveform instead of an OFDM-like envelope."""
    import dataclasses as dc

    from .frontend import Frontend60
    from .sim.link import LinkSim
    c = _ay_cfg_at(cfg, _ay_rule_payload(cfg.waveform) if mcs is None else mcs, pa_only=True)
    c = dc.replace(c, frontend=dc.replace(c.frontend, pa=dc.replace(c.frontend.pa, obo_db=float(obo_db))))
    sim = LinkSim(c, frontend=Frontend60.from_config(c))
    return float(sim.packet(None, np.random.default_rng(cfg.seed)).rx.evm_db)


def ay_operating_obo_db(cfg, lo_db: float = 0.0, hi_db: float = 15.0, tol_db: float = 0.02) -> float | None:
    """The preset operating rule applied to this 802.11ay waveform's own envelope (data/spec:
    assumed.ay_operating_point): the back-off at which the PA alone on its 16-QAM payload reaches the
    rule's EVM limit (``frontend.grid.operating_rule_evm_limit_db``); None when not even ``hi_db`` does."""
    from .frontend.grid import operating_rule_evm_limit_db
    target = operating_rule_evm_limit_db()
    if ay_pa_alone_evm_db(cfg, lo_db) <= target:
        return float(lo_db)
    if ay_pa_alone_evm_db(cfg, hi_db) > target:
        return None
    lo, hi = float(lo_db), float(hi_db)
    while hi - lo > tol_db:
        mid = 0.5 * (lo + hi)
        if ay_pa_alone_evm_db(cfg, mid) > target:
            lo = mid
        else:
            hi = mid
    return float(hi)


def ay_array_budget(cfg, fe, array: Array60, label: str = "", obo_db: float | None = None,
                    theta0_deg: float = 0.0, cal_cache: dict | None = None) -> ArrayBudget:
    """``array_budget`` for an 802.11ay waveform (milestone 3): the same array and front end, each element
    at ``obo_db`` from the PA's reference (default the front end's own back-off) or lower when the EIRP
    limit asks for it.  No analytic floor: the floor of each payload constellation is read on the chain
    wifitrx's sequence calibrated at the per-element back-off (``calcheck.run_cal_ay``; ``cal_cache``
    shares runs between budgets at the same back-off — the chain does not depend on the waveform).  The
    decoder cap is the be rows' rule (``decoder_cap``): the fastest MCS whose floor sits
    assumed.decoder_cap_margin_db under the noise its threshold tolerates, the threshold from
    assumed.ay_sensitivity (``ay_mcs_ranges``); no TX-conformance condition, as for the be rows."""
    import copy
    import dataclasses as dc

    from .ay import edmg
    from .calcheck import run_cal_ay
    from .sim.link import LinkSim
    eirp_cap = float(fe.eirp.avg_dbm)
    base = float(fe.obo_db if obo_db is None else obo_db)
    p_target = float(dc.replace(fe, obo_db=base).target_pout_dbm())
    p_e = array.element_pout_dbm(p_target, eirp_cap, theta0_deg)
    obo = float(base + (p_target - p_e))
    fe_e = dc.replace(fe, obo_db=obo)
    key = round(obo, 9)
    run = None if cal_cache is None else cal_cache.get(key)
    if run is None:
        run = run_cal_ay(fe_e, _ay_cfg_at(cfg))
        if cal_cache is not None:
            cal_cache[key] = run
    wf = cfg.waveform
    by_order: dict = {}
    for e in edmg.mcs_table(wf):
        by_order[e.tone_order] = max(by_order.get(e.tone_order, 0), e.mcs)
    floors = {}
    for o, m in sorted(by_order.items()):
        sim = LinkSim(_ay_cfg_at(cfg, m), frontend=fe_e, chains=copy.deepcopy(run.chains[:2]))
        floors[o] = float(sim.packet(None, np.random.default_rng(cfg.seed)).rx.evm_db)
    sim = LinkSim(_ay_cfg_at(cfg), frontend=fe_e, chains=copy.deepcopy(run.chains[:2]))
    eirp = array.eirp_dbm(p_e, theta0_deg)
    g_rx = float(array.rx_gain_db(theta0_deg, theta0_deg)[0])
    ranges = ay_mcs_ranges(sim, floors, eirp, g_rx)
    margin = float(spec.value("assumed.decoder_cap_margin_db"))
    ok = [m for m, r in ranges.items() if -r["floor_db"] >= r["threshold_db"] + margin]
    cap = max(ok, key=lambda m: (ranges[m]["rate_bps"], m)) if ok else None
    noise = float(sim.rx_input_dbm_for_snr(0.0))
    cap_order = None if cap is None else edmg.mcs_entry(wf, cap).tone_order
    out = ArrayBudget(label=label, n_tx=array.n("tx"), n_rx=array.n("rx"), p_elem_dbm=p_e, obo_db=obo,
                      pa_evm_db=ay_pa_alone_evm_db(cfg, obo), eirp_dbm=eirp, g_rx_db=g_rx,
                      floor_db=floors[cap_order] if cap is not None else max(floors.values()), dec_mcs=cap,
                      occupied_bw_hz=float(sim.occupied_bw_hz), nf_db=float(sim._rx_nf_db()), noise_dbm=noise)
    out.floor_by_order = floors
    out.rate_by_mcs = {m: r["rate_bps"] for m, r in ranges.items()}
    if cap is not None:
        for m, r in ranges.items():
            if r["rate_bps"] <= ranges[cap]["rate_bps"] and r["sens_dbm"] is not None:
                out.sens_by_mcs[m] = float(r["sens_dbm"])
                out.range_by_mcs[m] = float(r["range_m"])
    return out


def array_power_report(cfg, fe, array: Array60, budget: "ArrayBudget",
                       coeffs: PowerCoefficients | None = None) -> PowerReport | None:
    """The array link's power per link direction, priced per bit at its
    decoder cap (None without one): the single-element column
    (``power.power_report``) with the PA taken N_tx times at the per-element
    output ``budget.p_elem_dbm`` and one phase shifter per element on each
    side when N > 1.  At N = 1 it is ``power_report`` itself."""
    if budget.dec_mcs is None:
        return None
    k = coeffs or PowerCoefficients.from_spec()
    if getattr(cfg, "waveform", "").startswith("ay_"):
        from .sim.ay_link import AyPhy
        rep = power_report(cfg, fe, budget.rate_by_mcs[budget.dec_mcs], k, phy=AyPhy(cfg))
    else:
        phy = cfg.upclocked()
        rate = data_rate_bps(cfg.phy.standard, cfg.phy.bandwidth_hz, budget.dec_mcs, phy.t_symbol_eff)
        rep = power_report(cfg, fe, rate, k, phy=phy, mcs_index=budget.dec_mcs)
    n_tx, n_rx = array.n("tx"), array.n("rx")
    blocks = []
    for b in rep.blocks:
        if b.name == "pa" and (n_tx > 1 or budget.p_elem_dbm != float(fe.target_pout_dbm())):
            pae = float(fe.scaled_pa().pae(budget.p_elem_dbm))
            w = n_tx * dbm_to_mw(budget.p_elem_dbm) * 1e-3 / max(pae, 1e-6)
            b = PowerBlock("pa", w, f"{n_tx} x Pout {budget.p_elem_dbm:.1f} dBm, PAE {100 * pae:.1f} % each")
        blocks.append(b)
    n_ps = (n_tx if n_tx > 1 else 0) + (n_rx if n_rx > 1 else 0)
    omitted = list(rep.omitted)
    if n_ps:
        blocks.append(PowerBlock("phase_shifters", n_ps * k.phase_shifter_w,
                                 f"{n_tx} TX + {n_rx} RX at {1e3 * k.phase_shifter_w:g} mW each"))
        omitted.append("the LNA / mixer of each receive element and the 1:N / N:1 splitter / combiner "
                       "(as in the single-element column)")
    return PowerReport(tuple(blocks), rep.bit_rate, tuple(omitted))


def _ltf_field_s(phy) -> float:
    """GI2 + 2 LTF symbols: twice the FFT period plus a double guard interval."""
    t_fft = float(phy.t_fft_eff)
    return 2.0 * t_fft + 2.0 * float(phy.t_symbol_eff - t_fft)


def ay_mcs_ranges(sim, floor_by_order: dict, eirp_dbm: float, g_rx_db: float = 0.0,
                  keep_implementation_loss: bool = False, oxygen_db_km: float | None = None,
                  rule: str = "measured") -> dict:
    """The data link of an 802.11ay waveform (``sim`` an ``AyLinkSim`` on the
    shared front end), per EDMG MCS with a threshold: the decoder threshold
    (``ay.edmg.threshold_db`` under ``rule``: measured for the coded SC MCS,
    the DMG twin's elsewhere, assumed.ay_sensitivity; ``source`` says which), the
    in-band SNR it needs over the floor of its constellation
    (``floor_by_order[tone_order]``, a noise term as for the be rows'
    measured thresholds), the receiver input that gives it (the front end's
    noise figure at the AGC state, over the waveform's occupied bandwidth),
    the path loss EIRP + G_rx − that input and the distance (free space plus
    oxygen).  ``conforms`` says the floor meets the MCS's TX EVM limit;
    ``range_m`` is None where the floor alone exceeds what the decoder
    tolerates.  MCS without a threshold are left out."""
    from .ay import edmg
    wf = sim.cfg.waveform
    out = {}
    for e in edmg.mcs_table(wf):
        t, src = edmg.threshold_db(wf, e.mcs, sim.occupied_bw_hz, rule, keep_implementation_loss)
        if t is None:
            continue
        f = float(floor_by_order[e.tone_order])
        req = required_snr_db(t, f)
        row = {"mcs": e.mcs, "twin": edmg.dmg_twin(wf, e.mcs), "threshold_db": t, "source": src, "floor_db": f,
               "req_db": req,
               "conforms": f <= e.evm_limit_db, "rate_bps": e.rate_bps(sim.cfg.ay.gi), "sens_dbm": None,
               "pl_db": None, "range_m": None}
        if req is not None:
            s_in = float(sim.rx_input_dbm_for_snr(req))
            pl = float(eirp_dbm + g_rx_db - s_in)
            row.update(sens_dbm=s_in, pl_db=pl, range_m=range_m(pl, sim.cfg.carrier_hz, oxygen_db_km))
        out[e.mcs] = row
    return out


def noise_dbm_per_tone(nf_db: float, scs_hz: float) -> float:
    """kT + NF over one tone's bandwidth (a cross-check of the LinkSim reading)."""
    return float(KT_DBM_HZ + nf_db + 10.0 * np.log10(scs_hz))


__all__ = ["fspl_db", "oxygen_db_per_km", "path_loss_db", "range_m", "required_snr_db", "sweep_statistic",
           "selection_success",
           "required_training_snr_db", "ArrayBudget", "array_budget", "training_ranges", "sweep_time_s",
           "ssw_frame_s", "ay_sweep_time_s",
           "transmit_sweep_reach_db", "repetitions_to_reach", "hierarchical_training", "array_power_report",
           "ay_mcs_ranges", "ay_pa_alone_evm_db", "ay_operating_obo_db", "ay_array_budget", "noise_dbm_per_tone",
           "C0"]
