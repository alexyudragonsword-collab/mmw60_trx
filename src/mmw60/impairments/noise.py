"""AWGN at an in-band, per-active-subcarrier Es/N0 (data/spec: assumed.snr_definition).

wifitrx's ``awgn_snr`` defines SNR per sample over the whole simulated
band ``fs``.  With an oversampled N-point OFDM signal occupying
``n_active`` bins out of ``os·N``, the per-tone SNR is higher by
``os·N / n_active``; the offset is reported alongside every curve so a
reader using the other convention can shift the axis.
"""
from __future__ import annotations

import numpy as np

from ..vendor.wifitrx.impairments.noise import awgn_snr


def per_sample_snr_offset_db(fft_size: int, oversampling: int, n_active: int) -> float:
    """SNR_per_tone − SNR_per_sample in dB (positive)."""
    return 10.0 * np.log10(fft_size * oversampling / n_active)


def add_awgn_per_tone(x: np.ndarray, snr_tone_db: float, fft_size: int, oversampling: int,
                      n_active: int, rng: np.random.Generator) -> tuple[np.ndarray, float]:
    """Add noise so the in-band per-tone Es/N0 is ``snr_tone_db``; returns
    (y, noise variance per sample) — the variance is what the LLR weights use."""
    off = per_sample_snr_offset_db(fft_size, oversampling, n_active)
    snr_sample_db = snr_tone_db - off
    p_sig = float(np.mean(np.abs(x) ** 2))
    sigma2 = p_sig / 10.0 ** (snr_sample_db / 10.0)
    return awgn_snr(x, snr_sample_db, rng), sigma2
