"""Minimal reproduction of ROADMAP D5 with wifitrx alone (no mmw60 code).

wifitrx's own chains (TxParams / RxParams defaults, the LPF corners from
``recommended_lpf_corner_hz``, the DAC at the chain rate), its default
``LoopbackPath`` (6 ns), ``cal.sequence.capture_aligned`` and
``cal.sequence.score_views``, on its 11be 80 MHz scoring waveform with the
clock times K (the same active and pilot tones at K x 78.125 kHz).

Part 1 runs that path at 160 MHz (fs 640 MS/s) and at 2.56 GHz (fs 5.12
GS/s): the loopback delay in samples, what ``align_delay`` returns with
capture_aligned's window (``max_lag = n_guard // 2 = 32``) and with a wider
one, the linear phase ramp left across the tones, and the two views.
Part 2 isolates the estimator: the scoring frame delayed by a known
residual (no chain, AWGN only) read by ``score_views``.

Runs from this repository with ``python tools/repro_d5_wifitrx.py``; inside
wifi_trx_cal, drop the ``sys.path`` line (``import wifitrx`` resolves there).
"""
from __future__ import annotations

import dataclasses
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src" / "mmw60" / "vendor"))

import wifitrx  # noqa: E402
from wifitrx.cal.sequence import agc_for_loopback, capture_aligned, score_views, scoring_frame  # noqa: E402
from wifitrx.cal.sync import align_delay, compensate_delay  # noqa: E402
from wifitrx.chain.loopback import LoopbackPath, recommended_loopback_atten_db, run_loopback  # noqa: E402
from wifitrx.chain.params import RxParams, TxParams, recommended_lpf_corner_hz  # noqa: E402
from wifitrx.chain.rx import RxChain  # noqa: E402
from wifitrx.chain.tx import TxChain  # noqa: E402
from wifitrx.impairments.analog_filter import TunableLPF  # noqa: E402
from wifitrx.impairments.converters import DACParams  # noqa: E402
from wifitrx.waveform.ofdm import OFDMConfig, demodulate_ofdm  # noqa: E402
from wifitrx.waveform.pilots import pilot_positions  # noqa: E402
from wifitrx.waveform.tone_plan import contiguous  # noqa: E402


def upclocked_11be80(k: int, oversampling: int = 2, n_symbols: int = 8) -> OFDMConfig:
    """11be 80 MHz (64-QAM, GI 1/16) with the clock times k: same tones and pilots."""
    base = OFDMConfig(bandwidth_hz=80e6, subcarrier_spacing_hz=78.125e3, cp_fraction=1 / 16, qam_order=64,
                      n_symbols=n_symbols, oversampling=oversampling, window_fraction=1 / 32)
    tones = base.active_tone_indices()
    plan = contiguous(base.n_active, pilots=tones[pilot_positions(base)])
    return dataclasses.replace(base, bandwidth_hz=80e6 * k, subcarrier_spacing_hz=78.125e3 * k, tone_plan=plan)


def chains(bw: float, fs: float) -> tuple[TxChain, RxChain]:
    tx = TxChain(TxParams(bandwidth_hz=bw, dac=DACParams(fs_conv_hz=fs),
                          lpf=TunableLPF(fc_nominal_hz=recommended_lpf_corner_hz(bw, "tx"))), fs)
    rx = RxChain(RxParams(bandwidth_hz=bw, lpf=TunableLPF(fc_nominal_hz=recommended_lpf_corner_hz(bw, "rx"))), fs)
    return tx, rx


def ramp(y: np.ndarray, frame, n: int) -> tuple[float, float]:
    """Linear part of the per-tone channel phase (peak to peak, rad) and |mean e^(j phase)|."""
    syms = demodulate_ofdm(y[frame.preamble_len:], frame.data)[:n]
    ref = frame.data.tx_symbols[:n]
    h = np.sum(np.conj(ref) * syms, 0) / np.sum(np.abs(ref) ** 2, 0)
    ph = np.unwrap(np.angle(h))
    i = np.arange(ph.size)
    return float(np.ptp(np.polyval(np.polyfit(i, ph, 1), i))), float(np.abs(np.mean(np.exp(1j * ph))))


def part1() -> None:
    print("part 1: wifitrx chains, default LoopbackPath (6 ns), capture_aligned -> score_views")
    print(f"{'case':<26} {'true delay':>10} {'max_lag':>7} {'lag_total':>9} {'ramp':>6} {'coh':>5} "
          f"{'evm_db':>7} {'modem':>7}")
    for k, os_ in ((2, 4), (32, 2)):                 # 160 MHz at 640 MS/s (B38's rate); 2.56 GHz at 5.12 GS/s
        cfg = upclocked_11be80(k, oversampling=os_)
        bw, fs = cfg.bandwidth_hz, cfg.sample_rate_hz
        tx, rx = chains(bw, fs)
        path = LoopbackPath(atten_db=recommended_loopback_atten_db(bw))
        frame, cols, pilots = scoring_frame(cfg)
        drive = 0.12
        x = frame.x * drive
        agc_for_loopback(tx, rx, path, x)
        n_warm, n_guard = 512, 64
        xp = np.concatenate([x[-n_warm:], x, x[:n_guard]])
        cap = run_loopback(tx, rx, xp, path, seed=0)
        true = align_delay(xp, cap, max_lag=4096)[2]["lag_total"]
        for max_lag, label in ((n_guard // 2, "capture_aligned"), (4 * n_guard, "wider window")):
            if max_lag == n_guard // 2:
                y = capture_aligned(tx, rx, path, x, seed=0)            # wifitrx's own call
                tot = align_delay(xp, cap, max_lag=max_lag)[2]["lag_total"]
            else:
                tot = align_delay(xp, cap, max_lag=max_lag)[2]["lag_total"]
                y = compensate_delay(cap, tot, n_warm, len(x))
            y = y / (np.vdot(x, y) / np.vdot(x, x)) / drive
            v = score_views(y, frame, cols, pilots, cfg.n_symbols)
            r, c = ramp(y, frame, cfg.n_symbols)
            print(f"{bw / 1e6:6g} MHz, {label:<15} {true:10.2f} {max_lag:7d} {tot:9.2f} {r:6.2f} {c:5.2f} "
                  f"{v['evm_db']:7.2f} {v['evm_modem_db']:7.2f}")


def part2() -> None:
    print("\npart 2: the 2.56 GHz scoring frame delayed by a known residual, AWGN at 30 dB, no chain")
    print(f"{'residual (samples)':<20} {'ramp':>6} {'coh':>5} {'evm_db':>7} {'modem':>7}")
    cfg = upclocked_11be80(32)
    frame, cols, pilots = scoring_frame(cfg)
    rng = np.random.default_rng(1)
    x = frame.x
    n = x.size
    f = np.fft.fftfreq(n)
    noise = (rng.standard_normal(n) + 1j * rng.standard_normal(n)) * np.sqrt(np.mean(np.abs(x) ** 2) / 2 / 1e3)
    for d in (0.0, 0.5, 1.0, 2.0, 3.0):
        y = np.fft.ifft(np.fft.fft(x) * np.exp(-2j * np.pi * f * d)) + noise      # cyclic delay by d samples
        v = score_views(y, frame, cols, pilots, cfg.n_symbols)
        r, c = ramp(y, frame, cfg.n_symbols)
        print(f"{d:<20.1f} {r:6.2f} {c:5.2f} {v['evm_db']:7.2f} {v['evm_modem_db']:7.2f}")


if __name__ == "__main__":
    print(f"wifitrx {wifitrx.__version__}")
    part1()
    part2()
