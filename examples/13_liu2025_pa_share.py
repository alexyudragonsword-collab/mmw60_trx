"""Example 13 — Liu 2025's MCS4 floor: is the PA the paper's, and whose is the floor?

The published Fig. 3 (cairn/external-validation.md §3–§4, ROADMAP C12): the
impaired MCS4 curves flatten at PER 0.105 (8x) / 0.053 (16x) by 31 dB while
every set of example 00 reaches 1e-2; example 12 showed that no channel
K-factor gives that floor together with the steep MCS0 / 1 curves, and that
on fading channels the floor is the PA's.  This asks the question the other
way round, without tuning anything (AGENTS: no tuning to match):

1. what the receiver sees with no noise — the PA at the literal OBO 8 dB from
   Psat, the phase noise, the CFO after its estimators, each alone and all
   together; the PA against its back-off (and sampled at 1x, a sensitivity);
2. the paper's floor read through the paper's own "ideal" curves: if the
   impairments act on the decoder like extra noise, each impaired point at
   SNR s with PER p says SINR = ideal⁻¹(p), so the impairments' share is
   1/SINR − 1/s.  Compared with section 1 and turned into a back-off;
3. the same mapping in this library's engine (K = 8, flat channel): its
   own ideal curves plus section 1's no-noise EVM predict the impaired
   curves at OBO 8 / 7 / 6 / 5 dB, next to the simulated ones — the check that
   "acts like extra noise" holds here, and the back-off at which this
   receiver would floor where the paper's does.

    python examples/13_liu2025_pa_share.py [--quick] [--jobs N]
"""
from __future__ import annotations

import argparse
import dataclasses as dc
import os
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from mmw60 import ENGINE_BANNER, __version__, spec                # noqa: E402
from mmw60.config import ChannelConfig, liu2025_table2            # noqa: E402
from mmw60.sim.curves import CurveSpec, run_curves, sweep_line    # noqa: E402
from mmw60.sim.link import evm_at                                 # noqa: E402

TARGET = 1e-2
FLAT = ChannelConfig(model="flat")
AXIS_END_DB = 31.0                              # the paper's last MCS4 point
FLOOR_FROM_DB = 25.0                            # impaired MCS4 points read as "the floor region"
OBOS_EVM = (10.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0)
OBOS_SIM = (8.0, 7.0, 6.0, 5.0)
GRIDS = {0: [float(x) for x in range(0, 11)],               # 0 .. 10 dB
         1: [float(x) for x in range(3, 14)],               # 3 .. 13 dB
         4: [float(x) for x in range(13, 32, 2)]}           # 13 .. 31 dB, the paper's axis end
GRID_IDEAL4 = [float(x) for x in range(12, 23)]             # 12 .. 22 dB


def _db(x: float) -> float:
    return float(10 * np.log10(x))


def _lin(db: float) -> float:
    return 10.0 ** (db / 10.0)


def per_on(snr: list, per: list, s: float) -> float | None:
    """PER of a falling curve at SNR ``s`` (log-PER interpolation); None past its last positive point."""
    pts = [(a, b) for a, b in zip(snr, per) if b > 0]
    if not pts:
        return None
    if s <= pts[0][0]:
        return pts[0][1]
    for (a0, b0), (a1, b1) in zip(pts, pts[1:]):
        if a0 <= s <= a1:
            return float(10 ** (np.log10(b0) + (s - a0) / (a1 - a0) * (np.log10(b1) - np.log10(b0))))
    return None


def snr_on(snr: list, per: list, p: float) -> float | None:
    """SNR at which a falling curve reaches PER ``p``; None outside the drawn range."""
    pts = [(a, b) for a, b in zip(snr, per) if b > 0]
    for (a0, b0), (a1, b1) in zip(pts, pts[1:]):
        if b0 >= p >= b1 and b0 > b1:
            return float(a0 + (np.log10(p) - np.log10(b0)) / (np.log10(b1) - np.log10(b0)) * (a1 - a0))
    return None


def curve_of(r: dict) -> tuple[list, list]:
    """A simulated sweep as (SNR, PER) for the mapping; a point with no errors counts as half an
    error in its packets (so the log-PER interpolation has a finite end)."""
    sw = r["sweep"]
    per = [p if p > 0 else 0.5 / n for p, n in zip(sw["per"], sw["n_packets"])]
    return list(sw["snr_db"]), per


def impaired_from_ideal(ideal: tuple, d_lin: float) -> tuple[float | None, float | None]:
    """The impaired curve the mapping predicts: (SNR at PER 1e-2 or None for a floor, PER at the axis end)."""
    need = snr_on(*ideal, TARGET)
    at_1e2 = None
    if need is not None and 1 / _lin(need) - d_lin > 0:
        at_1e2 = -_db(1 / _lin(need) - d_lin)
    sinr_end = -_db(1 / _lin(AXIS_END_DB) + d_lin)
    return at_1e2, per_on(*ideal, sinr_end)


def fmt(v, f="{:.2f}"):
    return "never" if v is None else f.format(v)


