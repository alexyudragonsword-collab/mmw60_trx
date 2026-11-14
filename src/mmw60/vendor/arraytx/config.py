# Vendored from array_tx@5815c5a7ea43143fd58502d4894ac840b5b5fb86: src/arraytx/config.py
# Adapted-copy policy: see src/mmw60/vendor/__init__.py
"""The one configuration that is the truth (invariant 1).

Array geometry, element topology, standard, coupling source, DPD scheme and
scan angles all live in one YAML file, loaded into the dataclass tree below.
Nothing in the simulation reads a default from anywhere else.

Form-field declarations
-----------------------
Every leaf field carries ``metadata`` with a unit, a help string and, where
it applies, the allowed choices.  ``form_fields()`` walks the tree and returns
them as a flat list — the declaration a GUI (not built this round, polar_tx
style) would render, and what ``tests/test_config.py`` checks for coverage.

Provenance
----------
A numeric leaf in the YAML may be a plain scalar or a mapping
``{value: -16.0, source: survey, ref: "..."}``.  Plain scalars are recorded as
``source: assumed``.  The ``coupling.survey`` block is special: every number
in it must say ``survey`` and carry a ref, or the file does not load — a
survey value without a citation is not allowed into the config (AGENTS.md).
``ArrayConfig.provenance`` maps the dotted path of every numeric leaf to its
:class:`~arraytx.standards.Sourced`.
"""
from __future__ import annotations

import copy
import dataclasses
import math
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

import yaml

from .standards import STANDARDS, Sourced

CONFIG_VERSION = 1


def _f(default, unit: str, help: str, choices: tuple | None = None,
       source: str | None = None, ref: str | None = None, **kw):
    """A leaf field with its form declaration (and, for a default that is an
    external number, its provenance — used when the YAML leaves it out)."""
    md = {"unit": unit, "help": help}
    if choices is not None:
        md["choices"] = tuple(choices)
    if source is not None:
        md["source"] = source
        md["ref"] = ref or ""
    if isinstance(default, (list, dict, tuple)):
        # a fresh copy per instance: a shared list would let one config's
        # mutation leak into every later default_config()
        return field(default_factory=lambda: copy.deepcopy(default), metadata=md, **kw)
    return field(default=default, metadata=md, **kw)


@dataclass
class ArrayGeometryCfg:
    n_elements: int = _f(4, "", "elements per row (along x); the whole array is n_elements x n_rows, row-major")
    n_rows: int = _f(1, "", "rows (along y); 1 = the linear array")
    spacing_lambda: float = _f(0.5, "lambda0", "element pitch along x in carrier wavelengths (0.5 = half wave)")
    spacing_y_lambda: float = _f(0.5, "lambda0", "row pitch along y in carrier wavelengths")
    element_pattern: str = _f("isotropic", "", "element pattern applied to the far field", ("isotropic", "cos"))


@dataclass
class ElementErrorsCfg:
    enabled: bool = _f(True, "", "draw per-element gain/phase/delay errors and PA deviations (off: drawn, then zeroed)")
    gain_sigma_db: float = _f(0.5, "dB", "per-element gain error, 1 sigma")
    phase_sigma_deg: float = _f(5.0, "deg", "per-element phase error at the carrier, 1 sigma")
    delay_sigma_ps: float = _f(2.0, "ps", "per-element group-delay error, 1 sigma")
    pa_dev_sigma: float = _f(0.05, "", "relative 1-sigma deviation of the PA's compression knee (rapp drive) and AM-PM scale")


LOADPULL_REF = ("assumed: ideal voltage-source reading of a switched-capacitor / class-D DPA -- the port swing is v_fwd (1 + Gamma) "
                "and the supply rail limits that total swing, so compression is read at |1 + Gamma| times the drive; a measured "
                "load-pull table (source: measured) would replace this scalar (cairn/load-pull-proposal.md)")


