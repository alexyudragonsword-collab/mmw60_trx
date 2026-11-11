# Vendored from wifi_trx_cal@da37888ab16f6a5f34d1d0f3d329a4b857b5f37b: src/wifitrx/waveform/tone_plan.py
# Adapted-copy policy: see src/mmw60/vendor/__init__.py
"""Which subcarriers carry something, and where the holes are.

The model has always placed its active tones as one contiguous block
symmetric about DC: no DC gap, no segment nulls between the 80 MHz
halves of a 160/320 MHz channel, no OFDMA resource units, no preamble
puncturing.  The standard's occupied ranges were already in
``pilots.py`` — used only to rank-map the pilots *into* that block — and
this module promotes them to the thing the waveform is actually built
on.

Two facts make the change smaller than it looks:

* a standard plan holds **the same number of active tones** as the
  contiguous block it replaces (40 MHz: 242 a side either way), so it
  repositions tones rather than adding or removing them, and every
  ``sqrt(n_active)`` power normalisation is untouched;
* with the real plan the pilots sit on their standard tone indices
  directly, so the rank map that 0.7.17 needed becomes an identity and
  the lever arm the SCO estimator sees is the standard's exactly.

What a plan with holes does change is anything that treats *array
neighbours* as *frequency neighbours*.  The channel-estimate smoothing
is the one that matters (``preamble.smooth_channel_estimate``): a window
straddling a gap averages across a discontinuity, which is why that
function takes the plan's segments rather than convolving blindly.

``None`` everywhere keeps the contiguous behaviour, bit for bit.

A plan may also carry **its own pilot tones** (``TonePlan.pilots``).
The two pilot tables in ``pilots.py`` hold the standard's sets for the
two 802.11 numerologies at 20-320 MHz and nothing else; a numerology
outside them — another subcarrier spacing, 640 MHz, a clock scaled by
K — has no pilot set, so its scoring waveform could not be built and the
calibration's final step had nothing to score (issue #4, from the sister
library mmw60_trx).  This model does not invent tables for numerologies
the standard does not define; the caller names the pilots, and they
travel with the plan, because every caller of the pilot machinery
(``cal.sequence.scoring_frame``, the link studies, the workbench)
derives the pilots from the config and nothing else.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

#: positive-half occupied ranges (inclusive) of the standard tone plans
HE_RANGES = {
    20e6: ((2, 122),),
    40e6: ((3, 244),),
    80e6: ((3, 500),),
    160e6: ((12, 509), (515, 1012)),
    320e6: ((12, 509), (515, 1012), (1036, 1533), (1539, 2036)),
}
LEGACY_RANGES = {
    20e6: ((1, 26),),
    40e6: ((2, 58),),
    80e6: ((2, 122),),
    160e6: ((6, 126), (130, 250)),
}


@dataclass(frozen=True)
class TonePlan:
    """Signed, sorted, DC-excluded subcarrier indices plus a label, and
    optionally the plan's own pilot tones (signed indices, a subset of
    ``indices``).  ``pilots=None`` leaves the pilots to the numerology's
    table, exactly as before."""

    indices: np.ndarray
    label: str = "custom"
    pilots: np.ndarray | None = None

    def __post_init__(self) -> None:
        idx = np.asarray(self.indices, dtype=int)
        if idx.size == 0:
            raise ValueError("a tone plan must carry at least one tone")
        if bool((idx == 0).any()):
            raise ValueError("DC is never an active tone")
        if bool((np.diff(idx) <= 0).any()):
            raise ValueError("tone indices must be sorted and unique")
        object.__setattr__(self, "indices", idx)
        if self.pilots is not None:
            pil = np.sort(np.asarray(self.pilots, dtype=int).ravel())
            if pil.size == 0:
                raise ValueError("a plan's pilot set, when given, is not empty")
            if bool((np.diff(pil) == 0).any()):
                raise ValueError("pilot tones must be unique")
            if pil.size >= idx.size:
                raise ValueError(f"{pil.size} pilots leave no data tone in "
                                 f"a {idx.size}-tone plan")
            # explicit membership test rather than np.isin: the Android
            # call-surface allow-list holds names verified against numpy
            # 1.19.5, and isin is not one of them
            at = np.searchsorted(idx, pil)
            inside = (at < idx.size) & (idx[np.minimum(at, idx.size - 1)] == pil)
            if not bool(inside.all()):
                raise ValueError("pilot tones must be tones of the plan: "
                                 f"{pil[~inside].tolist()} are not")
            object.__setattr__(self, "pilots", pil)

    def pilot_columns(self) -> np.ndarray | None:
        """Column positions (into the plan's active-tone axis) of the
        plan's own pilots, or ``None`` when it carries none."""
        if self.pilots is None:
            return None
        return np.searchsorted(self.indices, self.pilots).astype(int)

    @property
    def n_active(self) -> int:
        return int(self.indices.size)

    @property
    def is_contiguous(self) -> bool:
        """True when the only gap is DC — the model's historical shape,
        for which the segment-aware paths reduce to the old ones."""
        return len(self.segments()) <= 2 and bool((np.diff(self.indices) <= 2).all())

    def segments(self) -> list[np.ndarray]:
        """Column ranges of the runs that are contiguous *in frequency*.
        Each entry is the array of column positions belonging to one run,
        so a caller can smooth or interpolate inside a run without
        crossing a null."""
        # explicit slicing rather than np.split: the Android call-surface
        # allowlist holds names verified against numpy 1.19.5, and split is
        # not one of them.  The loop is also plainer about what a segment is.
        breaks = [0, *(np.nonzero(np.diff(self.indices) != 1)[0] + 1).tolist(),
                  self.n_active]
        cols = np.arange(self.n_active)
        return [cols[a:b] for a, b in zip(breaks[:-1], breaks[1:]) if b > a]

    def mirror_ok(self) -> bool:
        """The plan is symmetric about DC.  ``cal.rx_iq`` fits its image
        correction on mirror pairs and silently drops unmatched tones, so
        a caller that breaks symmetry needs to know."""
        mirror = -self.indices[::-1]
        return bool(self.indices.shape == mirror.shape
                    and (self.indices == mirror).all())


def contiguous(n_active: int, pilots=None) -> TonePlan:
    """The historical block: +-1 .. +-n_active/2, DC excluded; optionally
    with the caller's own pilot tones (signed indices inside the block)."""
    half = n_active // 2
    idx = np.concatenate([np.arange(-half, 0), np.arange(1, half + 1)])
    return TonePlan(idx, label=f"contiguous {n_active}", pilots=pilots)


def _ranges_for(bandwidth_hz: float, subcarrier_spacing_hz: float,
                he_spacing_hz: float):
    table = (HE_RANGES if subcarrier_spacing_hz == he_spacing_hz
             else LEGACY_RANGES)
    name = "11ax/be" if table is HE_RANGES else "legacy 11a/n/ac"
    if bandwidth_hz not in table:
        raise ValueError(
            f"no {name} tone plan for {bandwidth_hz / 1e6:g} MHz; the "
            "standard plans are "
            + ", ".join(f"{b / 1e6:g}" for b in sorted(table)) + " MHz")
    return table[bandwidth_hz], name


def standard(bandwidth_hz: float, subcarrier_spacing_hz: float,
             he_spacing_hz: float) -> TonePlan:
    """The standard's own plan: the occupied ranges mirrored about DC, so
    the DC gap and the inter-segment nulls are real holes."""
    ranges, name = _ranges_for(bandwidth_hz, subcarrier_spacing_hz,
                               he_spacing_hz)
    pos = np.concatenate([np.arange(lo, hi + 1) for lo, hi in ranges])
    idx = np.concatenate([-pos[::-1], pos])
    return TonePlan(idx, label=f"{name} {bandwidth_hz / 1e6:g} MHz")


def punctured(plan: TonePlan, bandwidth_hz: float,
              subcarrier_spacing_hz: float, drop: tuple) -> TonePlan:
    """``plan`` with whole 20 MHz subchannels removed.

    ``drop`` holds 0-based subchannel numbers counted from the low edge,
    which is how preamble puncturing is described.  Dropping one takes
    its tones out of the plan, so ``n_active`` falls and the hole is
    wide — the case a smoothing window must not average across."""
    n20 = int(round(bandwidth_hz / 20e6))
    if n20 < 2:
        raise ValueError("puncturing needs at least two 20 MHz subchannels")
    per = (20e6 / subcarrier_spacing_hz)
    edges = (np.arange(n20 + 1) - n20 / 2.0) * per
    keep = np.ones(plan.n_active, dtype=bool)
    for d in drop:
        if not 0 <= int(d) < n20:
            raise ValueError(f"subchannel {d} outside 0..{n20 - 1}")
        lo, hi = edges[int(d)], edges[int(d) + 1]
        keep &= ~((plan.indices >= lo) & (plan.indices < hi))
    if not keep.any():
        raise ValueError("puncturing removed every tone")
    tag = ",".join(str(int(d)) for d in drop)
    pilots = None
    if plan.pilots is not None:
        # the plan's own pilots that survive; a punctured subchannel takes
        # its pilots with it, as it takes its data tones
        kept = plan.indices[keep]
        at = np.searchsorted(kept, plan.pilots)
        alive = (at < kept.size) & (kept[np.minimum(at, kept.size - 1)]
                                    == plan.pilots)
        if not bool(alive.any()):
            raise ValueError("puncturing removed every pilot of the plan")
        pilots = plan.pilots[alive]
    return TonePlan(plan.indices[keep], label=f"{plan.label} minus 20MHz #{tag}",
                    pilots=pilots)


def subband(bandwidth_hz: float, subcarrier_spacing_hz: float,
            n_tones: int, centre_tone: int) -> TonePlan:
    """``n_tones`` contiguous subcarriers centred on ``centre_tone``.

    This is the RU-shaped plan without the RU tables.  802.11ax/be
    partitions a channel into resource units of 26, 52, 106, 242, 484,
    996 and 2x996 tones at tabulated positions, and those tables are an
    external specification this project does not hold — the same reason
    the channel models are exponential profiles rather than TGn letters.
    What a narrow plan is actually *for* here is asking whether an
    impairment cares where in the band it sits, and that question needs
    a width and an offset, not the standard's grid.  So this builds one
    and does not call it an RU.

    DC is skipped; a span straddling it loses that one tone.
    """
    if n_tones < 2:
        raise ValueError("a sub-band needs at least two tones")
    nfft = int(round(bandwidth_hz / subcarrier_spacing_hz))
    lo = int(centre_tone) - n_tones // 2
    idx = np.arange(lo, lo + n_tones)
    idx = idx[idx != 0]
    if idx.size == 0:
        raise ValueError("sub-band collapsed to nothing")
    if idx.min() < -nfft // 2 or idx.max() > nfft // 2:
        raise ValueError(
            f"sub-band {idx.min()}..{idx.max()} leaves the {bandwidth_hz / 1e6:g} "
            f"MHz channel (+-{nfft // 2} tones)")
    return TonePlan(idx, label=f"{idx.size}-tone sub-band at {int(centre_tone):+d}")


def to_record(plan) -> object:
    """A tone plan as JSON-ready data, for the cal-state file's conditions
    block: a plan name (``"standard"``) passes through; a ``TonePlan``
    becomes its label, its contiguous runs as ``[lo, hi]`` pairs (a
    2.56 GHz plan is 30800 tones but a handful of runs) and its own
    pilots.  ``from_record`` inverts it exactly."""
    if plan is None or isinstance(plan, str):
        return plan
    idx = plan.indices
    breaks = [0, *(np.nonzero(np.diff(idx) != 1)[0] + 1).tolist(), idx.size]
    runs = [[int(idx[a]), int(idx[b - 1])] for a, b in zip(breaks[:-1], breaks[1:])]
    return {"label": plan.label, "ranges": runs,
            "pilots": None if plan.pilots is None
            else [int(x) for x in plan.pilots]}


def from_record(rec) -> object:
    """The plan a ``to_record`` value describes (``None`` and plan names
    pass through)."""
    if rec is None or isinstance(rec, str):
        return rec
    idx = np.concatenate([np.arange(int(lo), int(hi) + 1)
                          for lo, hi in rec["ranges"]])
    return TonePlan(idx, label=str(rec.get("label", "custom")),
                    pilots=rec.get("pilots"))
