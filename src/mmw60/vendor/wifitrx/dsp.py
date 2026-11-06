# Vendored from wifi_trx_cal@cc06b9ac8dafb5cbb261a59280e81ae0cfbf787c: src/wifitrx/dsp.py
# Adapted-copy policy: see src/mmw60/vendor/__init__.py
"""Small shared DSP helpers."""
from __future__ import annotations

import numpy as np


def conv_same(x: np.ndarray, h: np.ndarray) -> np.ndarray:
    """Center-referenced convolution; overlap-add FFT for long signals."""
    h = np.atleast_1d(h)
    if x.size * h.size > 1 << 18:
        from scipy.signal import oaconvolve
        return oaconvolve(x, h, mode="same")
    return np.convolve(x, h, mode="same")
