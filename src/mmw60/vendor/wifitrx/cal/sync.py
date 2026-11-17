# Vendored from wifi_trx_cal@a8edf503df74cf11d6069a6354c4c0ddbf6e82d1: src/wifitrx/cal/sync.py
# Adapted-copy policy: see src/mmw60/vendor/__init__.py
# Vendored from PA_DPD:src/padpd/data/align.py (internal sibling repo), adapted for wifitrx.
# Upstream changes should be ported manually; see PROVENANCE.md.
"""Time alignment of PA input/output captures.

Measured or EDA-exported data often has an unknown bulk delay (and complex
gain) between the stimulus and the capture. Behavioral-model fitting
assumes sample-aligned x/y, so run :func:`align_delay` first. (OpenDPD
datasets ship pre-aligned; Cadence envelope exports and lab captures
usually do not.)
"""

from __future__ import annotations

import numpy as np
from scipy import signal as sig


def _fractional_advance(y: np.ndarray, frac: float) -> np.ndarray:
    """Advance y by a fractional number of samples via an FFT phase ramp.

    Circular by construction; only the few edge samples are affected for
    |frac| < 1.
    """
    freq = np.fft.fftfreq(len(y))
    return np.fft.ifft(np.fft.fft(y) * np.exp(2j * np.pi * freq * frac))


def compensate_delay(y: np.ndarray, delay: float, start: int,
                     length: int) -> np.ndarray:
    """Extract ``length`` samples of ``y`` beginning at ``start`` with the
    (possibly fractional) bulk ``delay`` removed: integer part by slicing,
    fractional part by an FFT phase ramp on the slice.

    ``y`` must extend at least ``round(delay)`` samples past
    ``start + length`` — captures need a cyclic guard tail after the
    payload.  Advancing the *whole* capture circularly and keeping its
    tail instead wraps unrelated samples into the last OFDM symbol's FFT
    window; the resulting error scales with the filter group delay and
    1/fft_size, and at 20 MHz it floors measured EVM in the -30s dB while
    masquerading as an analog ISI floor.
    """
    k = int(round(delay))
    seg = y[start + k: start + k + length]
    if len(seg) < length:
        raise ValueError(
            "capture ends %d samples too early for delay compensation; "
            "append a cyclic guard tail" % (length - len(seg)))
    frac = delay - k
    if abs(frac) < 1e-9:
        return seg.copy()
    return _fractional_advance(seg, frac)


def align_delay(x: np.ndarray, y: np.ndarray, max_lag: int = 4096):
    """Estimate and remove the bulk delay of ``y`` relative to ``x``.

    The integer delay is the argmax of the complex cross-correlation
    within ``+/- max_lag`` samples (positive = y lags x). A residual
    fractional delay is then estimated by parabolic interpolation of the
    correlation peak and, if larger than 0.02 samples, removed with an
    FFT phase ramp.

    Returns ``(x_aligned, y_aligned, info)`` where the aligned arrays are
    the overlapping region and ``info`` holds ``{"lag"``: integer part,
    ``"lag_total"``: float total delay, ``"gain"``: least-squares complex
    gain with y ≈ gain * x after alignment, ``"lag_peak"``: the lag of the
    correlation's largest value over *all* lags, window or not -- when it
    differs from ``"lag"`` the true delay lies outside the window and
    ``"lag"`` is only the best the window had to offer``}``.
    """
    x = np.asarray(x)
    y = np.asarray(y)
    corr = sig.correlate(y, x, mode="full", method="fft")
    # scipy.signal.correlation_lags exists only from scipy 1.5; the
    # Android wheel is pinned at 1.4.1, and for mode="full" the lag axis
    # is exactly this arange (see tests/test_android_bridge.py guard).
    lags = np.arange(-(len(x) - 1), len(y))
    window = np.where(np.abs(lags) <= max_lag)[0]
    peak = window[np.argmax(np.abs(corr[window]))]
    lag = int(lags[peak])
    lag_peak = int(lags[np.argmax(np.abs(corr))])

    # Parabolic interpolation of |corr| around the peak -> fractional lag.
    frac = 0.0
    if 0 < peak < len(corr) - 1:
        c_m, c_0, c_p = np.abs(corr[peak - 1: peak + 2])
        denom = c_m - 2 * c_0 + c_p
        if denom != 0:
            frac = float(np.clip(0.5 * (c_m - c_p) / denom, -0.5, 0.5))

    if lag >= 0:
        y_a = y[lag:]
        x_a = x[: len(y_a)]
    else:
        x_a = x[-lag:]
        y_a = y[: len(x_a)]
    n = min(len(x_a), len(y_a))
    x_a, y_a = x_a[:n], y_a[:n]

    if abs(frac) > 0.02:
        y_a = _fractional_advance(y_a, frac)

    # Refine with the cross-spectrum phase slope: parabolic peak
    # interpolation is biased for wide-band or nonlinearly distorted
    # signals (0.1-0.3 sample residual on PA outputs), and a residual
    # fractional delay turns into a phase ramp across subcarriers that
    # caps constellation EVM around -20 dB. The phase-vs-frequency slope
    # of X* Y over the occupied band is a far more accurate estimator.
    resid = _phase_slope_delay(x_a, y_a)
    if abs(resid) > 0.002:
        y_a = _fractional_advance(y_a, resid)
        frac += resid

    gain = complex(np.vdot(x_a, y_a) / np.vdot(x_a, x_a))
    return x_a, y_a, {"lag": lag, "lag_total": lag + frac, "gain": gain,
                      "lag_peak": lag_peak}