def paper_curves() -> dict:
    out = {}
    for c in spec.fig4_readings()["curves"]:
        pts = c["points"]
        out[(c["set"], c["k"], c["mcs"])] = {"snr": [x for x, _ in pts], "per": [y for _, y in pts],
                                            "at": c["per_at_1e-2_snr_db"], "floor": c.get("floor_per")}
    return out


def base(k: int, mcs: int, obo: float = 8.0, oversampling: int = 2):
    cfg = dc.replace(liu2025_table2(k=k, mcs=mcs), channel=FLAT)
    return dc.replace(cfg, phy=dc.replace(cfg.phy, oversampling=oversampling),
                      frontend=dc.replace(cfg.frontend, pa=dc.replace(cfg.frontend.pa, obo_db=float(obo))))


def only(cfg, pa: bool, pn: bool, cfo: bool):
    lo = cfg.lo if pn else dc.replace(cfg.lo, phase_noise=dc.replace(cfg.lo.phase_noise, apply="off"))
    fe = cfg.frontend if pa else dc.replace(cfg.frontend, pa=dc.replace(cfg.frontend.pa, model="ideal"))
    return dc.replace(cfg, lo=lo, frontend=fe, xo_ppm_tx=cfg.xo_ppm_tx if cfo else 0.0,
                      xo_ppm_rx=cfg.xo_ppm_rx if cfo else 0.0)


