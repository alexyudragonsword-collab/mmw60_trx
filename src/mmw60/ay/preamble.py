"""The standard's Golay channel-estimation field (the DMG / EDMG L-CEF), built from numbers handed in.

This module imports numpy and ``golay`` and nothing else, on purpose: it is meant to be copied by
other libraries (jcas60 vendors it; mmw60_trx#89).  It reads no spec table.  Every number of the
standard is an argument, and the caller says where it got it:

* the generating recursion of the Golay pair (delays ``D_k``, weights ``W_k``) or the pair itself
  -- spec_sources ``dmg.golay_sequences``;
* how the 512-chip sequences are put together from the 128-chip pair, and in which order the field
  sends them -- spec_sources ``dmg.cef_golay_layout``.

``mmw60.ay.edmg.l_cef`` is this library's own caller (it reads the two entries and calls this).

What the field is.  ``Gu512`` and ``Gv512`` are four signed 128-chip blocks each.  The field sends
them one after the other followed by the first 128 chips of the second (single carrier:
``Gu512, Gv512, Gv128``; OFDM: ``Gv512, Gu512, Gu128``), every chip turned by ``exp(j*pi*n/2)``.

What makes it a channel-estimation field is not that ``Gu512`` and ``Gv512`` are a complementary
pair on their own -- they are not (``golay.is_complementary`` says no; a test holds that).  It is
the 128 chips on either side: the field's last 128 chips are the first 128 of the second sequence
(its cyclic suffix), and the 128 chips *before* the field are the last 128 of the first sequence
(its cyclic prefix, ``cyclic_prefix``; with the standard's layout both orders give ``-Ga128``).
With those in place the two correlations add up to ``2 * 512`` at lag 0 and to exactly zero for
every other lag within +-128 chips (``correlate``; measured in the tests, both orders).  Outside
that zone the sum is not zero.

Not here: the short training field before it and the TRN subfields (their composition is not in
the spec tables this library reads), the headers, pulse shaping, and anything about a receiver
beyond the one correlation that states the field's property.
"""
from __future__ import annotations

import numpy as np

from .golay import golay_pair

#: chips of the short blocks and of the sequences built from four of them
BLOCK = 128


def pair_from_recursion(delays, weights) -> tuple[np.ndarray, np.ndarray]:
    """``(Ga, Gb)`` of length ``2**len(delays)`` as the standard defines them: the recursion's
    ``A_K`` and ``B_K`` read backwards (``Ga(n) = A_K(N - n)``)."""
    a, b = golay_pair(delays, weights)
    return a[::-1].copy(), b[::-1].copy()


def compose(blocks: dict, items) -> np.ndarray:
    """Signed blocks one after the other: ``compose({"Ga128": ga, "Gb128": gb}, ["-Gb128", "+Ga128"])``.
    Every item is a sign and a name of ``blocks``; anything else is an error, not a guess."""
    out = []
    for item in items:
        text = str(item).strip()
        if len(text) < 2 or text[0] not in "+-" or text[1:] not in blocks:
            raise ValueError(f"{item!r} is not '+NAME' or '-NAME' with NAME one of {sorted(blocks)}")
        out.append((1.0 if text[0] == "+" else -1.0) * np.asarray(blocks[text[1:]]))
    if not out:
        raise ValueError("no blocks to compose")
    return np.concatenate(out)


def gu_gv(ga: np.ndarray, gb: np.ndarray, gu_items, gv_items) -> tuple[np.ndarray, np.ndarray]:
    """``(Gu, Gv)`` from the pair and the two block lists of the layout (four signed blocks each)."""
    ga, gb = np.asarray(ga), np.asarray(gb)
    if ga.shape != gb.shape or ga.ndim != 1:
        raise ValueError("Ga and Gb must be one-dimensional and of the same length")
    blocks = {f"Ga{ga.size}": ga, f"Gb{gb.size}": gb}
    return compose(blocks, gu_items), compose(blocks, gv_items)


