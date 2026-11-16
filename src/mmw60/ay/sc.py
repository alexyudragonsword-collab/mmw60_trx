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


def pair_estimate(rx: np.ndarray, a: np.ndarray, b: np.ndarray, cp: int, start: int = 0) -> np.ndarray:
    """H on the len(a)-point grid from a complementary pair sent as
    [a[-cp:] | a | b[-cp:] | b] from ``start``: (Y_a·A* + Y_b·B*) / (|A|² + |B|²).
    The OFDM link uses it with the DFT length and its cyclic prefix."""
    n = len(a)
    s = int(start)
    ya = np.fft.fft(rx[s + cp:s + cp + n])
    yb = np.fft.fft(rx[s + 2 * cp + n:s + 2 * cp + 2 * n])
    fa, fb = np.fft.fft(a), np.fft.fft(b)
    return (ya * np.conj(fa) + yb * np.conj(fb)) / (np.abs(fa) ** 2 + np.abs(fb) ** 2)


def window_estimate(h: np.ndarray, keep: int, pre: int = 0) -> np.ndarray:
    """``h`` with its impulse response kept on the first ``keep`` taps and the
    last ``pre`` (a pre-cursor from a timing offset): a channel no longer than
    the guard loses nothing, and the estimate's noise drops by len(h) / (keep + pre)."""
    t = np.fft.ifft(np.asarray(h, dtype=complex))
    w = np.zeros(t.size)
    w[:int(keep)] = 1.0
    if pre:
        w[-int(pre):] = 1.0
    return np.fft.fft(t * w)


def channel_estimate(rx: np.ndarray, frame: ScFrame) -> np.ndarray:
    """H on the ``block``-point grid from the frame's training pair."""
    if frame.pair is None:
        raise ValueError("the frame was built without a training pair")
    a, b = frame.pair
    return pair_estimate(rx, a, b, frame.numerology.guard)


def equalize(rx: np.ndarray, frame: ScFrame, h: np.ndarray, noise_var: float | None = None,
             track_phase: bool | str = True) -> np.ndarray:
    """Data symbols, shape (n_blocks, data_per_block).

    ``noise_var`` None = zero forcing; otherwise the MMSE equaliser
    H*/(|H|² + σ²) with its bias removed (divided by the mean of
    |H|²/(|H|² + σ²)), σ² being the noise per sample for unit-power
    symbols.  ``track_phase``: True / ``"block"`` rotates each block by the
    phase of its equalised tail guard against the known one; ``"interp"``
    interpolates the phase linearly between the guard before the block (the
    previous block's tail; the first block's own tail for the first) and the
    guard after it — a phase that drifts within the block is followed, not
    averaged; False / ``"off"`` does neither."""
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
    mode = {True: "block", False: "off"}.get(track_phase, track_phase)
    if mode not in ("block", "interp", "off"):
        raise ValueError("track_phase must be True / False / 'block' / 'interp' / 'off'")
    if mode != "off":
        ref = frame.guard_seq
        phi = np.unwrap(np.angle(z[:, d:] @ np.conj(ref)))           # the guard after each block
        if mode == "block":
            z = z * np.exp(-1j * phi)[:, None]
        else:
            before = np.concatenate([phi[:1], phi[:-1]])             # the guard in front of each block
            # guard centres: −g/2 (in front) and d + g/2 (after), relative to the window start
            t = (np.arange(n) + 0.5 * g) / (d + g)
            ph = before[:, None] + (phi - before)[:, None] * t[None, :]
            z = z * np.exp(-1j * ph)
    return z[:, :d]


__all__ = ["ScNumerology", "ScFrame", "build", "pair_estimate", "window_estimate", "channel_estimate", "equalize"]
