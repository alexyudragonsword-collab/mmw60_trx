"""Receiver refinements over wifitrx's per-symbol pilot CPE and fixed-span channel
smoothing (ROADMAP C1 / C2).  Both are options of ``RxConfig`` and off by
default, so the milestone-0 receiver (and its fingerprint) is unchanged.

**Cross-symbol CPE** (``smoothed_cpe``).  wifitrx's ``correct_cpe_pilots``
rotates every OFDM symbol by the phase of its own N_p pilots.  At low SNR
that estimate is far noisier than the phase it tracks: 4 pilots at 3 dB
give σ ≈ 14° against a common phase error of 2–3° for the Liu LO, and the
rare symbol whose pilot sum nearly cancels is rotated wholesale — a packet
error the decoder cannot repair.  The remedy is the textbook one, an MMSE
combination of each symbol's own estimate with its neighbours':

1. the per-symbol pilot phasor ``a_n = Σ_k conj(y_nk)·p_nk`` (the same
   quantity wifitrx normalises and applies);
2. the residual CFO's phase ramp is taken out with the lag-1 product
   ``Σ a_n·conj(a_{n−1})`` over the packet and put back at the end;
3. a leave-one-out mean ``m_n`` of the phasors in a window of W symbols is
   the smooth estimate;
4. the symbol's own deviation from it, ``φ_n = ∠(a_n·conj(m_n))``, is kept
   in proportion ``g`` = (variance of φ not explained by pilot noise) /
   (variance of φ): at low SNR φ is all estimator noise and ``g → 0`` (pure
   smoothing); at high SNR φ is the symbol's real common phase and
   ``g → 1`` (wifitrx's per-symbol answer).  The pilot noise variance is
   measured from the pilots' own residual after each symbol's LS rotation,
   so nothing about the SNR or the LO is assumed.

A window of 1 is wifitrx's per-symbol estimator, bit for bit.

**Channel-estimate smoothing span** (``auto_smooth_span``).  A fixed
boxcar across tones trades the LTF estimate's noise against the channel's
own variation, and the right width depends on the coherence bandwidth in
units of the tone spacing — which upclocking multiplies by K.  The span
is chosen per packet from the estimate itself: its autocorrelation across
tones at lags ≥ 1 is the channel's (the estimate's error is uncorrelated
from tone to tone), the excess at lag 0 over a fitted channel model is
that error's power W.  One tone or three is decided on that model; a
wider span is taken only when the bias it costs, read off the difference
between the smoothed and the raw estimate, is clearly below what it saves.
"""
from __future__ import annotations

import numpy as np

from ..vendor.wifitrx.metrics.cpe import correct_cpe_pilots


# ---------------------------------------------------------------- C1: cross-symbol CPE
def pilot_phasors(rx_symbols: np.ndarray, pilot_cols: np.ndarray, pilots: np.ndarray) -> np.ndarray:
    """a_n = Σ_k conj(y_nk)·p_nk: multiplying symbol n by a_n / |a_n| is
    wifitrx's per-symbol correction."""
    rx = np.asarray(rx_symbols, dtype=complex)
    cols = np.asarray(pilot_cols, dtype=int)
    return np.sum(np.conj(rx[:, cols]) * np.asarray(pilots, dtype=complex), axis=1)


def _window_sum(x: np.ndarray, half: int) -> np.ndarray:
    """Σ over the symmetric window [n − half, n + half], clipped at the ends."""
    c = np.concatenate([[0.0 + 0.0j], np.cumsum(x)])
    n = x.size
    lo = np.clip(np.arange(n) - half, 0, n)
    hi = np.clip(np.arange(n) + half + 1, 0, n)
    return c[hi] - c[lo]


