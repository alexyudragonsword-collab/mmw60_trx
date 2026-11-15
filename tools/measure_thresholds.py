"""Measure the decoder's own PER threshold of every coded MCS and write
``src/mmw60/data/spec/per_thresholds.yaml`` (source: derived).

    python tools/measure_thresholds.py --jobs 4 --cache DIR   # all bases, ~50 min on 4 cores (resumable with --cache)
    python tools/measure_thresholds.py --only 11be:80e6       # one base
    python tools/measure_thresholds.py --check                # re-measure and compare with the file (exit 1 beyond --tol)
    python tools/measure_thresholds.py --refine-errors 0      # the old single pass (~15 min; no refinement, wider intervals)

The threshold of an MCS is the SNR (per active subcarrier Es/N0) at which
the PER of a 4096-byte packet crosses 1e-2 on the **ideal** zero-IF chain
(no CFO, ideal LO, ideal PA, converters / IQ / leakage off, flat channel):
what this library's receiver — LTF channel estimate with the span chosen
per packet, cross-symbol pilot CPE (the ``zero_if_60ghz`` preset's
receiver, ``config.improved_rx``), BCC Viterbi or min-sum LDPC — needs when
the only impairment is thermal noise.  The two grid points that bracket
PER 1e-2 are run on to ``--refine-errors`` packet errors (or
``--refine-max-packets`` packets) as in example 00 (finding C3, ROADMAP C6),
and the file records each threshold's 95 % bootstrap interval from the
counts (``snr_at_per_ci``) next to it.  The "decoder cap" of the grid and of the comparison table
(``frontend/grid.py::decoder_cap``) treats a front end's EVM floor as one
more noise term against these numbers; example 05 shows that prediction
matching the impaired PER curves.

They are properties of this code, not of a standard: every one of them
moves if the receiver changes (the cross-symbol CPE and the automatic
smoothing span lowered them by 0.1–2.8 dB over the milestone-0 receiver),
which is why the file records the library version and why
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
#: the bracketing points of every curve run on to this many errors or packets (example 00's numbers)
REFINE_ERRORS, REFINE_MAX_PACKETS = 60, 3000
K_MEASURE = 4          # the ideal chain is K-invariant (tests/test_frontend.py::test_law2_ideal_chain_*)


def grid_for(mcs: int, step: float) -> list[float]:
    """From 6 dB under wifitrx's (pessimistic) ``snr_req_db`` to 3 dB over it."""
    lo = MCS_TABLE[mcs].snr_req_db - 6.0
    n = int(round(9.0 / step)) + 1
    return [round(lo + i * step, 3) for i in range(n)]


def specs(only: list[tuple[str, float]] | None, step: float, max_packets: int, min_errors: int,
          refine_errors: int = 0, refine_max_packets: int = 0) -> list[CurveSpec]:
    out = []
    for std, bws in BASES.items():
        for bw in bws:
            if only and (std, bw) not in only:
                continue
            for mcs in MCS_RANGE[std]:
                cfg = dc.replace(zero_if_60ghz(k=K_MEASURE, mcs=mcs, standard=std, bandwidth_hz=bw).ideal(),
                                 channel=ChannelConfig(model="flat"))
                out.append(CurveSpec(f"{std} {bw / 1e6:g}M MCS{mcs}", cfg, grid_for(mcs, step), max_packets,
                                     min_errors, tags={"standard": std, "bandwidth_hz": bw, "mcs": mcs},
                                     refine_errors=refine_errors, refine_max_packets=refine_max_packets))
    return out


def measure(only, step, max_packets, min_errors, jobs, log=print, refine_errors: int = 0,
            refine_max_packets: int = 0, cache_dir=None) -> tuple[dict, dict]:
    """``(thresholds, intervals)``: ``{std: {bw: {mcs: dB or None}}}`` and the
    same nesting of ``[lo, hi]`` (None where the curve does not cross)."""
    res = run_curves(specs(only, step, max_packets, min_errors, refine_errors, refine_max_packets),
                     TARGET, jobs, log=log, cache_dir=cache_dir)
    table: dict = {}
    ci: dict = {}
    for r in res:
        t = r["tags"]
        v = r["snr_at_target"]
        key = (t["standard"], float(t["bandwidth_hz"]), int(t["mcs"]))
        table.setdefault(key[0], {}).setdefault(key[1], {})[key[2]] = None if v is None else round(float(v), 2)
        c = r.get("ci") or {}
        ci.setdefault(key[0], {}).setdefault(key[1], {})[key[2]] = (
            None if v is None or c.get("lo_db") is None else [round(float(c["lo_db"]), 2), round(float(c["hi_db"]), 2)])
    return table, ci


