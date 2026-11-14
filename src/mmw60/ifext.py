"""Topology A — the IF extender: the WiFi 7 chip as it is, then a 60 GHz stage.

The chip is wifitrx's own transceiver at K = 1, built and calibrated the way
wifitrx builds one (``handoff/runner.build_calibrated_trx``: randomised
impairments, its own PA with memory, its own synthesizer, the delivered
calibration sequence).  Its RF output at the intermediate frequency f_IF
(a 6 GHz-band channel) is what the 60 GHz stage takes:

    chip TX (unmodified)  →  interstage level  →  IF band filter (ripple,
    group delay)  →  mixer with the fixed LO at f_LO = f_c − f_IF (its phase
    noise)  →  the 60 GHz PA (the shared ``Frontend60`` instance's Rapp)

and the mirror on receive.  The insertion point is explicit (iron rule 2):
``IfExtenderTx`` / ``IfExtenderRx`` subclass wifitrx's ``TxChain`` /
``RxChain`` and apply the stage *after* (before, on receive) the parent's
``__call__``; with the stage off they are the parent, bit for bit.  Being
chains, they go through wifitrx's loopback and calibration code unchanged
(iron rule 4): the sequence runs either on the chip's own coupler (stage
off) or through a 60 GHz observation loopback (stage on, the fixed LO shared
by the up- and down-conversion so its phase noise cancels).

Complex baseband throughout, centred on the channel: the IF filter is the
lowpass-equivalent of a bandpass centred ``filter_center_hz`` away from the
channel.  The other sideband of the mixer (f_LO − f_IF), the LO feedthrough
at f_LO and the chip's harmonics are outside the simulated band; this is a
linearised time-domain engine and endorses no spur conclusion (iron rule 6)
— ``if_plan`` only lists where they fall.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy import signal as sig

from . import spec
from .config import LO_SCHEMES
from .vendor.wifitrx.chain.rx import RxChain
from .vendor.wifitrx.chain.tx import TxChain
from .vendor.wifitrx.impairments.phase_noise import NoiseSource, synth_from_psd
from .vendor.wifitrx.units import db_to_amp, power_dbm


# ---------------------------------------------------------------- frequency plan
def if_plan(carrier_hz: float, if_hz: float, n_mult: int, bandwidth_hz: float) -> dict:
    """Where everything sits for a high-IF up-conversion with the LO below the
    carrier: f_LO = f_c − f_IF from a PLL at f_LO / N.  Lists the products the
    baseband model does not carry (positions only — iron rule 6)."""
    lo_hz = carrier_hz - if_hz
    band_lo = float(spec.value("fcc15255.band_low_hz"))
    band_hi = float(spec.value("fcc15255.band_high_hz"))
    edges = (carrier_hz - bandwidth_hz / 2, carrier_hz + bandwidth_hz / 2)
    image = lo_hz - if_hz
    notes = []
    in_band = band_lo <= edges[0] and edges[1] <= band_hi
    if not in_band:
        notes.append(f"channel edges {edges[0] / 1e9:.2f}–{edges[1] / 1e9:.2f} GHz leave the band")
    if band_lo <= lo_hz <= band_hi:
        notes.append(f"LO feedthrough at {lo_hz / 1e9:.2f} GHz falls inside the unlicensed band")
    if band_lo <= image <= band_hi:
        notes.append(f"image sideband at {image / 1e9:.2f} GHz falls inside the unlicensed band")
    return {"carrier_hz": carrier_hz, "if_hz": if_hz, "lo_hz": lo_hz, "n_mult": int(n_mult),
            "pll_hz": lo_hz / int(n_mult), "image_hz": image, "image_offset_hz": 2 * if_hz,
            "lo_offset_hz": if_hz, "edges_hz": edges, "in_unlicensed_band": in_band,
            "ok": in_band, "notes": notes,
            "not_modelled": ("image sideband at f_LO − f_IF, LO feedthrough at f_LO, chip harmonics × N: "
                             "outside the simulated band; positions only, no level is endorsed")}


# ---------------------------------------------------------------- the IF band filter
@dataclass(frozen=True)
class IfFilter:
    """Lowpass-equivalent of the IF band filter: a Chebyshev-I bandpass of
    ``bandwidth_hz`` (the IF band the chip tunes across), ``ripple_db`` of
    passband ripple, seen by a channel ``offset_hz`` from its centre.  Gain
    normalised to 1 at the channel centre; applied in the frequency domain
    (the frames carry a cyclic warm-up and guard)."""
    bandwidth_hz: float = 1.2e9
    order: int = 5
    ripple_db: float = 0.5
    offset_hz: float = 0.0
    enabled: bool = True

    def response(self, f_hz: np.ndarray) -> np.ndarray:
        """H at baseband offsets ``f_hz`` from the channel centre."""
        f = np.asarray(f_hz, dtype=float)
        if not self.enabled:
            return np.ones(f.shape, dtype=complex)
        b, a = sig.cheby1(int(self.order), float(self.ripple_db), 1.0, analog=True)
        w = (f + self.offset_hz) / (self.bandwidth_hz / 2.0)
        _, h = sig.freqs(b, a, worN=np.concatenate([w, [self.offset_hz / (self.bandwidth_hz / 2.0)]]))
        return h[:-1] / h[-1]

    def apply(self, y: np.ndarray, fs: float) -> np.ndarray:
        if not self.enabled:
            return y
        y = np.asarray(y, dtype=complex)
        return np.fft.ifft(np.fft.fft(y) * self.response(np.fft.fftfreq(y.size, 1.0 / fs)))

    def ripple_in_band_db(self, bandwidth_hz: float, n: int = 257) -> float:
        h = np.abs(self.response(np.linspace(-bandwidth_hz / 2, bandwidth_hz / 2, n)))
        return float(20 * np.log10(h.max() / h.min()))

    def group_delay_spread_s(self, bandwidth_hz: float, n: int = 513) -> float:
        f = np.linspace(-bandwidth_hz / 2, bandwidth_hz / 2, n)
        ph = np.unwrap(np.angle(self.response(f)))
        gd = -np.gradient(ph, f) / (2 * np.pi)
        return float(gd.max() - gd.min())


def _lo_phase(profile: NoiseSource | None, n: int, fs: float, rng: np.random.Generator) -> np.ndarray | None:
    if profile is None:
        return None
    return synth_from_psd(profile.psd, fs, n, rng)


# ---------------------------------------------------------------- the 60 GHz stages
@dataclass
class MmwTxStage:
    """Interstage level → IF filter → fixed-LO mixer → 60 GHz PA."""
    pa: object | None                      # the shared front end's ScaledRappPA (None = no PA)
    lo_profile: NoiseSource | None = None  # the fixed LO's phase noise (the shared Lo60 profile)
    if_filter: IfFilter = field(default_factory=IfFilter)
    interstage_gain_db: float = 0.0        # pad + mixer conversion gain, trimmed for the PA's back-off
    #: True during a 60 GHz observation loopback: the same LO converts up and
    #: down, a few ns apart, and its phase noise cancels in the capture
    lo_shared_loopback: bool = False
    seed: int = 0

    def __call__(self, y: np.ndarray, fs: float, rng: np.random.Generator | None = None,
                 nodes: dict | None = None) -> np.ndarray:
        y = np.asarray(y, dtype=complex) * db_to_amp(self.interstage_gain_db)
        y = self.if_filter.apply(y, fs)
        if self.lo_profile is not None and not self.lo_shared_loopback:
            rng = np.random.default_rng(self.seed + 11) if rng is None else rng
            y = y * np.exp(1j * _lo_phase(self.lo_profile, y.size, fs, rng))
        if nodes is not None:
            nodes["mmw_pa_in_dbm"] = power_dbm(y)
        if self.pa is not None:
            y = self.pa(y)
        if nodes is not None:
            nodes["mmw_pa_out_dbm"] = power_dbm(y)
        return y


@dataclass
class MmwRxStage:
    """Fixed-LO down-conversion → IF filter, in front of the chip's receiver.
    Unit gain: the SNR axis stays the chip's own (noise figure of its LNA
    state); what the stage adds is its LO's phase noise, the filter and the
    noise of the unrejected image band."""
    lo_profile: NoiseSource | None = None
    if_filter: IfFilter = field(default_factory=IfFilter)
    image_rejection_db: float | None = None
    lo_shared_loopback: bool = False
    seed: int = 0

    def __call__(self, y: np.ndarray, fs: float, rng: np.random.Generator | None = None) -> np.ndarray:
        y = np.asarray(y, dtype=complex)
        if self.lo_profile is not None and not self.lo_shared_loopback:
            rng = np.random.default_rng(self.seed + 13) if rng is None else rng
            y = y * np.exp(1j * _lo_phase(self.lo_profile, y.size, fs, rng))
        return self.if_filter.apply(y, fs)

    def image_noise_penalty_db(self) -> float:
        """Noise-figure penalty of the image band folding in: 10·log10(1 + 10^(−IRR/10))."""
        if self.image_rejection_db is None:
            return 0.0
        return float(10 * np.log10(1.0 + 10.0 ** (-self.image_rejection_db / 10.0)))


# ---------------------------------------------------------------- chains with the stage inserted
class IfExtenderTx(TxChain):
    """wifitrx's ``TxChain`` with the 60 GHz transmit stage after its RF output.
    ``stage_on = False`` (or no stage) is the parent chain, bit for bit."""

    def __init__(self, params, fs, stage: MmwTxStage | None = None, pa=None):
        super().__init__(params, fs, pa=pa)
        self.stage = stage
        self.stage_on = stage is not None
        self.stage_rng: np.random.Generator | None = None

    def chip(self, x_digital, phi_lo=None, nodes=None):
        """The chip's own RF output (the insertion point)."""
        return super().__call__(x_digital, phi_lo=phi_lo, nodes=nodes)

    def __call__(self, x_digital, phi_lo=None, nodes=None):
        y = super().__call__(x_digital, phi_lo=phi_lo, nodes=nodes)
        if self.stage is None or not self.stage_on:
            return y
        return self.stage(y, self.fs, self.stage_rng, nodes)