def loopback_capture_aligned(tx, rx, path, x: np.ndarray,
                             n_warmup: int = 512, n_guard: int = 64,
                             seed: int = 0,
                             max_guard: int = 1 << 14) -> np.ndarray:
    """Loopback capture of ``x``, delay-aligned and trimmed to ``len(x)``.

    A cyclic warm-up prefix settles the IIR baseband filters and a cyclic
    guard tail of ``n_guard`` samples keeps delay compensation inside the
    frame; the integer delay is searched within +/- ``n_guard // 2``.
    When the correlation's largest value over all lags is not strictly
    inside that window, the true delay lies beyond it: the guard grows
    until the window holds that peak, the frame is captured again and the
    search repeated.  A capture whose delay lies inside the window is the
    same capture, scored the same way, as with the fixed window.

    The window used to be fixed at +/-32 samples whatever the sampling
    rate, and a 6 ns coupler path is 30.7 samples at 5.12 GS/s before the
    chains' own group delay is added (mmw60_trx issue #7, B47).  0.7.44
    widened the search only when the *window's* peak sat on the window
    edge, taking that for the sign of a delay beyond it.  It is not: at
    2x oversampling the correlation of a band-limited frame has nulls
    about two samples from its peak, so with the true peak a few samples
    outside, the edge can sit in a null and the window's largest value is
    a sidelobe one or two samples inside.  Five of eleven path delays
    between 6.0 and 7.0 ns stayed misaligned by 3.4-6.0 samples that way
    (mmw60_trx's acceptance of 0.7.44); the two that were tested, 6 and
    7 ns, happened to trigger.  The peak over all lags does not depend on
    where the window ends.
    """
    from ..chain.loopback import run_loopback

    x = np.asarray(x)
    while True:
        xp = np.concatenate([x[-n_warmup:], x, x[:n_guard]])
        cap = run_loopback(tx, rx, xp, path, seed=seed)
        half = n_guard // 2
        _, _, info = align_delay(xp, cap, max_lag=half)
        beyond = abs(info["lag_peak"])
        if beyond < half:
            return compensate_delay(cap, info["lag_total"], n_warmup, len(x))
        while n_guard // 2 <= beyond:
            n_guard *= 2
        if n_guard > max_guard:
            raise ValueError(
                f"loopback delay of about {beyond} samples and the guard "
                f"tail is capped at {max_guard}: shorten the path or raise "
                "max_guard")


def _phase_slope_delay(x: np.ndarray, y: np.ndarray) -> float:
    """Residual delay of y vs x from the cross-spectrum phase slope.

    Weighted LS fit of unwrapped angle(X* Y) against frequency over the
    occupied band (bins with meaningful power); returns the delay in
    samples (positive = y still lags x).
    """
    n = len(x)
    xf = np.fft.fft(x)
    yf = np.fft.fft(y)
    cross = np.conj(xf) * yf
    w = np.abs(cross)
    band = w > 0.05 * w.max()
    if band.sum() < 8:
        return 0.0
    f = np.fft.fftfreq(n)
    order = np.argsort(f[band])
    fb = f[band][order]
    ph = np.unwrap(np.angle(cross[band][order]))
    wb = w[band][order]
    fc = fb - np.average(fb, weights=wb)
    denom = np.sum(wb * fc ** 2)
    if denom == 0:
        return 0.0
    slope = np.sum(wb * fc * (ph - np.average(ph, weights=wb))) / denom
    return float(np.clip(-slope / (2 * np.pi), -1.0, 1.0))
