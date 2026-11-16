"""Single-carrier blocks with a known guard and frequency-domain equalisation.

The block structure of the DMG / EDMG single-carrier PHY, with every
length a parameter (the 802.11ad / ay values are spec numbers,
spec_sources#29):

    stream = [G | d_0 | G | d_1 | … | G | d_{B−1} | G]

``G`` is a known guard sequence of length g, each data part d_b holds
``block − g`` symbols.  The window [d_b | G] that follows a guard is one
FFT block of length ``block``; the guard in front of it equals the guard at
its tail, so it is a cyclic prefix and a channel no longer than g makes the
window a circular convolution — one complex gain per bin.  The tail guard,
known to the receiver, then gives a per-block common phase (the
single-carrier counterpart of OFDM pilots).

An optional per-sample rotation e^{j·r·n} (the π/2-BPSK / π/2-QPSK family
when r = π/2) is applied over the whole stream; ``r·block`` must be a
multiple of 2π, or the guard in front of a window would no longer equal the
one at its tail.

The channel estimate here uses a complementary pair (a, b) of length
``block``, each sent once behind its own cyclic prefix of length g:
|A(f)|² + |B(f)|² = 2·block at every bin, so the pair sounds every bin
equally.  That is the principle of the DMG channel-estimation field, not
its layout (which is a spec number).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ScNumerology:
    block: int             # FFT length of the equaliser: guard + data samples
    guard: int             # guard-interval length (samples at the chip rate)
    fs_hz: float           # chip rate
    rotation_rad: float = 0.0

    def __post_init__(self):
        if not (0 < self.guard < self.block):
            raise ValueError(f"need 0 < guard < block, got guard={self.guard}, block={self.block}")
        if self.fs_hz <= 0:
            raise ValueError("fs_hz must be positive")
        turns = self.rotation_rad * self.block / (2 * np.pi)
        if abs(turns - round(turns)) > 1e-9:
            raise ValueError(f"rotation × block must be a multiple of 2π (got {turns:.6f} turns): "
                             "the guard in front of a window would differ from the one at its tail")

    @property
    def data_per_block(self) -> int:
        return self.block - self.guard

    @property
    def block_duration_s(self) -> float:
        return self.block / self.fs_hz


@dataclass(frozen=True)
class ScFrame:
    samples: np.ndarray        # training (if any) followed by the guarded stream
    numerology: ScNumerology
    guard_seq: np.ndarray
    pair: tuple[np.ndarray, np.ndarray] | None
    n_blocks: int

    @property
    def stream_start(self) -> int:
        """Index of the first guard (the start of the rotated stream)."""
        return 0 if self.pair is None else 2 * (self.numerology.guard + self.numerology.block)


def _rotation(num: ScNumerology, n: np.ndarray) -> np.ndarray:
    return np.exp(1j * num.rotation_rad * n) if num.rotation_rad else np.ones(n.shape, dtype=complex)


def build(symbols: np.ndarray, num: ScNumerology, guard_seq: np.ndarray,
          pair: tuple[np.ndarray, np.ndarray] | None = None) -> ScFrame:
    """The frame for ``symbols`` (a whole number of blocks' worth)."""
    sym = np.asarray(symbols, dtype=complex).reshape(-1)
    g, d = num.guard, num.data_per_block
    guard_seq = np.asarray(guard_seq, dtype=complex)
    if guard_seq.shape != (g,):
        raise ValueError(f"guard sequence must have length {g}")
    if sym.size % d:
        raise ValueError(f"{sym.size} symbols is not a whole number of {d}-symbol blocks")
    n_blocks = sym.size // d
    body = np.concatenate([np.concatenate([guard_seq, sym[i * d:(i + 1) * d]]) for i in range(n_blocks)]
                          + [guard_seq])
    body = body * _rotation(num, np.arange(body.size))
    parts = []
    if pair is not None:
        a, b = (np.asarray(x, dtype=complex) for x in pair)
        if a.shape != (num.block,) or b.shape != (num.block,):
            raise ValueError(f"the training pair must have the block length {num.block}")
        parts = [a[-g:], a, b[-g:], b]
        pair = (a, b)
    return ScFrame(samples=np.concatenate(parts + [body]), numerology=num, guard_seq=guard_seq,
                   pair=pair, n_blocks=n_blocks)


def channel_estimate(rx: np.ndarray, frame: ScFrame) -> np.ndarray:
    """H on the ``block``-point grid from the training pair:
    (Y_a·A* + Y_b·B*) / (|A|² + |B|²)."""
    if frame.pair is None:
        raise ValueError("the frame was built without a training pair")
    num = frame.numerology
    g, n = num.guard, num.block
    a, b = frame.pair
    ya = np.fft.fft(rx[g:g + n])
    yb = np.fft.fft(rx[2 * g + n:2 * g + 2 * n])
    fa, fb = np.fft.fft(a), np.fft.fft(b)
    return (ya * np.conj(fa) + yb * np.conj(fb)) / (np.abs(fa) ** 2 + np.abs(fb) ** 2)


def equalize(rx: np.ndarray, frame: ScFrame, h: np.ndarray, noise_var: float | None = None,
             track_phase: bool = True) -> np.ndarray:
    """Data symbols, shape (n_blocks, data_per_block).

    ``noise_var`` None = zero forcing; otherwise the MMSE equaliser
    H*/(|H|² + σ²) with its bias removed (divided by the mean of
    |H|²/(|H|² + σ²)), σ² being the noise per sample for unit-power
    symbols.  ``track_phase`` rotates each block by the phase of its
    equalised tail guard against the known one."""
    num = frame.numerology
    g, n, d = num.guard, num.block, num.data_per_block
    s0 = frame.stream_start + g
    idx = s0 + np.arange(frame.n_blocks)[:, None] * n + np.arange(n)[None, :]
    y = np.fft.fft(np.asarray(rx)[idx], axis=1)
    h = np.asarray(h, dtype=complex)
    if noise_var is None:
        z = np.fft.ifft(y / h[None, :], axis=1)
    else:
        p = np.abs(h) ** 2
        w = np.conj(h) / (p + float(noise_var))
        z = np.fft.ifft(y * w[None, :], axis=1) / float(np.mean(p / (p + float(noise_var))))
    z = z * np.conj(_rotation(num, idx - frame.stream_start))
    if track_phase:
        ref = frame.guard_seq
        phi = np.angle(z[:, d:] @ np.conj(ref))
        z = z * np.exp(-1j * phi)[:, None]
    return z[:, :d]


__all__ = ["ScNumerology", "ScFrame", "build", "channel_estimate", "equalize"]
