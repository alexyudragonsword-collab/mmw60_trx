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
from pathlib import Path
from typing import Any

from . import ENGINE_BANNER, __version__, calcheck, compare, guispec, spec
from .config import AY_WAVEFORMS, Mmw60Config, zero_if_60ghz
from .frontend import Frontend60
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
         _S - {"phy.packet_bytes", "rx.ce_smooth_auto", "rx.ce_smooth_tones"}, (), "table"),
)}

JOBS = {
    "calibration_be": {"parts": ("calibration.be",), "command": "python examples/03_calibration_at_k.py",
                       "report": "calibration", "seconds": [809],
                       "seconds_note": "809 s with three examples side by side on a 4-core container; "
                                       "12 steps per column"},
    "table": {"parts": ("table.analytic", "table.td", "table.ay"), "command": "python examples/04_comparison_table.py",
              "report": "table", "seconds": [58, 126, 174],
              "seconds_note": "58 s alone on a 4-core container; 126 / 174 s with three examples side by side"},
    "table_analytic": {"parts": ("table.analytic",),
                       "command": "python tools/budget_report.py --base 11ac:20e6 --base 11be:80e6 --no-time-domain",
                       "report": "table", "seconds": None,
                       "seconds_note": "about 20 s (topology A's rows build the chip and run its calibration)"},
}
#: stored measurements a study can make stale but this layer does not recompute (hours of PER curves)
STORED = {
    "thresholds.be": {"command": "python tools/measure_thresholds.py",
                      "file": "src/mmw60/data/spec/per_thresholds.yaml"},
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
def envelope(part: str, st: dict | None, payload: dict, seconds: float | None = None) -> dict:
    """A computed part with what it read and where it was computed."""
    st = study(st)
    return {"part": part, "schema": SCHEMA, "study": {k: v for k, v in st.items() if k in PARTS[part].reads},
            "signature": signature(part, st), "upstream": {u: signature(u, st) for u in closure(part)[:-1]},
            "provenance": provenance(), "seconds": seconds, "payload": _json(payload)}


def job_result(job: str, st: dict | None, report: dict, seconds: float | None = None, parts=None) -> dict:
    """What a host stores after a job: the report with the study it was computed for and where.
    ``parts`` narrows the parts the run produced (an analytic-only table has no time-domain column)."""
    st = study(st)
    return {"job": job, "schema": SCHEMA, "study": st, "parts": list(JOBS[job]["parts"] if parts is None else parts),
            "provenance": provenance(), "seconds": seconds, "report": _json(report)}


def envelopes_of(result: dict) -> dict[str, dict]:
    """A stored job result as one envelope per part it produced (what ``freshness`` reads)."""
    out = {}
    for pid in result["parts"]:
        st = result["study"]
        out[pid] = {"part": pid, "schema": result["schema"],
                    "study": {k: v for k, v in st.items() if k in PARTS[pid].reads},
                    "signature": signature(pid, st), "upstream": {u: signature(u, st) for u in closure(pid)[:-1]},
                    "provenance": result["provenance"], "seconds": result["seconds"], "payload": None}
    return out


def freshness(st: dict | None, envelopes: dict[str, dict] | None = None) -> dict:
    """Per part, against the form as it is now: ``fresh``, ``stale`` (with the knobs that moved it
    and the upstream parts that are stale) or ``missing``.

    A part with no envelope is judged against the accepted results, which are the presets'
    (study ``{}``): it is fresh while the study leaves the knobs it reads at their presets.  That
    is how the stored measurements (the decoder thresholds) are judged always."""
    st = study(st)
    envelopes = envelopes or {}
    out: dict[str, dict] = {}
    for pid in sorted(PARTS, key=lambda p: len(closure(p))):
        part, env = PARTS[pid], envelopes.get(pid)
        have = (env or {}).get("study", {}) if env and env.get("schema") == SCHEMA else {}
        changed = sorted(k for k in part.reads if st.get(k, None) != have.get(k, None))
        if env is not None and env.get("schema") != SCHEMA:
            changed = sorted(part.reads)
        up = [u for u in part.upstream if out[u]["state"] != "fresh"]
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
    for group in list(BE_FIELDS) + ["table.ay"]:
        own, _, up = group.partition("+")
        stale = bool(fresh[own]["changed"]) or (bool(up) and fresh[up]["state"] != "fresh")
        out[group] = "stale" if stale else "fresh"
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
    ref = apply_study(row if row is not None else reference_config(stv.get("carrier_hz", PRESET_CARRIER_HZ)), {})
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
    "table.analytic": ["floor_db", "terms_db", "dominant", "max_mcs", "rate_mbps", "power", "verdict", "reason",
                       "evm_budget", "eirp", "cfo_captured", "plan_ok"],
    "table.analytic+calibration.be": ["floor_cal_db", "irr_cal_db", "irr_cal_measured_at_hz", "max_mcs_cal",
                                      "rate_cal_mbps", "power_cal", "dec_mcs_cal", "dec_rate_cal_mbps",
                                      "dec_mcs_cal_range", "dec_cal_next_margin_db"],
    "table.analytic+thresholds.be": ["dec_mcs", "dec_mcs_range", "dec_next_margin_db", "dec_required_snr_db",
                                     "dec_penalty_db", "dec_rate_mbps", "power_dec", "dec_mcs_cal", "dec_rate_cal_mbps",
                                     "dec_mcs_cal_range", "dec_cal_next_margin_db"],
    "table.td": ["td_evm_db", "td_delta_db", "td_ok", "dec_floor_db"],
}
#: decimals the accepted outputs print each field with (one rounding, from the full value)
DISPLAY = {"floor_db": 1, "floor_cal_db": 1, "td_evm_db": 1, "td_delta_db": 1, "terms_db": 1, "rate_mbps": 0,
           "rate_cal_mbps": 0, "dec_rate_mbps": 0, "dec_rate_cal_mbps": 0, "pj_per_bit": 0, "irr_cal_db": 1,
           "dec_next_margin_db": 2, "dec_cal_next_margin_db": 2, "dec_required_snr_db": 2, "dec_penalty_db": 2,
           "eirp_margin_db": 0, "ay_floor_db": 2, "cfo_subcarriers": 2}


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
        "rx_front": {"gain_db": f.get("gain_db"), "nf_db": f.get("nf_db"), "iip3_dbm": f.get("iip3_dbm")},
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
                 irr_table: dict | None = None, ay: bool = True, labels=None, progress=None) -> dict:
    """The comparison table of a study: ``compare.build`` on its schemes and its front end, each row
    as ``compare`` reports it plus its footing, its config hash and the cross-check merged in.

    ``irr_table`` is a calibration result's IRR by bandwidth (``calibration_report(...)["irr_after_cal_db"]``);
    without one the calibrated columns use the accepted table, ``derived.irr_after_cal_measured_db``,
    which belongs to the presets — ``freshness`` says when a study has moved away from it.
    ``time_domain=False`` computes the analytic columns only (and leaves the 802.11ay rows out, whose
    floors are time-domain readings); ``ay=False`` leaves them out of a full run; ``labels`` keeps
    only those rows (one row recomputed, a test's subset)."""
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
        "irr_table": {"from": "calibration result" if irr_table is not None else "derived.irr_after_cal_measured_db",
                      "db_by_bandwidth_hz": (table if table is not None
                                             else spec.value("derived.irr_after_cal_measured_db"))},
        "margins": {"mcs_evm_margin_db": spec.value("assumed.mcs_evm_margin_db"),
                    "decoder_cap_margin_db": spec.value("assumed.decoder_cap_margin_db")},
    })


# ------------------------------------------------------------------ report: the calibration runs
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
                          "metric": metric or None, "value": value, "detail": detail or None})
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


def calibration_report(st: dict | None = None, *, plan=None, quick: bool = False, log=None) -> dict:
    """wifitrx's calibration sequence really run on the study's front end, one column per (K, base
    bandwidth) of ``plan`` (``calcheck.DEFAULT_PLAN``: example 03's six columns), exactly as
    example 03 runs it — at the front end's back-off, with the DPD step."""
    st = study(st)
    fe = frontend(st)
    plan = (calcheck.QUICK_PLAN if quick else calcheck.DEFAULT_PLAN) if plan is None else plan
    runs = []
    for k, base in plan:
        runs.append(calcheck.run_cal_at(fe, k, base, with_dpd=not quick, log=log,
                                        standard="11be" if base == 80e6 else "11ac", obo_db=fe.obo_db))
    return calibration_from_runs(runs, fe, st)


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
        "rx_gain_db": faces.get("gain_db"), "rx_nf_db": faces.get("nf_db"), "rx_iip3_dbm": faces.get("iip3_dbm"),
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
    "calibration_from_runs", "calibration_report", "repro", "calibration_column_for", "row_detail",
    "system_report",
]
