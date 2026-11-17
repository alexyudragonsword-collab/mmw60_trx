"""Measure the decoder's own PER threshold of every coded EDMG MCS (SC and
OFDM) and write ``src/mmw60/data/spec/ay_per_thresholds.yaml`` (source: derived).

    python tools/measure_ay_thresholds.py --jobs 4 --cache DIR   # SC and OFDM (~1.5 h, 4 cores; resumable)
    python tools/measure_ay_thresholds.py --waveform ay_ofdm --jobs 4 --cache DIR   # one waveform; the other kept
    python tools/measure_ay_thresholds.py --waveform ay_sc --only 14 --only 16
    python tools/measure_ay_thresholds.py --check           # re-measure and compare with the file (exit 1 beyond --tol)

The threshold of an MCS is the in-band SNR (over the occupied band: SC
the 1.76 GHz chip rate, OFDM the used tones; the same reading as
``ay.edmg.ideal_threshold_db``) at which the PER of a 4096-byte PSDU
crosses 1e-2 on the **ideal** chain (``ay.coding.threshold_config``:
``ay_60ghz`` ideal, flat channel), the PSDU in whole codewords of the
MCS's 672-bit code (``ay.coding.ay_code``: spec_sources#33's DMG
matrices, EDMG's own code at 7/8).  The receiver is the preset's (Golay
channel estimate, SC MMSE / OFDM per-tone zero forcing, max-log LLRs,
normalised min-sum).  OFDM's bits go onto the data tones in order
(assumed.ay_ofdm_tone_order): on a flat channel every tone has the same
SNR and the order does not change the PER.  The grid starts 0.5 dB under
the Shannon bound of the MCS's bits per chip or tone and runs in 0.5 dB
steps; the two points that bracket PER 1e-2 run on to
``--refine-errors`` packet errors as in ``tools/measure_thresholds.py``,
and the file keeps each threshold's 95 % bootstrap interval from the
counts.

Every EDMG MCS of both waveforms: SC MCS 1 through dmg.data_encoding's
rho = 2 codeword (``ay.coding.RepetitionCode``), OFDM's DCM MCS 1-10
through ``ay.dcm`` (the static pairing; both spec_sources#43).  These are
properties of this code and receiver, not of a standard.
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


WAVEFORMS = ("ay_sc", "ay_ofdm")


def mcs_list(waveform: str = "ay_sc") -> list[int]:
    """The MCS with a coded payload here: every MCS of the waveform."""
    return [e.mcs for e in edmg.mcs_table(waveform)]


def grid_for(mcs: int, step: float, span_db: float = 8.0, waveform: str = "ay_sc") -> list[float]:
    """From 0.5 dB under the Shannon bound of the MCS's bits per chip / tone."""
    e = edmg.mcs_entry(waveform, mcs)
    eta = float(e.code_rate) * np.log2(e.order) / e.repetition
    lo = 10.0 * np.log10(2.0 ** eta - 1.0) - 0.5
    lo = np.floor(lo / step) * step
    return [round(float(lo + i * step), 3) for i in range(int(round(span_db / step)) + 1)]


#: how often a sweep that stopped above the target is run again further up
RESTARTS = 3
#: an interval wider than this sends the points just outside the bracket on as well
CI_MAX_DB = 0.5


def _run_on_neighbours(cfg, sw: dict, job: dict) -> dict:
    """The crossing's interval can spill past the bracket onto a point that
    stopped at a handful of packets (MCS 11 OFDM: 9.5 dB at PER 0.0097 next
    to 10 dB at 2 errors in 200).  Run the point on each side of the
    bracket on to ``refine_errors`` errors or ``refine_max_packets``
    packets, on a seed of its own."""
    import numpy as np

    from mmw60.sim.link import LinkSim, _bracket
    idx = _bracket(sw["per"], TARGET)
    if not idx:
        return sw
    sim = LinkSim(cfg)
    rng = np.random.default_rng(int(cfg.seed) + 100)
    for i in (min(idx) - 1, max(idx) + 1):
        if not 0 <= i < len(sw["per"]):
            continue
        n, err = sw["n_packets"][i], sw["n_errors"][i]
        while n < job["refine_max_packets"] and err < job["refine_errors"]:
            pe, _ = coding.sweep_packet(sim, sw["snr_db"][i], rng)
            n += 1
            err += int(pe)
        sw["n_packets"][i], sw["n_errors"][i], sw["per"][i] = n, err, err / n
    sw["neighbours_run_on"] = True
    return sw


