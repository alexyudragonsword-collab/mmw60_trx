"""Diagnostic (ROADMAP D5): the final check's loopback read three ways on the
two wide chains, at the pinned wifitrx.

- 2.56 GHz: example 03's last column (K = 32 on an 11be 80 MHz base,
  fs 5.12 GS/s, the preset front end calibrated at its back-off, DPD on as
  in the full run of example 03);
- 2.16 GHz: example 15 section 7 (the ay chain at 5.28 GS/s, probe
  11be 80 MHz x 22, no DPD).

Per chain: wifitrx's isolation view (the per-tone equaliser first since
0.7.45), the order it used before (common phase first), its modem view, the linear phase ramp across the band and the
residual delay it implies, and the coherence of the tone phases.  Reading
only: nothing here changes the library or the vendored wifitrx.

    python tools/diag_d5_views.py [--no-dpd]
"""
from __future__ import annotations

import argparse
import time

import numpy as np

from mmw60 import __version__
from mmw60.calcheck import ay_probe_config, loopback_views, run_cal_at, run_cal_ay
from mmw60.config import ay_60ghz, zero_if_60ghz
from mmw60.frontend import Frontend60
from mmw60.vendor import wifitrx


def _delay(v: dict, span_hz: float, fs: float) -> tuple[float, float]:
    """Residual delay (ns, samples) implied by a linear phase ramp of
    ``phase_ramp_rad`` across ``span_hz`` of occupied tones."""
    tau = v["phase_ramp_rad"] / (2 * np.pi * span_hz)
    return tau * 1e9, tau * fs


def _row(label: str, v: dict, span_hz: float, fs: float, dt: float) -> None:
    ns, smp = _delay(v, span_hz, fs)
    print(f"{label:<34} {v['isolation_db']:9.2f} {v['isolation_cpe_first_db']:9.2f} {v['modem_db']:7.2f} "
          f"{v['phase_ramp_rad']:7.2f} {ns:7.3f} {smp:6.2f} {v['cpe_coherence']:6.2f}   [{dt:.0f}s]")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-dpd", action="store_true", help="2.56 GHz without the DPD step (the guarding test's setting)")
    a = ap.parse_args(argv)
    print(f"mmw60 {__version__}; vendored wifitrx {wifitrx.__version__}")
    print(f"{'chain':<34} {'isolation':>9} {'CPE first':>9} {'modem':>7} {'ramp':>7} {'ns':>7} {'samp':>6} {'coh':>6}")

    t0 = time.time()
    fe = Frontend60.from_config(zero_if_60ghz(k=8))
    run = run_cal_at(fe, 32, 80e6, with_dpd=not a.no_dpd, standard="11be", obo_db=fe.obo_db)
    v = loopback_views(run)
    occupied = (run.chains[2].n_active - 1) * run.chains[2].subcarrier_spacing_hz
    _row(f"2.56 GHz, fs 5.12 GS/s{'' if a.no_dpd else ', DPD'}", v, occupied, 5.12e9, time.time() - t0)

    t0 = time.time()
    base = ay_60ghz("ay_sc", 16)
    fe = Frontend60.from_config(base)
    run = run_cal_ay(fe, base)
    v = loopback_views(run)
    cfg = run.chains[2]
    _, _, p = ay_probe_config()
    occupied = (cfg.n_active - 1) * cfg.subcarrier_spacing_hz
    _row(f"ay 2.16 GHz, fs 5.28 GS/s (probe x{int(p['k'])})", v, occupied, 5.28e9, time.time() - t0)
    print("isolation = wifitrx cal/sequence.score_views evm_db (the per-tone equaliser, then each symbol's common "
          "phase; since 0.7.45); CPE first = the order before (common phase over all tones, then the equaliser); "
          "modem = score_views evm_modem_db.  ramp = the linear part of the loopback channel phase across the "
          "occupied tones; ns / samp = the residual delay it implies; coh = |mean of e^(j phase)| over the tones")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