def _named(name: str, gu: np.ndarray, gv: np.ndarray) -> np.ndarray:
    """``"Gu512"`` / ``"Gv128"`` ...: the first so-many chips of that sequence."""
    text = str(name).strip()
    base = {"Gu": gu, "Gv": gv}.get(text[:2])
    if base is None or not text[2:].isdigit():
        raise ValueError(f"{name!r} is not 'Gu<chips>' or 'Gv<chips>'")
    n = int(text[2:])
    if not 0 < n <= base.size:
        raise ValueError(f"{name!r} asks for {n} chips of a sequence of {base.size}")
    return base[:n]


def rotate(chips: np.ndarray, first_index: int = 0) -> np.ndarray:
    """Every chip turned by ``exp(j*pi*n/2)``, ``n`` counted from ``first_index`` (exact: the
    factors are 1, j, -1, -j, taken from a table, not from ``exp``)."""
    turn = np.array([1.0, 1.0j, -1.0, -1.0j])
    n = (np.arange(np.asarray(chips).size) + int(first_index)) % 4
    return np.asarray(chips) * turn[n]


def cef(gu: np.ndarray, gv: np.ndarray, order, rotated: bool = True) -> np.ndarray:
    """The field: the sequences ``order`` names, one after the other (``["Gu512", "Gv512",
    "Gv128"]`` for single carrier), turned chip by chip unless ``rotated`` is false (then real)."""
    gu, gv = np.asarray(gu), np.asarray(gv)
    field = np.concatenate([_named(name, gu, gv) for name in order])
    return rotate(field) if rotated else field


def cyclic_prefix(gu: np.ndarray, gv: np.ndarray, order, rotated: bool = True, chips: int = BLOCK) -> np.ndarray:
    """The ``chips`` chips that have to stand right before the field for its correlation to be
    clean: the last chips of the sequence the field opens with.  Turned as the continuation of the
    field's own rotation backwards (``n = -chips ... -1``) unless ``rotated`` is false."""
    first = _named(order[0], np.asarray(gu), np.asarray(gv))
    if not 0 < chips <= first.size:
        raise ValueError(f"a prefix of {chips} chips does not fit a sequence of {first.size}")
    tail = first[-chips:]
    return rotate(tail, -chips) if rotated else tail.copy()


def correlate(x: np.ndarray, gu: np.ndarray, gv: np.ndarray, order, start: int, lags,
              rotated: bool = True) -> np.ndarray:
    """The field's own channel reading: per lag, ``x`` against the two full sequences as the field
    sends them (``start`` = index of the field's first chip in ``x``), added and divided by the
    chips of both.  On ``prefix + field`` it is 1 at lag 0 and 0 at every other lag within +-128
    chips; on that signal through a channel it is the channel's taps at those lags.

    Chips that fall outside ``x`` count as zero.  ``rotated`` says whether ``x`` carries the
    field's chip rotation: the reference is then the turned chips, so a tap reads as itself (taking
    the rotation off ``x`` instead would leave a quarter turn per chip of delay on every tap)."""
    gu, gv = np.asarray(gu), np.asarray(gv)
    x = np.asarray(x)
    names = [str(n).strip() for n in order[:2]]
    refs = [_named(n, gu, gv) for n in names]
    if sorted(n[:2] for n in names) != ["Gu", "Gv"] or any(r.size != s.size for r, s in zip(refs, (gu, gv))):
        raise ValueError(f"the field must open with both full sequences, one each; got {list(order[:2])}")
    offsets = (0, refs[0].size)
    if rotated:
        refs = [np.conj(rotate(ref, off)) for ref, off in zip(refs, offsets)]
    out = np.zeros(len(lags), dtype=complex if rotated or np.iscomplexobj(x) else float)
    for i, lag in enumerate(lags):
        acc = 0.0
        for ref, off in zip(refs, offsets):
            idx = np.arange(ref.size) + int(start) + off + int(lag)
            ok = (idx >= 0) & (idx < x.size)
            acc = acc + np.sum(x[idx[ok]] * ref[ok])
        out[i] = acc / (refs[0].size + refs[1].size)
    return out
