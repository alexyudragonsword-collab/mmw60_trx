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
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import brentq

from . import spec
from .frontend.array60 import Array60
from .frontend.grid import analytic_floors, decoder_cap, pa_isolated_evm_db
from .vendor.wifitrx.units import KT_DBM_HZ

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
                             grid_db=np.arange(-20.0, 20.01, 0.5)) -> dict:
    """The lowest per-tone SNR of the best sector at which a sweep of
    ``side``'s codebook picks a good sector with probability ``p_target``,
    averaged over stations spread uniformly in sin(theta) across the scan."""
    tr = spec.value("assumed.array_training")
    est = tr["estimator"] if estimator is None else estimator
    within = float(tr["success_within_db"]) if within_db is None else float(within_db)
    p_t = float(tr["p_target"]) if p_target is None else float(p_target)
    smax = np.sin(np.deg2rad(array.scan_max_deg))
    users = np.rad2deg(np.arcsin(np.linspace(-smax, smax, n_users)))
    gains = [array.sector_gains_db(side, float(u)) for u in users]
    rng = np.random.default_rng(seed)
    curve = []
    for snr in grid_db:
        p = float(np.mean([selection_success(g, float(snr), n_tones, rng, trials, est, within) for g in gains]))
        curve.append((float(snr), p))
        if p >= p_t:
            return {"snr_db": float(snr), "p": p, "curve": curve, "sectors": int(gains[0].size), "estimator": est}
    return {"snr_db": None, "p": curve[-1][1], "curve": curve, "sectors": int(gains[0].size), "estimator": est}


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


def sweep_time_s(array: Array60, phy, side: str = "tx") -> float:
    """One sweep: every sector sends the training field (GI2 + 2 LTF symbols
    of the base PHY at the upclocked rate) plus the sector switch."""
    tr = spec.value("assumed.array_training")
    return float(array.codebook_deg(side).size * (_ltf_field_s(phy) + float(tr["sector_switch_s"])))


def _ltf_field_s(phy) -> float:
    """GI2 + 2 LTF symbols: twice the FFT period plus a double guard interval."""
    t_fft = float(phy.t_fft_eff)
    return 2.0 * t_fft + 2.0 * float(phy.t_symbol_eff - t_fft)


def noise_dbm_per_tone(nf_db: float, scs_hz: float) -> float:
    """kT + NF over one tone's bandwidth (a cross-check of the LinkSim reading)."""
    return float(KT_DBM_HZ + nf_db + 10.0 * np.log10(scs_hz))


__all__ = ["fspl_db", "oxygen_db_per_km", "path_loss_db", "range_m", "required_snr_db", "sweep_statistic",
           "selection_success",
           "required_training_snr_db", "ArrayBudget", "array_budget", "training_ranges", "sweep_time_s",
           "noise_dbm_per_tone", "C0"]