def document(table: dict, step: float, max_packets: int, min_errors: int, ci: dict | None = None,
             refine_errors: int = 0, refine_max_packets: int = 0) -> dict:
    refine = (f"; the two points bracketing PER {TARGET:g} run on to {refine_errors} errors or {refine_max_packets} packets"
              if refine_errors else "")
    return {
        "source": "derived",
        "cite": (f"tools/measure_thresholds.py (mmw60 {__version__}): PER {TARGET:g} crossing of a 4096-byte packet on the "
                 f"ideal zero-IF chain (zero_if_60ghz(k={K_MEASURE}).ideal(), flat channel), SNR per active subcarrier, "
                 f"{step:g} dB steps, up to {max_packets} packets or {min_errors} errors per point{refine}, "
                 f"log-linear interpolation; ci_db = 95 % bootstrap interval of the crossing from the counts"),
        "note": ("本库接收机自己的门限（LTF 信道估计、平滑跨度逐包自动选 + 跨符号导频 CPE 合并 + BCC Viterbi / min-sum LDPC，"
                 "即 zero_if_60ghz 预设的接收机），不是规范数：接收机一改就要重量（tests/test_thresholds.py 复量一个点）。"
                 "夹住 1e-2 的两点续跑到更多错包，每个门限的 95 % 区间记在 ci_db（只含计数统计，不含 0.5 dB 网格上插值的误差）。"
                 "11ac 只有 20 MHz 基准有编码数据域。"),
        "packet_bytes": 4096,
        "target_per": TARGET,
        "thresholds_db": table,
        "ci_db": ci or {},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--only", action="append", help="standard:bandwidth, e.g. 11be:80e6 (repeatable)")
    ap.add_argument("--step", type=float, default=0.5)
    ap.add_argument("--max-packets", type=int, default=200)
    ap.add_argument("--min-errors", type=int, default=15)
    ap.add_argument("--refine-errors", type=int, default=REFINE_ERRORS,
                    help="run the two points bracketing the target on to this many errors (0 = off)")
    ap.add_argument("--refine-max-packets", type=int, default=REFINE_MAX_PACKETS)
    ap.add_argument("--cache", type=Path, default=None,
                    help="keep each finished curve in this directory and reuse it (a stopped run resumes)")
    ap.add_argument("--check", action="store_true", help="compare a fresh measurement with the file instead of writing it")
    ap.add_argument("--tol", type=float, default=0.7, help="--check: allowed |difference| in dB")
    a = ap.parse_args(argv)
    only = None
    if a.only:
        only = [(s.split(":")[0], float(s.split(":")[1])) for s in a.only]
    t0 = time.time()
    table, ci = measure(only, a.step, a.max_packets, a.min_errors, a.jobs, refine_errors=a.refine_errors,
                        refine_max_packets=a.refine_max_packets, cache_dir=a.cache)
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
                    print(f"{std} {bw / 1e6:g}M MCS{mcs}: file {r} measured {v} {ci[std][bw][mcs]} "
                          f"diff {d if d is None else round(d, 2)}{flag}")
        print(f"[{time.time() - t0:.0f}s] {bad} point(s) outside ±{a.tol:g} dB")
        return 1 if bad else 0
    if only and OUT.exists():           # merge a partial measurement into the existing file
        doc = yaml.safe_load(OUT.read_text(encoding="utf-8"))
        for std, by_bw in table.items():
            for bw, by_mcs in by_bw.items():
                doc["thresholds_db"].setdefault(std, {})[bw] = by_mcs
                doc.setdefault("ci_db", {}).setdefault(std, {})[bw] = ci[std][bw]
        table, ci = doc["thresholds_db"], doc["ci_db"]
    OUT.write_text(yaml.safe_dump(document(table, a.step, a.max_packets, a.min_errors, ci, a.refine_errors,
                                           a.refine_max_packets), sort_keys=False, allow_unicode=True, width=160),
                   encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)}  [{time.time() - t0:.0f}s]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
