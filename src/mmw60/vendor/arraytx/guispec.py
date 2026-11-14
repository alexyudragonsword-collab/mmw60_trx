# Vendored from array_tx@5815c5a7ea43143fd58502d4894ac840b5b5fb86: src/arraytx/guispec.py
# Adapted-copy policy: see src/mmw60/vendor/__init__.py
"""The front-end contract: what the page may turn, what it reads back, what
it draws.  ``guiutil`` computes; this module only describes.

Rule 1 of the repository (the YAML is the one truth) is what this file
enforces for a GUI: every control IS a config leaf -- the list comes from
``config.form_fields()`` with its unit, help, choices and provenance, and
``values_to_config`` turns the page's flat ``{path: value}`` back into an
``ArrayConfig`` through the same ``config_from_dict`` a YAML file goes
through, so a value the page shows is a value the YAML would hold.  No
default is typed here; ``tests/test_guispec.py`` requires the default of
every control to equal ``default_config()`` and the default form to build
the default config bit for bit.

Rule 2 (metrics are read in space) shows up as ``METRICS``: each has a
domain, and the diagnostic (conducted) ones are declared diagnostic so the
page cannot promote them.
"""
from __future__ import annotations

import io
from dataclasses import asdict, dataclass
from typing import Any

import yaml

from .config import ArrayConfig, _get, config_from_dict, default_config, form_fields
from .dpd import SCHEMES
from .lo import list_bundled
from .standards import STANDARDS

#: control groups in display order: first path component -> (zh, en)
GROUPS: dict[str, tuple[str, str]] = {
    "standard": ("制式与阵列", "standard & array"),
    "element": ("单元", "element"),
    "coupling": ("互耦", "coupling"),
    "beam": ("波束", "beam"),
    "dpd": ("DPD", "DPD"),
    "metrics": ("指标与仿真", "metrics & sim"),
}
_GROUP_OF = {"arraytx_config": "standard", "seed": "standard", "standard": "standard", "array": "standard",
             "element": "element", "coupling": "coupling", "beam": "beam", "dpd": "dpd",
             "metrics": "metrics", "sim": "metrics"}

#: a control shown only while another control holds one of these values
VISIBLE_WHEN: dict[str, tuple[str, tuple[Any, ...]]] = {
    "coupling.analytic.": ("coupling.source", ("analytic",)),
    "coupling.survey.": ("coupling.source", ("survey",)),
    "coupling.touchstone.": ("coupling.source", ("touchstone",)),
    "element.pa.rapp_": ("element.pa.amam", ("rapp",)),
    "dpd.n_iterations": ("dpd.scheme", ("per_element", "array")),
    "dpd.regularization": ("dpd.scheme", ("per_element", "array")),
    "dpd.gmp.": ("dpd.scheme", ("per_element", "array")),
    "dpd.per_element_observe": ("dpd.scheme", ("per_element",)),
    "element.lo.spurs": ("element.lo.clock_profile", ("<set>",)),
    "element.pa.load_pull.": ("element.pa.load_pull.enabled", (True,)),
    "element.outphasing.": ("element.topology", ("outphasing",)),
}
#: hidden from the page (CI-only or structural), still part of the YAML
HIDDEN = ("arraytx_config", "sim.smoke_n_symbols")


@dataclass(frozen=True)
class Control:
    path: str                 # the YAML key, dotted
    kind: str                 # int | float | bool | choice | text | list | path | optional_float
    group: str
    label: str                # the leaf name (what the YAML calls it)
    unit: str
    help: str
    default: Any
    choices: tuple | None = None
    source: str | None = None   # provenance of the DEFAULT (declared on the field)
    ref: str | None = None
    visible_when: tuple | None = None   # (path, values) or None
    step: float | None = None
    lo: float | None = None
    hi: float | None = None


def _kind(ff) -> str:
    t = ff.type
    if ff.choices is not None:
        return "choice"
    if t == "bool":
        return "bool"
    if t == "int":
        return "int"
    if t == "float":
        return "float"
    if t == "float | None":
        return "optional_float"
    if t == "list":
        return "list"
    if ff.unit == "path":
        return "path"
    return "text"


