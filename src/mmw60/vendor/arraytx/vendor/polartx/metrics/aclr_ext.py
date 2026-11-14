# Vendored from array_tx@5815c5a7ea43143fd58502d4894ac840b5b5fb86: src/arraytx/vendor/polartx/metrics/aclr_ext.py
# Adapted-copy policy: see src/mmw60/vendor/__init__.py
# Vendored from polar_tx@b007e60: src/polartx/metrics/aclr_ext.py
# Adapted-copy policy: see src/arraytx/vendor/__init__.py
"""Multi-offset ACLR with cellular measurement conventions.

E-UTRA/NR ACLR: adjacent-channel power in a measurement bandwidth
(~occupied BW, e.g. 18 MHz for LTE20) at +/-1 and +/-2 channel spacings,
relative to the same measurement in the wanted channel.  Extends the
vendored single-offset padpd aclr().
"""
from __future__ import annotations

import numpy as np
from scipy import signal as sig


def aclr_multi(x: np.ndarray, fs: float, bw: float, *,
               offsets=(1, 2), meas_bw: float | None = None,
               nfft: int = 4096) -> dict:
    """ACLR at multiples of the channel spacing bw.

    meas_bw defaults to 0.9 * bw (the E-UTRA occupied-BW convention).
    Returns {"aclr1_lower_dbc", "aclr1_upper_dbc", "aclr2_...", ...}.
    """
    meas = 0.9 * bw if meas_bw is None else meas_bw
    if fs < 2 * (max(offsets) * bw + meas / 2):
        raise ValueError("fs too low for the requested ACLR offsets")
    f, pxx = sig.welch(x, fs=fs, nperseg=min(nfft, len(x)),
                       return_onesided=False, detrend=False)
    order = np.argsort(f)
    f, pxx = f[order], pxx[order]

    def _band(fc):
        m = (f >= fc - meas / 2) & (f < fc + meas / 2)
        return float(pxx[m].sum())

    p0 = _band(0.0)
    out = {}
    for k in offsets:
        out[f"aclr{k}_lower_dbc"] = float(10 * np.log10(_band(-k * bw) / p0))
        out[f"aclr{k}_upper_dbc"] = float(10 * np.log10(_band(+k * bw) / p0))
    return out
