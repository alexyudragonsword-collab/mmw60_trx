"""The interface's compute layer (the polar_tx / array_tx split: ``guispec`` describes, ``guiutil``
computes, a host dispatches and queues, the page only draws).

Everything here returns plain JSON-able dicts built from the library's own structured results —
``compare.build`` for the comparison table, ``calcheck`` for the calibration runs — so a page, a
command line (``tools/gui_report.py``) and the examples read the same numbers.  Nothing is drawn,
queued or stored here.

A run of this library is slow (a calibration takes minutes), so the interface browses computed
results and recomputes in the background.  Three ideas carry that:

* a **study** is the form: the values of the shared knobs that differ from the presets.  Every row
  of the comparison table is a preset; a study is applied to all of them (``schemes``) and to the
  one ``Frontend60`` they share (``frontend``).  The four *row* knobs (topology, waveform, K, MCS)
  pick a row instead and never make a result stale;
* a result is made of **parts** (``PARTS``), each with the knobs it reads and the parts it is built
  on.  ``tests/test_guiutil.py`` runs every part under a tracer of config reads and requires
  traced <= declared: a knob the code touches and the declaration omits would show a stale number
  as fresh;
* an **envelope** wraps a computed part with the signature of what it read and where it was
  computed (version, commit, vendored pins, spec-table digest); ``freshness`` compares stored
  envelopes with the form as it is now.

Iron rule 1 holds through ``guispec``: a study only ever sets ``Mmw60Config`` fields the form
declares, and a value changed on the form is no longer the source's — its tag reads *assumed*.
"""
from __future__ import annotations

import dataclasses as dc
import hashlib
import json
import math
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from . import ENGINE_BANNER, __version__, arrayreport, calcheck, compare, guispec, spec
from .ay import report as ayreport
from .config import AY_WAVEFORMS, Mmw60Config, zero_if_60ghz
from .frontend import Frontend60
from .frontend.array60 import Array60
from .frontend.grid import pa_isolated_evm_db

#: bump when the shape of a report changes: an envelope of another schema is never fresh
SCHEMA = 1
PACKAGE = Path(__file__).resolve().parent

# ------------------------------------------------------------------ the form: row knobs and shared knobs
#: these four pick a row of the table; the table itself spans them
ROW_KNOBS = ("topology", "waveform", "upclock_k", "phy.mcs")
KNOB = {k.id: k for k in guispec.KNOBS}
#: these apply to every row at once: a study is a set of values for them
SHARED_KNOBS = tuple(k.id for k in guispec.KNOBS if k.id not in ROW_KNOBS)
PRESET_CARRIER_HZ = 60.48e9

#: the spec-table entry behind a shared knob's preset value (None: a plain configuration choice).
#: ``tests/test_guiutil.py`` checks that the preset value is that entry's value
KNOB_SOURCE = {
    "xo_ppm_tx": "liu2025.xo_ppm_tx", "xo_ppm_rx": "liu2025.xo_ppm_rx", "phy.packet_bytes": "liu2025.packet_bytes",
    "lo.phase_noise.psd0_dbchz": "liu2025.pn_psd0_dbchz", "lo.phase_noise.f_pole_hz": "liu2025.pn_f_pole_hz",
    "lo.phase_noise.f_zero_hz": "liu2025.pn_f_zero_hz", "lo.phase_noise.apply": "assumed.pn_apply_sides",
    "frontend.pa.obo_db": "derived.pa60_obo_at_evm_limit_db", "frontend.pa.obo_reference": "assumed.pa_obo_reference",
    "channel.rms_delay_ns": "assumed.cr_rms_delay_ns", "rx.ce_smooth_tones": "assumed.ce_smooth_tones",
    "rx.cpe_window_symbols": "assumed.cpe_window_symbols",
}


def reference_config(carrier_hz: float = PRESET_CARRIER_HZ) -> Mmw60Config:
    """The preset the form's shared knobs show, and the one the shared front end is built from
    (example 04's ``zero_if_60ghz(k=8)``)."""
    return zero_if_60ghz(k=8, carrier_hz=carrier_hz)


def _coerce(knob: guispec.Knob, v):
    if knob.kind == "bool":
        if isinstance(v, str):
            if v.lower() not in ("true", "false", "1", "0"):
                raise ValueError(f"{knob.id}: {v!r} is not a boolean")
            return v.lower() in ("true", "1")
        return bool(v)
    if knob.kind == "choice":
        if v not in knob.choices:
            raise ValueError(f"{knob.id}: {v!r} is not one of {list(knob.choices)}")
        return v
    x = float(v)
    if not math.isfinite(x) or (knob.lo is not None and x < knob.lo) or (knob.hi is not None and x > knob.hi):
        raise ValueError(f"{knob.id}: {v!r} is outside {knob.lo} ... {knob.hi}")
    if knob.kind == "int":
        if x != int(x):
            raise ValueError(f"{knob.id}: {v!r} is not an integer")
        return int(x)
    return x


def study(values: dict | None = None) -> dict:
    """The form as a study: shared knobs only, values coerced and range-checked, entries equal to
    the preset dropped, keys sorted.  ``{}`` is the presets themselves (the accepted results)."""
    ref = reference_config()
    out = {}
    for key in sorted(values or {}):
        if key in ROW_KNOBS:
            raise KeyError(f"{key!r} picks a row of the table; a study holds the shared knobs only")
        if key not in KNOB:
            raise KeyError(f"unknown form field {key!r}")
        v = _coerce(KNOB[key], values[key])
        if v != KNOB[key].default(ref):
            out[key] = v
    return out


def apply_study(cfg: Mmw60Config, st: dict) -> Mmw60Config:
    """``cfg`` with the study's values set (``guispec.set_path``).  The carrier is left alone on a
    sub-7 row (the K = 1 WiFi 7 chain is the table's 6 GHz reference): the matrix takes the carrier
    as an argument and names its rows by it."""
    for key, v in st.items():
        if key == "carrier_hz" and cfg.carrier_hz < 50e9:
            continue
        cfg = guispec.set_path(cfg, key, v)
    return cfg


def frontend(st: dict | None = None) -> Frontend60:
    """The one ``Frontend60`` every row of a study runs on (iron rule 2)."""
    st = study(st)
    return Frontend60.from_config(apply_study(reference_config(st.get("carrier_hz", PRESET_CARRIER_HZ)), st))


def schemes(st: dict | None = None, quick: bool = False) -> list[compare.Scheme]:
    """The comparison table's schemes (``compare.default_matrix``) with the study applied to each."""
    st = study(st)
    out = []
    for s in compare.default_matrix(quick=quick, carrier_hz=st.get("carrier_hz", PRESET_CARRIER_HZ)):
        out.append(s if s.cfg is None else dc.replace(s, cfg=apply_study(s.cfg, st)))
    return out


# ------------------------------------------------------------------ parts, what they read, what they are built on
_S = frozenset(SHARED_KNOBS)
_FE = frozenset({"carrier_hz", "frontend.pa.model", "frontend.pa.obo_db", "frontend.pa.obo_reference",
                 "lo.phase_noise.model", "lo.phase_noise.psd0_dbchz", "lo.phase_noise.f_pole_hz",
                 "lo.phase_noise.f_zero_hz", "lo.phase_noise.apply"})


@dc.dataclass(frozen=True)
class Part:
    id: str
    zh: str
    en: str
    reads: frozenset                 # shared knobs this part's numbers depend on
    upstream: tuple = ()             # parts whose results it is built on
    job: str | None = None           # the job that computes it; None = a stored measurement, not recomputed here


PARTS = {p.id: p for p in (
    Part("calibration.be", "校准序列（升频零中频链，六列）",
         "calibration sequence (upclocked zero-IF chain, six columns)", _FE, (), "calibration_be"),
    Part("thresholds.be", "be 行的解码门限", "decoder thresholds of the be rows",
         frozenset(k for k in SHARED_KNOBS if k.startswith("rx.")) | {"phy.packet_bytes"}),
    Part("thresholds.ay", "ay 两种波形的解码门限", "decoder thresholds of the two ay waveforms",
         frozenset({"phy.packet_bytes", "channel.model", "channel.rms_delay_ns"})),
    Part("table.analytic", "同台表 · 解析列（底板、两种上限、速率、pJ/bit）",
         "comparison table, analytic columns (floors, both caps, rates, pJ/bit)",
         _S - {"phy.packet_bytes", "rx.ce_smooth_auto", "rx.ce_smooth_tones", "rx.cpe_window_symbols"},
         ("calibration.be", "thresholds.be"), "table"),
    Part("table.td", "同台表 · 时域核对列", "comparison table, time-domain cross-check column", _S, (), "table"),
    Part("table.ay", "同台表 · 802.11ay 两行", "comparison table, the two 802.11ay rows",
         _S - {"phy.packet_bytes", "rx.ce_smooth_auto", "rx.ce_smooth_tones"}, ("thresholds.ay",), "table"),
    # the array link is line of sight on a flat channel whatever the form's channel says (``array_inputs``)
    Part("array", "阵列页（阵面、EIRP 上限、距离、功耗、波束训练）",
         "array page (faces, EIRP limit, range, power, beam training)",
         _S - {"rx.ce_smooth_auto", "rx.ce_smooth_tones", "channel.model", "channel.rms_delay_ns"},
         ("thresholds.be", "thresholds.ay"), "array"),
    Part("ay", "SC 对 OFDM 页（PAPR、分项、底板、回退、校准、速率对距离、多径）",
         "SC against OFDM page (PAPR, impairments, floors, back-off, calibration, rate against range, multipath)",
         _S - {"phy.packet_bytes"}, ("thresholds.be", "thresholds.ay"), "ay"),
)}