class IfExtenderRx(RxChain):
    """wifitrx's ``RxChain`` with the 60 GHz receive stage in front of its RF input."""

    def __init__(self, params, fs, stage: MmwRxStage | None = None):
        super().__init__(params, fs)
        self.stage = stage
        self.stage_on = stage is not None
        self.stage_rng: np.random.Generator | None = None

    def __call__(self, y_rf, phi_lo=None, rng=None, nodes=None):
        if self.stage is not None and self.stage_on:
            y_rf = self.stage(y_rf, self.fs, self.stage_rng)
        return super().__call__(y_rf, phi_lo=phi_lo, rng=rng, nodes=nodes)


# ---------------------------------------------------------------- the chip, built and calibrated
CAL_QAM = 256
CAL_SYMBOLS = 4
TX_POWER_REF_DRIVE = 0.25      # cal/sequence.py: calibrate_tx_power(tx, wf.x * 0.25, ...)
_CHIP_CACHE: dict = {}


def cal_ofdm_config(bandwidth_hz: float, oversampling: int, subcarrier_spacing_hz: float | None = None):
    """The OFDM stimulus wifitrx's own recipe calibrates on (``build_calibrated_trx``)."""
    from .vendor.wifitrx.waveform.ofdm import OFDMConfig
    kw = dict(bandwidth_hz=bandwidth_hz, qam_order=CAL_QAM, n_symbols=CAL_SYMBOLS, oversampling=int(oversampling))
    if subcarrier_spacing_hz is not None:
        kw["subcarrier_spacing_hz"] = subcarrier_spacing_hz
        kw["cp_fraction"] = 1 / 4 if subcarrier_spacing_hz > 100e3 else 1 / 16
    return OFDMConfig(**kw)