#: display ranges / steps for the numeric controls (display only: the config
#: validates; a value outside the range is still a legal YAML value)
_RANGES: dict[str, tuple[float, float, float]] = {
    "seed": (0, 2**31 - 1, 1), "array.n_elements": (1, 256, 1), "array.spacing_lambda": (0.1, 2.0, 0.05),
    "element.errors.gain_sigma_db": (0, 5, 0.1), "element.errors.phase_sigma_deg": (0, 30, 0.5),
    "element.errors.delay_sigma_ps": (0, 50, 0.5), "element.errors.pa_dev_sigma": (0, 0.5, 0.01),
    "element.pa.n_bits": (4, 14, 1), "element.pa.n_thermo": (0, 10, 1), "element.pa.sigma_cell": (0, 0.05, 0.001),
    "element.pa.rapp_p": (0.5, 5, 0.1), "element.pa.rapp_drive": (0.2, 3, 0.05), "element.pa.ampm_deg_at_fs": (0, 30, 0.5),
    "element.lo.loop_bw_hz": (1e4, 1e7, 1e4), "coupling.scale_db": (-60, 6, 1),
    "coupling.analytic.c1_db": (-40, 0, 0.5), "coupling.analytic.c1_deg": (-180, 180, 1), "coupling.analytic.c2_rel_db": (-30, 0, 0.5),
    "coupling.survey.c1_db": (-40, 0, 0.5), "coupling.survey.c1_deg_at_f0": (-180, 180, 1), "coupling.survey.c2_rel_db": (-30, 0, 0.5),
    "dpd.n_iterations": (1, 5, 1), "dpd.regularization": (0, 1e-3, 1e-9), "dpd.gmp.order": (1, 11, 2),
    "dpd.gmp.memory_depth": (1, 8, 1), "dpd.gmp.lag_order": (0, 9, 1), "dpd.gmp.lag_memory": (0, 8, 1), "dpd.gmp.lag_span": (0, 4, 1),
    "dpd.gmp.lead_order": (0, 9, 1), "dpd.gmp.lead_memory": (0, 8, 1), "dpd.gmp.lead_span": (0, 4, 1),
    "sim.n_symbols": (1, 64, 1), "sim.cfr_papr_db": (4, 12, 0.1),
}


def controls() -> list[Control]:
    """Every config leaf as a control, in YAML order.  Choices for the clock
    profile are the bundled presets (plus "none"), read from the package."""
    out = []
    for ff in form_fields():
        if ff.path in HIDDEN:
            continue
        vis = None
        for prefix, rule in VISIBLE_WHEN.items():
            if ff.path.startswith(prefix) and ff.path != rule[0]:      # the switch itself is always shown
                vis = rule
                break
        choices = ff.choices
        if ff.path == "element.lo.clock_profile":
            choices = (None,) + tuple(f"bundled:{n}" for n in list_bundled())
        if ff.path == "dpd.scheme":
            choices = tuple(SCHEMES)
        if ff.path == "standard":
            choices = tuple(sorted(STANDARDS))
        lo, hi, step = _RANGES.get(ff.path, (None, None, None))
        out.append(Control(ff.path, _kind(ff) if ff.path != "element.lo.clock_profile" else "choice",
                           _GROUP_OF[ff.path.split(".")[0]], ff.path.split(".")[-1], ff.unit, ff.help,
                           ff.default, choices, ff.source, ff.ref, vis, step, lo, hi))
    return out


#: metrics the page reads back; ``better`` says which way is an improvement
#: for the delta against a baseline; ``domain`` is the repository's rule 2
METRICS: dict[str, dict[str, Any]] = {
    "evm_db": {"zh": "EVM", "en": "EVM", "unit": "dB", "better": "lower", "domain": "ota", "digits": 2},
    "evm_pct": {"zh": "EVM", "en": "EVM", "unit": "%", "better": "lower", "domain": "ota", "digits": 2},
    "aclr1_dbc": {"zh": "ACLR1", "en": "ACLR1", "unit": "dBc", "better": "lower", "domain": "ota", "digits": 1},
    "aclr2_dbc": {"zh": "ACLR2", "en": "ACLR2", "unit": "dBc", "better": "lower", "domain": "ota", "digits": 1},
    "sem_margin_db": {"zh": "谱模板余量", "en": "mask margin", "unit": "dB", "better": "higher", "domain": "ota", "digits": 2,
                      "note_zh": "stylized 工程模板，非一致性条款", "note_en": "stylized template, not a conformance clause"},
    "evm_per_tone_db": {"zh": "EVM（per-tone 均衡）", "en": "EVM (per-tone EQ)", "unit": "dB", "better": "lower", "domain": "ota", "digits": 2},
    "squint_deg": {"zh": "带边斜视", "en": "band-edge squint", "unit": "°", "better": None, "domain": "info", "digits": 2},
    "beamwidth_deg": {"zh": "3 dB 波束宽", "en": "3 dB beamwidth", "unit": "°", "better": None, "domain": "info", "digits": 2},
    "eta_array_pct": {"zh": "阵列漏极效率（含 Γ）", "en": "array drain efficiency (Gamma in)", "unit": "%", "better": "higher", "domain": "info", "digits": 1,
                    "note_zh": "阵列：辐射功率 / 直流功率；端口净功率 |a|²(1−|Γ|²)，开关损耗按码（polar_tx 的 SCPA 律）", "note_en": "array: radiated / DC power; net port power |a|^2 (1-|Gamma|^2), switching loss set by the code (polar_tx's SCPA law)"},
    "conducted_evm_db": {"zh": "导通 EVM", "en": "conducted EVM", "unit": "dB", "better": "lower", "domain": "diagnostic", "digits": 2},
    "conducted_aclr1_dbc": {"zh": "导通 ACLR1", "en": "conducted ACLR1", "unit": "dBc", "better": "lower", "domain": "diagnostic", "digits": 1},
}