#: ``seconds``: measured durations of the job itself (``run_job``), shortest first; the note says how each was
#: taken.  The examples named in ``command`` print the same numbers but some do more than the job (example 03's
#: 809 s is its whole script, not these six columns: that figure stood here until 2026-11-19 and was wrong).
JOBS = {
    "calibration_be": {"parts": ("calibration.be",), "command": "python tools/gui_report.py calibration",
                       "example": "python examples/03_calibration_at_k.py", "report": "calibration", "seconds": [42],
                       "seconds_note": "42 s with three other jobs side by side on a 4-core container; "
                                       "12 steps per column, six columns"},
    "table": {"parts": ("table.analytic", "table.td", "table.ay"), "command": "python tools/gui_report.py table",
              "example": "python examples/04_comparison_table.py", "report": "table", "seconds": [55, 126],
              "seconds_note": "55 s alone on a 4-core container, with the sensitivity and LO-model sections; "
                              "106 s with three other jobs side by side before those sections existed"},
    "array": {"parts": ("array",), "command": "python tools/gui_report.py array",
              "example": "python examples/10_array_link_and_training.py", "report": "array",
              "seconds": [560, 893, 1650],
              "seconds_note": "560 s alone on a 4-core container (example 10, the same computation); 893 s with "
                              "three other jobs side by side; 1650 s with three examples side by side"},
    "ay": {"parts": ("ay",), "command": "python tools/gui_report.py ay",
           "example": "python examples/15_ay_on_the_shared_front_end.py", "report": "ay", "seconds": [224, 428, 563],
           "seconds_note": "224 s alone on a 4-core container (example 15, the same computation); 428 s with three "
                           "other jobs side by side; 563 s with three examples side by side"},
    "table_analytic": {"parts": ("table.analytic",), "command": "python tools/gui_report.py table --no-time-domain",
                       "example": "python tools/budget_report.py --base 11ac:20e6 --base 11be:80e6 --no-time-domain",
                       "report": "table", "seconds": [24],
                       "seconds_note": "24 s on a 4-core container with a page being tested alongside (topology A's "
                                       "rows build the chip and run its calibration)"},
}
#: stored measurements a study can make stale but this layer does not recompute (hours of PER curves)
STORED = {
    "thresholds.be": {"command": "python tools/measure_thresholds.py --jobs 4 --cache DIR",
                      "file": "src/mmw60/data/spec/per_thresholds.yaml",
                      "seconds_note": "about 2.3 hours on 4 cores (README, the decoder-cap section)"},
    "thresholds.ay": {"command": "python tools/measure_ay_thresholds.py",
                      "file": "src/mmw60/data/spec/ay_per_thresholds.yaml"},
}


def reads(part: str, knob_id: str) -> bool:
    return knob_id in PARTS[part].reads


def closure(part: str) -> list[str]:
    """``part`` and everything it is built on, upstream first."""
    seen: list[str] = []

    def walk(p):
        for u in PARTS[p].upstream:
            walk(u)
        if p not in seen:
            seen.append(p)
    walk(part)
    return seen


def signature(part: str, st: dict | None = None) -> str:
    """What a part's numbers depend on, as a hash: the study restricted to the knobs the part
    reads.  Two studies with the same signature give the same numbers for that part (at one code
    version: the envelope's provenance says which)."""
    st = study(st)
    own = sorted((k, v) for k, v in st.items() if k in PARTS[part].reads)
    return hashlib.sha256(json.dumps([SCHEMA, part, own], sort_keys=True).encode()).hexdigest()[:16]


# ------------------------------------------------------------------ provenance
_HDR = re.compile(r"#\s*Vendored from ([\w.-]+)@([0-9a-f]{7,40})")
_PIN_FILES = {"wifi_trx_cal": "vendor/wifitrx/__init__.py", "spec_sources": "vendor/spec_sources/__init__.py",
              "array_tx": "vendor/arraytx/geometry.py"}


def pins() -> dict[str, str]:
    """The pinned commit of each vendored library, read from the header its files carry."""
    out = {}
    for repo, rel in _PIN_FILES.items():
        m = _HDR.search((PACKAGE / rel).read_text(encoding="utf-8").splitlines()[0])
        if m is None or m.group(1) != repo:
            raise RuntimeError(f"{rel}: no 'Vendored from {repo}@<sha>' header")
        out[repo] = m.group(2)
    return out


def vendored() -> dict:
    from .vendor import spec_sources as _ss
    from .vendor import wifitrx as _w
    p = pins()
    return {"wifitrx": {"version": _w.__version__, "pin": p["wifi_trx_cal"]},
            "spec_sources": {"version": _ss.__version__, "pin": p["spec_sources"]},
            "array_tx": {"pin": p["array_tx"], "files": ["geometry.py", "beam.py"]}}


def spec_digest() -> str:
    """One hash over every table the numbers come from (this library's and the vendored ones)."""
    h = hashlib.sha256()
    files = (sorted((PACKAGE / "data" / "spec").glob("*.yaml"))
             + sorted((PACKAGE / "vendor" / "spec_sources" / "data").glob("*.yaml")))
    for f in files:
        h.update(f.name.encode())
        h.update(f.read_bytes())
    return h.hexdigest()[:16]


