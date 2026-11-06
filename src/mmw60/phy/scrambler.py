"""802.11 data scrambler, S(x) = x^7 + x^4 + 1 (self-synchronising LFSR as a sequence)."""
from __future__ import annotations

import numpy as np

DEFAULT_SEED = 93      # 0b1011101 — the MATLAB default (data/spec: assumed.scrambler_seed)


def scrambling_sequence(n: int, seed: int = DEFAULT_SEED) -> np.ndarray:
    """First ``n`` bits of the 127-periodic sequence for a 7-bit ``seed``."""
    if not 1 <= int(seed) <= 127:
        raise ValueError("scrambler seed must be a non-zero 7-bit value")
    state = int(seed)
    period = np.empty(127, dtype=np.uint8)
    for i in range(127):
        fb = ((state >> 6) ^ (state >> 3)) & 1
        period[i] = fb
        state = ((state << 1) | fb) & 0x7F
    reps = -(-n // 127)
    return np.tile(period, reps)[:n]


def scramble(bits: np.ndarray, seed: int = DEFAULT_SEED) -> np.ndarray:
    bits = np.asarray(bits, dtype=np.uint8)
    return bits ^ scrambling_sequence(bits.size, seed)


descramble = scramble   # XOR with the same sequence
