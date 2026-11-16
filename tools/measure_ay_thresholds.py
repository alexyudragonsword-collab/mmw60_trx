"""Measure the decoder's own PER threshold of every coded EDMG SC MCS and
write ``src/mmw60/data/spec/ay_per_thresholds.yaml`` (source: derived).

    python tools/measure_ay_thresholds.py --jobs 4 --cache DIR   # every SC MCS at repetition 1 (~1 h on 4 cores; resumable)
    python tools/measure_ay_thresholds.py --only 14 --only 16
    python tools/measure_ay_thresholds.py --check           # re-measure and compare with the file (exit 1 beyond --tol)

The threshold of an MCS is the in-band SNR (over the 1.76 GHz chip rate,
the same reading as ``ay.edmg.ideal_threshold_db``) at which the PER of a
4096-byte PSDU crosses 1e-2 on the **ideal** SC chain
(``ay.coding.threshold_config``: ``ay_60ghz`` ideal, flat channel), the
PSDU in whole codewords of the MCS's 672-bit code (``ay.coding.sc_code``:
spec_sources#33's DMG matrices, EDMG's own code at 7/8).  The receiver is
the preset's (Golay channel estimate, SC MMSE, max-log LLRs, normalised
min-sum).  The grid starts 0.5 dB under the Shannon bound of the MCS's
bits per chip and runs in 0.5 dB steps; the two points that bracket PER
1e-2 run on to ``--refine-errors`` packet errors as in
``tools/measure_thresholds.py``, and the file keeps each threshold's 95 %
bootstrap interval from the counts.

MCS 1 (repetition 2) is left out: the repetition procedure
(dmg.data_encoding, rho = 2) is not built.  These are properties of this
code and receiver, not of a standard.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from multiprocessing import get_context
from pathlib import Path

import numpy as np
import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from mmw60 import __version__                                       # noqa: E402
from mmw60.ay import coding, edmg                                   # noqa: E402
from mmw60.sim.link import per_sweep, snr_at_per, snr_at_per_ci     # noqa: E402

OUT = REPO / "src" / "mmw60" / "data" / "spec" / "ay_per_thresholds.yaml"
TARGET = 1e-2
REFINE_ERRORS, REFINE_MAX_PACKETS = 60, 3000


def mcs_list() -> list[int]:
    """The SC MCS with a coded payload here (repetition 1)."""
    return [e.mcs for e in edmg.mcs_table("ay_sc") if e.repetition == 1]


def grid_for(mcs: int, step: float, span_db: float = 8.0) -> list[float]:
    """From 0.5 dB under the Shannon bound of the MCS's bits per chip."""
    e = edmg.mcs_entry("ay_sc", mcs)
    eta = float(e.code_rate) * np.log2(e.order) / e.repetition
    lo = 10.0 * np.log10(2.0 ** eta - 1.0) - 0.5
    lo = np.floor(lo / step) * step
    return [round(float(lo + i * step), 3) for i in range(int(round(span_db / step)) + 1)]


def _one(job: dict) -> dict:
    cfg = coding.threshold_config(job["mcs"])
    sw = per_sweep(cfg, job["grid"], job["max_packets"], job["min_errors"], refine_errors=job["refine_errors"],
                   refine_max_packets=job["refine_max_packets"], target=TARGET, packet=coding.sweep_packet)
    ci = snr_at_per_ci(sw, TARGET)
    return {"mcs": job["mcs"], "sweep": sw, "snr_at_target": snr_at_per(sw, TARGET), "ci": ci}


def _from_counts(mcs: int, sweep: dict) -> dict:
    """A finished MCS from its sweep's counts: the crossing and its interval
    depend on nothing else."""
    return {"mcs": mcs, "sweep": sweep, "snr_at_target": snr_at_per(sweep, TARGET), "ci": snr_at_per_ci(sweep, TARGET)}


