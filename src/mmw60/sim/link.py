"""One packet through TX → impairments → channel → RX, and the PER sweep.

Two front-end models, both topology B (``upclock_zero_if``):

* ``behavioural`` (milestone 0): the wifitrx frame at the base numerology,
  then at ``fs_eff``: Rapp PA at OBO → TX LO phase noise → channel → CFO
  (ppm × f_c) → RX LO phase noise → AWGN at the in-band per-tone SNR.
* ``zero_if_chain`` (milestone 1): the same frame through wifitrx's
  ``TxChain`` / ``RxChain`` built at ``fs_eff`` from the shared
  ``Frontend60`` (DAC / ADC at ENOB(fs_eff), LPFs at the K-scaled corner,
  IQ mismatch in absolute ps, LO leakage and RX self-mixing DC, the Rapp PA
  at Psat − OBO through the analog VGA, the LO profile on both LOs), the
  channel and the CFO between them at the RF plane, the receiver's input
  level set from the SNR through the LNA state's noise figure; timing by
  cross-correlation with the known frame (the chain's group delay).

Topology A raises ``NotImplementedError`` until the other session lands it;
the config already names it (iron rule 1).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..channel import make_channel
from ..config import Mmw60Config
from ..impairments.cfo import CfoModel
from ..impairments.noise import add_awgn_per_tone, per_sample_snr_offset_db
from ..impairments.phase_noise import PoleZeroPhase, lo_phase
from ..pa.rapp import ModifiedRappPA, apply_pa_at_obo
from ..phy.mcs import vht_mcs
from ..phy.ppdu import build_data_field, random_psdu
from ..rx.receiver import RxResult, TxRef, receive
from ..vendor.wifitrx.units import KT_DBM_HZ, db_to_amp, power_dbm
from ..vendor.wifitrx.waveform.ofdm import generate_ofdm
from ..vendor.wifitrx.waveform.pilots import (generate_ofdm_with_pilots, pilot_positions,
                                             pilot_sequence)
from ..vendor.wifitrx.waveform.preamble import build_frame

DIGITAL_DRIVE_RMS = 0.15      # −16.5 dBFS: wifitrx's own snapshot drive, DAC peaks clear
N_WARMUP = 512                # cyclic prefix / guard for the chain's IIR settling and delay
N_GUARD = 64


def envelope_lag(x_ref: np.ndarray, y: np.ndarray, max_lag: int) -> int:
    """Integer delay of ``y`` against ``x_ref`` from the cross-correlation of
    the two power envelopes.  wifitrx's ``align_delay`` correlates the complex
    waveforms, which a 2.94 MHz CFO decorrelates within a microsecond; the
    envelope is CFO-blind, and the fractional part of the chain's group delay
    is a linear phase the LTF channel estimate absorbs."""
    from scipy import signal as sig
    a = np.abs(np.asarray(x_ref)) ** 2
    b = np.abs(np.asarray(y)) ** 2
    a = a - a.mean()
    b = b - b.mean()
    corr = sig.correlate(b, a, mode="full", method="fft")
    lags = np.arange(-(a.size - 1), b.size)
    win = np.where(np.abs(lags) <= max_lag)[0]
    return int(lags[win[np.argmax(corr[win])]])


@dataclass
class PacketResult:
    rx: RxResult
    snr_db: float
    cfo_true_hz: float
    pa_info: dict
    taps: np.ndarray


class LinkSim:
    """Everything that does not change from packet to packet, built once.
    ``frontend`` may be passed in so two topologies share one instance
    (iron rule 2); otherwise it is built from the config."""

    def __init__(self, cfg: Mmw60Config, frontend=None):
        if cfg.topology != "upclock_zero_if":
            raise NotImplementedError(f"topology {cfg.topology!r}: milestone 1")
        self.cfg = cfg
        self.coded = cfg.coded
        if self.coded:
            self.mcs = vht_mcs(cfg.phy.mcs)
            self.n_symbols = self.mcs.n_symbols(cfg.phy.packet_bytes)
        else:
            self.mcs = None
            self.n_symbols = int(cfg.phy.evm_symbols)
        self.phy = cfg.upclocked(self.n_symbols)
        self.base = self.phy.base
        self.pilot_cols = pilot_positions(self.base)
        self.n_active = self.base.n_active
        self.data_cols = np.setdiff1d(np.arange(self.n_active), self.pilot_cols)
        self.pilots = pilot_sequence(self.n_symbols, self.pilot_cols.size, cfg.phy.pilot_seed)
        self.cfo = CfoModel(cfg.carrier_hz, cfg.xo_ppm_tx, cfg.xo_ppm_rx)
        pn = cfg.lo.phase_noise
        self.pn_profile = (PoleZeroPhase(psd0_dbchz=pn.psd0_dbchz, f_pole_hz=pn.f_pole_hz,
                                         f_zero_hz=pn.f_zero_hz) if pn.enabled else None)
        self.pn_sides = pn.apply if pn.enabled else "off"
        self.channel = make_channel(cfg.channel.model, cfg.channel.rms_delay_ns,
                                    cfg.channel.los_k_db, cfg.channel.taps)
        self.snr_offset_db = per_sample_snr_offset_db(self.base.fft_size, self.base.oversampling,
                                                      self.n_active)
        self.model = cfg.frontend.model
        self.pa = None
        self.frontend = None
        if self.model == "behavioural":
            self.pa = ModifiedRappPA(ampm=cfg.frontend.pa.ampm) if cfg.frontend.pa.enabled else None
        else:
            from ..frontend import Frontend60
            self.frontend = frontend if frontend is not None else Frontend60.from_config(cfg)
            self.tx, self.rx = self.frontend.build_chains(self.phy.bandwidth_eff, self.phy.fs_eff)
            # the operating point: PA average output at Psat − OBO for this waveform
            _, frame0 = self.transmit(np.random.default_rng(cfg.seed))
            self.pout_dbm = self.frontend.set_vga_for_obo(self.tx, frame0.x * DIGITAL_DRIVE_RMS)
            self.occupied_bw_hz = self.n_active * self.phy.scs_eff

    # --- transmitter ----------------------------------------------------
    def transmit(self, rng: np.random.Generator):
        if self.coded:
            psdu = random_psdu(self.cfg.phy.packet_bytes, rng)
            ref = build_data_field(self.mcs, psdu, self.n_active, self.pilot_cols, self.pilots,
                                   self.cfg.phy.scrambler_seed)
            wf = generate_ofdm(self.base, symbols=ref.symbols)
        else:
            seed = int(rng.integers(0, 2 ** 31))
            from dataclasses import replace
            wf, cols = generate_ofdm_with_pilots(replace(self.base, seed=seed), self.cfg.phy.pilot_seed)
            ref = TxRef(symbols=wf.tx_symbols, data_cols=self.data_cols, pilot_cols=cols,
                        pilots=self.pilots)
        frame = build_frame(self.base, data=wf, stf_periods=self.cfg.phy.stf_periods)
        return ref, frame

    # --- the air: behavioural ---------------------------------------------
    def _impair_behavioural(self, x: np.ndarray, rng: np.random.Generator, snr_db: float | None):
        fs = self.phy.fs_eff
        pa_info = {}
        if self.pa is not None:
            x, pa_info = apply_pa_at_obo(self.pa, x, self.cfg.frontend.pa.obo_db,
                                         self.cfg.frontend.pa.obo_reference)
        if self.pn_sides in ("tx", "both"):
            x = x * np.exp(1j * lo_phase(self.pn_profile, x.size, fs, rng))
        x, taps = self.channel.apply(x, fs, rng)
        x = self.cfo.apply(x, fs)
        if self.pn_sides in ("rx", "both"):
            x = x * np.exp(1j * lo_phase(self.pn_profile, x.size, fs, rng))
        if snr_db is not None:
            x, _ = add_awgn_per_tone(x, snr_db, self.base.fft_size, self.base.oversampling,
                                     self.n_active, rng)
        return x, taps, pa_info

    # --- the air: wifitrx zero-IF chain at fs_eff ----------------------------
    def rx_input_dbm_for_snr(self, snr_tone_db: float) -> float:
        """Receiver input power that gives ``snr_tone_db`` per active tone with
        the LNA state's noise figure (AGC and NF are solved together)."""
        p = -60.0
        for _ in range(3):
            self.rx.agc(p)
            nf = self.rx.params.lna_states[self.rx.lna_idx].nf_db
            p = snr_tone_db + KT_DBM_HZ + nf + 10 * np.log10(self.occupied_bw_hz)
        return float(p)

    def _impair_chain(self, x: np.ndarray, rng: np.random.Generator, snr_db: float | None):
        fs = self.phy.fs_eff
        n = x.size
        xp = np.concatenate([x[-N_WARMUP:], x, x[:N_GUARD]]) * DIGITAL_DRIVE_RMS
        tx, rx = self.tx, self.rx
        phi_tx = tx.lo_phase(xp.size, rng) if tx.params.lo.enabled else None
        y = tx(xp, phi_lo=phi_tx)
        pa_info = {"pout_dbm": power_dbm(y[N_WARMUP:N_WARMUP + n])}
        y, taps = self.channel.apply(y, fs, rng)
        y = self.cfo.apply(y, fs)
        if snr_db is None:
            p_in = -50.0
            rx.noise_enabled = False
        else:
            p_in = self.rx_input_dbm_for_snr(snr_db)
            rx.noise_enabled = True
        y = y * db_to_amp(p_in - power_dbm(y))
        rx.agc(p_in)
        phi_rx = rx.lo_phase(y.size, rng) if rx.params.lo.enabled else None
        z = rx(y, phi_lo=phi_rx, rng=rng)
        # timing: the chain's group delay, from the envelopes (CFO-blind)
        lag = envelope_lag(xp, z, N_GUARD // 2)
        z = z[N_WARMUP + lag:N_WARMUP + lag + n]
        pa_info.update({"rx_input_dbm": p_in, "lna_state": rx.lna_idx, "delay_samples": lag})
        return z, taps, pa_info

    def impair(self, x: np.ndarray, rng: np.random.Generator, snr_db: float | None):
        if self.model == "behavioural":
            return self._impair_behavioural(x, rng, snr_db)
        return self._impair_chain(x, rng, snr_db)

    # --- one packet ----------------------------------------------------
    def packet(self, snr_db: float | None, rng: np.random.Generator,
               keep_symbols: bool = False, kernel: str | None = None) -> PacketResult:
        ref, frame = self.transmit(rng)
        y, taps, pa_info = self.impair(frame.x, rng, snr_db)
        true_h = None
        if self.cfg.rx.genie_csi:
            if self.model != "behavioural":
                raise ValueError("genie_csi is a behavioural-model diagnostic (the chain's response is not known)")
            tones = self.base.active_tone_indices() * self.phy.scs_eff
            delays = np.arange(np.asarray(taps).size) / self.phy.fs_eff
            true_h = np.exp(-2j * np.pi * np.outer(tones, delays)) @ np.asarray(taps)
        res = receive(y, frame, ref, self.phy, self.cfg.rx, keep_symbols, kernel, true_h)
        return PacketResult(rx=res, snr_db=float("nan") if snr_db is None else snr_db,
                            cfo_true_hz=self.cfo.cfo_hz, pa_info=pa_info, taps=taps)

    def describe(self) -> dict:
        d = self.phy.summary()
        d.update({"mcs": self.cfg.phy.mcs if self.coded else None, "coded": self.coded,
                  "n_symbols": self.n_symbols,
                  "cfo_hz": self.cfo.cfo_hz, "cfo_subcarriers": self.cfo.in_subcarriers(self.phy.scs_eff),
                  "pn": self.pn_sides, "pa": self.cfg.frontend.pa.model if self.cfg.frontend.pa.enabled else "ideal",
                  "pa_obo_db": self.cfg.frontend.pa.obo_db if self.cfg.frontend.pa.enabled else None,
                  "pa_obo_reference": self.cfg.frontend.pa.obo_reference if self.cfg.frontend.pa.enabled else None,
                  "channel": self.channel.name,
                  "channel_rms_delay_ns": (self.cfg.channel.rms_delay_ns
                                           if self.cfg.channel.model == "tdl_exp" else 0.0),
                  "cfo_estimation": self.cfg.rx.cfo_estimation,
                  "snr_per_sample_offset_db": self.snr_offset_db, "frontend_model": self.model})
        if self.frontend is not None:
            d["frontend"] = self.frontend.describe(self.phy.fs_eff)
            d["frontend"]["pout_dbm_set"] = self.pout_dbm
        return d


# ------------------------------------------------------------------ sweep
def per_sweep(cfg: Mmw60Config, snr_db: list[float], max_packets: int = 400,
              min_errors: int = 20, stop_below: float = 1e-3, seed: int | None = None,
              progress=None) -> dict:
    """PER at each SNR (ascending).  Each point stops at ``min_errors`` packet
    errors or ``max_packets``; the sweep stops once a point's PER is below
    ``stop_below`` with zero errors (the curve is past the target)."""
    sim = LinkSim(cfg)
    if not sim.coded:
        raise ValueError("per_sweep needs the coded VHT 20 MHz base; use evm_at for other bases")
    rng = np.random.default_rng(cfg.seed if seed is None else seed)
    out = {"snr_db": [], "per": [], "n_packets": [], "n_errors": [], "evm_db": []}
    for s in snr_db:
        n = err = 0
        evm = []
        while n < max_packets and err < min_errors:
            r = sim.packet(s, rng)
            n += 1
            err += int(r.rx.packet_error)
            evm.append(r.rx.evm_db)
        per = err / n
        out["snr_db"].append(float(s))
        out["per"].append(per)
        out["n_packets"].append(n)
        out["n_errors"].append(err)
        out["evm_db"].append(float(np.mean(evm)))
        if progress:
            progress(s, per, n, err)
        if err == 0 and 1.0 / n < stop_below:
            break
        if err == 0 and n >= max_packets:
            break
    return out


def evm_at(cfg: Mmw60Config, snr_db: float | None, n_packets: int = 3, seed: int | None = None,
           frontend=None) -> dict:
    """Mean EVM over a few packets (any base), the grid's time-domain reading."""
    sim = LinkSim(cfg, frontend=frontend)
    rng = np.random.default_rng(cfg.seed if seed is None else seed)
    rs = [sim.packet(snr_db, rng) for _ in range(n_packets)]
    e = np.array([r.rx.evm_db for r in rs])
    return {"evm_db": float(10 * np.log10(np.mean(10 ** (e / 10)))), "evm_db_packets": e.tolist(),
            "cfo_err_hz": float(np.mean([abs(r.rx.cfo_hat_hz - r.cfo_true_hz) for r in rs])),
            "describe": sim.describe()}


def snr_at_per(sweep: dict, target: float = 1e-2) -> float | None:
    """SNR where the log-PER curve crosses ``target`` (linear interpolation
    in log10 PER between the two bracketing points); None if never reached."""
    s = np.asarray(sweep["snr_db"], dtype=float)
    p = np.asarray(sweep["per"], dtype=float)
    if p.size == 0 or p.min() > target:
        return None
    for i in range(1, p.size):
        if p[i - 1] > target >= p[i]:
            lo = np.log10(max(p[i], 1e-12))
            hi = np.log10(p[i - 1])
            if hi == lo:
                return float(s[i])
            frac = (hi - np.log10(target)) / (hi - lo)
            return float(s[i - 1] + frac * (s[i] - s[i - 1]))
    if p[0] <= target:
        return float(s[0])
    return None