def smoothed_cpe(rx_symbols: np.ndarray, pilot_cols: np.ndarray, pilots: np.ndarray,
                 window: int, return_info: bool = False):
    """Rotate each symbol by the MMSE-combined common phase (module docstring).

    ``window`` is the number of symbols the smooth estimate averages over
    (odd; an even value is raised to the next odd).  Returns the corrected
    symbols, and with ``return_info`` a dict with the shrinkage ``g``, the
    measured pilot-noise and total phase variances and the ramp."""
    rx = np.asarray(rx_symbols, dtype=complex)
    pil = np.asarray(pilots, dtype=complex)
    cols = np.asarray(pilot_cols, dtype=int)
    n_sym = rx.shape[0]
    w = int(window)
    if w <= 1 or n_sym < 3:
        out = correct_cpe_pilots(rx, cols, pil)          # wifitrx's estimator, bit for bit
        return (out, {"g": 1.0, "window": 1}) if return_info else out
    a = pilot_phasors(rx, cols, pil)
    half = min((w | 1) // 2, n_sym - 1)
    # 2. the residual-CFO ramp: lag-1 products over the packet (unambiguous to ±π per symbol),
    #    then refined on the derotated phasors at a lag of half a window (its error is 1/lag of lag-1's)
    idx = np.arange(n_sym)
    ramp = float(np.angle(np.sum(a[1:] * np.conj(a[:-1]))))
    lag = max(min(half, n_sym // 4), 1)
    if lag > 1:
        b0 = a * np.exp(-1j * ramp * idx)
        ramp += float(np.angle(np.sum(b0[lag:] * np.conj(b0[:-lag])))) / lag
    b = a * np.exp(-1j * ramp * idx)
    # 3. leave-one-out window mean
    m = _window_sum(b, half) - b
    m_mag = np.abs(m)
    m_unit = np.where(m_mag > 0, m / np.where(m_mag > 0, m_mag, 1.0), 1.0)
    # 4. the symbol's own deviation and how much of it is real
    phi = np.angle(b * np.conj(m_unit))
    v_tot = float(np.mean(phi ** 2))
    # pilot noise: residual of the pilots after each symbol's own LS rotation
    own = np.where(np.abs(a) > 0, a / np.where(np.abs(a) > 0, np.abs(a), 1.0), 1.0)
    resid = rx[:, cols] * own[:, None] - pil
    n_p = cols.size
    dof = max(n_p - 0.5, 0.5)                       # the LS rotation removes one real dimension of 2·N_p
    sigma_e2 = float(np.sum(np.abs(resid) ** 2) / (n_sym * dof))
    p_energy = float(np.mean(np.sum(np.abs(pil) ** 2, axis=1)))
    v_noise_own = sigma_e2 / (2.0 * p_energy)        # phase variance of one symbol's pilot estimate
    n_others = np.clip(np.minimum(idx + half, n_sym - 1) - np.maximum(idx - half, 0), 1, None)
    v_noise = v_noise_own * (1.0 + float(np.mean(1.0 / n_others)))     # φ also carries the window mean's noise
    v_real = max(v_tot - v_noise, 0.0)
    g = 0.0 if v_tot <= 0 else v_real / v_tot
    g_eff = g + (1.0 - g) / (float(np.mean(n_others)) + 1.0)           # the symbol's own share of a plain average
    rot = m_unit * np.exp(1j * (g_eff * phi + ramp * idx))
    out = rx * rot[:, None]
    if return_info:
        return out, {"g": g, "g_eff": g_eff, "window": 2 * half + 1, "ramp_rad_per_symbol": ramp,
                     "phase_var_total": v_tot, "phase_var_pilot_noise": v_noise}
    return out


# ---------------------------------------------------------------- C2: smoothing span from the estimate
_FLAT_TOL = 1e-6       # a model bias under −60 dBc of the channel power is below anything this chain resolves


def tone_autocorrelation(h: np.ndarray, segments, max_lag: int) -> np.ndarray:
    """Re R(d) = Re mean_k H_k·conj(H_{k+d}) for d = 0 … max_lag, pairs taken
    inside the frequency-contiguous runs only."""
    h = np.asarray(h, dtype=complex)
    runs = [np.arange(h.size)] if segments is None else list(segments)
    acc = np.zeros(max_lag + 1)
    cnt = np.zeros(max_lag + 1)
    for cols in runs:
        x = h[cols]
        for d in range(max_lag + 1):
            if x.size > d:
                acc[d] += float(np.real(np.sum(x[:x.size - d] * np.conj(x[d:]))))
                cnt[d] += x.size - d
    return acc / np.maximum(cnt, 1)


def auto_smooth_span(h: np.ndarray, segments=None, max_tones: int = 9, return_info: bool = False):
    """The odd boxcar span S ≤ ``max_tones`` for smoothing a channel estimate,
    chosen from the estimate itself in two steps (module docstring).

    **Smooth at all?**  The tone autocorrelation at lags 1 and 2 — which the
    estimate's tone-to-tone-uncorrelated error (thermal noise, the LTF
    pattern's share of an IQ image or PA distortion) does not reach — is
    fitted with the real part of an exponential delay profile's,
    ``c(d) = P / (1 + a²·d²)``; P is the channel's own power and
    ``W = R(0) − P`` the error a boxcar averages down.  One tone is taken
    when the model's bias, ≈ (8/3)·P·a⁴, exceeds the (2/3)·W three tones
    remove, three otherwise — a tie (no noise visible, flat model) goes to
    three: the first version gave up smoothing there and the noise-free
    11be 20 MHz chain read −41.2 dB for the fixed span's −45.6.  (A parabolic extrapolation instead of this fit
    under-reads P on a selective channel — 0.91 for 1.0 at 15 ns rms and a
    5 MHz tone spacing — and books the rest as noise to be smoothed.)

    **More than three?**  Beyond 3 tones the most there is to gain is
    0.4 dB of estimation noise, and what there is to lose — the roll-off of
    the chain's own filters at 256-QAM and above — no channel model knows.
    So the bias is measured: with the error power read off the 3-tone
    result, ``W₃ = 1.5·mean|H₃ − H|²``, a wider span's
    ``mean|H_S − H|² − W₃·(1 − 1/S)`` is its extra bias, and S is widened
    only while  bias²(S) + W₃/S  falls by more than that estimate's own
    scatter, ``W₃·√(2/N)`` for N tones.  On 56 tones that keeps 3; on
    996 it goes to the ceiling when the channel allows.  (First version,
    bias from the model alone: the 11ac 20 MHz MCS8 threshold moved from
    25.9 to 28.0 dB.)"""
    from ..vendor.wifitrx.waveform.preamble import smooth_channel_estimate
    h = np.asarray(h, dtype=complex)
    max_tones = max(int(max_tones) | 1, 1)
    r = tone_autocorrelation(h, segments, 2)
    info = {"acf": r.tolist()}
    if max_tones == 1 or r.size < 3 or r[0] <= 0 or r[1] <= 0:
        return (1, info) if return_info else 1
    den = 4.0 * r[2] - r[1]
    if den <= 0:                       # decorrelated within two tones: nothing to average over
        a2, p = np.inf, float(r[0])
    else:
        a2 = max(float((r[1] - r[2]) / den), 0.0)
        p = float(min(r[1] * (1.0 + a2), r[0]))
    white = max(float(r[0]) - p, 0.0)
    if np.isfinite(a2):
        c1, c2 = p / (1.0 + a2), p / (1.0 + 4.0 * a2)
        bias3 = max(p - 2.0 * (p + 2.0 * c1) / 3.0 + (3.0 * p + 4.0 * c1 + 2.0 * c2) / 9.0, 0.0)
    else:
        bias3 = p
    info.update({"channel_power": p, "white_power": white, "a2": a2, "model_bias2_3": bias3})
    # one tone only when the model's bias is worth more than the noise three tones remove.  A tie is
    # not that: with no noise visible (W clipped at 0: a noise-free chain, or a narrow band at high
    # SNR where W's own scatter exceeds it) and a channel the model calls flat, three tones cost
    # nothing and still take out whatever tone-to-tone error sits under the fit's resolution
    if bias3 + white / 3.0 > white + _FLAT_TOL * p:
        return (1, info) if return_info else 1
    best = 3
    if max_tones >= 5:
        d3 = float(np.mean(np.abs(smooth_channel_estimate(h, 3, segments) - h) ** 2))
        w3 = 1.5 * d3
        scatter = w3 * np.sqrt(2.0 / max(h.size, 1))
        mse = {3: w3 / 3.0}
        for s_ in range(5, max_tones + 1, 2):
            d = float(np.mean(np.abs(smooth_channel_estimate(h, s_, segments) - h) ** 2))
            mse[s_] = max(d - w3 * (1.0 - 1.0 / s_), 0.0) + w3 / s_ + scatter
        best = min(mse, key=lambda k: (mse[k], k))
        info.update({"mse": mse, "w3": w3, "scatter": scatter})
    return (best, info) if return_info else best
