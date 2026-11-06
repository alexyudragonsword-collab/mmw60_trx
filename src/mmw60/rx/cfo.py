"""CFO estimators (cairn/upclocking.md derives the capture ranges).

* ``stf_coarse_cfo`` — autocorrelation at the L-STF period (0.8 µs / K):
  unambiguous ±1/(2·T_stf) = ±625 kHz × K.  wifitrx only uses its STF as an
  AGC stimulus; this is the estimator Liu 2025's "4.7" argument assumes.
* ``ltf_fine_cfo`` — wifitrx's two-repeat L-LTF estimate, ±SCS/2.
* ``ltf_integer_cfo`` — the integer-subcarrier ambiguity of the LTF
  estimate resolved by a differential frequency-domain correlation of the
  received LTF spectrum with the known sequence over shifts of ±M tones
  (example 01: what a receiver that is allowed to be smarter than the
  standard preamble processing can do at K = 4).
"""
from __future__ import annotations

import numpy as np

from ..vendor.wifitrx.waveform.preamble import Frame, apply_cfo, estimate_cfo


def stf_coarse_cfo(rx: np.ndarray, period: int, n_periods: int, fs: float,
                   skip_periods: int = 1) -> float:
    """CFO [Hz] from the phase of Σ conj(r[n])·r[n+P] over the STF, skipping
    the first ``skip_periods`` periods (channel transient)."""
    start = skip_periods * period
    stop = n_periods * period - period
    if stop <= start:
        raise ValueError("not enough STF periods for the estimate")
    r1 = rx[start:stop]
    r2 = rx[start + period:stop + period]
    acc = np.vdot(r1, r2)
    return float(np.angle(acc) / (2 * np.pi * period / fs))


def ltf_fine_cfo(rx: np.ndarray, frame: Frame, fs: float) -> float:
    return estimate_cfo(rx, frame, fs)


def ltf_integer_cfo(rx: np.ndarray, frame: Frame, max_shift: int) -> int:
    """Integer-tone part of the CFO left after the fractional LTF estimate:
    argmax over m of |Σ_k S[t_k + m]·conj(L_k) · conj(S[t_{k+1} + m]·conj(L_{k+1}))|,
    the differential correlation (robust to a frequency-selective channel)."""
    s1, s2 = frame.ltf_starts()
    n = frame.ltf_len
    avg = 0.5 * (rx[s1:s1 + n] + rx[s2:s2 + n])
    spec_rx = np.fft.fft(avg)
    tones = frame.config.active_tone_indices()
    ltf = frame.ltf
    best, best_m = -1.0, 0
    for m in range(-max_shift, max_shift + 1):
        z = spec_rx[(tones + m) % n] * np.conj(ltf)
        metric = abs(np.sum(z[:-1] * np.conj(z[1:])))
        if metric > best:
            best, best_m = metric, m
    return best_m


def correct(rx: np.ndarray, cfo_hz: float, fs: float) -> np.ndarray:
    return apply_cfo(rx, -cfo_hz, fs)
