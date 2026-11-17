"""Diagnostic (ROADMAP C8): the DPD cliff of the memory study.

Example 07's PA whose memory scales with the signal (wifitrx's reference PA
at the front end's gain / Psat / PAE, taps one sample apart), K = 8 on the
11be 80 MHz base (640 MHz, 1.28 GS/s), wifitrx's own DPD step with
sample-spaced taps, the final check at each back-off from Psat.  At every
back-off this records what the DPD step decided and why:

- ``kept``: the candidate the step programmed (0 = no predistorter, k = the
  k-th ILA pass; wifitrx B40: the best the observation path reads);
- ``observed``: each candidate's per-tone EVM read through the loopback
  (the step's own criterion, ``estimated["observed_evm_db"]``);
- ``true``: the same per-tone EVM read at the PA output for each candidate
  (the step's ``pa_out_metrics``, which a part cannot read);
- ``final TX``: the final check's TX EVM as a standard receiver reads it
  (``final_views["tx_evm_modem_db"]``, example 07's number).

Reading only: the vendored DPD step runs unchanged; this script wraps it to
record the candidates and score each one at the PA output.

    python tools/diag_c8_dpd_cliff.py [--from 6.5] [--to 8.0] [--step 0.1] [--jobs 4] [--k 8]
"""
from __future__ import annotations

import argparse
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np

BASE_HZ, STANDARD = 80e6, "11be"


