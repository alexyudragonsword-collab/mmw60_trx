"""PER-curve bookkeeping shared by the examples and the external check:
curve specs → sweeps (optionally in parallel processes) → table rows, with
the SNR at the target PER interpolated from each sweep."""
from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Mmw60Config
from .link import per_sweep, snr_at_per


@dataclass
class CurveSpec:
    name: str
    cfg: Mmw60Config
    snr_db: list
    max_packets: int = 400
    min_errors: int = 20
    stop_below: float = 1e-3
    tags: dict = field(default_factory=dict)


def _run(spec_dict: dict) -> dict:
    cfg = Mmw60Config.from_dict(spec_dict["cfg"])
    sw = per_sweep(cfg, spec_dict["snr_db"], spec_dict["max_packets"],
                   spec_dict["min_errors"], spec_dict["stop_below"])
    return {"name": spec_dict["name"], "tags": spec_dict["tags"], "cfg": spec_dict["cfg"],
            "sweep": sw, "snr_at_target": snr_at_per(sw, spec_dict["target"])}


def run_curves(specs: list[CurveSpec], target: float = 1e-2, jobs: int = 1,
               log=print) -> list[dict]:
    todo = [{"name": s.name, "cfg": s.cfg.to_dict(), "snr_db": list(map(float, s.snr_db)),
             "max_packets": s.max_packets, "min_errors": s.min_errors,
             "stop_below": s.stop_below, "tags": s.tags, "target": target} for s in specs]
    out: list[dict] = []
    if jobs > 1:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            for r in pool.map(_run, todo):
                out.append(r)
                log(f"  done {r['name']}: SNR@{target:g} = {_fmt(r['snr_at_target'])}")
    else:
        for d in todo:
            r = _run(d)
            out.append(r)
            log(f"  done {r['name']}: SNR@{target:g} = {_fmt(r['snr_at_target'])}")
    return out


def _fmt(v) -> str:
    return "never" if v is None else f"{v:.2f} dB"


def sweep_line(r: dict) -> str:
    sw = r["sweep"]
    pts = " ".join(f"{s:g}:{p:.3g}" for s, p in zip(sw["snr_db"], sw["per"]))
    return f"{r['name']:<34} SNR@1e-2 {_fmt(r['snr_at_target']):>9}   {pts}"


def save_results(results: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, indent=1, sort_keys=True))


def load_results(path: Path) -> list[dict]:
    return json.loads(Path(path).read_text())