#: plots a report carries; ``kind`` tells charts.js what to draw
PLOTS: list[dict[str, str]] = [
    {"id": "direction", "kind": "lines", "zh": "ACLR1 随方向 · 失真往哪辐射", "en": "ACLR1 vs direction",
     "x": "θ [deg]", "y": "ACLR1 [dBc]", "y2": "方向图 [dB]"},
    {"id": "spectrum", "kind": "lines", "zh": "波束方向远场频谱 + stylized 模板", "en": "far-field spectrum at the beam + stylized mask",
     "x": "基带频率 [MHz]", "y": "PSD [dB]"},
    {"id": "constellation", "kind": "scatter", "zh": "星座 @ 波束", "en": "constellation at the beam", "x": "I", "y": "Q"},
]


def spec() -> dict:
    """The whole contract as JSON-ready data (what ``GET /api/spec`` serves)."""
    return {"groups": [{"id": g, "zh": zh, "en": en} for g, (zh, en) in GROUPS.items()],
            "controls": [asdict(c) for c in controls()],
            "metrics": METRICS, "plots": PLOTS,
            "schemes": list(SCHEMES), "steering": ["phase", "ttd"],
            "standards": sorted(STANDARDS), "bundled_profiles": list_bundled()}


# ------------------------------------------------------------ values <-> config
def values_from_config(cfg: ArrayConfig) -> dict[str, Any]:
    """The flat ``{path: value}`` the page edits (hidden leaves included, so a
    round trip loses nothing)."""
    return {ff.path: _get(cfg, ff.path) for ff in form_fields()}


def _nest(flat: dict[str, Any]) -> dict:
    out: dict = {}
    for path, v in flat.items():
        d = out
        parts = path.split(".")
        for p in parts[:-1]:
            d = d.setdefault(p, {})
        d[parts[-1]] = v
    return out


def values_to_config(flat: dict[str, Any], base: ArrayConfig | None = None) -> ArrayConfig:
    """Flat values -> ArrayConfig through ``config_from_dict`` (validated).

    Provenance of the numbers the page did not touch is carried over from
    ``base`` (the loaded file): a survey number keeps its citation unless the
    page changed it, in which case it becomes ``assumed`` with a note saying
    so -- a GUI edit is a design choice, not a citation."""
    data = _nest({k: v for k, v in flat.items()})
    if base is None:
        base = default_config()          # provenance declared on the fields (the survey defaults' citations)
    for path, s in base.provenance.items():
        cur = flat.get(path, _get(base, path))
        if cur == s.value and (s.ref or s.source != "assumed"):
            _set_mapping(data, path, {"value": cur, "source": s.source, "ref": s.ref})
        elif path.startswith("coupling.survey.") and cur != s.value:
            _set_mapping(data, path, {"value": cur, "source": "assumed",
                                      "ref": f"assumed: edited in the GUI (was {s.value!r}, {s.source})"})
    return config_from_dict(data, base.source_path)


def _set_mapping(data: dict, path: str, mapping: dict) -> None:
    d = data
    parts = path.split(".")
    for p in parts[:-1]:
        d = d.setdefault(p, {})
    d[parts[-1]] = mapping


def to_yaml(cfg: ArrayConfig) -> str:
    """The config as a YAML text that ``load_config`` reads back to the same
    values AND the same provenance: numbers with a citation (or a declared
    non-assumed source) are written in ``{value, source, ref}`` form."""
    data = cfg.to_dict()
    for path, s in cfg.provenance.items():
        if s.ref or s.source != "assumed":
            _set_mapping(data, path, {"value": s.value, "source": s.source, "ref": s.ref})
    buf = io.StringIO()
    buf.write("# written by arraytx-gui; numbers without {value, source, ref} are design choices (source: assumed)\n")
    yaml.safe_dump(data, buf, sort_keys=False, allow_unicode=True, width=120)
    return buf.getvalue()


def diff(a: ArrayConfig, b: ArrayConfig) -> list[dict[str, Any]]:
    """Leaves that differ between two configs: [{path, a, b}]."""
    va, vb = values_from_config(a), values_from_config(b)
    return [{"path": p, "a": va[p], "b": vb[p]} for p in va if va[p] != vb[p]]