@dataclass
class LoadPullCfg:
    enabled: bool = _f(False, "", "load modulation: each element's PA compresses on its total port swing |1 + Gamma_k| (Gamma_k from the coupling leakage); off = milestone-1 linear leakage")
    kappa_amam: float = _f(1.0, "", "how much of Gamma reaches the AM-AM knee (1 = ideal voltage source)", source="assumed", ref=LOADPULL_REF)
    kappa_ampm: float = _f(1.0, "", "how much of Gamma reaches the AM-PM (1 = read at the total swing)", source="assumed", ref=LOADPULL_REF)
    iterations: int = _f(2, "", "fixed-point rounds Gamma -> PA -> Gamma per radiate (|S| <= -16 dB converges in 2)")
    gamma_max: float = _f(1.0, "", "clip on |Gamma_k| per sample: total reflection, a guard against envelope dips, not physics. 0.5 (the first default) acted on 40 % of the 8 x 8 broadside samples and moved its efficiency by 1-2 points (ex13); info['load_pull']['clip_fraction'] says how often it acts")
    floor: float = _f(0.05, "", "Gamma_k = 0 where |y_k| < floor x full scale (the ratio means nothing near an envelope zero)")


@dataclass
class ElementPACfg:
    n_bits: int = _f(10, "bit", "DPA amplitude resolution (polar_tx DPAConfig)")
    n_thermo: int = _f(6, "bit", "thermometer-coded MSBs (polar_tx DPAConfig)")
    sigma_cell: float = _f(0.002, "", "relative random unit-cell mismatch (polar_tx DPAConfig)")
    amam: str = _f("rapp", "", "AM-AM law (ideal = polar_tx nr_dtc default)", ("ideal", "rapp"))
    rapp_p: float = _f(2.0, "", "Rapp smoothness (CMOS PA ~1-3); used when amam=rapp")
    rapp_drive: float = _f(1.0, "", "Rapp drive at full scale (compression depth); used when amam=rapp")
    backoff_db: float = _f(0.0, "dB", "envelope full-scale headroom above the undistorted peak: the chain's full scale is raised by this, so the signal uses 10^(-backoff/20) of the code range (output power backoff; 0 = peak at full scale, polar_tx's pin)")
    backoff_per_element_db: list = _f([], "dB", "per-element output backoff, one value per element in row-major order (empty = every element at backoff_db). Element k's full scale sits b_k above the undistorted peak, and its radiated amplitude drops by b_k - min(b): it really gives that power up (ROADMAP B9, ex20)")
    ampm_deg_at_fs: float = _f(8.0, "deg", "AM-PM at full scale, quadratic in amplitude (0 = none)")
    load_pull: LoadPullCfg = field(default_factory=LoadPullCfg)


@dataclass
class ElementLOCfg:
    shared: bool = _f(True, "", "one physical LO for all elements (identical LO phase-noise sample; jitter stays per element)")
    clock_profile: str | None = _f(None, "path", "pll_simulator clock-profile YAML for the shared LO: a path, or bundled:<preset> for one shipped with arraytx; null = polar_tx preset LO")
    loop_bw_hz: float = _f(400e3, "Hz", "LO PLL loop bandwidth below which the profile is flattened (polar_tx convention)")
    spurs: bool = _f(True, "", "inject the clock profile's discrete spurs (reference / fractional, its spurs: table) as sinusoidal LO phase modulation at the carrier, start phase per spur from its own seed stream; off = L(f) curve only (the phases are still drawn)")


OUTPHASING_RHO_REF = ("assumed: no published R_on / Z0 for a 28 GHz outphasing branch was found; 0 = ideal voltage "
                      "sources (polar_tx), 0.02-0.1 is the range the study scans (cairn/outphasing-load-proposal.md)")


