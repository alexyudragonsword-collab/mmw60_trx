"""Example 05 — 11be coded PER on the upclocked zero-IF chain (ROADMAP A2).

The 11be bases now carry the EHT data field (LDPC, ``phy/eht.py``), so the
rows of the comparison table that were EVM-only get a packet error rate.
Base 802.11be 80 MHz × K = 4 / 8 (320 / 640 MHz at 60.48 GHz), 4096-byte
packets, MCS 0 / 4 / 7 (BPSK 1/2, 16-QAM 3/4, 64-QAM 5/6), three sets:

- **ideal**: no CFO, ideal LO, ideal PA, converters / IQ / leakage off, flat
  channel — the LDPC decoder against AWGN;
- **impaired**: the shared 60 GHz front end as example 04 has it (Rapp at
  OBO 8 dB, Liu's phase noise, 40 ppm, converters at ENOB(fs_eff), the
  uncalibrated IQ mismatch), flat channel;
- **no PA**: the same with the PA ideal — the cap in the comparison table
  is the PA's, so this set says what the back-off costs in MCS.

The cross-check this example exists for: the analytic MCS cap of example 04
(the EVM floor 3 dB under the MCS TX-EVM limit) against where the PER
curves actually give up.  A cap of MCS2 means MCS4 impaired should never
reach PER 1e-2, and MCS0 should.

    python examples/05_11be_ldpc_per.py [--quick] [--jobs N]
"""
from __future__ import annotations

import argparse
import dataclasses as dc
import math
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from mmw60 import ENGINE_BANNER, __version__, spec                             # noqa: E402
from mmw60.config import ChannelConfig, zero_if_60ghz                          # noqa: E402
from mmw60.frontend import Frontend60                                          # noqa: E402
from mmw60.frontend.grid import (analytic_floors, decoder_cap, decoder_floor_db, max_mcs_for_floor,  # noqa: E402
                                 pa_isolated_evm_db)
from mmw60.phy.ldpc import active_kernel                                       # noqa: E402
from mmw60.sim.curves import CurveSpec, run_curves, save_results, sweep_line   # noqa: E402
from mmw60.sim.link import LinkSim, evm_at                                     # noqa: E402

OUT = HERE / "output"
TARGET = 1e-2
BASE_BW = 80e6
KS = (4, 8)
CAP_KS = (4, 8, 16, 32)
MCSS = (0, 4, 7)
GRIDS = {0: [-2.0 + x for x in range(0, 8)],            # −2 … 5 dB
         4: [10.0 + x for x in range(0, 9)],            # 10 … 18 dB
         7: [18.0 + x for x in range(0, 11)]}           # 18 … 28 dB
FLAT = ChannelConfig(model="flat")


def no_pa(cfg):
    return dc.replace(cfg, frontend=dc.replace(cfg.frontend, pa=dc.replace(cfg.frontend.pa, model="ideal")))


def specs(quick: bool) -> list[CurveSpec]:
    mp, me = (6, 2) if quick else (150, 10)
    out = []
    for k in ((8,) if quick else KS):
        for mcs in ((0,) if quick else MCSS):
            grid = GRIDS[mcs][::3] if quick else GRIDS[mcs]
            cfg = dc.replace(zero_if_60ghz(k=k, mcs=mcs, standard="11be", bandwidth_hz=BASE_BW), channel=FLAT)
            out.append(CurveSpec(f"11be 80M x{k:<2} MCS{mcs} ideal", cfg.ideal(), grid, mp, me,
                                 tags={"k": k, "mcs": mcs, "set": "ideal"}))
            out.append(CurveSpec(f"11be 80M x{k:<2} MCS{mcs} impaired", cfg, grid, mp, me,
                                 tags={"k": k, "mcs": mcs, "set": "impaired"}))
            if not quick:
                out.append(CurveSpec(f"11be 80M x{k:<2} MCS{mcs} no PA", no_pa(cfg), grid, mp, me,
                                     tags={"k": k, "mcs": mcs, "set": "no_pa"}))
    return out