def _one(job: dict) -> dict:
    """One MCS.  ``per_sweep`` stops at the first point with no error in
    ``max_packets``; when the refinement then finds errors there (the true
    PER was just above the target: 0 in 200 at PER 1.6 % happens 4 % of the
    time) the curve has no crossing.  Such a sweep is run again from two
    steps under its last point, on a new seed, and the new sweep replaces it
    (``restarts`` says how often)."""
    cfg = coding.threshold_config(job["mcs"], waveform=job["waveform"])
    kw = dict(refine_errors=job["refine_errors"], refine_max_packets=job["refine_max_packets"], target=TARGET,
              packet=coding.sweep_packet)
    sw = per_sweep(cfg, job["grid"], job["max_packets"], job["min_errors"], **kw)
    restarts = 0
    while snr_at_per(sw, TARGET) is None and sw["n_errors"] and sw["n_errors"][-1] > 0 and restarts < RESTARTS:
        restarts += 1
        step = job["grid"][1] - job["grid"][0]
        start = sw["snr_db"][-1] - 2 * step
        grid = [round(start + i * step, 3) for i in range(int(round(6.0 / step)) + 1)]
        sw = per_sweep(cfg, grid, job["max_packets"], job["min_errors"], seed=cfg.seed + restarts, **kw)
    sw["restarts"] = restarts
    ci = snr_at_per_ci(sw, TARGET)
    wide = ci and ci.get("lo_db") is not None and ci.get("hi_db") is not None
    if wide and ci["hi_db"] - ci["lo_db"] > CI_MAX_DB:
        sw = _run_on_neighbours(cfg, sw, job)
        ci = snr_at_per_ci(sw, TARGET)
    return {"mcs": job["mcs"], "sweep": sw, "snr_at_target": snr_at_per(sw, TARGET), "ci": ci}


def _from_counts(mcs: int, sweep: dict) -> dict:
    """A finished MCS from its sweep's counts: the crossing and its interval
    depend on nothing else."""
    return {"mcs": mcs, "sweep": sweep, "snr_at_target": snr_at_per(sweep, TARGET), "ci": snr_at_per_ci(sweep, TARGET)}