def main(argv=None) -> int:
    print(ENGINE_BANNER)
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--jobs", type=int, default=max(1, min(4, os.cpu_count() or 1)))
    a = ap.parse_args(argv)
    quick = a.quick or os.environ.get("MMW60_SMOKE") == "1"
    t0 = time.time()
    n_pk = 1 if quick else 4
    mp, me = (6, 2) if quick else (300, 20)
    c0 = base(8, 4)
    print(f"mmw60 {__version__}; {'QUICK (numbers meaningless)' if quick else 'full size'}; Liu 2025 Table II on a "
          f"flat channel: PA {c0.frontend.pa.model} OBO {c0.frontend.pa.obo_db:g} dB from "
          f"{c0.frontend.pa.obo_reference}, PN {c0.lo.phase_noise.psd0_dbchz:g} dBc/Hz at "
          f"{c0.lo.phase_noise.apply}, CFO {c0.cfo_hz / 1e6:.2f} MHz with the L-STF / L-LTF estimators")

    # ---------------------------------------------------------------- 1. no noise
    print(f"\n== 1. what the receiver sees with no noise (data-tone EVM after equalisation, {n_pk} packets, "
          "MCS4 frames) ==")
    nf: dict = {}
    for k in (8, 16):
        c = base(k, 4)
        for name, kw in (("all on", dict(pa=True, pn=True, cfo=True)), ("PA only", dict(pa=True, pn=False, cfo=False)),
                         ("PN only", dict(pa=False, pn=True, cfo=False)),
                         ("CFO only", dict(pa=False, pn=False, cfo=True))):
            nf[(k, name)] = evm_at(only(c, **kw), None, n_packets=n_pk)["evm_db"]
        print(f"K = {k:<2}  all on {nf[(k, 'all on')]:7.2f} dB   PA only {nf[(k, 'PA only')]:7.2f}   "
              f"PN only {nf[(k, 'PN only')]:7.2f}   CFO only "
              f"{'< -100' if nf[(k, 'CFO only')] < -100 else format(nf[(k, 'CFO only')], '.2f')}", flush=True)
    pa_obo = {o: evm_at(only(base(8, 4, o), pa=True, pn=False, cfo=False), None, n_packets=n_pk)["evm_db"]
              for o in OBOS_EVM}
    print("PA only against its back-off from Psat (K-independent: the PA has no memory):")
    print("  OBO [dB] " + " ".join(f"{o:7.0f}" for o in OBOS_EVM))
    print("  EVM [dB] " + " ".join(f"{pa_obo[o]:7.2f}" for o in OBOS_EVM))
    os1 = evm_at(only(base(8, 4, 8.0, oversampling=1), pa=True, pn=False, cfo=False), None, n_packets=n_pk)["evm_db"]
    print(f"  sensitivity: the PA applied at 1x sampling (its intermodulation folded into the band) at OBO 8 dB: "
          f"{os1:.2f} dB, {os1 - pa_obo[8.0]:+.2f} dB against 2x")
    all_obo = {o: evm_at(base(8, 4, o), None, n_packets=n_pk)["evm_db"] for o in OBOS_SIM}
    print("all on, K = 8, against the PA's back-off:  "
          + "   ".join(f"OBO {o:g}: {all_obo[o]:.2f}" for o in OBOS_SIM))

    # ---------------------------------------------------------------- 2. the paper, through its own ideal curves
    print(f"\n== 2. the paper's MCS4 floor read through its own 'ideal' curves (impaired points at SNR >= "
          f"{FLOOR_FROM_DB:g} dB; liu2025_fig4.yaml) ==")
    pc = paper_curves()
    print("K   SNR [dB]  impaired PER  -> SINR on its ideal curve  -> impairments' share [dB]")
    implied = {}
    for k in (8, 16):
        imp, idl = pc[("impaired", k, 4)], pc[("ideal", k, 4)]
        ds = []
        for s, p in zip(imp["snr"], imp["per"]):
            if s < FLOOR_FROM_DB:
                continue
            sinr = snr_on(idl["snr"], idl["per"], p)
            if sinr is None:
                continue
            d = 1 / _lin(sinr) - 1 / _lin(s)
            ds.append(d)
            print(f"{k:<3} {s:6.0f}    {p:10.3f}          {sinr:8.2f}                  {_db(d):7.2f}")
        implied[k] = float(np.mean(ds))
    print("\nK   implied share   ours, all on (section 1)   diff   -> the PA's share (minus our PN)   "
          "-> our OBO for it")
    obo_x, evm_y = np.array(OBOS_EVM), np.array([pa_obo[o] for o in OBOS_EVM])
    for k in (8, 16):
        d = implied[k]
        pa_share = d - _lin(nf[(k, "PN only")])
        obo = float(np.interp(_db(pa_share), evm_y, obo_x)) if pa_share > 0 else None     # EVM rises as OBO falls
        print(f"{k:<3} {_db(d):10.2f} dB      {nf[(k, 'all on')]:10.2f} dB           "
              f"{_db(d) - nf[(k, 'all on')]:+5.2f}      {fmt(None if pa_share <= 0 else _db(pa_share)):>8} dB"
              f"                     {fmt(obo, '{:.1f}')} dB")
    print("\nthe same share moves the paper's MCS0 / 1 by (its ideal -> predicted impaired, against its drawn "
          "impaired; SNR at PER 1e-2 [dB]):")
    for k in (8, 16):
        for mcs in (0, 1):
            idl, imp = pc[("ideal", k, mcs)], pc[("impaired", k, mcs)]
            pred = None if idl["at"] is None else -_db(1 / _lin(idl["at"]) - implied[k])
            print(f"  K = {k:<2} MCS{mcs}: ideal {idl['at']:g} -> predicted {fmt(pred)}  (+{pred - idl['at']:.2f}); "
                  f"drawn impaired {imp['at']:g} (+{imp['at'] - idl['at']:.2f})")

    # ---------------------------------------------------------------- 3. the same mapping in this engine
    print(f"\n== 3. the same mapping in this engine: K = 8, flat channel, its own ideal curves plus section 1's "
          f"no-noise EVM, against the simulated impaired curves (up to {mp} packets or {me} errors per point) ==")
    mcss = (0, 4) if quick else (0, 1, 4)
    obos = OBOS_SIM[::3] if quick else OBOS_SIM
    specs = []
    for mcs in mcss:
        g_ideal = GRID_IDEAL4 if mcs == 4 else GRIDS[mcs]
        specs.append(CurveSpec(f"MCS{mcs} ideal", base(8, mcs).ideal(), g_ideal[::4] if quick else g_ideal, mp, me,
                               tags={"mcs": mcs, "obo": None}))
        for o in obos:
            specs.append(CurveSpec(f"MCS{mcs} all on, OBO {o:g}", base(8, mcs, o),
                                   GRIDS[mcs][::4] if quick else GRIDS[mcs], mp, me, tags={"mcs": mcs, "obo": o}))
    res = run_curves(specs, TARGET, a.jobs, log=lambda s: None)
    for r in res:
        print(sweep_line(r))
    ideal = {r["tags"]["mcs"]: curve_of(r) for r in res if r["tags"]["obo"] is None}
    ideal_at = {r["tags"]["mcs"]: r["snr_at_target"] for r in res if r["tags"]["obo"] is None}
    print(f"\nMCS  OBO   no-noise EVM   SNR@1e-2 predicted / simulated     PER at {AXIS_END_DB:g} dB predicted / "
          "simulated")
    for r in res:
        o, mcs = r["tags"]["obo"], r["tags"]["mcs"]
        if o is None:
            print(f"{mcs:<4} ideal                {fmt(r['snr_at_target']):>18}")
            continue
        pred, pend = impaired_from_ideal(ideal[mcs], _lin(all_obo[o]))
        sw = r["sweep"]
        send = sw["per"][-1] if sw["snr_db"] and sw["snr_db"][-1] == AXIS_END_DB else None
        print(f"{mcs:<4} {o:3.0f}   {all_obo[o]:9.2f} dB    {fmt(pred):>8} / {fmt(r['snr_at_target']):<8}            "
              f"{fmt(pend, '{:.3g}') if mcs == 4 else '':>9} / "
              f"{(fmt(send, '{:.3g}') if send is not None else '—') if mcs == 4 else ''}")
    print("predicted = the ideal curve read at SINR = 1 / (1/SNR + EVM²); 'never' = the floor sits above 1e-2; "
          "'—' = the sweep stopped early below 1e-3")
    paper4 = pc[("impaired", 8, 4)]
    print(f"the paper's 8x MCS4: floor PER {paper4['floor']:g} at {paper4['snr'][-1]:g} dB; its ideal needs "
          f"{pc[('ideal', 8, 4)]['at']:g} dB, this engine's flat ideal {fmt(ideal_at.get(4))} dB")
    print(f"\n[{time.time() - t0:.0f}s]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
