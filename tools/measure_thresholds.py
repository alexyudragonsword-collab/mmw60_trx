"""Measure the decoder's own PER threshold of every coded MCS and write
``src/mmw60/data/spec/per_thresholds.yaml`` (source: derived).

    python tools/measure_thresholds.py --jobs 4            # all bases, ~15 min on 4 cores
    python tools/measure_thresholds.py --only 11be:80e6    # one base
    python tools/measure_thresholds.py --check             # re-measure and compare with the file (exit 1 beyond --tol)

The threshold of an MCS is the SNR (per active subcarrier Es/N0) at which
the PER of a 4096-byte packet crosses 1e-2 on the **ideal** zero-IF chain
(no CFO, ideal LO, ideal PA, converters / IQ / leakage off, flat channel):
what this library's receiver — LTF channel estimate, per-symbol pilot CPE,
BCC Viterbi or min-sum LDPC — needs when the only impairment is thermal
noise.  The "decoder cap" of the grid and of the comparison table
(``frontend/grid.py::decoder_cap``) treats a front end's EVM floor as one
more noise term against these numbers; example 05 shows that prediction
matching the impaired PER curves.

They are properties of this code, not of a standard: every one of them
moves if the receiver changes (ROADMAP C1's CPE smoothing would lower
them), which is why the file records the library version and why
``tests/test_thresholds.py`` re-measures one point.  wifitrx's
``link/mcs.py::snr_req_db`` is not used: it is marked unaudited there and
sits 1–3.5 dB above what this receiver measures.
"""
from __future__ import annotations

import argparse
import dataclasses as dc
import sys
import time
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from mmw60 import __version__                                       # noqa: E402
from mmw60.config import ChannelConfig, zero_if_60ghz               # noqa: E402
from mmw60.sim.curves import CurveSpec, run_curves                  # noqa: E402
from mmw60.vendor.wifitrx.link.mcs import MCS_TABLE                 # noqa: E402

OUT = REPO / "src" / "mmw60" / "data" / "spec" / "per_thresholds.yaml"
BASES = {"11ac": (20e6,), "11be": (20e6, 40e6, 80e6, 160e6, 320e6)}
MCS_RANGE = {"11ac": range(0, 9), "11be": range(0, 14)}
TARGET = 1e-2
K_MEASURE = 4          # the ideal chain is K-invariant (tests/test_frontend.py::test_law2_ideal_chain_*)


def grid_for(mcs: int, step: float) -> list[float]:
    """From 6 dB under wifitrx's (pessimistic) ``snr_req_db`` to 3 dB over it."""
    lo = MCS_TABLE[mcs].snr_req_db - 6.0
    n = int(round(9.0 / step)) + 1
    return [round(lo + i * step, 3) for i in range(n)]


def specs(only: list[tuple[str, float]] | None, step: float, max_packets: int, min_errors: int) -> list[CurveSpec]:
    out = []
    for std, bws in BASES.items():
        for bw in bws:
            if only and (std, bw) not in only:
                continue
            for mcs in MCS_RANGE[std]:
                cfg = dc.replace(zero_if_60ghz(k=K_MEASURE, mcs=mcs, standard=std, bandwidth_hz=bw).ideal(),
                                 channel=ChannelConfig(model="flat"))
                out.append(CurveSpec(f"{std} {bw / 1e6:g}M MCS{mcs}", cfg, grid_for(mcs, step), max_packets,
                                     min_errors, tags={"standard": std, "bandwidth_hz": bw, "mcs": mcs}))
    return out


def measure(only, step, max_packets, min_errors, jobs, log=print) -> dict:
    res = run_curves(specs(only, step, max_packets, min_errors), TARGET, jobs, log=log)
    table: dict = {}
    for r in res:
        t = r["tags"]
        v = r["snr_at_target"]
        table.setdefault(t["standard"], {}).setdefault(float(t["bandwidth_hz"]), {})[int(t["mcs"])] = (
            None if v is None else round(float(v), 2))
    return table


def document(table: dict, step: float, max_packets: int, min_errors: int) -> dict:
    return {
        "source": "derived",
        "cite": (f"tools/measure_thresholds.py (mmw60 {__version__}): PER {TARGET:g} crossing of a 4096-byte packet on the "
                 f"ideal zero-IF chain (zero_if_60ghz(k={K_MEASURE}).ideal(), flat channel), SNR per active subcarrier, "
                 f"{step:g} dB steps, up to {max_packets} packets or {min_errors} errors per point, log-linear interpolation"),
        "note": ("本库接收机自己的门限（LTF 信道估计 + 逐符号导频 CPE + BCC Viterbi / min-sum LDPC），不是规范数：接收机一改就要重量"
                 "（tests/test_thresholds.py 复量一个点）。统计散布约 ±0.3 dB（1e-2 处每点十几个错包，见 ROADMAP C3）。"
                 "11ac 只有 20 MHz 基准有编码数据域。"),
        "packet_bytes": 4096,
        "target_per": TARGET,
        "thresholds_db": table,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--only", action="append", help="standard:bandwidth, e.g. 11be:80e6 (repeatable)")
    ap.add_argument("--step", type=float, default=0.5)
    ap.add_argument("--max-packets", type=int, default=200)
    ap.add_argument("--min-errors", type=int, default=15)
    ap.add_argument("--check", action="store_true", help="compare a fresh measurement with the file instead of writing it")
    ap.add_argument("--tol", type=float, default=0.7, help="--check: allowed |difference| in dB")
    a = ap.parse_args(argv)
    only = None
    if a.only:
        only = [(s.split(":")[0], float(s.split(":")[1])) for s in a.only]
    t0 = time.time()
    table = measure(only, a.step, a.max_packets, a.min_errors, a.jobs)
    if a.check:
        ref = yaml.safe_load(OUT.read_text(encoding="utf-8"))["thresholds_db"]
        bad = 0
        for std, by_bw in table.items():
            for bw, by_mcs in by_bw.items():
                for mcs, v in by_mcs.items():
                    r = ref[std][bw][mcs]
                    d = None if (v is None or r is None) else v - r
                    flag = "" if (d is not None and abs(d) <= a.tol) else "  <-- outside tolerance"
                    bad += bool(flag)
                    print(f"{std} {bw / 1e6:g}M MCS{mcs}: file {r} measured {v} diff {d if d is None else round(d, 2)}{flag}")
        print(f"[{time.time() - t0:.0f}s] {bad} point(s) outside ±{a.tol:g} dB")
        return 1 if bad else 0
    if only and OUT.exists():           # merge a partial measurement into the existing file
        doc = yaml.safe_load(OUT.read_text(encoding="utf-8"))
        for std, by_bw in table.items():
            for bw, by_mcs in by_bw.items():
                doc["thresholds_db"].setdefault(std, {})[bw] = by_mcs
        table = doc["thresholds_db"]
    OUT.write_text(yaml.safe_dump(document(table, a.step, a.max_packets, a.min_errors), sort_keys=False,
                                  allow_unicode=True, width=160), encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)}  [{time.time() - t0:.0f}s]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