def build_chip_wifitrx(bandwidth_hz: float, fs_hz: float, seed: int):
    """wifitrx's transceiver the way wifitrx builds one (``handoff/runner.
    build_calibrated_trx``: randomised impairments, LPF corners at 1.3 / 1.12 ×
    BW/2), as ``IfExtenderTx`` / ``IfExtenderRx`` with no stage yet — uncalibrated."""
    from .vendor.wifitrx.chain.params import RxParams, TxParams
    rng = np.random.default_rng(seed)
    txp = TxParams(bandwidth_hz=bandwidth_hz).randomize(rng)
    rxp = RxParams(bandwidth_hz=bandwidth_hz).randomize(rng)
    txp.lpf.fc_nominal_hz = bandwidth_hz / 2 * 1.3
    rxp.lpf.fc_nominal_hz = bandwidth_hz / 2 * 1.12
    return IfExtenderTx(txp, fs_hz), IfExtenderRx(rxp, fs_hz)


def calibrate_chip(tx: IfExtenderTx, rx: IfExtenderRx, bandwidth_hz: float, oversampling: int,
                   with_dpd: bool = True, target_pout_dbm: float | None = None,
                   drive_scale: float = 0.15, on_step=None) -> list:
    """wifitrx's delivered sequence (``run_full_cal``) on the chip's own coupler
    (the chains come without a stage, or with it switched off)."""
    from .vendor.wifitrx.cal.sequence import run_full_cal
    from .vendor.wifitrx.chain.loopback import LoopbackPath, recommended_loopback_atten_db
    cfg = cal_ofdm_config(bandwidth_hz, oversampling)
    path = LoopbackPath(atten_db=recommended_loopback_atten_db(bandwidth_hz), delay_ns=6.0)
    return run_full_cal(tx, rx, cfg, path, with_dpd=with_dpd, target_pout_dbm=target_pout_dbm,
                        final_drive_scale=drive_scale, on_step=on_step)