def measure(mcs: list[int], step: float, max_packets: int, min_errors: int, jobs: int,
            refine_errors: int, refine_max_packets: int, log=print, cache_dir: Path | None = None
            ) -> tuple[dict, dict, list]:
    """``cache_dir``: every finished MCS's sweep is kept there as JSON (the
    settings in its name) and a rerun reuses it — a stopped run resumes."""
    tag = f"s{step:g}_p{max_packets}_e{min_errors}_r{refine_errors}_{refine_max_packets}"
    todo, out = [], []
    for m in mcs:
        f = None if cache_dir is None else Path(cache_dir) / f"mcs{m}_{tag}.json"
        if f is not None and f.exists():
            out.append(_from_counts(m, json.loads(f.read_text())))
            continue
        todo.append({"mcs": m, "grid": grid_for(m, step), "max_packets": max_packets, "min_errors": min_errors,
                     "refine_errors": refine_errors, "refine_max_packets": refine_max_packets, "file": f})
    if cache_dir is not None:
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
    with get_context("fork").Pool(max(1, jobs)) as pool:
        for r in pool.imap_unordered(_one, todo):
            f = next(j["file"] for j in todo if j["mcs"] == r["mcs"])
            if f is not None:
                f.write_text(json.dumps(r["sweep"]))
            v = r["snr_at_target"]
            log(f"MCS{r['mcs']:>2}: {'never' if v is None else f'{v:.2f} dB'}  "
                + " ".join(f"{s:g}:{e}/{n}" for s, e, n in zip(r["sweep"]["snr_db"], r["sweep"]["n_errors"],
                                                               r["sweep"]["n_packets"])), flush=True)
            out.append(r)
    out.sort(key=lambda r: r["mcs"])
    table = {r["mcs"]: None if r["snr_at_target"] is None else round(float(r["snr_at_target"]), 2) for r in out}
    ci = {}
    for r in out:
        c = r["ci"] or {}
        ci[r["mcs"]] = (None if r["snr_at_target"] is None or c.get("lo_db") is None
                        else [round(float(c["lo_db"]), 2), round(float(c["hi_db"]), 2)])
    return table, ci, out


def document(table: dict, ci: dict, step: float, max_packets: int, min_errors: int, refine_errors: int,
             refine_max_packets: int) -> dict:
    return {
        "source": "derived",
        "cite": (f"tools/measure_ay_thresholds.py (mmw60 {__version__}): PER {TARGET:g} crossing of a 4096-byte PSDU "
                 f"in whole 672-bit codewords (ay.coding.sc_code: spec_sources#33's dmg.ldpc_matrices, "
                 f"edmg.ldpc_672_r7_8 at 7/8) on the ideal SC chain (ay.coding.threshold_config: ay_60ghz ideal, "
                 f"flat channel), in-band SNR over the chip rate, {step:g} dB steps from 0.5 dB under the Shannon "
                 f"bound, up to {max_packets} packets or {min_errors} errors per point; the two points bracketing "
                 f"PER {TARGET:g} run on to {refine_errors} errors or {refine_max_packets} packets, log-linear "
                 f"interpolation; ci_db = 95 % bootstrap interval of the crossing from the counts"),
        "note": ("本库接收机自己的 EDMG SC 门限（Golay 信道估计、SC MMSE、max-log LLR、归一化 min-sum），不是规范数；"
                 "接收机或码一改就要重量（tests/test_ay_link.py 复量一个点）。MCS 1（重复 2）没有：重复的编码步骤没建。"
                 "不含扰码与填充规则（载荷是随机比特，扰码不改 PER；PSDU 按整数个码字发）。"),
        "packet_bytes": 4096,
        "target_per": TARGET,
        "thresholds_db": {"ay_sc": table},
        "ci_db": {"ay_sc": ci},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--only", type=int, action="append", help="one SC MCS (repeatable)")
    ap.add_argument("--step", type=float, default=0.5)
    ap.add_argument("--max-packets", type=int, default=200)
    ap.add_argument("--min-errors", type=int, default=15)
    ap.add_argument("--refine-errors", type=int, default=REFINE_ERRORS)
    ap.add_argument("--refine-max-packets", type=int, default=REFINE_MAX_PACKETS)
    ap.add_argument("--cache", type=Path, default=None, help="keep each finished MCS here and reuse it (resumable)")
    ap.add_argument("--check", action="store_true", help="compare a fresh measurement with the file instead of writing it")
    ap.add_argument("--tol", type=float, default=0.7, help="--check: allowed |difference| in dB")
    a = ap.parse_args(argv)
    t0 = time.time()
    mcs = a.only or mcs_list()
    table, ci, _ = measure(mcs, a.step, a.max_packets, a.min_errors, a.jobs, a.refine_errors, a.refine_max_packets,
                           cache_dir=a.cache)
    if a.check:
        ref = yaml.safe_load(OUT.read_text(encoding="utf-8"))["thresholds_db"]["ay_sc"]
        bad = 0
        for m, v in table.items():
            r = ref.get(m)
            d = None if (v is None or r is None) else v - r
            ok = (v is None and r is None) or (d is not None and abs(d) <= a.tol)
            bad += not ok
            print(f"MCS{m:>2}: file {r}, now {v}, {'ok' if ok else 'DIFFERS'}")
        print(f"[{time.time() - t0:.0f}s]")
        return 1 if bad else 0
    if a.only and OUT.exists():
        doc = yaml.safe_load(OUT.read_text(encoding="utf-8"))
        doc["thresholds_db"]["ay_sc"].update(table)
        doc["ci_db"]["ay_sc"].update(ci)
    else:
        doc = document(table, ci, a.step, a.max_packets, a.min_errors, a.refine_errors, a.refine_max_packets)
    OUT.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=160), encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)} [{time.time() - t0:.0f}s]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
