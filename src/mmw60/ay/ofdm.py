"""OFDM on an arbitrary tone plan.

wifitrx's OFDM generator looks its pilot and tone tables up by bandwidth and
subcarrier spacing (the 802.11 ones only), so the EDMG OFDM plan cannot go
through it; this module takes the plan as data: FFT size, cyclic prefix,
sample rate, the signed indices of the data and pilot tones and the pilot
values.  The EDMG numbers (spec_sources#29) become one instance of
:class:`OfdmNumerology`.

Frame: ``n_training`` known training symbols (all used tones) then the data
symbols, each behind its cyclic prefix.  The receiver averages the
training symbols into a per-tone channel estimate, zero-forces, and removes
each symbol's common phase with its pilots.  Unit average power per used
tone gives unit average power per sample.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class OfdmNumerology:
    n_fft: int
    cp: int
    fs_hz: float
    data_tones: tuple[int, ...]
    pilot_tones: tuple[int, ...] = ()
    pilot_values: tuple[complex, ...] = ()       # empty = all ones

    def __post_init__(self):
        half = self.n_fft // 2
        tones = list(self.data_tones) + list(self.pilot_tones)
        if not self.data_tones:
            raise ValueError("no data tones")
        if len(set(tones)) != len(tones):
            raise ValueError("a tone is listed twice (data and pilot sets must be disjoint)")
        if any(not (-half <= k < half) for k in tones):
            raise ValueError(f"tone indices must lie in [−{half}, {half})")
        if not (0 <= self.cp < self.n_fft):
            raise ValueError("need 0 ≤ cp < n_fft")
        if self.pilot_values and len(self.pilot_values) != len(self.pilot_tones):
            raise ValueError("one pilot value per pilot tone")

    @property
    def scs_hz(self) -> float:
        return self.fs_hz / self.n_fft

    @property
    def used_tones(self) -> np.ndarray:
        return np.array(sorted(list(self.data_tones) + list(self.pilot_tones)))

    @property
    def occupied_bandwidth_hz(self) -> float:
        u = self.used_tones
        return float(u[-1] - u[0] + 1) * self.scs_hz

    @property
    def symbol_samples(self) -> int:
        return self.n_fft + self.cp

    def pilots(self) -> np.ndarray:
        return (np.asarray(self.pilot_values, dtype=complex) if self.pilot_values
                else np.ones(len(self.pilot_tones), dtype=complex))

    def bins(self, tones) -> np.ndarray:
        return np.asarray(tones, dtype=int) % self.n_fft


def _symbols_to_time(num: OfdmNumerology, freq: np.ndarray) -> np.ndarray:
    """(n, n_fft) bin values → (n, n_fft + cp) time samples, unit power per used tone → per sample."""
    scale = num.n_fft / np.sqrt(len(num.used_tones))
    t = np.fft.ifft(freq, axis=1) * scale
    return np.concatenate([t[:, num.n_fft - num.cp:], t], axis=1) if num.cp else t


def modulate(num: OfdmNumerology, data: np.ndarray, training: np.ndarray | None, n_training: int = 2) -> np.ndarray:
    """``data`` (n_sym, n_data) on the data tones, pilots on the pilot tones,
    behind ``n_training`` copies of ``training`` (one value per used tone,
    in ``used_tones`` order)."""
    data = np.asarray(data, dtype=complex)
    if data.ndim != 2 or data.shape[1] != len(num.data_tones):
        raise ValueError(f"data must be (n_symbols, {len(num.data_tones)})")
    if training is None and n_training == 0:
        training = np.ones(len(num.used_tones))         # no training field: the values are never sent
    training = np.asarray(training, dtype=complex)
    if training.shape != (len(num.used_tones),):
        raise ValueError(f"training must have one value per used tone ({len(num.used_tones)})")
    f_tr = np.zeros((n_training, num.n_fft), dtype=complex)
    f_tr[:, num.bins(num.used_tones)] = training
    f = np.zeros((data.shape[0], num.n_fft), dtype=complex)
    f[:, num.bins(num.data_tones)] = data
    if num.pilot_tones:
        f[:, num.bins(num.pilot_tones)] = num.pilots()
    return np.concatenate([_symbols_to_time(num, f_tr), _symbols_to_time(num, f)]).reshape(-1)


def _time_to_bins(num: OfdmNumerology, rx: np.ndarray, first: int, count: int) -> np.ndarray:
    n_s = num.symbol_samples
    idx = (first + np.arange(count))[:, None] * n_s + num.cp + np.arange(num.n_fft)[None, :]
    return np.fft.fft(np.asarray(rx)[idx], axis=1) * np.sqrt(len(num.used_tones)) / num.n_fft


def receive(num: OfdmNumerology, rx: np.ndarray, training: np.ndarray | None, n_symbols: int,
            n_training: int = 2, cpe: bool = True, h: np.ndarray | None = None,
            cpe_window: int = 1) -> np.ndarray:
    """Equalised data-tone values, shape (n_symbols, n_data).

    ``cpe_window`` > 1 combines each symbol's pilot phase with its
    neighbours' over that many symbols (``rx.tracking.smoothed_cpe``, the
    be rows' receiver refinement C1, used as it is); 1 is the per-symbol
    pilot phase.

    ``h`` (one value per used tone) replaces the training-symbol estimate:
    the isolation reading of a PA, where the training field's own peaks
    going through the PA would otherwise colour the estimate (with ±1
    training on 169 tones the back-off for −20 dB EVM moved 1.5 dB with the
    training seed; all-ones training is an impulse of PAPR = n_used)."""
    if h is None:
        tr = _time_to_bins(num, rx, 0, n_training)[:, num.bins(num.used_tones)]
        h_used = tr.mean(axis=0) / np.asarray(training, dtype=complex)
    else:
        h_used = np.asarray(h, dtype=complex)
        if h_used.shape != (len(num.used_tones),):
            raise ValueError(f"h must have one value per used tone ({len(num.used_tones)})")
    pos = {k: i for i, k in enumerate(num.used_tones)}
    y = _time_to_bins(num, rx, n_training, n_symbols)
    z = y[:, num.bins(num.data_tones)] / h_used[[pos[k] for k in num.data_tones]][None, :]
    if cpe and num.pilot_tones:
        zp = y[:, num.bins(num.pilot_tones)] / h_used[[pos[k] for k in num.pilot_tones]][None, :]
        if int(cpe_window) > 1:
            from ..rx.tracking import smoothed_cpe
            n_d = z.shape[1]
            both = smoothed_cpe(np.concatenate([z, zp], axis=1), np.arange(n_d, n_d + zp.shape[1]),
                                np.tile(num.pilots(), (z.shape[0], 1)), int(cpe_window))
            return both[:, :n_d]
        phi = np.angle(zp @ np.conj(num.pilots()))
        z = z * np.exp(-1j * phi)[:, None]
    return z


__all__ = ["OfdmNumerology", "modulate", "receive"]