def mmw_observation_path(tx: IfExtenderTx, bandwidth_hz: float, x_probe: np.ndarray, min_atten_db: float = 0.0):
    """The 60 GHz observation loopback as a wifitrx ``LoopbackPath``: a coupler
    after the second PA sized so the chip's receiver sees the level it sees on
    its own coupler (the cal steps' AGC and distortion budgets are tuned for it)."""
    from .vendor.wifitrx.chain.loopback import LoopbackPath, recommended_loopback_atten_db
    on = tx.stage_on
    tx.stage_on = False
    p_chip = power_dbm(tx(x_probe))
    tx.stage_on = True
    p_mmw = power_dbm(tx(x_probe))
    tx.stage_on = on
    atten = max(recommended_loopback_atten_db(bandwidth_hz), min_atten_db) - (p_chip - p_mmw)
    return LoopbackPath(atten_db=float(atten), delay_ns=6.0)


def calibrated_chip(bandwidth_hz: float, fs_hz: float, seed: int, with_dpd: bool,
                    target_pout_dbm: float | None, drive_scale: float):
    """A calibrated chip (deep copy of a cached one: the sequence takes seconds
    and a sweep builds many links on the same chip).  Returns (tx, rx, results)."""
    import copy
    key = (float(bandwidth_hz), float(fs_hz), int(seed), bool(with_dpd),
           None if target_pout_dbm is None else float(target_pout_dbm), float(drive_scale))
    if key not in _CHIP_CACHE:
        tx, rx = build_chip_wifitrx(bandwidth_hz, fs_hz, seed)
        # wifitrx's tx_power step sets the average output at its own reference drive
        # (TX_POWER_REF_DRIVE rms); the target here is the output at the link's drive
        target = None if target_pout_dbm is None else (
            float(target_pout_dbm) + 20 * np.log10(TX_POWER_REF_DRIVE / drive_scale))
        res = calibrate_chip(tx, rx, bandwidth_hz, int(round(fs_hz / bandwidth_hz)), with_dpd,
                             target, drive_scale)
        _CHIP_CACHE[key] = (tx, rx, res)
    tx, rx, res = _CHIP_CACHE[key]
    # the predistorter is a fitted, stateless callable (and wifitrx's BoundedDPD does not
    # survive deepcopy: its __getattr__ delegates before its model is set): share it
    dpd, tx.dpd = tx.dpd, None
    try:
        tx2 = copy.deepcopy(tx)
    finally:
        tx.dpd = dpd
    tx2.dpd = dpd
    return tx2, copy.deepcopy(rx), res


def _pa_out_evm_db(tx, wf, x: np.ndarray) -> float:
    """EVM at the transmit output with per-tone equalisation — the metric
    wifitrx's ``calibrate_dpd`` reports before / after (``cal/dpd_cal.py``)."""
    from .vendor.wifitrx.metrics import evm
    from .vendor.wifitrx.waveform.ofdm import demodulate_ofdm
    y = tx(x)
    g = np.vdot(x, y) / np.vdot(x, x)
    return float(evm(demodulate_ofdm(y / g, wf), wf.tx_symbols, equalize="per_tone").db)


