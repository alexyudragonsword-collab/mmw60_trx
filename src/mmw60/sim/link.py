"""One packet through TX → impairments → channel → RX, and the PER sweep.

Topology B (``upclock_zero_if``) in milestone 0: the wifitrx frame at the
base numerology, then at ``fs_eff``: Rapp PA at OBO → TX LO phase noise →
channel → CFO (ppm × f_c) → RX LO phase noise → AWGN at the in-band per-tone
SNR → the composed receiver.  Topology A raises ``NotImplementedError``
until milestone 1; the config already names it (iron rule 1).
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
from ..rx.receiver import RxResult, receive
from ..vendor.wifitrx.waveform.ofdm import generate_ofdm
from ..vendor.wifitrx.waveform.pilots import pilot_positions, pilot_sequence
from ..vendor.wifitrx.waveform.preamble import build_frame


@dataclass
class PacketResult:
    rx: RxResult
    snr_db: float
    cfo_true_hz: float
    pa_info: dict
    taps: np.ndarray


class LinkSim:
    """Everything that does not change from packet to packet, built once."""

    def __init__(self, cfg: Mmw60Config):
        if cfg.topology != "upclock_zero_if":
            raise NotImplementedError(f"topology {cfg.topology!r}: milestone 1")
        self.cfg = cfg
        self.mcs = vht_mcs(cfg.phy.mcs)
        self.n_symbols = self.mcs.n_symbols(cfg.phy.packet_bytes)
        self.phy = cfg.upclocked(self.n_symbols)
        self.base = self.phy.base
        self.pilot_cols = pilot_positions(self.base)
        self.n_active = self.base.n_active
        self.pilots = pilot_sequence(self.n_symbols, self.pilot_cols.size, cfg.phy.pilot_seed)
        self.cfo = CfoModel(cfg.carrier_hz, cfg.xo_ppm_tx, cfg.xo_ppm_rx)
        pn = cfg.lo.phase_noise
        self.pn_profile = (PoleZeroPhase(psd0_dbchz=pn.psd0_dbchz, f_pole_hz=pn.f_pole_hz,
                                         f_zero_hz=pn.f_zero_hz) if pn.enabled else None)
        self.pn_sides = pn.apply if pn.enabled else "off"
        self.pa = ModifiedRappPA(ampm=cfg.frontend.pa.ampm) if cfg.frontend.pa.enabled else None
        self.channel = make_channel(cfg.channel.model, cfg.channel.rms_delay_ns,
                                    cfg.channel.los_k_db, cfg.channel.taps)
        self.snr_offset_db = per_sample_snr_offset_db(self.base.fft_size, self.base.oversampling,
                                                      self.n_active)

    # --- transmitter ----------------------------------------------------
    def transmit(self, rng: np.random.Generator):
        psdu = random_psdu(self.cfg.phy.packet_bytes, rng)
        field = build_data_field(self.mcs, psdu, self.n_active, self.pilot_cols, self.pilots,
                                 self.cfg.phy.scrambler_seed)
        wf = generate_ofdm(self.base, symbols=field.symbols)
        frame = build_frame(self.base, data=wf, stf_periods=self.cfg.phy.stf_periods)
        return field, frame

    # --- the air -------------------------------------------------------
    def impair(self, x: np.ndarray, rng: np.random.Generator, snr_db: float | None):
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

    # --- one packet ----------------------------------------------------
    def packet(self, snr_db: float | None, rng: np.random.Generator,
               keep_symbols: bool = False, kernel: str | None = None) -> PacketResult:
        field, frame = self.transmit(rng)
        y, taps, pa_info = self.impair(frame.x, rng, snr_db)
        true_h = None
        if self.cfg.rx.genie_csi:
            tones = self.base.active_tone_indices() * self.phy.scs_eff
            delays = np.arange(np.asarray(taps).size) / self.phy.fs_eff
            true_h = np.exp(-2j * np.pi * np.outer(tones, delays)) @ np.asarray(taps)
        res = receive(y, frame, field, self.phy, self.cfg.rx, keep_symbols, kernel, true_h)
        return PacketResult(rx=res, snr_db=float("nan") if snr_db is None else snr_db,
                            cfo_true_hz=self.cfo.cfo_hz, pa_info=pa_info, taps=taps)

    def describe(self) -> dict:
        d = self.phy.summary()
        d.update({"mcs": self.mcs.index, "n_symbols": self.n_symbols,
                  "cfo_hz": self.cfo.cfo_hz, "cfo_subcarriers": self.cfo.in_subcarriers(self.phy.scs_eff),
                  "pn": self.pn_sides, "pa": self.cfg.frontend.pa.model if self.pa else "ideal",
                  "pa_obo_db": self.cfg.frontend.pa.obo_db if self.pa else None,
                  "pa_obo_reference": self.cfg.frontend.pa.obo_reference if self.pa else None,
                  "channel_rms_delay_ns": (self.cfg.channel.rms_delay_ns
                                           if self.cfg.channel.model == "tdl_exp" else 0.0),
                  "channel": self.channel.name, "cfo_estimation": self.cfg.rx.cfo_estimation,
                  "snr_per_sample_offset_db": self.snr_offset_db})
        return d


# ------------------------------------------------------------------ sweep
def per_sweep(cfg: Mmw60Config, snr_db: list[float], max_packets: int = 400,
              min_errors: int = 20, stop_below: float = 1e-3, seed: int | None = None,
              progress=None) -> dict:
    """PER at each SNR (ascending).  Each point stops at ``min_errors`` packet
    errors or ``max_packets``; the sweep stops once a point's PER is below
    ``stop_below`` with zero errors (the curve is past the target)."""
    sim = LinkSim(cfg)
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