@dataclass
class ElementOutphasingCfg:
    source_impedance_rel: float = _f(0.0, "", "branch PA source impedance relative to the branch load (rho): with the Chireix susceptance it distorts AM-AM; the array's Gamma enters only as a complex gain (Thevenin). 0 = polar_tx's ideal combiner, bit for bit", source="assumed", ref=OUTPHASING_RHO_REF)


@dataclass
class ElementCfg:
    topology: str = _f("polar", "", "element TX topology (polar_tx class)", ("polar", "outphasing", "rfdac"))
    errors: ElementErrorsCfg = field(default_factory=ElementErrorsCfg)
    pa: ElementPACfg = field(default_factory=ElementPACfg)
    lo: ElementLOCfg = field(default_factory=ElementLOCfg)
    outphasing: ElementOutphasingCfg = field(default_factory=ElementOutphasingCfg)


@dataclass
class CouplingAnalyticCfg:
    c1_db: float = _f(-16.0, "dB", "adjacent-element coupling magnitude, flat over frequency")
    c1_deg: float = _f(180.0, "deg", "adjacent-element coupling phase, flat over frequency")
    c2_rel_db: float = _f(-6.0, "dB", "next-adjacent coupling relative to c1; further neighbours are zero")
    c1y_rel_db: float = _f(0.0, "dB", "adjacent coupling ALONG Y (next row) relative to c1 (planar arrays only)")
    c_diag_rel_db: float = _f(-6.0, "dB", "diagonal neighbour (next row, next column) relative to c1 (planar arrays only)")
    phase_from_distance: bool = _f(True, "", "phase of the farther classes = c1_deg + the free-space electrical length beyond one pitch (x2 at lambda/2 pitch: +180 deg); off = every class at c1_deg (the milestone-1 reading, not passive on a 2-D grid)")


SURVEY_REF_C1 = ('assumed (ROADMAP A1): no full text read gives a measured adjacent coupling for a 28 GHz lambda/2 '
                 'patch array without decoupling. Abstract-level only: US patent 10910732 — 28 GHz array, measured '
                 'mutual coupling better than -16 dB; Int. J. Electron. Commun. (ScienceDirect S1434841126001263) — '
                 'lambda/2 (5.4 mm) SIW endfire array, adjacent coupling below -15 dB in the lower band. Full texts '
                 'read 2026-11-05: arXiv:2407.09944 (28 GHz linear patch array, lambda0/2 = 5.34 mm, CATR OTA) states '
                 'no coupling number; simulated, no decoupling: JEES 26(3) 2026, doi:10.26866/jees.2026.3.r.363, '
                 'adjacent below -20 dB at 5 mm (~0.47 lambda), arXiv:2010.16049 -24 dB at 28 GHz (circular array). '
                 '-16 dB is kept as the pessimistic end of these')
SURVEY_REF_PHASE = ("assumed: sign convention only -- the adjacent coupled wave arrives half a wavelength (pi) later "
                    "at f0 for lambda/2 pitch; the papers above do not publish the phase")
SURVEY_REF_C2 = ("assumed: next-adjacent coupling 6 dB below adjacent is the common reading of published S-parameter "
                 "plots for lambda/2 patch rows (free-space 1/r over twice the distance); no paper-level number")
SURVEY_REF_C1Y = ("assumed: the same adjacent coupling along y as along x -- the papers above are linear rows and give "
                  "no H-plane number; for patches the E- and H-plane couplings differ by several dB, which this knob is for")
SURVEY_REF_DIAG = ("assumed: a diagonal neighbour at sqrt(2) pitch 6 dB below adjacent -- free-space 1/r would give 3 dB, "
                   "published patch S-parameter plots fall faster than 1/r; no paper-level number")


