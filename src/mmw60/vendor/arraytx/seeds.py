# Vendored from array_tx@5815c5a7ea43143fd58502d4894ac840b5b5fb86: src/arraytx/seeds.py
# Adapted-copy policy: see src/mmw60/vendor/__init__.py
"""Seed derivation: one ``seed`` in the config, one independent stream per
element per impairment (invariant 5).

polar_tx's own random draws are positional on shared generators (its DTC
jitter and LO phase noise share one rng, its Monte Carlo draws in order), so
flipping one switch there shifts every later draw.  array_tx does not reach
into those; at the array layer every random quantity gets a stream of its own,
derived from ``numpy.random.SeedSequence`` so that

* element k's streams never overlap element k+1's (no ``seed + 1`` tricks),
* adding elements leaves the existing elements' draws unchanged
  (``spawn`` is indexed, not positional),
* a switch that turns an impairment off still consumes nothing from any
  other stream — because every stream is its own generator.  The owner of the
  switch draws and zeroes (see ``element.py``), so the draw itself is also
  stable.

The ``run`` and ``dpa_mismatch`` streams are handed to polar_tx as integer
seeds (its APIs take ints); the ``lo`` stream is shared by every element when
``element.lo.shared`` is true (one physical LO).
"""
from __future__ import annotations

import numpy as np
from numpy.random import Generator, SeedSequence, default_rng

#: per-element streams, in a fixed order (the order is the spawn index)
ELEMENT_STREAMS: tuple[str, ...] = (
    "gain", "phase", "delay", "pa_dev", "dpa_mismatch", "run", "lo_spurs")
#: array-wide streams
GLOBAL_STREAMS: tuple[str, ...] = ("lo", "waveform", "lo_spurs")
# ``lo_spurs`` (the start phase of each clock-profile spur) was appended to
# both tuples later; SeedSequence.spawn is indexed, so the streams before it
# kept their values bit for bit (fingerprinted).  New streams go at the END.


class SeedTree:
    """All the array's random streams, derived from one integer seed."""

    def __init__(self, seed: int, n_elements: int):
        if n_elements < 1:
            raise ValueError("n_elements must be >= 1")
        self.seed = int(seed)
        self.n_elements = int(n_elements)
        root = SeedSequence(self.seed)
        glob, elems = root.spawn(2)
        g = glob.spawn(len(GLOBAL_STREAMS))
        self._global: dict[str, SeedSequence] = dict(zip(GLOBAL_STREAMS, g))
        self._elements: list[dict[str, SeedSequence]] = []
        for e in elems.spawn(self.n_elements):
            ss = e.spawn(len(ELEMENT_STREAMS))
            self._elements.append(dict(zip(ELEMENT_STREAMS, ss)))

    # ------------------------------------------------------------ lookup
    def _ss(self, stream: str, k: int | None) -> SeedSequence:
        if k is None:
            if stream not in self._global:
                raise KeyError(f"unknown global stream {stream!r}; "
                               f"one of {GLOBAL_STREAMS}")
            return self._global[stream]
        if stream not in ELEMENT_STREAMS:
            raise KeyError(f"unknown element stream {stream!r}; "
                           f"one of {ELEMENT_STREAMS}")
        if not 0 <= k < self.n_elements:
            raise IndexError(f"element {k} out of range 0..{self.n_elements - 1}")
        return self._elements[k][stream]

    def rng(self, stream: str, k: int | None = None) -> Generator:
        """A fresh generator for ``stream`` (element ``k``, or global)."""
        return default_rng(self._ss(stream, k))

    def int_seed(self, stream: str, k: int | None = None) -> int:
        """A 31-bit integer seed for APIs that take an int (polar_tx)."""
        state = self._ss(stream, k).generate_state(1, dtype=np.uint32)[0]
        return int(state & 0x7FFFFFFF)
