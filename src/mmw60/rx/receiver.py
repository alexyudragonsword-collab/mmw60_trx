"""Composed receiver: genie timing → CFO (per ``RxConfig.cfo_estimation``) →
L-LTF channel estimate → zero-forcing → per-symbol pilot CPE → LLR → decode.

The order and the functions are wifitrx's ``cal/sequence.score_views``
(``estimate_cfo`` / ``channel_estimate`` / ``smooth_channel_estimate`` /
``demodulate_ofdm`` / ``correct_cpe_pilots``); what is added is the STF
coarse step, the extended-range step and the decoder.  ``"off"`` is the
literal reading of Liu 2025 §V-A (no CFO estimation, pilots only).

``ref`` is anything with ``symbols`` (the transmitted constellation, pilots
included), ``data_cols``, ``pilot_cols`` and ``pilots``: a ``DataField``
(coded VHT 20 MHz, decoded to a PER) or a ``TxRef`` (any other base, EVM
only — ``bit_errors`` is then None).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..config import RxConfig
from ..phy.ppdu import DataField, decode_data_field
from ..upclock import UpclockedPhy
from ..vendor.wifitrx.metrics.cpe import correct_cpe_pilots
from ..vendor.wifitrx.waveform.ofdm import demodulate_ofdm
from ..vendor.wifitrx.waveform.preamble import (Frame, channel_estimate,
                                                smooth_channel_estimate)
from . import cfo as cfo_est


@dataclass(frozen=True)
class TxRef:
    """What the receiver needs to score an uncoded (EVM-only) frame."""
    symbols: np.ndarray
    data_cols: np.ndarray
    pilot_cols: np.ndarray
    pilots: np.ndarray


@dataclass
class RxResult:
    bit_errors: int | None
    packet_error: bool | None
    evm_db: float
    cfo_hat_hz: float
    cfo_stf_hz: float
    cfo_ltf_hz: float
    cfo_integer_tones: int
    eq_symbols: np.ndarray | None = None


def receive(y: np.ndarray, frame: Frame, ref, phy: UpclockedPhy,
            rxc: RxConfig, keep_symbols: bool = False, kernel: str | None = None,
            true_h: np.ndarray | None = None) -> RxResult:
    fs = phy.fs_eff
    y = np.asarray(y, dtype=complex)
    f_stf = f_ltf = 0.0
    m_int = 0
    mode = rxc.cfo_estimation
    if mode == "stf_ltf":
        f_stf = cfo_est.stf_coarse_cfo(y, phy.stf_period_samples, frame.stf_len // phy.stf_period_samples,
                                       fs)
        y = cfo_est.correct(y, f_stf, fs)
    if mode in ("ltf", "stf_ltf", "extended"):
        f_ltf = cfo_est.ltf_fine_cfo(y, frame, fs)
        y = cfo_est.correct(y, f_ltf, fs)
    if mode == "extended":
        m_int = cfo_est.ltf_integer_cfo(y, frame, rxc.extended_max_subcarriers)
        if m_int:
            y = cfo_est.correct(y, m_int * phy.scs_eff, fs)
    cfo_hat = f_stf + f_ltf + m_int * phy.scs_eff

    if rxc.genie_csi:
        if true_h is None:
            raise ValueError("genie_csi needs the true per-tone channel")
        h = np.asarray(true_h, dtype=complex)
    else:
        h = channel_estimate(y, frame)
        if rxc.ce_smooth_tones > 1:
            h = smooth_channel_estimate(h, rxc.ce_smooth_tones,
                                        frame.config.plan().segments())
    raw = demodulate_ofdm(y[frame.preamble_len:], frame.data)
    eq = raw / h[None, :]
    if rxc.cpe_tracking:
        eq = correct_cpe_pilots(eq, ref.pilot_cols, ref.pilots)
    tx = ref.symbols[:, ref.data_cols]
    rx_d = eq[:, ref.data_cols]
    evm_db = float(10 * np.log10(np.mean(np.abs(rx_d - tx) ** 2) / np.mean(np.abs(tx) ** 2)))
    errors = None
    if isinstance(ref, DataField):
        weight = np.abs(h[ref.data_cols]) ** 2
        _, errors = decode_data_field(eq, ref, weight, kernel=kernel)
    return RxResult(bit_errors=errors, packet_error=None if errors is None else errors > 0,
                    evm_db=evm_db, cfo_hat_hz=float(cfo_hat), cfo_stf_hz=float(f_stf),
                    cfo_ltf_hz=float(f_ltf), cfo_integer_tones=int(m_int),
                    eq_symbols=eq if keep_symbols else None)