@dataclass
class CouplingSurveyCfg:
    c1_db: float = _f(-16.0, "dB", "adjacent-element coupling magnitude at f0 (28 GHz lambda/2 patch row; published bounds in the ref)",
                      source="assumed", ref=SURVEY_REF_C1)
    c1_deg_at_f0: float = _f(180.0, "deg", "adjacent coupling phase at f0", source="assumed", ref=SURVEY_REF_PHASE)
    c2_rel_db: float = _f(-6.0, "dB", "next-adjacent coupling relative to c1", source="assumed", ref=SURVEY_REF_C2)
    c1y_rel_db: float = _f(0.0, "dB", "adjacent coupling along y (next row) relative to c1 (planar arrays only)",
                           source="assumed", ref=SURVEY_REF_C1Y)
    c_diag_rel_db: float = _f(-6.0, "dB", "diagonal neighbour relative to c1 (planar arrays only)", source="assumed", ref=SURVEY_REF_DIAG)
    phase_from_distance: bool = _f(True, "", "phase at f0 of the farther classes = c1_deg_at_f0 + free-space electrical length beyond one pitch (consistent with path_delay_from_spacing); off = every class at c1_deg_at_f0")
    path_delay_from_spacing: bool = _f(True, "", "phase slope vs frequency = free-space delay over the element pitch (linear phase)")


@dataclass
class CouplingTouchstoneCfg:
    path: str | None = _f(None, "path", ".sNp file with N = n_elements x n_rows ports in row-major element order; interpolated onto the baseband grid")


@dataclass
class CouplingCfg:
    source: str = _f("survey", "", "where the coupling matrix comes from", ("analytic", "survey", "touchstone"))
    scale_db: float = _f(0.0, "dB", "overall scaling of the off-diagonal terms (sweeps); -inf = no coupling")
    analytic: CouplingAnalyticCfg = field(default_factory=CouplingAnalyticCfg)
    survey: CouplingSurveyCfg = field(default_factory=CouplingSurveyCfg)
    touchstone: CouplingTouchstoneCfg = field(default_factory=CouplingTouchstoneCfg)


@dataclass
class BeamCfg:
    steering: str = _f("phase", "", "phase shifters (aligned at f0, squints) or true time delay", ("phase", "ttd"))
    scan_deg: list = _f([0.0, 30.0, 60.0], "deg", "scan angles (theta from broadside) to evaluate, in the plane below")
    plane_phi_deg: float = _f(0.0, "deg", "azimuth of the scan / observation plane from the row direction x: 0 = the x-z plane (a linear array's plane), 90 = the y-z plane")
    sidelobe: "float | str" = _f("auto", "deg", "sidelobe direction for the second metric set: auto = highest sidelobe of the array factor at f0, or an angle")


@dataclass
class GMPCfg:
    """Defaults from the milestone-1 sweep (cairn/LOG.md 2026-10-13): the
    element chain is nearly memoryless (DPA + DTC, no measured memory model),
    so memory taps only fit noise and cost ACLR2 (order 9: -48.3 dBc at one
    tap, -44.8 at five); a memoryless 7th order is the best of the 24
    settings tried on ACLR1, ACLR2 and EVM alike, with 7 coefficients."""
    order: int = _f(7, "", "GMP aligned nonlinearity order")
    memory_depth: int = _f(1, "taps", "GMP aligned memory depth (1 = memoryless)")
    lag_order: int = _f(0, "", "GMP lagging cross-term order (0 disables)")
    lag_memory: int = _f(0, "taps", "GMP lagging memory")
    lag_span: int = _f(0, "taps", "GMP lagging span")
    lead_order: int = _f(0, "", "GMP leading cross-term order (0 disables)")
    lead_memory: int = _f(0, "taps", "GMP leading memory")
    lead_span: int = _f(0, "taps", "GMP leading span")


@dataclass
class DPDCfg:
    scheme: str = _f("none", "", "none | one ILA-GMP per element (trained at its conducted port) | one ILA-GMP for the array (trained on the OTA observation at the beam)", ("none", "per_element", "array"))
    n_iterations: int = _f(2, "", "ILA iterations")
    regularization: float = _f(1e-9, "", "relative ridge in the GMP least squares")
    gmp: GMPCfg = field(default_factory=GMPCfg)
    per_element_observe: str = _f("pa_output", "", "what the per-element DPD observes: its own PA forward output, or the antenna port including coupled leakage", ("pa_output", "antenna_port"))
    train_angles_deg: list = _f([], "deg", "scan angles the DPD is trained on JOINTLY (one fit over all of them, then used at whatever angle the beam points); empty = train at the beam only")