def _point(args: tuple) -> dict:
    obo, k, tap_spacing, pa_kind, over, genie = args
    from mmw60 import pamemory
    from mmw60.calcheck import run_cal_at
    from mmw60.config import zero_if_60ghz
    from mmw60.frontend import Frontend60
    from mmw60.vendor.wifitrx.cal import dpd_cal, sequence
    from mmw60.vendor.wifitrx.cal.sync import align_delay, compensate_delay
    from mmw60.vendor.wifitrx.metrics import evm
    from mmw60.vendor.wifitrx.waveform.ofdm import demodulate_ofdm

    calls: list[dict] = []
    made: list = []
    original, bounded = sequence.calibrate_dpd, dpd_cal.BoundedDPD

    class Recording(bounded):                          # the vendored class, unchanged; it only remembers itself
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            made.append(self)

    capture = dpd_cal._capture

    def genie_capture(tx, rx, path, x, n_warmup=512, n_guard=64):
        # the PA output itself, aligned as the step aligns its capture: no coupler, no RX chain
        xp = np.concatenate([x[-n_warmup:], x, x[:n_guard]])
        y = tx(xp)
        info = align_delay(xp, y, max_lag=n_guard // 2)[2]
        return compensate_delay(y, info["lag_total"], n_warmup, len(x))

    def wrapped(tx, rx, wf, path=None, **kw):
        made.clear()
        kw.update(over)                                # diagnostic overrides of the step's own arguments
        res = original(tx, rx, wf, path, **kw)
        x = wf.x * kw.get("drive_scale", 0.25)
        kept = tx.dpd

        def pa_out(cand):
            tx.dpd = cand
            y = tx(x)
            g = np.vdot(x, y) / np.vdot(x, x)
            return float(evm(demodulate_ofdm(y / g, wf), wf.tx_symbols, equalize="per_tone").db)

        true = [pa_out(c) for c in [None, *made]]
        tx.dpd = kept
        calls.append({"kept": int(res.estimated["kept_iteration"]),
                      "observed": [float(v) for v in res.estimated["observed_evm_db"]], "true": true,
                      "before": float(res.metrics_before["evm_db"]), "after": float(res.metrics_after["evm_db"]),
                      "passed": bool(res.passed)})
        return res

    sequence.calibrate_dpd, dpd_cal.BoundedDPD = wrapped, Recording
    if genie:
        dpd_cal._capture = genie_capture
    try:
        fe = Frontend60.from_config(zero_if_60ghz(k=8))
        fs_eff = BASE_HZ * k * 2
        pa = pamemory.memory_pa(fe, fs_eff, None) if pa_kind == "scales" else None
        run = run_cal_at(fe, k, BASE_HZ, standard=STANDARD, pa=pa, with_dpd=True, dpd_tap_spacing=tap_spacing,
                         obo_db=obo)
    finally:
        sequence.calibrate_dpd, dpd_cal.BoundedDPD, dpd_cal._capture = original, bounded, capture
    last = calls[-1]
    return {"obo": obo, "obo_read": fe.psat_dbm - run.pout_dbm, "passes": run.passes, "kept": last["kept"],
            "observed": last["observed"], "true": last["true"], "step_after": last["after"],
            "step_before": last["before"], "step_passed": last["passed"],
            "tx": float(run.final_views["tx_evm_modem_db"]), "loop": float(run.final_views["evm_modem_db"])}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="lo", type=float, default=6.5)
    ap.add_argument("--to", dest="hi", type=float, default=8.0)
    ap.add_argument("--step", type=float, default=0.1)
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--tap-spacing", type=int, default=1)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--pa", choices=("scales", "rapp"), default="scales",
                    help="scales: the reference PA, memory scales with the signal; rapp: the preset memoryless PA")
    ap.add_argument("--n-iter", type=int, help="diagnostic: the DPD step's ILA passes (wifitrx default 2)")
    ap.add_argument("--order", type=int, help="diagnostic: the GMP nonlinearity order (wifitrx default 7)")
    ap.add_argument("--memory", type=int, help="diagnostic: the GMP memory depth (wifitrx default 5)")
    ap.add_argument("--genie", action="store_true",
                    help="diagnostic: the ILA observes the PA output directly (aligned; no coupler, no RX chain)")
    a = ap.parse_args(argv)
    over = {key: v for key, v in (("n_iter", a.n_iter), ("order", a.order), ("memory_depth", a.memory))
            if v is not None}
    from mmw60 import __version__
    from mmw60.vendor import wifitrx
    obos = [round(v, 3) for v in np.arange(a.lo, a.hi + a.step / 2, a.step)]
    pa_txt = ("reference PA, memory scales with the signal" if a.pa == "scales"
              else "the preset PA (memoryless Rapp)")
    print(f"mmw60 {__version__}; vendored wifitrx {wifitrx.__version__}; {pa_txt}; "
          f"K = {a.k} on 11be 80 MHz ({BASE_HZ * a.k / 1e6:g} MHz, {2 * BASE_HZ * a.k / 1e9:.2f} GS/s); "
          f"DPD tap spacing {a.tap_spacing}; overrides {over or 'none'}"
          f"{'; genie observation' if a.genie else ''}")
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=a.jobs) as ex:
        rows = list(ex.map(_point, [(o, a.k, a.tap_spacing, a.pa, over, a.genie) for o in obos]))
    n = len(rows[0]["observed"])
    w = 8 * n
    head = " / ".join(str(i) for i in range(n))
    print(f"{'OBO':>5} {'read':>6} {'runs':>4} {'kept':>4}   {'observed ' + head:>{w}}   {'true ' + head:>{w}}  "
          f"{'obs pick':>8} {'true pick':>9} {'final TX':>8} {'loop':>6}")
    for r in rows:
        tpick = int(np.argmin(r["true"]))
        obs = " / ".join(f"{v:6.2f}" for v in r["observed"])
        tru = " / ".join(f"{v:6.2f}" for v in r["true"])
        print(f"{r['obo']:5.1f} {r['obo_read']:6.2f} {r['passes']:4d} {r['kept']:4d}   {obs:>{w}}   {tru:>{w}}  "
              f"{r['kept']:8d} {tpick:9d} {r['tx']:8.2f} {r['loop']:6.2f}")
    print(f"[{time.time() - t0:.0f}s]  OBO = the asked back-off from Psat; read = where the final check landed; runs = "
          "sequence runs to land it; kept = the candidate the DPD step programmed (0 none, k the k-th ILA pass); "
          "observed / true = each candidate's per-tone EVM through the loopback (the step's criterion) / at the PA "
          "output; obs pick / true pick = the argmin of each; final TX = the final check's TX EVM (standard "
          "receiver, example 07's number); loop = the same through the loopback")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
