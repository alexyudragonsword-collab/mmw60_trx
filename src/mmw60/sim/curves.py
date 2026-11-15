"""PER-curve bookkeeping shared by the examples and the external check:
curve specs → sweeps (optionally in parallel processes) → table rows, with
the SNR at the target PER interpolated from each sweep."""
from __future__ import annotations

import hashlib
import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Mmw60Config
from .link import per_sweep, snr_at_per, snr_at_per_ci


@dataclass
class CurveSpec:
    name: str
    cfg: Mmw60Config
    snr_db: list
    max_packets: int = 400
    min_errors: int = 20
    stop_below: float = 1e-3
    tags: dict = field(default_factory=dict)
    #: run the two points bracketing the target on to this many packet errors
    #: (0 = off) or ``refine_max_packets`` packets (finding C3)
    refine_errors: int = 0
    refine_max_packets: int = 0


def _run(spec_dict: dict) -> dict:
    cfg = Mmw60Config.from_dict(spec_dict["cfg"])
    sw = per_sweep(cfg, spec_dict["snr_db"], spec_dict["max_packets"],
                   spec_dict["min_errors"], spec_dict["stop_below"],
                   refine_errors=spec_dict.get("refine_errors", 0),
                   refine_max_packets=spec_dict.get("refine_max_packets", 0), target=spec_dict["target"])
    return {"name": spec_dict["name"], "tags": spec_dict["tags"], "cfg": spec_dict["cfg"],
            "sweep": sw, "snr_at_target": snr_at_per(sw, spec_dict["target"]),
            "ci": snr_at_per_ci(sw, spec_dict["target"])}


def _source_digest() -> str:
    """sha256 over every ``.py`` file of the installed ``mmw60`` package
    (vendored copies included): a cached curve is only reused by the very
    code that produced it."""
    root = Path(__file__).resolve().parents[1]
    h = hashlib.sha256()
    for f in sorted(root.rglob("*.py")):
        h.update(f.relative_to(root).as_posix().encode())
        h.update(f.read_bytes())
    return h.hexdigest()


def _run_cached(spec_dict: dict) -> dict:
    """``_run`` behind a one-file-per-curve cache.  A sweep is seeded from
    its own config only, so a curve does not depend on which run, process
    or order produced it; both a hit and a miss return the JSON round trip,
    so a run split over several invocations prints what one run would."""
    path = Path(spec_dict.pop("cache_path"))
    if path.exists():
        return json.loads(path.read_text())
    r = json.loads(json.dumps(_run(spec_dict)))
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(r, sort_keys=True))
    tmp.replace(path)
    return r


def run_curves(specs: list[CurveSpec], target: float = 1e-2, jobs: int = 1,
               log=print, cache_dir: Path | None = None) -> list[dict]:
    """Run every spec; with ``cache_dir`` each finished curve is kept on
    disk (keyed by the spec and the package source) and reused, so a long
    run stopped part-way resumes where it was."""
    todo = [{"name": s.name, "cfg": s.cfg.to_dict(), "snr_db": list(map(float, s.snr_db)),
             "max_packets": s.max_packets, "min_errors": s.min_errors,
             "stop_below": s.stop_below, "tags": s.tags, "target": target,
             "refine_errors": s.refine_errors, "refine_max_packets": s.refine_max_packets} for s in specs]
    run = _run
    if cache_dir is not None:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        src = _source_digest()
        for d in todo:
            key = hashlib.sha256((src + json.dumps(d, sort_keys=True)).encode()).hexdigest()[:24]
            d["cache_path"] = str(cache_dir / f"{key}.json")
        run = _run_cached
    out: list[dict] = []
    if jobs > 1:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            for r in pool.map(run, todo):
                out.append(r)
                log(f"  done {r['name']}: SNR@{target:g} = {_fmt(r['snr_at_target'])}")
    else:
        for d in todo:
            r = run(d)
            out.append(r)
            log(f"  done {r['name']}: SNR@{target:g} = {_fmt(r['snr_at_target'])}")
    return out


def _fmt(v) -> str:
    return "never" if v is None else f"{v:.2f} dB"


def sweep_line(r: dict) -> str:
    sw = r["sweep"]
    pts = " ".join(f"{s:g}:{p:.3g}" for s, p in zip(sw["snr_db"], sw["per"]))
    return f"{r['name']:<34} SNR@1e-2 {_fmt(r['snr_at_target']):>9}   {pts}"


def ci_text(r: dict) -> str:
    """'[lo, hi] (errors a/b)' of a result's bootstrap interval, for tables."""
    ci = r.get("ci") or {}
    if ci.get("lo_db") is None:
        return "[  —  ,   —  ]"
    eb = ci.get("errors_at_bracket")
    tail = "" if not eb else f" ({eb[0]}/{eb[1]} errors)"
    return f"[{ci['lo_db']:5.2f}, {ci['hi_db']:5.2f}]{tail}"


def save_results(results: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, indent=1, sort_keys=True))


def load_results(path: Path) -> list[dict]:
    return json.loads(Path(path).read_text())