@dataclass
class MetricsCfg:
    aclr_offsets: list = _f([1, 2], "channels", "ACLR adjacent-channel offsets to report")
    evm_equalize: str = _f("scalar", "", "EVM equalisation convention (polar_tx evm_equalize_default)", ("scalar", "per_tone"))


@dataclass
class SimCfg:
    n_symbols: int = _f(8, "symbols", "OFDM symbols per burst")
    smoke_n_symbols: int = _f(2, "symbols", "burst length when ARRAYTX_SMOKE=1 (CI)")
    noise: bool = _f(True, "", "random impairments on (polar_tx run(noise=))")
    cfr_papr_db: float | None = _f(8.5, "dB", "CFR target PAPR applied to the common signal before steering/DPD; null = off")
    oversampling: int = _f(0, "x", "baseband oversampling of the waveform and every chain on it (fs = FFT x SCS x this); 0 = the standard's sourced value (4). A study knob: ACLR1 needs fs >= 3 BW, ACLR2 fs >= 4.9 BW (ex22 runs 4 / 8 / 16)")


@dataclass
class ArrayConfig:
    arraytx_config: int = _f(CONFIG_VERSION, "", "config schema version")
    seed: int = _f(1, "", "the one seed every random stream derives from")
    standard: str = _f("fr2_nr400", "", "radio standard", tuple(sorted(STANDARDS)))
    array: ArrayGeometryCfg = field(default_factory=ArrayGeometryCfg)
    element: ElementCfg = field(default_factory=ElementCfg)
    coupling: CouplingCfg = field(default_factory=CouplingCfg)
    beam: BeamCfg = field(default_factory=BeamCfg)
    dpd: DPDCfg = field(default_factory=DPDCfg)
    metrics: MetricsCfg = field(default_factory=MetricsCfg)
    sim: SimCfg = field(default_factory=SimCfg)
    provenance: dict = field(default_factory=dict, metadata={"internal": True})
    source_path: str | None = field(default=None, metadata={"internal": True})

    def validate(self) -> None:
        if self.arraytx_config != CONFIG_VERSION:
            raise ValueError(f"arraytx_config must be {CONFIG_VERSION}")
        for ff in form_fields():
            if ff.choices is not None:
                v = _get(self, ff.path)
                if v not in ff.choices:
                    raise ValueError(f"{ff.path}={v!r} not in {ff.choices}")
        if self.array.n_elements < 1 or self.array.n_rows < 1:
            raise ValueError("array.n_elements and array.n_rows must be >= 1")
        if self.coupling.source == "touchstone" and not self.coupling.touchstone.path:
            raise ValueError("coupling.source=touchstone needs coupling.touchstone.path")
        if self.dpd.n_iterations < 1:
            raise ValueError("dpd.n_iterations must be >= 1")
        if not 0.0 <= self.element.outphasing.source_impedance_rel < 1.0:
            raise ValueError("element.outphasing.source_impedance_rel must be in [0, 1)")
        if self.sim.oversampling < 0:
            raise ValueError("sim.oversampling must be 0 (the standard's) or a positive integer")
        if self.element.pa.backoff_db < 0.0:
            raise ValueError("element.pa.backoff_db must be >= 0 (a negative value would clip the undistorted peak)")
        bpe = self.element.pa.backoff_per_element_db
        if bpe:
            n_el = self.array.n_elements * self.array.n_rows
            if len(bpe) != n_el or not all(isinstance(b, (int, float)) and math.isfinite(b) and b >= 0.0 for b in bpe):
                raise ValueError(f"element.pa.backoff_per_element_db: empty, or {n_el} finite values >= 0 "
                                 f"(one per element, row-major), got {len(bpe)}")
        lp = self.element.pa.load_pull
        if lp.iterations < 1 or not 0.0 < lp.gamma_max <= 1.0 or not 0.0 <= lp.floor < 1.0:
            raise ValueError("element.pa.load_pull: iterations >= 1, 0 < gamma_max <= 1, 0 <= floor < 1")
        # the survey block: every number carries a WRITTEN provenance.  A value
        # read from a paper says survey + citation; one that is not in any
        # paper says assumed (or derived) + why.  A bare scalar, or survey
        # without a ref, does not load (AGENTS.md: no uncited number may
        # call itself survey, and nothing enters this block without a note).
        for p, s in self.provenance.items():
            if p.startswith("coupling.survey.") and isinstance(_get(self, p), (int, float)) \
                    and not isinstance(_get(self, p), bool):
                if not s.ref:
                    raise ValueError(f"{p}: every coupling.survey number needs a ref (source {s.source!r}); "
                                     "write {value, source, ref} -- survey with a citation, or assumed/derived with why")
        if self.beam.sidelobe != "auto":
            try:
                float(self.beam.sidelobe)
            except (TypeError, ValueError):
                raise ValueError(f"beam.sidelobe must be 'auto' or a number, got {self.beam.sidelobe!r}") from None
        for a in self.dpd.train_angles_deg:
            if isinstance(a, bool) or not isinstance(a, (int, float)) or not -90.0 < float(a) < 90.0:
                raise ValueError(f"dpd.train_angles_deg entries must be numbers in (-90, 90), got {a!r}")
        if not self.beam.scan_deg:
            raise ValueError("beam.scan_deg must list at least one angle")
        for a in self.beam.scan_deg:
            if not isinstance(a, (int, float)) or isinstance(a, bool) or not -90.0 < a < 90.0:
                raise ValueError(f"beam.scan_deg entries must be numbers in (-90, 90), got {a!r}")

    def to_dict(self) -> dict:
        d = _asdict_public(self)
        return d