CHIP_DRIVE_RMS = 0.15          # the digital drive the link runs at (sim/link.py::DIGITAL_DRIVE_RMS)
_CHIP_FACTS: dict = {}


def chip_facts(cfg, bandwidth_hz: float, fs_hz: float) -> dict:
    """What the analytic floor and the power column need to know about the
    calibrated chip: its residual EVM (the sequence's own ``final_loopback_evm``
    — TX and RX of one chip in loopback, predistorter on), its PA's average
    output and DC power at the link's drive, its LO profile.  Measured on the
    cached chip, not assumed."""
    ix = cfg.ifext
    key = (float(bandwidth_hz), float(fs_hz), int(ix.chip_seed), bool(ix.with_dpd),
           None if ix.chip_pout_dbm is None else float(ix.chip_pout_dbm))
    if key not in _CHIP_FACTS:
        from .vendor.wifitrx.waveform.ofdm import generate_ofdm
        tx, rx, res = calibrated_chip(bandwidth_hz, fs_hz, ix.chip_seed, ix.with_dpd, ix.chip_pout_dbm,
                                      CHIP_DRIVE_RMS)
        final = next((r for r in res if r.name == "final_loopback_evm"), None)
        x = generate_ofdm(cal_ofdm_config(bandwidth_hz, int(round(fs_hz / bandwidth_hz)))).x * CHIP_DRIVE_RMS
        y = tx.chip(x)
        _CHIP_FACTS[key] = {
            "residual_evm_db": None if final is None else float(final.metrics_after["evm_db"]),
            "pout_dbm": float(power_dbm(y)), "pa_dc_w": float(tx.pa.dc_power_w(y)),
            "pa_pae": float(tx.pa.average_pae(y)), "psat_dbm": float(tx.params.psat_dbm),
            "lo_profile": tx.params.lo.profile if tx.params.lo.enabled else None,
            "steps": [(r.name, r.passed) for r in res]}
    return _CHIP_FACTS[key]


