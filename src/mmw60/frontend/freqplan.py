"""Zero-IF frequency plan for an upclocked channel at 60 GHz.

What a zero-IF plan has to answer: does the channel fit the unlicensed
band, where does the LO sit (at the centre: its leakage and the RX
self-mixing DC land on the DC tone, which the 802.11 plans leave empty but
which a CFO of a few tones moves into the data), what the image problem is
(none in frequency — the image is the signal's own mirror, rejected only by
IRR), and whether the converters' Nyquist rate covers the band.  No
intermediate frequency, so no spur table to walk: that is topology A's
burden (``fixed_lo_x3/x4``, the other session).
"""
from __future__ import annotations

from .. import spec


def ay_channel_centres_hz() -> list[float]:
    """802.11ay 2.16 GHz channel centres (data/spec: ieee80211ay.channel_centres_ghz)."""
    return [float(f) * 1e9 for f in spec.value("ieee80211ay.channel_centres_ghz")]


def zero_if_plan(carrier_hz: float, bandwidth_hz: float, fs_eff_hz: float,
                 scs_eff_hz: float, cfo_hz: float = 0.0) -> dict:
    lo_hz = carrier_hz
    f_lo_edge, f_hi_edge = carrier_hz - bandwidth_hz / 2, carrier_hz + bandwidth_hz / 2
    band_lo = float(spec.value("fcc15255.band_low_hz"))
    band_hi = float(spec.value("fcc15255.band_high_hz"))
    in_band = band_lo <= f_lo_edge and f_hi_edge <= band_hi
    nyquist_ok = fs_eff_hz >= bandwidth_hz * 1.0          # complex sampling: fs >= BW
    notes = []
    if not in_band:
        notes.append(f"channel edges {f_lo_edge / 1e9:.2f}–{f_hi_edge / 1e9:.2f} GHz leave the "
                     f"{band_lo / 1e9:.0f}–{band_hi / 1e9:.0f} GHz band")
    if not nyquist_ok:
        notes.append("converter rate below the channel bandwidth")
    leak_tone = cfo_hz / scs_eff_hz if scs_eff_hz else 0.0
    return {"lo_hz": lo_hz, "if_hz": 0.0, "image": "self (zero-IF): rejected by IRR only",
            "edges_hz": (f_lo_edge, f_hi_edge), "in_unlicensed_band": in_band,
            "fs_eff_hz": fs_eff_hz, "nyquist_ok": nyquist_ok,
            "lo_leak_lands_on_tone": leak_tone,
            "channels_in_band": int((band_hi - band_lo) // bandwidth_hz),
            "ok": in_band and nyquist_ok, "notes": notes}