# --------------------------------------------------------------- utilities
@dataclass(frozen=True)
class FormField:
    path: str
    type: str
    default: Any
    unit: str
    help: str
    choices: tuple | None = None
    source: str | None = None     # provenance of the DEFAULT value, if declared
    ref: str | None = None


def form_fields(cls=ArrayConfig, prefix: str = "") -> list[FormField]:
    """Flat list of every leaf field with its declaration (GUI contract)."""
    out: list[FormField] = []
    for fd in fields(cls):
        if fd.metadata.get("internal"):
            continue
        path = f"{prefix}{fd.name}"
        if is_dataclass(fd.type) or (isinstance(fd.type, str) and fd.type.endswith("Cfg")):
            sub = fd.type if is_dataclass(fd.type) else globals()[fd.type]
            out.extend(form_fields(sub, path + "."))
            continue
        default = fd.default if fd.default is not dataclasses.MISSING else fd.default_factory()  # type: ignore[misc]
        out.append(FormField(path, str(fd.type), default, fd.metadata.get("unit", ""),
                             fd.metadata.get("help", ""), fd.metadata.get("choices"),
                             fd.metadata.get("source"), fd.metadata.get("ref")))
    return out


def _get(obj, path: str):
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


def _asdict_public(obj):
    if is_dataclass(obj):
        return {fd.name: _asdict_public(getattr(obj, fd.name)) for fd in fields(obj)
                if not fd.metadata.get("internal")}
    if isinstance(obj, (list, tuple)):
        return [_asdict_public(v) for v in obj]
    return obj