@dataclass
class IfExtender:
    """Topology A's hardware for one link: the chip's chains with the 60 GHz
    stages inserted, the frequency plan, and what the calibration measured."""
    tx: IfExtenderTx
    rx: IfExtenderRx
    plan: dict
    chip: str
    cal_results: list = field(default_factory=list)
    dpd_observation: str = "chip"
    dpd_max_iterations: int = 2
    pout_dbm: float | None = None
    chip_pout_dbm: float | None = None
    dpd_mmw: dict | None = None

    @classmethod
    def build(cls, cfg, fe, bandwidth_hz: float, fs_hz: float, drive_scale: float = 0.15) -> "IfExtender":
        """From the config and the **shared** front end (iron rule 2): the 60 GHz
        PA is ``fe``'s Rapp, the fixed LO's phase noise is ``fe.lo``'s profile at
        f_LO = f_c − f_IF (the same objects topology B's chains use; a pllsim
        clock profile is the same synthesizer design placed at f_LO)."""
        if cfg.lo.scheme == "zero_if":
            raise ValueError("topology A needs lo.scheme "
                             + " | ".join(s for s in LO_SCHEMES if s != "zero_if")
                             + " (the fixed LO's multiplication)")
        ix = cfg.ifext
        plan = if_plan(cfg.carrier_hz, cfg.lo.if_hz, cfg.lo.n_mult, bandwidth_hz)
        src = fe.lo.profile_source
        if src is not None and src["multiply_by"] > 1 and src["multiply_by"] != plan["n_mult"]:
            raise ValueError(f"{Path(src['path']).name}: the clock profile went through a x{src['multiply_by']} "
                             f"multiplier, lo.scheme {cfg.lo.scheme} is x{plan['n_mult']} "
                             f"(PLL {plan['pll_hz'] / 1e9:.4g} GHz)")
        flt = IfFilter(bandwidth_hz=ix.filter_bw_hz, order=ix.filter_order, ripple_db=ix.filter_ripple_db,
                       offset_hz=cfg.lo.if_hz - ix.filter_center_hz, enabled=ix.filter_enabled)
        lo_prof = fe.lo.at(plan["lo_hz"]).profile if cfg.lo.phase_noise.enabled else None
        sides = cfg.lo.phase_noise.apply
        tx_stage = MmwTxStage(pa=fe.scaled_pa() if fe.pa_enabled else None,
                              lo_profile=lo_prof if sides in ("tx", "both") else None,
                              if_filter=flt, seed=cfg.seed)
        rx_stage = MmwRxStage(lo_profile=lo_prof if sides in ("rx", "both") else None, if_filter=flt,
                              image_rejection_db=ix.image_rejection_db, seed=cfg.seed)
        if ix.chip == "wifitrx":
            tx, rx, res = calibrated_chip(bandwidth_hz, fs_hz, ix.chip_seed, ix.with_dpd,
                                          ix.chip_pout_dbm, drive_scale)
        else:
            # the shared front end's own chain at 1×: its PA bypassed (the IF is taken
            # before it) and its LO off — in this build the one LO profile is the fixed
            # LO's, in the stage; the chip's own synthesizer is not a second copy of it
            from dataclasses import replace
            t0, r0 = fe.build_chains(bandwidth_hz, fs_hz)
            t0.params.pa_enabled = False
            t0.params.lo = replace(t0.params.lo, enabled=False)
            r0.params.lo = replace(r0.params.lo, enabled=False)
            tx, rx, res = IfExtenderTx(t0.params, fs_hz), IfExtenderRx(r0.params, fs_hz), []
        tx.stage, rx.stage = tx_stage, rx_stage
        tx.stage_on = rx.stage_on = True
        return cls(tx=tx, rx=rx, plan=plan, chip=ix.chip, cal_results=res, dpd_observation=ix.dpd_observation,
                   dpd_max_iterations=ix.dpd_max_iterations)

    # ------------------------------------------------------------ operating point
    def set_interstage(self, x_digital: np.ndarray, target_pout_dbm: float, tol_db: float = 0.02) -> float:
        """Trim the interstage level so the 60 GHz PA's average output is the
        target for this waveform (the pad / mixer gain — never the chip's drive)."""
        st = self.tx.stage
        if st.pa is None:
            # no PA: unit conversion gain from the chip's output
            st.interstage_gain_db = 0.0
            return power_dbm(self.tx(x_digital))
        # coarse on a short piece of the frame (each pass runs the chip's predistorter,
        # the filter and both PAs), then to tolerance on the whole frame
        for seg in (x_digital[:min(x_digital.size, 1 << 14)], x_digital):
            for _ in range(14):
                p = power_dbm(self.tx(seg))
                err = target_pout_dbm - p
                if abs(err) < tol_db:
                    break
                # compression makes dPout/dPin < 1: step a little more than the error
                st.interstage_gain_db += err * 1.2
        return p

    def train_dpd_mmw(self, bandwidth_hz: float, oversampling: int, drive_scale: float,
                      target_pout_dbm: float | None = None, max_iterations: int = 2) -> dict:
        """Retrain the predistorter on the cascade through a 60 GHz observation
        loopback (coupler after the second PA, the same fixed LO converting
        down, the chip's receiver) with wifitrx's ``calibrate_dpd``, unchanged
        — and keep it only if it beats the one the chip already has.

        wifitrx's indirect-learning fit iterates.  On a soft-compressing PA
        near saturation every further pass undoes the one before it (this
        Rapp at 8 dB back-off: −21 dB after one pass, −15 dB after two, +3 dB
        after three — cairn/topology-a.md §4).  Since wifi_trx_cal 0.7.39 the
        step handles that itself: it reads "no predistorter" and each of its
        ``max_iterations`` passes on the observation path and programs the
        best, or none.  What it cannot know is that this chip already carries
        a predistorter fitted on its own coupler, nor that a predistorter
        changes the cascade's output power: so its pick is put back at the
        target output power and read against the chip-only one there, on the
        same observation path, and the better of the two stays."""
        from dataclasses import replace

        from .vendor.wifitrx.cal.dpd_cal import calibrate_dpd
        from .vendor.wifitrx.waveform.ofdm import generate_ofdm
        tx, rx = self.tx, self.rx
        st = tx.stage
        wf = generate_ofdm(replace(cal_ofdm_config(bandwidth_hz, oversampling), n_symbols=8))
        x = wf.x * drive_scale
        tx.stage_on = True
        if target_pout_dbm is None:
            target_pout_dbm = power_dbm(tx(x))
        chip_dpd = tx.dpd
        gain0 = st.interstage_gain_db
        st.lo_shared_loopback = rx.stage.lo_shared_loopback = True      # the observation: the LO's phase noise cancels
        try:
            def read() -> float:
                """EVM at the 60 GHz PA output with the candidate programmed, at the target output power."""
                self.set_interstage(x, target_pout_dbm)
                e = _pa_out_evm_db(tx, wf, x)
                return float(e) if np.isfinite(e) else float("inf")

            evm_chip = read()
            st.interstage_gain_db = gain0
            tx.dpd = None
            # the DPD observes at the cold coupler point (≥ 40 dB on the chip, wifitrx's dpd step)
            path = mmw_observation_path(tx, bandwidth_hz, x, min_atten_db=40.0)
            res = calibrate_dpd(tx, rx, wf, path, n_iter=int(max_iterations), drive_scale=drive_scale)
            kept = int(res.estimated["kept_iteration"])
            evm_fitted = read()
            fitted = (kept, tx.dpd, evm_fitted, st.interstage_gain_db)
        finally:
            st.lo_shared_loopback = rx.stage.lo_shared_loopback = False
        best = min((("chip", chip_dpd, evm_chip, gain0), fitted), key=lambda c: c[2])
        tx.dpd, st.interstage_gain_db = best[1], best[3]
        self.dpd_mmw = {"evm_chip_dpd_db": evm_chip,
                        # wifitrx's own readings on the observation path at the training drive:
                        # index 0 is no predistorter, k the predistorter after k passes
                        "observed_by_pass_db": [float(v) for v in res.estimated["observed_evm_db"]],
                        "kept_pass": kept, "evm_fitted_db": evm_fitted,
                        "programmed": best[0], "evm_programmed_db": float(best[2]),
                        "chip_dpd_kept": best[0] == "chip", "coupler_atten_db": float(path.atten_db),
                        "max_iterations": int(max_iterations)}
        return self.dpd_mmw

    def finish(self, x_digital: np.ndarray, target_pout_dbm: float, bandwidth_hz: float,
               oversampling: int, drive_scale: float) -> float:
        """Operating point, then (if asked) the 60 GHz-observed DPD and the point again."""
        self.tx.stage_on = False
        self.chip_pout_dbm = power_dbm(self.tx(x_digital)) if self.tx.params.pa_enabled else None
        self.tx.stage_on = True
        self.pout_dbm = self.set_interstage(x_digital, target_pout_dbm)
        if self.chip == "wifitrx" and self.dpd_observation == "mmw" and self.tx.stage.pa is not None:
            self.train_dpd_mmw(bandwidth_hz, oversampling, drive_scale, target_pout_dbm, self.dpd_max_iterations)
            self.pout_dbm = self.set_interstage(x_digital, target_pout_dbm)
        return self.pout_dbm

    def describe(self) -> dict:
        st = self.tx.stage
        return {"chip": self.chip, "plan": self.plan, "interstage_gain_db": st.interstage_gain_db,
                "chip_pout_dbm": self.chip_pout_dbm, "pout_dbm": self.pout_dbm,
                "dpd_observation": self.dpd_observation, "dpd_mmw": self.dpd_mmw,
                "if_filter_ripple_db": st.if_filter.ripple_in_band_db(self.tx.params.bandwidth_hz),
                "if_filter_gd_spread_ps": st.if_filter.group_delay_spread_s(self.tx.params.bandwidth_hz) * 1e12,
                "image_noise_penalty_db": self.rx.stage.image_noise_penalty_db(),
                "cal_steps": [(r.name, bool(r.passed) if r.passed is not None else None) for r in self.cal_results]}


__all__ = ["if_plan", "IfFilter", "MmwTxStage", "MmwRxStage", "IfExtenderTx", "IfExtenderRx",
           "IfExtender", "build_chip_wifitrx", "calibrate_chip", "calibrated_chip", "cal_ofdm_config",
           "mmw_observation_path", "chip_facts", "CHIP_DRIVE_RMS"]