def commit() -> str | None:
    """The checkout's commit, or None outside a git checkout (an installed wheel)."""
    try:
        r = subprocess.run(["git", "-C", str(PACKAGE), "rev-parse", "HEAD"], capture_output=True, text=True,
                           timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", r.stdout.strip()) else None


def provenance() -> dict:
    return {"library": "mmw60_trx", "version": __version__, "commit": commit(), "vendored": vendored(),
            "spec_digest": spec_digest(), "engine": ENGINE_BANNER, "schema": SCHEMA}


def config_sha(cfg: Mmw60Config) -> str:
    """sha256 of the config's canonical JSON (``to_dict()``, keys sorted)."""
    return hashlib.sha256(json.dumps(cfg.to_dict(), sort_keys=True, default=str).encode()).hexdigest()


def _json(v: Any):
    """Plain JSON types only: numpy scalars and arrays to Python, tuples to lists, non-finite floats
    to None, mapping keys to strings (a float key as its shortest repr)."""
    if isinstance(v, dict):
        return {(repr(float(k)) if isinstance(k, float) else str(k)): _json(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json(x) for x in v]
    if hasattr(v, "tolist") and not isinstance(v, (str, bytes)):
        return _json(v.tolist())
    if isinstance(v, bool) or v is None or isinstance(v, (int, str)):
        return v
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    return str(v)


# ------------------------------------------------------------------ envelopes and freshness
def _upstream(part: str, built_on: dict | None) -> dict:
    """The signature of each upstream part as the result was really built on it: ``built_on`` maps
    an upstream part to the study its result was computed for; one it does not name was the accepted
    result of the presets (the stored thresholds always are; a table computed without a calibration
    result looks its IRR up in the accepted table)."""
    built_on = built_on or {}
    return {u: signature(u, built_on.get(u) or {}) for u in closure(part)[:-1]}


def envelope(part: str, st: dict | None, payload: dict, seconds: float | None = None,
             built_on: dict | None = None) -> dict:
    """A computed part with what it read, what it was built on (``_upstream``) and where it was
    computed."""
    st = study(st)
    return {"part": part, "schema": SCHEMA, "study": {k: v for k, v in st.items() if k in PARTS[part].reads},
            "signature": signature(part, st), "upstream": _upstream(part, built_on),
            "provenance": provenance(), "seconds": seconds, "payload": _json(payload)}


def job_result(job: str, st: dict | None, report: dict, seconds: float | None = None, parts=None,
               built_on: dict | None = None) -> dict:
    """What a host stores after a job: the report with the study it was computed for, the upstream
    results it was built on (``built_on``: upstream part -> that result's study; presets when not
    named) and where.  ``parts`` narrows the parts the run produced (an analytic-only table has no
    time-domain column)."""
    st = study(st)
    return {"job": job, "schema": SCHEMA, "study": st, "parts": list(JOBS[job]["parts"] if parts is None else parts),
            "built_on": {u: study(v) for u, v in (built_on or {}).items()},
            "provenance": provenance(), "seconds": seconds, "report": _json(report)}


def envelopes_of(result: dict) -> dict[str, dict]:
    """A stored job result as one envelope per part it produced (what ``freshness`` reads)."""
    out = {}
    for pid in result["parts"]:
        st = result["study"]
        out[pid] = {"part": pid, "schema": result["schema"],
                    "study": {k: v for k, v in st.items() if k in PARTS[pid].reads},
                    "signature": signature(pid, st), "upstream": _upstream(pid, result.get("built_on")),
                    "provenance": result["provenance"], "seconds": result["seconds"], "payload": None}
    return out


def freshness(st: dict | None, envelopes: dict[str, dict] | None = None, accepted: bool = True) -> dict:
    """Per part, against the form as it is now: ``fresh``, ``stale`` (with the knobs that moved it
    and the upstream parts that are stale) or ``missing``.

    A part with no envelope is judged against the accepted results, which are the presets'
    (study ``{}``): it is fresh while the study leaves the knobs it reads at their presets.  That
    is how the stored measurements (the decoder thresholds) are judged always.  A host that draws
    only what its store holds passes ``accepted=False``: a part a job computes then reads
    ``missing`` when no result of it is stored, instead of fresh on the strength of numbers the
    page cannot show.  A missing upstream does not by itself make a part stale: the part's own
    record of what it was built on decides."""
    st = study(st)
    envelopes = envelopes or {}
    out: dict[str, dict] = {}
    for pid in sorted(PARTS, key=lambda p: len(closure(p))):
        part, env = PARTS[pid], envelopes.get(pid)
        if env is None and not accepted and part.job is not None:
            out[pid] = {"state": "missing", "changed": [], "upstream": [], "basis": "nothing stored",
                        "recompute": part.job, "stored": None, "computed_at": None}
            continue
        have = (env or {}).get("study", {}) if env and env.get("schema") == SCHEMA else {}
        changed = sorted(k for k in part.reads if st.get(k, None) != have.get(k, None))
        if env is not None and env.get("schema") != SCHEMA:
            changed = sorted(part.reads)
        up = [u for u in part.upstream if out[u]["state"] == "stale"]
        if env is not None:
            # an envelope computed on stale upstream results stays stale until it is rebuilt on fresh ones
            up += [u for u in part.upstream if u not in up and env.get("upstream", {}).get(u) != signature(u, st)]
        state = "fresh" if not changed and not up else "stale"
        out[pid] = {"state": state, "changed": changed, "upstream": up,
                    "basis": "envelope" if env is not None else "accepted presets",
                    "recompute": part.job, "stored": STORED.get(pid),
                    "computed_at": None if env is None else {k: env["provenance"].get(k)
                                                             for k in ("version", "commit")}}
    return out


def field_states(fresh: dict) -> dict:
    """The state of each group of table fields (``BE_FIELDS``): a plain part's fields are stale only
    when the knobs that part reads moved; a ``part+upstream`` group also when that upstream is."""
    out = {}
    for group in dict.fromkeys(list(BE_FIELDS) + ["table.ay"]):
        own, _, up = group.partition("+")
        stale = bool(fresh[own]["changed"]) or (bool(up) and up in fresh[own]["upstream"])
        out[group] = "missing" if fresh[own]["state"] == "missing" else "stale" if stale else "fresh"
    return out


def freshness_matrix() -> dict:
    """Part x shared knob: does the part read it (the page's dot matrix; grouped by ``guispec.GROUPS``)."""
    return {"knobs": [{"id": k, "group": KNOB[k].group} for k in SHARED_KNOBS],
            "parts": [{"id": p.id, "zh": p.zh, "en": p.en, "reads": sorted(p.reads), "upstream": list(p.upstream),
                       "job": p.job, "stored": STORED.get(p.id)} for p in PARTS.values()],
            "jobs": {j: dict(v, parts=list(v["parts"])) for j, v in JOBS.items()}}


# ------------------------------------------------------------------ the form's description, sources and tags
def _short(v, n: int = 240):
    s = json.dumps(_json(v), ensure_ascii=False)
    return _json(v) if len(s) <= n else s[: n - 3] + "..."


def source(key: str) -> dict:
    e = spec.all_entries()[key]
    return {"key": key, "source": e.source, "unit": e.unit, "value": _short(e.value), "cite": e.cite or "",
            "note": e.note or ""}


def sources(keys=None) -> dict:
    """Spec-table entries by key (all of them by default) with their source label."""
    return {k: source(k) for k in (sorted(spec.all_entries()) if keys is None else keys)}


def source_counts() -> dict:
    out: dict[str, int] = {}
    for e in spec.all_entries().values():
        out[e.source] = out.get(e.source, 0) + 1
    return out


def knob_tag(knob_id: str, st: dict | None = None) -> dict:
    """The source label a knob's value carries on the form: its spec entry's while the value is the
    preset, *assumed* once the study changes it (a number changed on the form is no longer the
    source's).  ``was`` keeps the label it had."""
    st = study(st) if knob_id not in ROW_KNOBS else {}
    key = KNOB_SOURCE.get(knob_id)
    was = None if key is None else spec.all_entries()[key].source
    if knob_id in st:
        return {"source": "assumed", "edited": True, "was": was, "key": key}
    return {"source": was, "edited": False, "was": was, "key": key}


def form(st: dict | None = None, row: Mmw60Config | None = None) -> dict:
    """The form for a page: every knob of ``guispec`` with its group, whether it is a row knob,
    its preset and current value, its source tag and the parts that read it."""
    stv = study(st)
    ref = row if row is not None else reference_config()      # the presets: ``preset`` never follows the study
    items = []
    for k in guispec.KNOBS:
        d = _json(k.as_dict())
        preset = k.default(row if row is not None else ref)
        d.update(row_knob=k.id in ROW_KNOBS, group_zh=guispec.GROUPS[k.group][0], group_en=guispec.GROUPS[k.group][1],
                 preset=preset, value=stv.get(k.id, preset), tag=knob_tag(k.id, stv),
                 read_by=[] if k.id in ROW_KNOBS else [p.id for p in PARTS.values() if k.id in p.reads])
        items.append(d)
    return {"kind": "form", "study": stv, "knobs": items,
            "groups": {g: {"zh": z, "en": e, "count": sum(1 for k in guispec.KNOBS if k.group == g)}
                       for g, (z, e) in guispec.GROUPS.items()},
            "source_counts": source_counts()}


# ------------------------------------------------------------------ report: the comparison table
#: how each kind of row arrives at its numbers (the "footing"): shown per row, never merged away
FOOTING = {
    "be_zero_if": {
        "raw_floor": "analytic sum of terms; cross-checked by a time-domain EVM run of the same cell",
        "cal_floor": "not measured on this chain: the analytic sum with the IQ image at the IRR the calibration runs "
                     "measured at that bandwidth (a looked-up value)",
        "calibration_run_on_this_chain": False, "decoder_counted_in_pj": True},
    "be_if_extender": {
        "raw_floor": "analytic sum of terms; the chip's residual in it is measured after the chip's own calibration, "
                     "which runs when the chain is built",
        "cal_floor": "the same as the raw floor (the chip is already calibrated)",
        "calibration_run_on_this_chain": True, "decoder_counted_in_pj": True},
    "ay": {
        "raw_floor": "time-domain EVM on the uncalibrated chain, worst constellation (no analytic sum)",
        "cal_floor": "measured: time-domain EVM on the chain wifitrx's calibration sequence calibrated",
        "calibration_run_on_this_chain": True, "decoder_counted_in_pj": False},
}
#: which part a field of a be row belongs to (and the upstream part it additionally rests on)
BE_FIELDS = {
    "table.analytic": ["floor_db", "terms_db", "terms_share", "dominant", "max_mcs", "rate_mbps", "power", "verdict",
                       "reason", "usable", "evm_budget", "eirp", "cfo_captured", "plan_ok"],
    "table.analytic+calibration.be": ["floor_cal_db", "irr_cal_db", "irr_cal_measured_at_hz", "max_mcs_cal",
                                      "usable_cal", "rate_cal_mbps", "power_cal", "dec_mcs_cal", "dec_rate_cal_mbps",
                                      "power_dec_cal", "dec_mcs_cal_range", "dec_cal_next_margin_db"],
    "table.analytic+thresholds.be": ["dec_mcs", "dec_mcs_range", "dec_next_margin_db", "dec_required_snr_db",
                                     "dec_penalty_db", "dec_rate_mbps", "power_dec", "dec_mcs_cal", "dec_rate_cal_mbps",
                                     "power_dec_cal", "dec_mcs_cal_range", "dec_cal_next_margin_db"],
    "table.td": ["td_evm_db", "td_delta_db", "td_ok", "dec_floor_db"],
    # the 802.11ay rows: every field is ``table.ay``'s; these also lean on the stored ay thresholds
    "table.ay+thresholds.ay": ["dec_mcs", "dec_mcs_cal", "dec_rate_mbps", "dec_rate_cal_mbps", "power_dec",
                               "power_dec_cal", "dec_margin_db"],
}
#: decimals the accepted outputs print each field with (one rounding, from the full value)
DISPLAY = {"floor_db": 1, "floor_cal_db": 1, "td_evm_db": 1, "td_delta_db": 1, "terms_db": 1, "rate_mbps": 0,
           "rate_cal_mbps": 0, "dec_rate_mbps": 0, "dec_rate_cal_mbps": 0, "pj_per_bit": 0, "irr_cal_db": 1,
           "dec_next_margin_db": 2, "dec_cal_next_margin_db": 2, "dec_required_snr_db": 2, "dec_penalty_db": 2,
           "eirp_margin_db": 0, "ay_floor_db": 2, "cfo_subcarriers": 2, "terms_share_pct": 1, "pj_ratio": 2,
           "ipn_dbc": 1, "pn_ici_db": 1}


def terms_share(terms_db: dict) -> dict:
    """Each EVM term's share of the floor's power (the terms add in power: the floor is their sum).
    A term that is absent (below ``compare.ABSENT_DB``) has no share.  Fractions summing to 1."""
    lin = {k: 10.0 ** (v / 10.0) for k, v in terms_db.items() if v is not None and v >= compare.ABSENT_DB}
    total = sum(lin.values())
    return {k: (lin[k] / total if k in lin and total > 0 else None) for k in terms_db}


def sensitivity_report(sch: list, fe: Frontend60, progress=None) -> dict:
    """Which guesses decide the verdict: ``compare.sensitivity`` (example 04's section) as a page
    reads it — per knob end, the rows whose MCS cap or decoder cap moved, whether the pJ/bit
    ranking changed and how far any row's pJ/bit moved (a ratio to the base)."""
    sens = compare.sensitivity(sch, fe, progress=progress)
    meta = {k["name"]: k for k in compare.sensitivity_knobs()}
    knobs = []
    for k in sens["knobs"]:
        m = meta[k["knob"]]
        knobs.append({"knob": k["knob"], "knob_zh": m["name_zh"], "value": k["value"],
                      "value_text": compare.knob_value_text(k["value"]), "unit": m["unit"], "mode": m["mode"],
                      "source_keys": list(m["sources"]), "source_note": m.get("source_note"),
                      "mcs_moved": [{"label": lab, "from": a, "to": b} for lab, (a, b) in k["mcs_moved"].items()],
                      "dec_mcs_moved": [{"label": lab, "from": a, "to": b}
                                        for lab, (a, b) in k["dec_mcs_moved"].items()],
                      "ranking": k["ranking"], "ranking_changed": k["ranking_changed"],
                      "pj_ratio_min": k["pj_ratio_min"], "pj_ratio_max": k["pj_ratio_max"]})

    def named(pred):
        return [n for n in meta if any(pred(k) for k in knobs if k["knob"] == n)]
    return {"base_ranking": sens["base"]["ranking"], "knobs": knobs,
            # example 04 prints this caveat with the section: it is part of how the numbers read
            "decoder_basis": {
                "zh": "这里的解码器上限只从解析底板出发（每个旋钮端不再跑时域）："
                      "同台表里上限取自时域底板的行，在这一节里起点高一档",
                "en": "the decoder caps here start from the analytic floor alone (no time-domain run per knob end): "
                      "a row whose cap in the table came from the time-domain floor starts one MCS higher in this "
                      "section"},
            "moves_a_cap": named(lambda k: k["mcs_moved"] or k["dec_mcs_moved"]),
            "changes_ranking": named(lambda k: k["ranking_changed"])}


def lo_models_report(st: dict | None = None, *, time_domain: bool = True, quick: bool = False,
                     progress=None) -> dict:
    """The LO models side by side (example 04's section 5, ``compare.lo_comparison``): each model on
    its own ``Frontend60`` at K = 1, 8 and 32 of the 11ac 20 MHz zero-IF preset, with the study
    applied to everything but the LO — the form's LO knobs describe one LO, this section swaps in
    each of the models whatever they say.  ``is_preset_model`` marks the presets' own."""
    stv = study(st)
    not_lo = {k: v for k, v in stv.items() if not k.startswith("lo.")}
    fe = frontend(stv)
    pa_evm = pa_isolated_evm_db(fe.pa_model, fe.obo_db, fe.obo_reference) if fe.pa_enabled else None

    def base(k):
        return apply_study(zero_if_60ghz(k=k, carrier_hz=stv.get("carrier_hz", PRESET_CARRIER_HZ)), not_lo)
    preset_kind = zero_if_60ghz().lo.phase_noise.model
    rows = compare.lo_comparison(pa_evm, ks=(8,) if quick else (1, 8, 32), time_domain=time_domain, base=base,
                                 progress=progress)
    for r in rows:
        r["is_preset_model"] = r["kind"] == preset_kind
    return _json({"rows": rows, "ks": sorted({r["k"] for r in rows}), "base": "11ac 20 MHz zero-IF preset",
                  "form_lo_knobs_ignored": sorted(k for k in SHARED_KNOBS if k.startswith("lo.")),
                  "edited_lo_knobs": sorted(k for k in stv if k.startswith("lo."))})


def _cap_display(mcs, rng) -> str | None:
    """The decoder cap as example 04 prints it: ``MCS5–6`` when the two ends of the threshold
    intervals give different caps."""
    if mcs is None:
        return None
    if not rng or rng[0] == rng[1]:
        return f"MCS{mcs}"
    return f"MCS{min(rng)}–{max(rng)}"


def front_end_report(fe: Frontend60, st: dict | None = None) -> dict:
    """The shared front end as the table's header shows it, each number with its source key."""
    st = study(st)
    d, f = fe.describe(), fe.faces()
    pa_evm = pa_isolated_evm_db(fe.pa_model, fe.obo_db, fe.obo_reference) if fe.pa_enabled else None
    return _json({
        "carrier_hz": d["carrier_hz"], "pa_model": d["pa"], "psat_dbm": d["psat_dbm"], "pa_gain_db": d["pa_gain_db"],
        "obo_db": d["obo_db"], "obo_reference": d["obo_reference"], "pout_dbm": d["pout_dbm"],
        "pa_isolated_evm_db": pa_evm,
        "lo_profile": d["lo_profile"], "lo_ipn_dbc": d["lo_ipn_dbc"], "tx_lo_leak_dbc": d["tx_leak_dbc"],
        "rx_dc_dbc": d["rx_dc_dbc"],
        "rx_front": {"gain_db": f["rx_gain_db"], "nf_db": f["rx_nf_db"], "iip3_dbm": f["rx_iip3_dbm"]},
        "antenna_gain_tx_dbi": f["antenna_gain_tx_dbi"], "antenna_gain_rx_dbi": f["antenna_gain_rx_dbi"],
        "shared_antenna": f["shared_antenna"], "tx_rx_isolation_db": f["tx_rx_isolation_db"],
        "eirp_dbm": d.get("eirp_avg_dbm"), "eirp_margin_db": d.get("margin_avg_db"),
        "eirp_limit_avg_dbm": None if fe.eirp is None else fe.eirp.avg_dbm,
        "converters": {"enob_ref": fe.converters.enob_ref, "fs_ref_hz": fe.converters.fs_ref_hz,
                       "bits_per_octave": fe.converters.bits_per_octave},
        "source_keys": {"psat_dbm": "pa60.asada_eumc2011", "pa_gain_db": "pa60.asada_eumc2011",
                        "obo_db": "derived.pa60_obo_at_evm_limit_db", "lo": "liu2025.pn_psd0_dbchz",
                        "tx_lo_leak_dbc": "assumed.lo_leak_dbc", "rx_dc_dbc": "assumed.rx_dc_dbc",
                        "rx_front": "rx60.comm_asada2011", "rx_front_pick": "assumed.preset_rx_front",
                        "antenna": "assumed.preset_antenna", "eirp_limit_avg_dbm": "fcc15255.eirp_avg_dbm",
                        "converters": "assumed.converter_enob_ref"},
        "derived_fields": ["pout_dbm", "pa_isolated_evm_db", "lo_ipn_dbc", "eirp_dbm", "eirp_margin_db"],
        "edited": sorted(k for k in st if k in _FE),
    })


def table_report(st: dict | None = None, *, time_domain: bool = True, quick: bool = False,
                 irr_table: dict | None = None, ay: bool = True, labels=None, progress=None,
                 sensitivity: bool = False, lo_models: bool = False) -> dict:
    """The comparison table of a study: ``compare.build`` on its schemes and its front end, each row
    as ``compare`` reports it plus its footing, its config hash and the cross-check merged in.

    ``irr_table`` is a calibration result's IRR by bandwidth (``calibration_report(...)["irr_after_cal_db"]``);
    without one the calibrated columns use the accepted table, ``derived.irr_after_cal_measured_db``,
    which belongs to the presets — ``freshness`` says when a study has moved away from it.
    ``time_domain=False`` computes the analytic columns only (and leaves the 802.11ay rows out, whose
    floors are time-domain readings); ``ay=False`` leaves them out of a full run; ``labels`` keeps
    only those rows (one row recomputed, a test's subset).  ``sensitivity=True`` adds which guesses
    decide the verdict (``sensitivity_report``: the analytic side rerun at every knob end, about
    20 s on the full matrix); a job always asks for it.  ``lo_models=True`` adds the LO models side
    by side (``lo_models_report``; time-domain runs, so a full job only)."""
    st = study(st)
    sch = schemes(st, quick=quick)
    if labels is not None:
        missing = set(labels) - {s.label for s in sch}
        if missing:
            raise KeyError(f"no such row(s): {sorted(missing)}")
        sch = [s for s in sch if s.label in set(labels)]
    if not time_domain or not ay:
        sch = [s for s in sch if s.waveform not in AY_WAVEFORMS or s.status != "built"]
    fe = frontend(st)
    table = None if irr_table is None else {float(k): float(v) for k, v in irr_table.items()}
    rep = compare.build(sch, fe, time_domain=time_domain, progress=progress, irr_table=table)
    cfg_of = {s.label: s.cfg for s in sch if s.cfg is not None}
    checks = {c["label"]: c for c in rep["cross_checks"]}
    rows = []
    for r in rep["rows"]:
        c = checks[r["label"]]
        r = dict(r)
        r.update(footing="be_if_extender" if r["topology"] == "if_extender" else "be_zero_if",
                 terms_share=terms_share(r["terms_db"]),
                 td_delta_db=c.get("td_delta_db"), td_ok=c.get("td_ok"), budget_delta_db=c.get("budget_delta_db"),
                 dec_cap_display=_cap_display(r["dec_mcs"], r["dec_mcs_range"]),
                 dec_cap_cal_display=_cap_display(r["dec_mcs_cal"], r["dec_mcs_cal_range"]),
                 cfg_sha=config_sha(cfg_of[r["label"]]), seed=cfg_of[r["label"]].seed)
        rows.append(r)
    ay_rows = []
    for r in rep["ay_rows"]:
        r = {k: v for k, v in r.items() if k != "frontend_id"}
        r.update(footing="ay", cfg_sha=config_sha(cfg_of[r["label"]]), seed=cfg_of[r["label"]].seed,
                 floor_raw_worst_db=max(r["floor_raw_db"].values()), floor_cal_worst_db=max(r["floor_cal_db"].values()))
        ay_rows.append(r)
    best = None
    be_cal = [r for r in rows if r["power_cal"] and r["cfo_captured"] and r["plan_ok"] is not False]
    if be_cal:
        fast = max(be_cal, key=lambda r: r["rate_cal_mbps"])
        cheap = min(be_cal, key=lambda r: r["power_cal"]["pj_per_bit"])
        best = {"fastest": fast["label"], "fewest_pj_per_bit": cheap["label"]}
    return _json({
        "kind": "table", "study": st, "engine": ENGINE_BANNER, "time_domain": time_domain, "quick": quick,
        "front_end": front_end_report(fe, st), "footing": FOOTING, "fields": BE_FIELDS, "display": DISPLAY,
        "rows": rows, "ay_rows": ay_rows, "pending": rep["pending"], "matrix": rep["matrix"],
        "be_best_at_calibrated_cap": best, "coefficients": rep["coefficients"],
        "sensitivity": sensitivity_report(sch, fe) if sensitivity else None,
        "lo_models": lo_models_report(st, time_domain=time_domain, quick=quick) if lo_models else None,
        "irr_table": {"from": "calibration result" if irr_table is not None else "derived.irr_after_cal_measured_db",
                      "db_by_bandwidth_hz": (table if table is not None
                                             else spec.value("derived.irr_after_cal_measured_db"))},
        # a term below this is absent (zero to double precision), as example 04 prints it: a dash, not a number
        "absent_below_db": compare.ABSENT_DB,
        "margins": {"mcs_evm_margin_db": spec.value("assumed.mcs_evm_margin_db"),
                    "decoder_cap_margin_db": spec.value("assumed.decoder_cap_margin_db")},
    })


def assemble_table(by_part: dict) -> dict | None:
    """The comparison table a page draws, put together from the table report each part is drawn from
    (``by_part``: ``table.analytic`` / ``table.td`` / ``table.ay`` -> a table report or None).

    One report for all three is returned as it is.  Otherwise the analytic part's report is the
    base (its rows, its header, its sensitivity section); each row's time-domain fields
    (``BE_FIELDS["table.td"]``) and the LO-model section come from the time-domain part's report,
    the 802.11ay rows from theirs.  So an analytic-only run for the form on screen shows new
    analytic columns next to the last full run's time-domain column and 802.11ay rows — which
    ``freshness`` marks stale per part.  Nothing is recomputed and nothing is mixed inside a
    field group.

    One caveat travels with an analytic-only base (``assembled["decoder_caps_from_analytic_floor"]``):
    its decoder caps start from the analytic floor alone, while a full run takes the worse of that
    and the time-domain EVM — a row whose time-domain floor is the worse one reads one MCS higher."""
    ana, td, ay = (by_part.get(k) for k in ("table.analytic", "table.td", "table.ay"))
    base = ana or td or ay
    if base is None:
        return None
    if all(x is base for x in (ana, td, ay)):
        return base
    out = dict(base)
    td_rows = {r["label"]: r for r in (td or {}).get("rows", [])}
    rows = []
    for r in base["rows"]:
        src = td_rows.get(r["label"])
        r = dict(r)
        if src is not r:
            for f in BE_FIELDS["table.td"]:
                r[f] = None if src is None else src.get(f)
        rows.append(r)
    preview = ana is not None and not ana.get("time_domain")
    out.update(rows=rows, ay_rows=list((ay or {}).get("ay_rows", [])), lo_models=(td or {}).get("lo_models"),
               time_domain=bool(td and td.get("time_domain")),
               assembled={"parts": {k: v is not None for k, v in (("table.analytic", ana), ("table.td", td),
                                                                  ("table.ay", ay))},
                          "analytic_only_base": preview, "decoder_caps_from_analytic_floor": preview})
    return out


# ------------------------------------------------------------------ report: the calibration runs
#: wifitrx names a reading after its unit; the suffix is read here, once, not by a page
_METRIC_UNITS = (("_dbfs", "dBFS"), ("_dbc", "dBc"), ("_dbm", "dBm"), ("_db", "dB"), ("_pct", "%"), ("_ns", "ns"),
                 ("_ps", "ps"), ("_hz", "Hz"))


def metric_unit(metric: str | None) -> str | None:
    """The unit of a wifitrx metric from its name's suffix (``irr_min_db`` -> dB); None when it says none."""
    return next((u for suffix, u in _METRIC_UNITS if metric and metric.endswith(suffix)), None)


def calibration_from_runs(runs: list, fe: Frontend60, st: dict | None = None) -> dict:
    """The calibration report from finished runs (``calcheck.run_cal_at``): per step and column the
    reading and **two verdicts kept apart** — wifitrx's own, and the summary's, which additionally
    calls an ok step degraded when its dB metric is more than 3 dB worse than the first column's."""
    labels = [r.label for r in runs]
    steps = []
    for row in calcheck.compare_runs(runs):
        cells = []
        for lab in labels:
            st_ = row["by_k"].get(lab)
            if st_ is None:
                cells.append(None)
                continue
            status, metric, value, detail = st_
            cells.append({"status_summary": status, "status_wifitrx": row["wifitrx_by_k"][lab],
                          "metric": metric or None, "unit": metric_unit(metric), "value": value,
                          "detail": detail or None})
        steps.append({"step": row["step"], "mechanism_zh": row["mechanism"], "cells": cells})
    cols = []
    for run in runs:
        views = calcheck.loopback_views(run) if run.chains is not None else None
        fv = run.final_views or {}
        cols.append({
            "label": run.label, "k": run.k, "bw_eff_hz": run.bw_eff_hz, "fs_eff_hz": run.fs_eff_hz,
            "waveform": run.waveform, "passes": run.passes, "pout_dbm": run.pout_dbm,
            "backoff_db": None if run.pout_dbm is None else fe.psat_dbm - run.pout_dbm,
            "evm_before_db": run.evm_before_db, "evm_after_db": run.evm_after_db,
            "capture_symbols": run.n_symbols, "capture_samples": run.capture_samples,
            "modem_view": ({k: fv.get(k) for k in ("evm_modem_db", "tx_evm_modem_db", "rx_evm_modem_db", "rx_nf_db")}
                           if fv else None),
            "three_views": views})
    return _json({
        "kind": "calibration", "study": study(st), "engine": ENGINE_BANNER, "columns": cols, "steps": steps,
        "irr_after_cal_db": calcheck.irr_after_cal(runs),
        "status_rule": {"status_wifitrx": "wifitrx's own verdict of the step on that run",
                        "status_summary": "wifitrx's verdict, and additionally 'degraded' when an ok step's dB metric "
                                          "reads more than 3 dB worse than the first column (this library's rule, "
                                          "calcheck.compare_runs)",
                        "degrade_db": 3.0},
        "operating_point": {"psat_dbm": fe.psat_dbm, "obo_db": fe.obo_db, "obo_reference": fe.obo_reference,
                            "target_pout_dbm": fe.target_pout_dbm()},
    })


def calibration_report(st: dict | None = None, *, plan=None, quick: bool = False, log=None, progress=None) -> dict:
    """wifitrx's calibration sequence really run on the study's front end, one column per (K, base
    bandwidth) of ``plan`` (``calcheck.DEFAULT_PLAN``: example 03's six columns), exactly as
    example 03 runs it — at the front end's back-off, with the DPD step.  ``log`` gets wifitrx's
    line per step; ``progress(done, total, text)`` is called after each step (total = columns x the
    steps of the sequence, known once the first column is through)."""
    st = study(st)
    fe = frontend(st)
    plan = (calcheck.QUICK_PLAN if quick else calcheck.DEFAULT_PLAN) if plan is None else plan
    done, per_column = [0], [None]

    def step(line: str) -> None:
        done[0] += 1
        if log:
            log(line)
        if progress:
            total = None if per_column[0] is None else max(done[0], len(plan) * per_column[0])
            progress(done[0], total, " ".join(line.split()[:2]))
    runs = []
    for k, base in plan:
        runs.append(calcheck.run_cal_at(fe, k, base, with_dpd=not quick, log=step,
                                        standard="11be" if base == 80e6 else "11ac", obo_db=fe.obo_db))
        per_column[0] = len(runs[-1].rows)              # the sequence's length is wifitrx's, read off the first run
    return calibration_from_runs(runs, fe, st)


# ------------------------------------------------------------------ report: the array page
_CHANNEL_KNOBS = ("channel.model", "channel.rms_delay_ns")


def array_inputs(st: dict | None = None, ay: bool = True) -> dict:
    """What the array report runs on: the study's front end and example 10's schemes with the study
    applied.  The link is line of sight on a flat channel, so the form's channel knobs do not reach
    it (multipath enters only through the stored thresholds)."""
    st = {k: v for k, v in study(st).items() if k not in _CHANNEL_KNOBS}
    return {"fe": frontend(st),
            "schemes": tuple((lab, apply_study(c, st)) for lab, c in arrayreport.default_schemes()),
            "ay_cfgs": {wf: apply_study(c, st) for wf, c in arrayreport.default_ay_cfgs().items()} if ay else {},
            "squint_schemes": tuple((lab, apply_study(c, st)) for lab, c in arrayreport.default_squint_schemes())}


def _table_label(cfg: Mmw60Config, sch: list) -> str | None:
    """The comparison-table row that is the same scheme as an array scheme (same topology, waveform,
    base PHY, K and carrier; the array link only swaps the channel for a flat one)."""
    def ident(c):
        return (c.topology, c.waveform, c.phy.standard, c.phy.bandwidth_hz, c.upclock_k, c.carrier_hz,
                c.ifext.chip_pa_bypass)
    return next((s.label for s in sch if s.cfg is not None and ident(s.cfg) == ident(cfg)), None)


def eirp_limit_report(fe: Frontend60, base: Mmw60Config, n_max: int = 256) -> dict:
    """Where the EIRP limit starts to bind at the front end's own back-off: the smallest N whose
    broadside EIRP reaches the limit (example 10's search, on the real array gain)."""
    from .config import array_frontend
    p = float(fe.target_pout_dbm())
    limit = fe.eirp.avg_dbm
    n_min = next((n for n in range(1, n_max + 1)
                  if p + Array60.from_config(array_frontend(base, n), fe).tx_gain_db(0.0, 0.0)[0] >= limit), None)
    return {"limit_avg_dbm": limit, "element_pout_dbm": p, "element_gain_dbi": fe.antenna_gain_tx_dbi,
            "single_element_eirp_dbm": p + fe.antenna_gain_tx_dbi, "binds_from_n": n_min,
            "law": "EIRP = element EIRP + 20 log10 N (TX gain = 20 log10 N + element gain)",
            "source_key": "fcc15255.eirp_avg_dbm"}


def array_report(st: dict | None = None, *, quick: bool = False, ay: bool = True, progress=None, **kw) -> dict:
    """The array page of a study: ``arrayreport.build`` (every number of example 10) on the study's
    front end and schemes, plus which comparison-table row each scheme is and where the EIRP limit
    starts to bind.  ``quick`` is the example's smoke size; ``ay=False`` leaves the two 802.11ay
    waveforms out (they are most of the run time); other keywords go to ``arrayreport.build``."""
    stv = study(st)
    inp = array_inputs(stv, ay=ay)
    args = dict(arrayreport.quick_kwargs() if quick else {}, **kw)
    rep = arrayreport.build(inp["fe"], inp["schemes"], inp["ay_cfgs"], progress=progress,
                            squint_schemes=inp["squint_schemes"], **args)
    sch = schemes(stv)
    rows = {lab: _table_label(cfg, sch) for lab, cfg in inp["schemes"]}
    rows.update({wf: _table_label(cfg, sch) for wf, cfg in inp["ay_cfgs"].items()})
    rep.update(kind="array", study=stv, table_row_of=rows,
               eirp_limit=eirp_limit_report(inp["fe"], inp["schemes"][0][1]))
    return _json(rep)


def single_antenna_ranges(array: dict) -> dict:
    """Per comparison-table row, the one-element link of an array report (its N = 1 rows): the
    distances the table's range column shows.  Only the schemes the array report carries have one."""
    out = {}
    for r in array.get("link", []):
        lab = array["table_row_of"].get(r["scheme"])
        if r["n"] == 1 and lab:
            out[lab] = {k: v for k, v in r.items() if k not in ("scheme", "n")}
    for r in array.get("ay", []):
        lab = array["table_row_of"].get(r["waveform"])
        if r["n"] == 1 and r["point"] == "preset" and lab:
            out[lab] = {k: v for k, v in r.items() if k not in ("waveform", "n", "point")}
    return out


# ------------------------------------------------------------------ report: SC against OFDM
def ay_inputs(st: dict | None = None) -> dict:
    """What the SC-against-OFDM report runs on: example 15's two presets with the study applied and
    the one front end both waveforms share, built from them as the example builds it."""
    st = study(st)
    cfgs = {wf: apply_study(c, st) for wf, c in ayreport.default_cfgs().items()}
    return {"cfgs": cfgs, "fe": ayreport.default_frontend(cfgs)}


def ay_report(st: dict | None = None, *, quick: bool = False, progress=None, **kw) -> dict:
    """The SC-against-OFDM page of a study: ``ay.report.build`` (every number of example 15) on the
    study's two waveform configs and their shared front end.  ``quick`` is the example's smoke size."""
    stv = study(st)
    inp = ay_inputs(stv)
    rep = ayreport.build(inp["fe"], inp["cfgs"], quick=quick, progress=progress, **kw)
    for step in (rep.get("calibration") or {}).get("steps", []):
        step["unit"] = metric_unit(step.get("metric"))
    rep.update(kind="sc_vs_ofdm", study=stv)
    return _json(rep)


def sc_vs_ofdm_headline(array: dict, n: int | None = None, point: str = "preset") -> dict:
    """Who wins, by how much, computed from an array report's 802.11ay rows — not quoted from a
    document.  At array size ``n`` (default the largest the report has) and operating point
    ``point``: rate x range of the two waveforms at the same modulation and code rate (16-QAM 3/4:
    ``arrayreport.AY_COMMON_MCS``) and at each waveform's own decoder cap; ``sc_advantage_pct`` is
    the single carrier's product over OFDM's, minus one."""
    rows = [r for r in array.get("ay", []) if r["point"] == point]
    if not rows:
        raise ValueError("this array report has no 802.11ay rows")
    n = max(r["n"] for r in rows) if n is None else n
    by = {r["waveform"]: r for r in rows if r["n"] == n}
    rate = {(m["waveform"], m["mcs"]): m["rate_bps"] for m in ayreport.numbers()["mcs"]}
    common = arrayreport.AY_COMMON_MCS

    def pair(rate_of, range_key):
        out = {}
        for wf in ("ay_sc", "ay_ofdm"):
            r = by[wf]
            bps, d = rate_of(wf, r), r[range_key]
            out[wf] = {"rate_bps": bps, "range_m": d, "product": None if bps is None or d is None else bps * d}
        a, b = out["ay_sc"]["product"], out["ay_ofdm"]["product"]
        out["sc_advantage_pct"] = None if not a or not b else 100.0 * (a / b - 1.0)
        return out
    same = pair(lambda wf, r: rate[(wf, common[wf])], "range_common_m")
    same["mcs"] = dict(common)
    cap = pair(lambda wf, r: None if r["cap_mcs"] is None else rate[(wf, r["cap_mcs"])], "range_cap_m")
    cap["mcs"] = {wf: by[wf]["cap_mcs"] for wf in by}
    return _json({"n": n, "point": point, "eirp_dbm": by["ay_sc"]["eirp_dbm"], "same_modulation_16qam_3_4": same,
                  "own_decoder_cap": cap, "from": "array report, 802.11ay rows"})


def sc_vs_ofdm_items(table: dict | None, array: dict | None, ay: dict | None) -> list[dict]:
    """SC against OFDM item by item — rate, range, pJ/bit on each footing the reports carry — computed
    from the three reports, not quoted from a document (``cairn/ay.md`` opens with this table).

    Each item: the two values with the MCS / array size they are read at, the unit, which direction
    is better, ``sc_over_ofdm_pct`` (100 x (SC / OFDM - 1)) and ``winner`` by its sign (no "tie"
    threshold is invented here: the percentage says how close it is).  ``part`` names the part the
    numbers come from, so a page marks the item stale with it.  An item whose report is missing, or
    whose numbers a report does not have, is left out."""
    items: list[dict] = []
    common = arrayreport.AY_COMMON_MCS
    mcs_of = {(m["waveform"], m["mcs"]): m for m in ayreport.numbers()["mcs"]}
    mod = mcs_of[("ay_sc", common["ay_sc"])]
    mod_txt = f"{mod['modulation'].replace('π/2-', '')} {mod['code_rate']}"

    def add(iid, metric, part, zh, en, sc, ofdm, unit, **ctx):
        if sc is None or ofdm is None or sc.get("value") is None or ofdm.get("value") is None:
            return
        better = "lower" if metric == "pj_per_bit" else "higher"
        pct = 100.0 * (sc["value"] / ofdm["value"] - 1.0)
        ahead = pct > 0 if better == "higher" else pct < 0
        items.append({"id": iid, "metric": metric, "better": better, "part": part, "zh": zh, "en": en, "unit": unit,
                      "sc": sc, "ofdm": ofdm, "sc_over_ofdm_pct": pct,
                      "winner": None if pct == 0 else ("ay_sc" if ahead else "ay_ofdm"), **ctx})

    def val(v, **kw):
        return {"value": v, **kw}
    tab = {r["waveform"]: r for r in (table or {}).get("ay_rows", [])}
    arr = {(r["waveform"], r["n"]): r for r in (array or {}).get("ay", []) if r["point"] == "preset"}
    sizes = sorted({n for _, n in arr})
    binds = ((array or {}).get("eirp_limit") or {}).get("binds_from_n")
    n_top = sizes[-1] if sizes else None
    below = [n for n in sizes if binds is None or n < binds]          # arrays still at the preset back-off
    n_free = below[-1] if below else None

    def a(wf, n, key, cap=False, mcs=None):
        r = arr.get((wf, n))
        return None if r is None else val(r.get(key), n=n, mcs=r.get("cap_mcs") if cap else mcs)

    def same_below(key):
        """Do the arrays still at the preset back-off all read the same (so "N <= n" is the truth)?"""
        return all(len({(arr[(wf, n)].get("cap_mcs"), arr[(wf, n)].get(key)) for n in below}) == 1
                   for wf in ("ay_sc", "ay_ofdm"))
    limited_zh, limited_en = "EIRP 上限卡住", "held at the EIRP limit"
    preset_zh, preset_en = "预设回退", "preset back-off"
    # ---- rate
    if n_top is not None:
        add("rate_dec_cap_top", "rate", "array", f"速率：解码器上限，N = {n_top}（{limited_zh}）",
            f"rate: decoder cap, N = {n_top} ({limited_en})",
            a("ay_sc", n_top, "rate_mbps", cap=True), a("ay_ofdm", n_top, "rate_mbps", cap=True), "Mb/s", n=n_top)
    if n_free is not None and n_free != n_top:
        rel = "≤" if same_below("rate_mbps") else "="
        add("rate_dec_cap_free", "rate", "array", f"速率：解码器上限，N {rel} {n_free}（{preset_zh}）",
            f"rate: decoder cap, N {rel} {n_free} ({preset_en})",
            a("ay_sc", n_free, "rate_mbps", cap=True), a("ay_ofdm", n_free, "rate_mbps", cap=True), "Mb/s", n=n_free)
    if tab:
        margin = tab["ay_sc"].get("cap_margin_db")
        add("rate_conformance_at_limit", "rate", "table.ay", "速率：TX EVM 合规上限，不留余量",
            "rate: TX EVM conformance cap, no margin",
            val(tab["ay_sc"]["rate_cal_at_limit_mbps"], mcs=tab["ay_sc"]["cap_cal_at_limit"]),
            val(tab["ay_ofdm"]["rate_cal_at_limit_mbps"], mcs=tab["ay_ofdm"]["cap_cal_at_limit"]), "Mb/s")
        add("rate_conformance_margin", "rate", "table.ay", f"速率：TX EVM 合规上限，留 {margin:g} dB（同台表）",
            f"rate: TX EVM conformance cap with a {margin:g} dB margin (the comparison table)",
            val(tab["ay_sc"]["rate_cal_mbps"], mcs=tab["ay_sc"]["cap_cal"]),
            val(tab["ay_ofdm"]["rate_cal_mbps"], mcs=tab["ay_ofdm"]["cap_cal"]), "Mb/s", margin_db=margin)
    # ---- range
    if n_top is not None:
        one = {"ay_sc": 1, "ay_ofdm": 1}                      # ``range_mcs1_m``: the slowest data MCS of each
        for iid, key, at, zh, en in (
                ("range_common_top", "range_common_m", common, mod_txt, mod_txt),
                ("range_slowest_top", "range_mcs1_m", one, "最慢一档", "the slowest MCS"),
                ("range_common_multipath_top", "range_common_multipath_m", common, f"{mod_txt}，多径一列",
                 f"{mod_txt}, the multipath column")):
            add(iid, "range", "array", f"距离：N = {n_top}，{zh}", f"range: N = {n_top}, {en}",
                a("ay_sc", n_top, key, mcs=at["ay_sc"]), a("ay_ofdm", n_top, key, mcs=at["ay_ofdm"]), "m", n=n_top)
    rvr = {(r["waveform"], r["mcs"]): r for r in (ay or {}).get("rate_vs_range", [])}
    if rvr:
        slow = {wf: min(m for w, m in rvr if w == wf) for wf in ("ay_sc", "ay_ofdm")}
        for iid, pick, zh, en in (("range_common_single", common, mod_txt, mod_txt),
                                  ("range_slowest_single", slow, "最慢一档", "the slowest MCS")):
            sc, of = rvr.get(("ay_sc", pick["ay_sc"])), rvr.get(("ay_ofdm", pick["ay_ofdm"]))
            add(iid, "range", "ay", f"距离：单天线，{zh}，各取最佳回退",
                f"range: one antenna, {en}, each at its best back-off",
                sc and val(sc["best_range_m"], mcs=sc["mcs"], backoff_db=sc["best_backoff_db"]),
                of and val(of["best_range_m"], mcs=of["mcs"], backoff_db=of["best_backoff_db"]), "m", n=1)
    # ---- pJ/bit
    for n, tag_zh, tag_en in [(n_top, limited_zh, limited_en)] + [(n, preset_zh, preset_en) for n in below]:
        if n is not None:
            add(f"pj_dec_cap_n{n}", "pj_per_bit", "array", f"pJ/bit：解码器上限，N = {n}（{tag_zh}）",
                f"pJ/bit: decoder cap, N = {n} ({tag_en})",
                a("ay_sc", n, "pj_per_bit", cap=True), a("ay_ofdm", n, "pj_per_bit", cap=True), "pJ/bit", n=n)
    if tab and tab["ay_sc"].get("power_cal") and tab["ay_ofdm"].get("power_cal"):
        add("pj_conformance_margin", "pj_per_bit", "table.ay", "pJ/bit：同台表的合规上限",
            "pJ/bit: the comparison table's conformance cap",
            val(tab["ay_sc"]["power_cal"]["pj_per_bit"], mcs=tab["ay_sc"]["cap_cal"]),
            val(tab["ay_ofdm"]["power_cal"]["pj_per_bit"], mcs=tab["ay_ofdm"]["cap_cal"]), "pJ/bit")
    small = {r["waveform"]: r for r in (array or {}).get("ay_smallest", []) if r["point"] == "own"}
    if len(small) == 2:
        add("pj_smallest_array", "pj_per_bit", "array", f"pJ/bit：顶到 EIRP 上限的最小阵列，{mod_txt}，各自的工作点",
            f"pJ/bit: the smallest array that reaches the EIRP limit, {mod_txt}, each at its own operating point",
            val(small["ay_sc"]["pj_per_bit"], n=small["ay_sc"]["n"], backoff_db=small["ay_sc"]["operating_obo_db"]),
            val(small["ay_ofdm"]["pj_per_bit"], n=small["ay_ofdm"]["n"],
                backoff_db=small["ay_ofdm"]["operating_obo_db"]), "pJ/bit")
    return _json(items)


# ------------------------------------------------------------------ a row's detail and its reproducibility card
def repro(label: str, cfg: Mmw60Config, st: dict | None = None, commands=()) -> dict:
    """What it takes to compute a row again: the config (hash, seed), the study, the code and the
    vendored libraries, the spec tables, the equivalent command lines."""
    return {"label": label, "config_label": cfg.label, "config_sha256": config_sha(cfg), "seed": cfg.seed,
            "study": study(st), "provenance": provenance(), "commands": list(commands)}


def calibration_column_for(row: dict, calibration: dict | None) -> str | None:
    """The calibration column that ran on a zero-IF be row's own chain (same K, same base
    bandwidth), else None — the row's calibrated floor then only *looks up* an IRR."""
    if calibration is None or row.get("footing") != "be_zero_if":
        return None
    for c in calibration["columns"]:
        if c["k"] == row["k"] and abs(c["bw_eff_hz"] - row["bw_eff_hz"]) < 1.0:
            return c["label"]
    return None


def row_detail(table: dict, label: str, calibration: dict | None = None) -> dict:
    """One row of a table report with what a page shows when it is opened: the row itself, the
    calibration column that ran on its chain (if any), the column its IRR was looked up from, and
    the reproducibility card."""
    row = next((r for r in table["rows"] + table["ay_rows"] if r["label"] == label), None)
    if row is None:
        raise KeyError(f"no row {label!r} in this table")
    cfg = next(s.cfg for s in schemes(table["study"], quick=table.get("quick", False)) if s.label == label)
    own = calibration_column_for(row, calibration)
    looked_up = None
    if calibration is not None and row.get("footing") == "be_zero_if":
        at = row.get("irr_cal_measured_at_hz")
        looked_up = next((c["label"] for c in calibration["columns"]
                          if at is not None and abs(c["bw_eff_hz"] - at) < 1.0), None)
    cmds = [JOBS["table"]["command"]]
    if row.get("footing") == "be_zero_if":
        cmds.append(JOBS["calibration_be"]["command"])
    return _json({"kind": "row_detail", "row": row, "footing": table["footing"][row["footing"]],
                  "absent_below_db": compare.ABSENT_DB,
                  "calibration_column": own, "irr_looked_up_from_column": looked_up,
                  "repro": repro(label, cfg, table["study"], cmds)})


# ------------------------------------------------------------------ report: the system block diagram
SYSTEM_FILE = PACKAGE / "data" / "gui" / "system.yaml"
#: the ``v:`` values that are computed from sourced numbers (the others are configuration)
_SYSTEM_DERIVED = frozenset({"pout_dbm", "pa_isolated_evm_db", "lo_ipn_dbc", "eirp_dbm", "f_lo_hz", "image_hz",
                             "fc_over_sub7", "cfo_hz"})


def _system_values(st: dict) -> dict:
    """The named values ``data/gui/system.yaml`` refers to with ``v:`` — read from the study's
    front end and reference config, never typed."""
    fe = frontend(st)
    d, faces = fe.describe(), fe.faces()
    ref = apply_study(reference_config(st.get("carrier_hz", PRESET_CARRIER_HZ)), st)
    fc, if_hz = ref.carrier_hz, float(spec.value("assumed.ifext_if_hz"))
    pn, rx, ch = ref.lo.phase_noise, ref.rx, ref.channel
    return {
        "carrier_hz": fc, "oversampling": ref.phy.oversampling,
        "psat_dbm": fe.psat_dbm, "pa_gain_db": fe.pa_gain_db, "pa_model": d["pa"], "obo_db": fe.obo_db,
        "obo_reference": fe.obo_reference, "pout_dbm": d["pout_dbm"],
        "pa_isolated_evm_db": pa_isolated_evm_db(fe.pa_model, fe.obo_db, fe.obo_reference) if fe.pa_enabled else None,
        "pn_model": pn.model, "pn_psd0_dbchz": pn.psd0_dbchz, "pn_f_pole_hz": pn.f_pole_hz,
        "pn_f_zero_hz": pn.f_zero_hz, "pn_apply": pn.apply, "lo_ipn_dbc": d["lo_ipn_dbc"],
        "tx_lo_leak_dbc": d["tx_leak_dbc"], "rx_dc_dbc": d["rx_dc_dbc"],
        "enob_ref": fe.converters.enob_ref, "enob_fs_ref_hz": fe.converters.fs_ref_hz,
        "enob_per_octave": -fe.converters.bits_per_octave,
        "rx_gain_db": faces["rx_gain_db"], "rx_nf_db": faces["rx_nf_db"], "rx_iip3_dbm": faces["rx_iip3_dbm"],
        "antenna_tx_dbi": faces["antenna_gain_tx_dbi"], "antenna_rx_dbi": faces["antenna_gain_rx_dbi"],
        "eirp_dbm": d.get("eirp_avg_dbm"),
        "chip_widest_channel_hz": max(float(k) for k in spec.value("ieee80211be.n_sd")),
        "f_lo_hz": fc - if_hz, "image_hz": fc - 2 * if_hz,
        "fc_over_sub7": fc / float(spec.value("assumed.mlo_sub7")["carrier_hz"]),
        "xo_ppm_tx": ref.xo_ppm_tx, "xo_ppm_rx": ref.xo_ppm_rx, "cfo_hz": (ref.xo_ppm_tx + ref.xo_ppm_rx) * 1e-6 * fc,
        "channel_model": ch.model, "channel_rms_delay_ns": ch.rms_delay_ns, "channel_los_k_db": ch.los_k_db,
        "rx_timing": rx.timing, "rx_dc_removal": rx.dc_removal, "rx_cfo_estimation": rx.cfo_estimation,
        "rx_ce_smooth_auto": rx.ce_smooth_auto, "rx_ce_smooth_max_tones": rx.ce_smooth_max_tones,
        "rx_ce_smooth_tones": rx.ce_smooth_tones, "rx_cpe_window_symbols": rx.cpe_window_symbols,
        "rx_ldpc_max_iterations": rx.ldpc_max_iterations,
    }


def _resolve_param(p: dict, values: dict, st: dict) -> dict:
    """One ``params`` entry of the description with its value and source label filled in."""
    out = {"zh": p["zh"], "en": p["en"], "unit": p.get("unit", "")}
    key = p.get("key")
    if "spec" in p:
        key, _, fld = str(p["spec"]).partition("#")
        v = spec.value(key)
        out["value"] = v[fld] if fld else v
    elif "v" in p:
        out["value"] = values[p["v"]]
    else:
        out["value"] = p["text"]
    if key:
        out.update(source_key=key, source=spec.all_entries()[key].source)
    elif p.get("v") in _SYSTEM_DERIVED:
        out["source"] = "derived"          # computed from sourced numbers; a plain configuration value carries no label
    knob = p.get("knob")
    if knob:
        out["knob"] = knob
        if knob in st:
            out.update(edited=True, source_was=out.get("source"), source="assumed")
    return out


def _resolve(node, values: dict, st: dict):
    if isinstance(node, list):
        return [_resolve(x, values, st) for x in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for k, v in node.items():
        if k == "params":
            out[k] = [_resolve_param(p, values, st) for p in v]
        elif k == "key":
            out.update(source_key=v, source=spec.all_entries()[v].source)
        else:
            out[k] = _resolve(v, values, st)
    return out


def system_report(st: dict | None = None) -> dict:
    """The facts a system block diagram draws: the blocks of both topologies in signal order, what
    is shared, each block's parameters with their sources, which block each EVM term comes from,
    and how far the x K clock reaches on each topology.

    The structure and the words are a description (``data/gui/system.yaml``, following the code:
    vendored wifitrx ``TxChain`` / ``RxChain``, ``ifext``, ``frontend``, ``arraylink``); every
    number is resolved here from the spec table, the study's front end or its configs.  Nothing in
    it is a result: the per-row EVM terms a page lights the blocks with are in the table report."""
    import yaml
    st = study(st)
    doc = _resolve(yaml.safe_load(SYSTEM_FILE.read_text(encoding="utf-8")), _system_values(st), st)
    sch = schemes(st)
    key_a = ("if_extender", "be_upclocked")
    chans = sorted(float(k) for k in spec.value("ieee80211be.n_sd"))
    widest = max(chans)
    up = doc["upclock_scope"]
    up["topology_a"].update(
        chip_channels_hz=chans, chip_channels_source_key="ieee80211be.n_sd",
        rows_in_comparison_table=[s.label for s in sch if s.key == key_a and s.status == "built"],
        rows_without_numbers=[s.label for s in sch if s.key == key_a and s.status != "built" and "K=" in s.label])
    # the same bandwidth three ways: the chip's widest channel native on A, by x K on A, by x K on B
    same = [s for s in sch if s.status == "built" and s.waveform not in AY_WAVEFORMS and s.cfg.carrier_hz > 50e9
            and abs(s.cfg.upclocked().bandwidth_eff - widest) < 1.0 and not s.cfg.ifext.chip_pa_bypass]
    native = [s for s in same if s.topology == "if_extender" and s.cfg.upclock_k == 1]
    std = native[0].cfg.phy.standard if native else None
    by_k = [s for s in same if s.cfg.upclock_k > 1 and s.cfg.phy.standard == std]
    k_common = sorted({s.cfg.upclock_k for s in by_k if s.topology == "if_extender"}
                      & {s.cfg.upclock_k for s in by_k if s.topology == "upclock_zero_if"})
    pick = native[:1] + [s for topo in ("if_extender", "upclock_zero_if") for s in by_k
                         if k_common and s.cfg.upclock_k == k_common[0] and s.topology == topo]
    up["same_bandwidth_three_ways"].update(bandwidth_hz=widest, rows=[s.label for s in pick])
    doc.update(kind="system", study=st, engine=ENGINE_BANNER, parts={"per_row_terms": "table.analytic"})
    return _json(doc)


__all__ = [
    "SCHEMA", "ROW_KNOBS", "SHARED_KNOBS", "KNOB_SOURCE", "PARTS", "JOBS", "STORED", "FOOTING", "BE_FIELDS",
    "DISPLAY", "Part", "reference_config", "study", "apply_study", "frontend", "schemes", "reads",
    "closure", "signature", "pins", "vendored", "spec_digest", "commit", "provenance", "config_sha",
    "envelope", "job_result", "envelopes_of", "freshness", "field_states", "freshness_matrix", "source",
    "sources", "source_counts", "knob_tag", "form", "front_end_report", "table_report",
    "calibration_from_runs", "assemble_table", "lo_models_report", "sensitivity_report", "terms_share",
    "sc_vs_ofdm_items", "run_job", "metric_unit", "calibration_report", "array_inputs",
    "eirp_limit_report", "array_report", "single_antenna_ranges",
    "ay_inputs", "ay_report", "sc_vs_ofdm_headline", "repro", "calibration_column_for", "row_detail",
    "system_report",
]


# ------------------------------------------------------------------ a job, run (command line and hosts alike)
def run_job(job: str, st: dict | None = None, *, quick: bool = False, progress=None,
            calibration: dict | None = None, log=None) -> dict:
    """Compute one job of ``JOBS`` for a study and return its ``job_result`` (the thing a host
    stores and ``tools/gui_report.py`` writes).

    ``progress(done, total, text)`` is called as the run advances; ``total`` is None where the
    number of steps is not known beforehand.  It may raise to stop the run (a thread host's
    cancel).  ``calibration`` is a stored ``calibration_be`` result: a table job looks its IRR up
    there instead of in the accepted table when that result was computed for this study's
    calibration signature, and records it in ``built_on``.  ``quick`` is the smoke size (tests):
    its numbers are not the study's."""
    if job not in JOBS:
        raise KeyError(f"no such job {job!r} (have {sorted(JOBS)})")
    st = study(st)
    t0 = time.time()
    count = [0]

    def tick(total, text):
        count[0] += 1
        if progress:
            progress(count[0] if total is None else min(count[0], total), total, text)
    built_on: dict = {}
    parts = None
    if job in ("table", "table_analytic"):
        irr = None
        if calibration is not None and (signature("calibration.be", calibration["study"])
                                        == signature("calibration.be", st)) and not quick:
            irr = calibration["report"]["irr_after_cal_db"]
            built_on["calibration.be"] = calibration["study"]
        full = job == "table"
        n = len([s for s in schemes(st, quick=quick) if s.status == "built" and s.waveform not in AY_WAVEFORMS])
        rep = table_report(st, time_domain=full, quick=quick, irr_table=irr, sensitivity=not quick,
                           lo_models=full and not quick,
                           progress=lambda row: tick(n + (1 if full else 0), row.label))
        if full:
            tick(n + 1, "802.11ay")
        else:
            parts = ["table.analytic"]
    elif job == "calibration_be":
        rep = calibration_report(st, quick=quick, log=log, progress=progress)
    elif job == "array":
        sec = arrayreport.SECTIONS
        rep = array_report(st, quick=quick, progress=lambda s, row: (
            progress(sec.index(s) + 1 if s in sec else len(sec), len(sec), s) if progress and row is None else None))
        rep["headline"] = sc_vs_ofdm_headline(rep) if rep.get("ay") else None
    else:
        sec = ayreport.SECTIONS
        rep = ay_report(st, quick=quick, progress=lambda s, row: (
            progress(sec.index(s) + 1 if s in sec else len(sec), len(sec), s) if progress and row is None else None))
    out = job_result(job, st, rep, time.time() - t0, parts, built_on)
    out["quick"] = bool(quick)
    return out
