"""The two 802.11ay waveforms through topology B's hardware (milestone 3, EVM only).

``LinkSim(cfg)`` hands a config with ``waveform: ay_ofdm | ay_sc`` to
``AyLinkSim``: the same front-end models, front-end instance, channel,
CFO, phase noise and SNR plumbing as the be links (iron rule 2), with the
EDMG single-channel waveform in place of the wifitrx frame and an ay
receiver in place of the wifitrx one.

The frame, at the waveform's own rate (data/spec: assumed.ay_preamble):

    [ STF: a 128-point Golay sequence × 16 ] [ CEF: Golay pair a, b, each behind a GI ] [ payload ]

* ``ay_sc``: payload = 64 blocks [G | 448 data chips] and a closing G at
  1.76 Gchip/s, π/2-rotated, root-raised-cosine shaped at 3 samples per
  chip (assumed.ay_sc_pulse); the receiver matched-filters, estimates the
  CFO on the STF, the channel on the pair, and equalises in the frequency
  domain block by block, tracking each block's phase on its tail guard;
* ``ay_ofdm``: payload = 64 symbols of the channel's 336 data + 16 pilot
  tones at 2.64 GS/s, interpolated × 2; the receiver decimates, estimates
  the CFO on the STF and the 512-bin channel on the pair, zero-forces and
  removes each symbol's common phase on its pilots.

Both reach the chain at 5.28 GS/s (assumed.ay_chain_rate).  The SNR is in
band: per chip for SC (noise bandwidth = chip rate), per active tone for
OFDM, as for the be links; ``snr_per_sample_offset_db`` says how far that
is from a per-sample SNR at 5.28 GS/s.

Iron rule 3: the CFO is (ppm_tx + ppm_rx) × f_c as everywhere; the ay link
catches it with its own STF — at a lag of 128 samples the estimate spans
±fs / 256 (±6.875 MHz for SC, ±10.3 MHz for OFDM), so the 2.42 MHz of
40 ppm at 60.48 GHz is 35 % / 23 % of the range — and tracks what is left
with the pilots / tail guards.  No MLO pre-compensation.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..ay import edmg, golay, ofdm, papr, sc
from ..channel import make_channel
from ..impairments.cfo import CfoModel
from ..impairments.phase_noise import lo_phase, make_profile
from ..pa.rapp import ModifiedRappPA, apply_pa_at_obo
from ..phy.mapper import map_bits
from ..rx import cfo as cfo_est
from ..rx.receiver import RxResult
from .link import DIGITAL_DRIVE_RMS, LinkSim, PacketResult


def _golay(n: int) -> tuple[np.ndarray, np.ndarray]:
    """The Golay pair of length n by concatenation (delays 2^(K−1) … 1, weights +1; assumed.ay_preamble)."""
    k = int(round(np.log2(n)))
    if 1 << k != n:
        raise ValueError(f"a Golay length must be a power of two, got {n}")
    return golay.golay_pair([1 << i for i in reversed(range(k))], [1] * k)


class AyPhy:
    """What the shared link plumbing reads from ``.phy`` (``fs_eff``,
    ``bandwidth_eff``) plus the ay numerology."""

    def __init__(self, cfg):
        self.waveform = cfg.waveform
        self.channel = edmg.channel_of(cfg.carrier_hz)
        self.gi = cfg.ay.gi
        cr = edmg.chain_rate()
        self.fs_eff = cr["fs_hz"]
        self.bandwidth_eff = edmg.channel_spacing_hz()
        self.mcs = edmg.mcs_entry(cfg.waveform, cfg.ay.mcs)
        if cfg.waveform == "ay_ofdm":
            self.num = edmg.ofdm_numerology(self.channel, self.gi)
            self.native_fs = self.num.fs_hz
            self.up = cr["ofdm_oversampling"]
            self.occupied_bw_hz = len(self.num.used_tones) * self.num.scs_hz
        else:
            self.num = edmg.sc_numerology(self.gi)
            self.native_fs = self.num.fs_hz
            self.up = cr["sc_samples_per_chip"]
            self.occupied_bw_hz = self.num.fs_hz
        if abs(self.native_fs * self.up - self.fs_eff) > 1.0:
            raise ValueError("assumed.ay_chain_rate does not put this waveform on the chain's rate")

    def summary(self) -> dict:
        d = {"waveform": self.waveform, "channel": self.channel, "gi": self.gi, "fs_native_hz": self.native_fs,
             "fs_eff_hz": self.fs_eff, "oversampling": self.up, "bandwidth_eff_hz": self.bandwidth_eff,
             "occupied_bw_hz": self.occupied_bw_hz, "mcs": self.mcs.mcs, "modulation": self.mcs.modulation,
             "evm_limit_db": self.mcs.evm_limit_db, "rate_bps": self.mcs.rate_bps(self.gi)}
        if self.waveform == "ay_ofdm":
            d.update({"n_fft": self.num.n_fft, "cp": self.num.cp, "scs_hz": self.num.scs_hz,
                      "n_data": len(self.num.data_tones), "n_pilot": len(self.num.pilot_tones)})
        else:
            d.update({"block": self.num.block, "guard": self.num.guard, "data_per_block": self.num.data_per_block})
        return d


@dataclass
class AyRef:
    """The transmitted payload and the native-rate frame layout the receiver needs."""
    symbols: np.ndarray          # (units, data per unit) constellation points sent
    n_native: int                # samples of the frame at the waveform's own rate
    stf_len: int
    cef_len: int
    sc_frame: sc.ScFrame | None = None


@dataclass
class AyFrame:
    x: np.ndarray                # at the chain rate, unit average power


class AyLinkSim(LinkSim):
    """``chains``: a (tx, rx) pair built elsewhere — the chains wifitrx's
    sequence calibrated (``calcheck.run_cal_ay``, iron rule 4) — used in
    place of fresh ones; the PA is trimmed to the back-off on this waveform
    either way."""

    def __init__(self, cfg, frontend=None, chains=None):
        self.cfg = cfg
        self.topology_a = False
        self.coded = False
        self.ldpc = False
        self.phy = AyPhy(cfg)
        self.mcs = self.phy.mcs
        self.n_symbols = int(cfg.ay.units)
        self.cfo = CfoModel(cfg.carrier_hz, cfg.xo_ppm_tx, cfg.xo_ppm_rx)
        pn = cfg.lo.phase_noise
        self.pn_profile = make_profile(pn, cfg.lo_hz)
        self.pn_sides = pn.apply if pn.enabled else "off"
        self.channel = make_channel(cfg.channel.model, cfg.channel.rms_delay_ns, cfg.channel.los_k_db,
                                    cfg.channel.taps)
        self.occupied_bw_hz = self.phy.occupied_bw_hz
        self.snr_offset_db = 10.0 * np.log10(self.phy.fs_eff / self.occupied_bw_hz)
        a = cfg.ay
        self.stf_seq = _golay(int(a.stf_length))[0]
        if cfg.waveform == "ay_sc":
            n = self.phy.num.block
            self.cef_cp = self.phy.num.guard
            self.guard_seq = _golay(self.phy.num.guard)[0]
            self.taps = papr.rrc_taps(self.phy.up, float(a.sc_rolloff), int(a.sc_span_symbols))
        else:
            n = self.phy.num.n_fft
            self.cef_cp = self.phy.num.cp
        self.pair = _golay(n)
        self.model = cfg.frontend.model
        self.pa = None
        self.frontend = None
        self.ifx = None
        self.calibrated = False
        if self.model == "behavioural":
            if chains is not None:
                raise ValueError("calibrated chains need frontend.model zero_if_chain")
            self.pa = (ModifiedRappPA(ampm=cfg.frontend.pa.ampm, p=cfg.frontend.pa.rapp_p)
                       if cfg.frontend.pa.enabled else None)
        else:
            from ..frontend import Frontend60
            self.frontend = frontend if frontend is not None else Frontend60.from_config(cfg)
            if chains is not None:
                self.tx, self.rx = chains
                if (self.tx.fs, self.tx.params.bandwidth_hz) != (self.phy.fs_eff, self.phy.bandwidth_eff):
                    raise ValueError("the chains were not built for this ay chain's rate and bandwidth")
            else:
                self.tx, self.rx = self.frontend.build_chains(self.phy.bandwidth_eff, self.phy.fs_eff)
            self.calibrated = chains is not None
            _, frame0 = self.transmit(np.random.default_rng(cfg.seed))
            self.pout_dbm = self.frontend.set_vga_for_obo(self.tx, frame0.x * DIGITAL_DRIVE_RMS)

    # --- transmitter ----------------------------------------------------
    def _stf(self) -> np.ndarray:
        return golay.repeated(self.stf_seq, int(self.cfg.ay.stf_repeats)).astype(complex)

    def _cef(self) -> np.ndarray:
        a, b = (np.asarray(v, dtype=complex) for v in self.pair)
        cp = self.cef_cp
        return np.concatenate([a[-cp:], a, b[-cp:], b])

    def transmit(self, rng: np.random.Generator, bits: np.ndarray | None = None):
        """``bits``: the payload's bits (SC only; ``ay.coding`` hands the codewords in), one block's worth
        per unit; None = random bits, the EVM-only payload."""
        m = self.mcs
        stf = self._stf()
        if bits is not None and self.cfg.waveform != "ay_sc":
            raise NotImplementedError("a coded OFDM payload (DCM, tone mapping) is not built: SC only")
        if self.cfg.waveform == "ay_sc":
            num = self.phy.num
            n_sym = num.data_per_block * self.n_symbols
            n_bits = n_sym * int(np.log2(m.order))
            if bits is None:
                bits = rng.integers(0, 2, n_bits)
            elif np.asarray(bits).size != n_bits:
                raise ValueError(f"the SC payload carries {n_bits} bits, got {np.asarray(bits).size}")
            syms = map_bits(np.asarray(bits), m.order)
            frm = sc.build(syms, num, self.guard_seq, self.pair)        # [CEF | G d G d … G]
            native = np.concatenate([stf, frm.samples])
            x = papr.shape(native, self.phy.up, self.taps)
            ref = AyRef(symbols=syms.reshape(self.n_symbols, -1), n_native=native.size, stf_len=stf.size,
                        cef_len=2 * (num.guard + num.block), sc_frame=frm)
        else:
            num = self.phy.num
            n_tone = len(num.data_tones) * self.n_symbols
            syms = map_bits(rng.integers(0, 2, n_tone * int(np.log2(m.tone_order))), m.tone_order)
            syms = syms.reshape(self.n_symbols, -1)
            payload = ofdm.modulate(num, syms, None, n_training=0)
            cef = self._cef()
            native = np.concatenate([stf, cef, payload])
            x = papr.interpolate(native, self.phy.up)
            ref = AyRef(symbols=syms, n_native=native.size, stf_len=stf.size, cef_len=cef.size)
        return ref, AyFrame(x=x / np.sqrt(np.mean(np.abs(x) ** 2)))

    # --- the air: behavioural ---------------------------------------------
    def _impair_behavioural(self, x: np.ndarray, rng: np.random.Generator, snr_db: float | None):
        fs = self.phy.fs_eff
        pa_info = {}
        if self.pa is not None:
            x, pa_info = apply_pa_at_obo(self.pa, x, self.cfg.frontend.pa.obo_db, self.cfg.frontend.pa.obo_reference)
        if self.pn_sides in ("tx", "both"):
            x = x * np.exp(1j * lo_phase(self.pn_profile, x.size, fs, rng))
        x, taps = self.channel.apply(x, fs, rng)
        x = self.cfo.apply(x, fs)
        if self.pn_sides in ("rx", "both"):
            x = x * np.exp(1j * lo_phase(self.pn_profile, x.size, fs, rng))
        if snr_db is not None:
            # in-band SNR: noise density from the occupied bandwidth, spread over fs
            p_sig = float(np.mean(np.abs(x) ** 2))
            sigma2 = p_sig * (fs / self.occupied_bw_hz) / 10.0 ** (snr_db / 10.0)
            x = x + np.sqrt(sigma2 / 2) * (rng.standard_normal(x.size) + 1j * rng.standard_normal(x.size))
        return x, taps, pa_info

    # --- receiver -----------------------------------------------------------
    def receive(self, y: np.ndarray, ref: AyRef, snr_db: float | None, keep_symbols: bool = False) -> RxResult:
        rxc = self.cfg.rx
        if self.cfg.waveform == "ay_sc":
            r = papr.matched(y, self.phy.up, self.taps, ref.n_native)
        else:
            r = papr.decimate(y[:ref.n_native * self.phy.up], self.phy.up)
        fs = self.phy.native_fs
        f_stf = 0.0
        if rxc.cfo_estimation != "off":
            f_stf = cfo_est.stf_coarse_cfo(r, int(self.cfg.ay.stf_length), int(self.cfg.ay.stf_repeats), fs)
            r = cfo_est.correct(r, f_stf, fs)
        body = r[ref.stf_len:]
        cp = self.cef_cp
        if self.cfg.waveform == "ay_sc":
            h = sc.channel_estimate(body, ref.sc_frame)
            if self.cfg.ay.ce_window:
                h = sc.window_estimate(h, cp, max(4, cp // 8))
            # the in-band SNR is the received signal over the noise, and the estimate carries the
            # chain's gain: the noise per chip on the estimate's own scale is mean|h|² / SNR.  (Until
            # 2026-11-16 it was 1 / SNR: harmless on a flat channel, where the MMSE only rescales and
            # the bias removal undoes it, but 16 times too much regularisation under multipath.)
            nv = (None if snr_db is None or self.cfg.ay.sc_equalizer == "zf"
                  else float(np.mean(np.abs(h) ** 2)) * 10.0 ** (-snr_db / 10.0))
            eq = sc.equalize(body, ref.sc_frame, h, noise_var=nv,
                             track_phase=self.cfg.ay.sc_phase if rxc.cpe_tracking else "off")
        else:
            num = self.phy.num
            a, b = self.pair
            h512 = sc.pair_estimate(body, a, b, cp)
            if self.cfg.ay.ce_window:
                h512 = sc.window_estimate(h512, cp, max(4, cp // 8))
            h_used = h512[num.bins(num.used_tones)]
            eq = ofdm.receive(num, body[ref.cef_len:], None, self.n_symbols, n_training=0,
                              cpe=rxc.cpe_tracking, h=h_used)
        tx = ref.symbols
        evm_db = float(10 * np.log10(np.mean(np.abs(eq - tx) ** 2) / np.mean(np.abs(tx) ** 2)))
        return RxResult(bit_errors=None, packet_error=None, evm_db=evm_db, cfo_hat_hz=float(f_stf),
                        cfo_stf_hz=float(f_stf), cfo_ltf_hz=0.0, cfo_integer_tones=0,
                        eq_symbols=eq if keep_symbols else None, ce_span=0)

    def packet(self, snr_db: float | None, rng: np.random.Generator, keep_symbols: bool = False,
               kernel: str | None = None) -> PacketResult:
        ref, frame = self.transmit(rng)
        y, taps, pa_info = self.impair(frame.x, rng, snr_db)
        res = self.receive(y, ref, snr_db, keep_symbols)
        return PacketResult(rx=res, snr_db=float("nan") if snr_db is None else snr_db,
                            cfo_true_hz=self.cfo.cfo_hz, pa_info=pa_info, taps=taps)

    def describe(self) -> dict:
        d = self.phy.summary()
        d.update({"coded": False, "n_units": self.n_symbols, "cfo_hz": self.cfo.cfo_hz,
                  "cfo_range_hz": self.phy.native_fs / (2 * int(self.cfg.ay.stf_length)),
                  "pn": self.pn_sides,
                  "pa": self.cfg.frontend.pa.model if self.cfg.frontend.pa.enabled else "ideal",
                  "pa_obo_db": self.cfg.frontend.pa.obo_db if self.cfg.frontend.pa.enabled else None,
                  "channel": self.channel.name, "cfo_estimation": "off" if self.cfg.rx.cfo_estimation == "off"
                  else "stf", "snr_per_sample_offset_db": self.snr_offset_db, "frontend_model": self.model})
        if self.frontend is not None:
            d["frontend"] = self.frontend.describe(self.phy.fs_eff)
            d["frontend"]["pout_dbm_set"] = self.pout_dbm
            d["calibrated"] = self.calibrated
        return d


__all__ = ["AyPhy", "AyRef", "AyFrame", "AyLinkSim"]