def measure(mcs: list[int], step: float, max_packets: int, min_errors: int, jobs: int,
            refine_errors: int, refine_max_packets: int, log=print, cache_dir: Path | None = None,
            waveform: str = "ay_sc") -> tuple[dict, dict, list]:
    """``cache_dir``: every finished MCS's sweep is kept there as JSON (the
    settings in its name) and a rerun reuses it — a stopped run resumes."""
    tag = f"s{step:g}_p{max_packets}_e{min_errors}_r{refine_errors}_{refine_max_packets}"
    todo, out = [], []
    for m in mcs:
        name = f"mcs{m}_{tag}.json" if waveform == "ay_sc" else f"{waveform}_mcs{m}_{tag}.json"
        f = None if cache_dir is None else Path(cache_dir) / name
        if f is not None and f.exists():
            out.append(_from_counts(m, json.loads(f.read_text())))
            continue
        todo.append({"mcs": m, "grid": grid_for(m, step, waveform=waveform), "max_packets": max_packets,
                     "min_errors": min_errors, "refine_errors": refine_errors,
                     "refine_max_packets": refine_max_packets, "file": f, "waveform": waveform})
    if cache_dir is not None:
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
    with get_context("fork").Pool(max(1, jobs)) as pool:
        for r in pool.imap_unordered(_one, todo):
            f = next(j["file"] for j in todo if j["mcs"] == r["mcs"])
            if f is not None:
                f.write_text(json.dumps(r["sweep"]))
            v = r["snr_at_target"]
            log(f"{waveform} MCS{r['mcs']:>2}: {'never' if v is None else f'{v:.2f} dB'}  "
                + (f"(restarted {r['sweep']['restarts']}x) " if r["sweep"].get("restarts") else "")
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


def document(tables: dict, cis: dict, step: float, max_packets: int, min_errors: int, refine_errors: int,
             refine_max_packets: int) -> dict:
    return {
        "source": "derived",
        "cite": (f"tools/measure_ay_thresholds.py (mmw60 {__version__}): PER {TARGET:g} crossing of a 4096-byte PSDU "
                 f"in whole 672-bit codewords (ay.coding.ay_code: spec_sources#33's dmg.ldpc_matrices, "
                 f"edmg.ldpc_672_r7_8 at 7/8) on the ideal chain (ay.coding.threshold_config: ay_60ghz ideal, "
                 f"flat channel), in-band SNR over the occupied band (SC the chip rate, OFDM the used tones; OFDM "
                 f"bits on the data tones in order, assumed.ay_ofdm_tone_order), {step:g} dB steps from 0.5 dB "
                 f"under the Shannon "
                 f"bound, up to {max_packets} packets or {min_errors} errors per point; the two points bracketing "
                 f"PER {TARGET:g} run on to {refine_errors} errors or {refine_max_packets} packets (a sweep left "
                 f"without a crossing that way is run again from two steps under its last point on a new seed, up "
                 f"to {RESTARTS} times; an interval wider than {CI_MAX_DB:g} dB runs the points just outside the "
                 f"bracket on as well), log-linear interpolation; ci_db = 95 % bootstrap interval of the crossing "
                 f"from the counts"),
        "note": ("本库接收机自己的 EDMG 门限（Golay 信道估计；SC 的 MMSE、OFDM 的逐音迫零；"
                 "max-log LLR、归一化 min-sum），"
                 "不是规范数；接收机或码一改就要重量（tests/test_ay_link.py 复量一个点）。"
                 "SC MCS 1（重复 2）按 dmg.data_encoding 的 rho = 2 码字（数据、数据 ⊕ PN、校验，spec_sources#43），"
                 "接收端两份 LLR 相加、补的零已知。"
                 "OFDM 的 DCM 档（MCS 1–10）按 edmg.ofdm_modulation_mapping 的静态配对（spec_sources#43），"
                 "一对子载波联合解映射。"
                 "不含扰码与填充规则（载荷是随机比特，扰码不改 PER；PSDU 按整数个码字发）。"
                 "OFDM 的比特按顺序放在数据子载波上（assumed.ay_ofdm_tone_order）：flat 信道上各子载波 SNR 相同，"
                 "比特怎么排不改 PER；多径下还缺 16 / 64-QAM 的符号内交织置换（公开文件没有）。"),
        "packet_bytes": 4096,
        "target_per": TARGET,
        "thresholds_db": tables,
        "ci_db": cis,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--waveform", choices=WAVEFORMS + ("both",), default="both")
    ap.add_argument("--only", type=int, action="append", help="one MCS of --waveform (repeatable)")
    ap.add_argument("--step", type=float, default=0.5)
    ap.add_argument("--max-packets", type=int, default=200)
    ap.add_argument("--min-errors", type=int, default=15)
    ap.add_argument("--refine-errors", type=int, default=REFINE_ERRORS)
    ap.add_argument("--refine-max-packets", type=int, default=REFINE_MAX_PACKETS)
    ap.add_argument("--cache", type=Path, default=None, help="keep each finished MCS here and reuse it (resumable)")
    ap.add_argument("--check", action="store_true",
                    help="compare a fresh measurement with the file instead of writing it")
    ap.add_argument("--tol", type=float, default=0.7, help="--check: allowed |difference| in dB")
    a = ap.parse_args(argv)
    t0 = time.time()
    wfs = WAVEFORMS if a.waveform == "both" else (a.waveform,)
    if a.only and len(wfs) > 1:
        ap.error("--only needs a single --waveform")
    tables, cis = {}, {}
    for wf in wfs:
        tables[wf], cis[wf], _ = measure(a.only or mcs_list(wf), a.step, a.max_packets, a.min_errors,
                                         a.jobs, a.refine_errors, a.refine_max_packets, cache_dir=a.cache,
                                         waveform=wf)
    if a.check:
        ref = yaml.safe_load(OUT.read_text(encoding="utf-8"))["thresholds_db"]
        bad = 0
        for wf, table in tables.items():
            for m, v in table.items():
                r = ref.get(wf, {}).get(m)
                d = None if (v is None or r is None) else v - r
                ok = (v is None and r is None) or (d is not None and abs(d) <= a.tol)
                bad += not ok
                print(f"{wf} MCS{m:>2}: file {r}, now {v}, {'ok' if ok else 'DIFFERS'}")
        print(f"[{time.time() - t0:.0f}s]")
        return 1 if bad else 0
    old = yaml.safe_load(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    keep_t, keep_c = dict(old.get("thresholds_db", {})), dict(old.get("ci_db", {}))
    for wf in wfs:
        if a.only:
            keep_t.setdefault(wf, {}).update(tables[wf])
            keep_c.setdefault(wf, {}).update(cis[wf])
        else:
            keep_t[wf], keep_c[wf] = tables[wf], cis[wf]
    order = [wf for wf in WAVEFORMS if wf in keep_t]
    doc = document({wf: keep_t[wf] for wf in order}, {wf: keep_c.get(wf, {}) for wf in order}, a.step,
                   a.max_packets, a.min_errors, a.refine_errors, a.refine_max_packets)
    OUT.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=160), encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)} [{time.time() - t0:.0f}s]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