def _coerce(value, typ: str, path: str):
    if value is None:
        if "None" in typ:
            return None
        raise ValueError(f"{path}: null not allowed")
    if typ == "float | str":              # beam.sidelobe: 'auto' or an angle
        if isinstance(value, str):
            return value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{path}: expected 'auto' or a number, got {value!r}")
        return float(value)
    if typ.startswith("bool"):
        if not isinstance(value, bool):
            raise ValueError(f"{path}: expected bool, got {value!r}")
        return value
    if typ.startswith("int"):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
            raise ValueError(f"{path}: expected int, got {value!r}")
        return int(value)
    if typ.startswith("float"):
        if isinstance(value, str) and value.lower() in ("-inf", "inf", "-.inf", ".inf"):
            return -math.inf if value.startswith("-") else math.inf
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{path}: expected number, got {value!r}")
        return float(value)
    if typ.startswith("str"):
        if not isinstance(value, str):
            raise ValueError(f"{path}: expected string, got {value!r}")
        return value
    if typ.startswith("list"):
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"{path}: expected list, got {value!r}")
        return list(value)
    return value


def _build(cls, data: dict, prefix: str, prov: dict):
    if not isinstance(data, dict):
        raise ValueError(f"{prefix or 'root'}: expected a mapping")
    known = {fd.name: fd for fd in fields(cls) if not fd.metadata.get("internal")}
    unknown = set(data) - set(known)
    if unknown:
        raise ValueError(f"{prefix or 'root'}: unknown key(s) {sorted(unknown)}; known: {sorted(known)}")
    kw = {}
    for name, fd in known.items():
        path = f"{prefix}{name}"
        sub = fd.type if is_dataclass(fd.type) else (globals().get(fd.type) if isinstance(fd.type, str) else None)
        if is_dataclass(sub):
            kw[name] = _build(sub, data.get(name, {}), path + ".", prov)
            continue
        if name not in data:
            continue   # dataclass default
        raw = data[name]
        if isinstance(raw, dict) and "value" in raw:
            extra = set(raw) - {"value", "source", "ref"}
            if extra:
                raise ValueError(f"{path}: unknown provenance key(s) {sorted(extra)}")
            src = raw.get("source", "assumed")
            ref = raw.get("ref", "")
            if isinstance(ref, (list, tuple)):
                ref = "; ".join(str(r) for r in ref)
            val = _coerce(raw["value"], str(fd.type), path)
            try:
                prov[path] = Sourced(val, src, ref)
            except ValueError as e:
                raise ValueError(f"{path}: {e}") from None
        else:
            val = _coerce(raw, str(fd.type), path)
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                prov[path] = Sourced(val, "assumed")
        kw[name] = val
    return cls(**kw)


def config_from_dict(data: dict, source_path: str | None = None) -> ArrayConfig:
    prov: dict[str, Sourced] = {}
    cfg = _build(ArrayConfig, data, "", prov)
    # default (not-in-file) numeric leaves are assumed too
    for ff in form_fields():
        if ff.path not in prov and isinstance(_get(cfg, ff.path), (int, float)) \
                and not isinstance(_get(cfg, ff.path), bool):
            prov[ff.path] = Sourced(_get(cfg, ff.path), ff.source or "assumed", ff.ref or "")
    cfg.provenance = prov
    cfg.source_path = source_path
    cfg.validate()
    return cfg


def load_config(path: str | Path) -> ArrayConfig:
    path = Path(path)
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    cfg = config_from_dict(data, str(path))
    # file paths are relative to the config file; "bundled:<name>" is a
    # clock profile shipped with the package (arraytx.lo)
    ts = cfg.coupling.touchstone.path
    if ts and not Path(ts).is_absolute():
        cfg.coupling.touchstone.path = str((path.parent / ts).resolve())
    cp = cfg.element.lo.clock_profile
    if cp and not cp.startswith("bundled:") and not Path(cp).is_absolute():
        cfg.element.lo.clock_profile = str((path.parent / cp).resolve())
    return cfg


def default_config() -> ArrayConfig:
    return config_from_dict({})