def main(argv=None) -> int:
    print(ENGINE_BANNER)
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--jobs", type=int, default=max(1, min(4, os.cpu_count() or 1)))
    a = ap.parse_args(argv)
    quick = a.quick or os.environ.get("MMW60_SMOKE") == "1"
    t0 = time.time()
    print(f"mmw60 {__version__}; LDPC kernel: {active_kernel()}; {'QUICK (numbers meaningless)' if quick else 'full size'}")
    sim = LinkSim(dc.replace(zero_if_60ghz(k=8, mcs=0, standard="11be", bandwidth_hz=BASE_BW), channel=FLAT))
    d = sim.describe()
    fe = sim.frontend
    print(f"11be 80 MHz base x K at {sim.cfg.carrier_hz / 1e9:.2f} GHz, 4096 B, {sim.cfg.xo_ppm_tx:g}+{sim.cfg.xo_ppm_rx:g} ppm "
          f"-> CFO {d['cfo_hz'] / 1e6:.3f} MHz; FEC {d['fec']} (max {sim.cfg.rx.ldpc_max_iterations} iterations, "
          f"alpha {sim.cfg.rx.ldpc_minsum_scale:g}); PA {d['pa']} OBO {d['pa_obo_db']:g} dB from {d['pa_obo_reference']} -> "
          f"Pout {d['frontend']['pout_dbm']:g} dBm; LO IPN {d['frontend']['lo_ipn_dbc']:.1f} dBc; channel flat")
    print("K    BW[MHz]  fs_eff[GS/s]  SCS[MHz]  T_sym[ns]  MCS  N_DBPS   symbols/packet  codewords  L   shortened  punctured")
    from mmw60.phy.eht import eht_mcs, ldpc_encoding_params
    for k in KS:
        for mcs in MCSS:
            m = eht_mcs(mcs, BASE_BW)
            p = ldpc_encoding_params(16 + 8 * 4096, m)
            phy = zero_if_60ghz(k=k, standard="11be", bandwidth_hz=BASE_BW).upclocked()
            print(f"{k:<4} {phy.bandwidth_eff / 1e6:7.0f}  {phy.fs_eff / 1e9:11.2f}  {phy.scs_eff / 1e6:8.3f}  "
                  f"{phy.t_symbol_eff * 1e9:9.0f}  {mcs:<4} {m.n_dbps:7.0f}   {p.n_sym:14d}  {p.n_cw:9d}  {p.l_ldpc}  "
                  f"{p.n_shrt:9d}  {p.n_punc:9d}")

    print("\n== the analytic cap of example 04 for these cells (floor 3 dB under the MCS TX-EVM limit) ==")
    pa_evm = pa_isolated_evm_db(fe.pa_model, fe.obo_db, fe.obo_reference)
    caps, floors = {}, {}
    for k in KS:
        cfg = dc.replace(zero_if_60ghz(k=k, standard="11be", bandwidth_hz=BASE_BW), channel=FLAT)
        a_imp = analytic_floors(cfg, fe, pa_evm)
        fe_np = Frontend60.from_config(no_pa(cfg))
        a_np = analytic_floors(no_pa(cfg), fe_np, None)
        caps[k] = (max_mcs_for_floor(a_imp["floor_db"], "11be"), max_mcs_for_floor(a_np["floor_db"], "11be"))
        floors[k] = (a_imp["floor_db"], a_np["floor_db"])
        print(f"  K={k}: impaired floor {a_imp['floor_db']:.1f} dB -> cap MCS{caps[k][0]}; "
              f"no PA floor {a_np['floor_db']:.1f} dB -> cap MCS{caps[k][1]}")

    print(f"\n== PER vs SNR ({'quick' if quick else 'up to 150 packets or 10 errors per point'}; "
          "SNR = per active subcarrier Es/N0) ==")
    results = run_curves(specs(quick), TARGET, a.jobs, log=lambda s: print(s, flush=True))
    print("\ncurve                               SNR @ PER 1e-2      SNR:PER points")
    for r in results:
        print(sweep_line(r))
    print("\n== SNR at PER 1e-2 [dB]: ideal / impaired / no PA; the example-04 cap (floor 3 dB under the TX-EVM limit) "
          "and the floor-as-noise prediction (effective SNR = 1 / (1/SNR + 10^(floor/10)) must reach the ideal threshold) ==")
    print("K   MCS      ideal   impaired      no PA   cap(imp) cap(noPA)  cap verdict          floor-as-noise: impaired  no PA")
    at = {(r["tags"]["k"], r["tags"]["mcs"], r["tags"]["set"]): r["snr_at_target"] for r in results}

    def from_floor(ideal_db, floor_db):
        if ideal_db is None:
            return None
        lin = 10 ** (-ideal_db / 10) - 10 ** (floor_db / 10)
        return None if lin <= 0 else -10 * math.log10(lin)

    for k in (KS if not quick else (8,)):
        for mcs in (MCSS if not quick else (0,)):
            cells = [at.get((k, mcs, s)) for s in ("ideal", "impaired", "no_pa")]
            cap_i, cap_n = caps[k]
            pred_i = "reachable" if mcs <= (cap_i if cap_i is not None else -1) else "beyond cap"
            got_i = "never" if cells[1] is None else "reached"
            agree = (pred_i == "reachable") == (got_i == "reached")
            fl = [from_floor(cells[0], floors[k][0]), from_floor(cells[0], floors[k][1])]
            print(f"{k:<3} {mcs:<5} " + "  ".join(f"{'never' if c is None else f'{c:.2f}':>9}" for c in cells)
                  + f"   MCS{cap_i}     MCS{cap_n}     {pred_i + ' / ' + got_i:<20} "
                  + "  ".join(f"{'never' if c is None else f'{c:.2f}':>9}" for c in fl)
                  + f"   ({'agree' if agree else 'cap DISAGREES'})")
    print("The floor-as-noise prediction is the one to compare with the impaired / no-PA columns: the TX-EVM-limit cap is a "
          "conformance figure, not the decoder's tolerance (cairn/comparison-table.md §6).")
    # ---- the decoder cap of the grid / comparison table, checked where it lands
    print("\n== the decoder cap (frontend/grid.py::decoder_cap, thresholds from data/spec/per_thresholds.yaml), checked: "
          "impaired PER at the cap MCS and one MCS above it ==")
    print("K   BW[MHz]  floor   cap    T[dB]  SNR needed (predicted)  measured @ PER 1e-2   one MCS above: predicted  measured")
    cap_specs, cap_rows = [], []
    mp, me = (6, 2) if quick else (150, 10)
    for k in ((8,) if quick else CAP_KS):
        cfg = dc.replace(zero_if_60ghz(k=k, standard="11be", bandwidth_hz=BASE_BW), channel=FLAT)
        td = evm_at(cfg, None, n_packets=1, frontend=fe)["evm_db"]
        floor = decoder_floor_db(analytic_floors(cfg, fe, pa_evm)["floor_db"], td)
        d = decoder_cap(floor, "11be", BASE_BW)
        if d["mcs"] is None:
            cap_rows.append((k, floor, None, None, None, None))
            continue
        above = d["mcs"] + 1
        t_above = spec.per_threshold_db("11be", BASE_BW, above)
        pred_above = from_floor(t_above, floor)
        cap_rows.append((k, floor, d, above, t_above, pred_above))
        for mcs, centre in ((d["mcs"], d["required_snr_db"]), (above, pred_above if pred_above is not None else t_above + 6)):
            grid = [round(centre - 2 + i, 2) for i in range(0, 7 if not quick else 2, 1 if not quick else 3)]
            cap_specs.append(CurveSpec(f"cap check x{k:<2} MCS{mcs}", dc.replace(cfg, phy=dc.replace(cfg.phy, mcs=mcs)),
                                       grid, mp, me, tags={"k": k, "mcs": mcs, "set": "cap"}))
    cap_res = run_curves(cap_specs, TARGET, a.jobs, log=lambda s: None)
    got = {(r["tags"]["k"], r["tags"]["mcs"]): r["snr_at_target"] for r in cap_res}
    fmt = lambda v: "never" if v is None else f"{v:.2f}"  # noqa: E731
    for k, floor, d, above, t_above, pred_above in cap_rows:
        bw = BASE_BW * k / 1e6
        if d is None:
            print(f"{k:<3} {bw:7.0f}  {floor:5.1f}   none")
            continue
        print(f"{k:<3} {bw:7.0f}  {floor:5.1f}   MCS{d['mcs']:<2}  {d['threshold_db']:5.2f}  {d['required_snr_db']:10.2f}"
              f"              {fmt(got.get((k, d['mcs']))):>8}              MCS{above}: {fmt(pred_above):>8}   {fmt(got.get((k, above))):>8}")
    print("floor = the worse of the analytic floor and the time-domain EVM of the cell (frontend/grid.py::decoder_floor_db); "
          "'never' above the cap means the floor is over that MCS's ideal threshold or the sweep's 4 dB over the prediction "
          "was not enough.")
    results = results + cap_res
    OUT.mkdir(exist_ok=True)
    save_results(results, OUT / "05_sweeps.json")
    print(f"\nwrote {OUT / '05_sweeps.json'}  [{time.time() - t0:.0f}s]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
