"""The one configuration (iron rule 1): topology, carrier, K, base PHY, LO, front end,
channel, receiver and array all in one frozen ``Mmw60Config``.  Examples, tools
and the GUI form (``guispec.py``) only read it.

Numbers that come from the literature are not typed here: the Liu 2025
preset is built from ``data/spec/survey.yaml`` through :mod:`mmw60.spec`,
so ``grep "source:"`` still lists every one of them.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path

import yaml

from . import spec
from .upclock import UpclockedPhy
from .vendor.wifitrx.waveform.ofdm import OFDMConfig
from .vendor.wifitrx.waveform.tone_plan import contiguous

TOPOLOGIES = ("if_extender", "upclock_zero_if")
CFO_MODES = ("off", "ltf", "stf_ltf", "extended")
PN_SIDES = ("off", "tx", "rx", "both")
CHANNELS = ("flat", "tdl_exp", "tap_table")


@dataclass(frozen=True)
class PhyConfig:
    """The base (K = 1) PHY the clock multiplies."""
    standard: str = "11ac"            # 11ac (312.5 kHz legacy numerology) | 11be (78.125 kHz)
    bandwidth_hz: float = 20e6
    mcs: int = 0
    packet_bytes: int = 4096
    gi: str = "long"                  # long = 0.8 µs at K = 1 (cp 1/4); short = 0.4 µs (1/8)
    oversampling: int = 2
    window_fraction: float = 1 / 16
    stf_periods: int = 10
    scrambler_seed: int = 93
    pilot_seed: int = 42

    @property
    def subcarrier_spacing_hz(self) -> float:
        return {"11ac": 312.5e3, "11be": 78.125e3}[self.standard]

    @property
    def cp_fraction(self) -> float:
        if self.standard == "11ac":
            return {"long": 1 / 4, "short": 1 / 8}[self.gi]
        return {"long": 1 / 16, "short": 1 / 32}[self.gi]


@dataclass(frozen=True)
class PhaseNoiseConfig:
    model: str = "pole_zero"          # pole_zero | off
    psd0_dbchz: float = -93.0
    f_pole_hz: float = 1.0e6
    f_zero_hz: float = 100.0e6
    apply: str = "both"               # off | tx | rx | both (data/spec: assumed.pn_apply_sides)

    @property
    def enabled(self) -> bool:
        return self.model != "off" and self.apply != "off"


@dataclass(frozen=True)
class LoConfig:
    scheme: str = "zero_if"           # zero_if (topology B) | fixed_lo_x3 | fixed_lo_x4 (topology A, M1)
    phase_noise: PhaseNoiseConfig = field(default_factory=PhaseNoiseConfig)


@dataclass(frozen=True)
class PaConfig:
    model: str = "rapp_11ad"          # rapp_11ad | ideal
    obo_db: float = 8.0
    #: what the back-off is counted from: "psat" (saturated output power, the
    #: literal OBO) or "p1db" (the 1 dB compression point; this Rapp's P1dB is
    #: 9.5 dB below Psat, so the two readings of "OBO 8 dB" differ by that)
    obo_reference: str = "psat"
    ampm: bool = True

    @property
    def enabled(self) -> bool:
        return self.model != "ideal"


@dataclass(frozen=True)
class ArrayConfig:
    """Placeholder until milestone 2 (array_tx vendored then)."""
    n_elements: int = 1


@dataclass(frozen=True)
class FrontendConfig:
    pa: PaConfig = field(default_factory=PaConfig)
    eirp_limit_dbm: float | None = None
    array: ArrayConfig = field(default_factory=ArrayConfig)


@dataclass(frozen=True)
class ChannelConfig:
    model: str = "tdl_exp"            # flat | tdl_exp | tap_table
    rms_delay_ns: float = 7.0         # data/spec: assumed.cr_rms_delay_ns
    los_k_db: float | None = 10.0     # LOS / diffuse power; data/spec: assumed.cr_los_k_db
    taps: dict | None = None


@dataclass(frozen=True)
class RxConfig:
    cfo_estimation: str = "stf_ltf"   # off | ltf | stf_ltf | extended
    extended_max_subcarriers: int = 8
    ce_smooth_tones: int = 3          # data/spec: assumed.ce_smooth_tones
    timing: str = "genie"
    cpe_tracking: bool = True
    #: diagnostic only: equalise with the true channel (flat channel: ones)
    #: instead of the L-LTF estimate, to separate decoder loss from CSI loss
    genie_csi: bool = False


@dataclass(frozen=True)
class Mmw60Config:
    topology: str = "upclock_zero_if"
    carrier_hz: float = 60.0e9
    upclock_k: int = 1
    xo_ppm_tx: float = 0.0
    xo_ppm_rx: float = 0.0
    phy: PhyConfig = field(default_factory=PhyConfig)
    lo: LoConfig = field(default_factory=LoConfig)
    frontend: FrontendConfig = field(default_factory=FrontendConfig)
    channel: ChannelConfig = field(default_factory=ChannelConfig)
    rx: RxConfig = field(default_factory=RxConfig)
    seed: int = 0
    label: str = ""

    def __post_init__(self):
        if self.topology not in TOPOLOGIES:
            raise ValueError(f"topology must be one of {TOPOLOGIES}, got {self.topology!r}")
        if self.rx.cfo_estimation not in CFO_MODES:
            raise ValueError(f"rx.cfo_estimation must be one of {CFO_MODES}")
        if self.lo.phase_noise.apply not in PN_SIDES:
            raise ValueError(f"lo.phase_noise.apply must be one of {PN_SIDES}")
        if self.channel.model not in CHANNELS:
            raise ValueError(f"channel.model must be one of {CHANNELS}")
        if int(self.upclock_k) < 1:
            raise ValueError("upclock_k must be >= 1")
        if self.frontend.pa.obo_reference not in ("psat", "p1db"):
            raise ValueError("frontend.pa.obo_reference must be psat | p1db")

    # --- derived ---------------------------------------------------------
    @property
    def cfo_hz(self) -> float:
        """(ppm_tx + ppm_rx) × f_c; exactly 0.0 when both are zero (iron rule 3)."""
        ppm = float(self.xo_ppm_tx) + float(self.xo_ppm_rx)
        return 0.0 if ppm == 0.0 else ppm * 1e-6 * float(self.carrier_hz)

    def base_ofdm(self, n_symbols: int = 1) -> OFDMConfig:
        """The wifitrx config of the base numerology.  VHT 20 MHz has 56
        active tones (52 data + 4 pilots), which wifitrx's legacy table
        (52, the 11a plan) does not know: an explicit contiguous plan of
        56 keeps the standard pilot tones ±7 / ±21 by index."""
        p = self.phy
        kw = dict(bandwidth_hz=p.bandwidth_hz, subcarrier_spacing_hz=p.subcarrier_spacing_hz,
                  cp_fraction=p.cp_fraction, window_fraction=p.window_fraction,
                  oversampling=p.oversampling, n_symbols=int(n_symbols), seed=self.seed,
                  qam_order=4)
        if p.standard == "11ac" and p.bandwidth_hz == 20e6:
            kw["tone_plan"] = contiguous(56)
        return OFDMConfig(**kw)

    def upclocked(self, n_symbols: int = 1) -> UpclockedPhy:
        return UpclockedPhy(self.base_ofdm(n_symbols), int(self.upclock_k))

    @property
    def impairments_on(self) -> dict:
        return {"cfo": self.cfo_hz != 0.0, "phase_noise": self.lo.phase_noise.enabled,
                "pa": self.frontend.pa.enabled}

    def ideal(self) -> "Mmw60Config":
        """The same link with CFO, phase noise and PA off (the paper's
        "without non-idealities"); channel and receiver unchanged."""
        return dataclasses.replace(
            self, xo_ppm_tx=0.0, xo_ppm_rx=0.0,
            lo=dataclasses.replace(self.lo, phase_noise=dataclasses.replace(
                self.lo.phase_noise, apply="off")),
            frontend=dataclasses.replace(self.frontend, pa=dataclasses.replace(
                self.frontend.pa, model="ideal")),
            label=(self.label + " ideal").strip())

    def with_(self, **top) -> "Mmw60Config":
        return dataclasses.replace(self, **top)

    # --- (de)serialisation -------------------------------------------------
    def to_dict(self) -> dict:
        return _asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Mmw60Config":
        return _from_dict(cls, d)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Mmw60Config":
        return cls.from_dict(yaml.safe_load(Path(path).read_text(encoding="utf-8")))

    def to_yaml(self, path: str | Path) -> None:
        Path(path).write_text(yaml.safe_dump(self.to_dict(), sort_keys=False,
                                             allow_unicode=True), encoding="utf-8")


def _asdict(obj):
    if is_dataclass(obj):
        return {f.name: _asdict(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, dict):
        return {k: _asdict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_asdict(v) for v in obj]
    return obj


def _from_dict(cls, d: dict):
    kw = {}
    for f in fields(cls):
        if f.name not in d:
            continue
        v = d[f.name]
        t = f.type if not isinstance(f.type, str) else None
        sub = _nested_type(cls, f.name)
        kw[f.name] = _from_dict(sub, v) if sub is not None and isinstance(v, dict) else v
        del t
    unknown = set(d) - {f.name for f in fields(cls)}
    if unknown:
        raise ValueError(f"{cls.__name__}: unknown field(s) {sorted(unknown)}")
    return cls(**kw)


_NESTED = {
    (Mmw60Config, "phy"): PhyConfig, (Mmw60Config, "lo"): LoConfig,
    (Mmw60Config, "frontend"): FrontendConfig, (Mmw60Config, "channel"): ChannelConfig,
    (Mmw60Config, "rx"): RxConfig, (LoConfig, "phase_noise"): PhaseNoiseConfig,
    (FrontendConfig, "pa"): PaConfig, (FrontendConfig, "array"): ArrayConfig,
}


def _nested_type(cls, name):
    return _NESTED.get((cls, name))


# ---------------------------------------------------------------- presets
def liu2025_table2(k: int = 8, mcs: int = 0, **top) -> Mmw60Config:
    """Liu 2025 Table II / Sec. V-A, every number through the spec table."""
    s = spec.value
    pn = PhaseNoiseConfig(model="pole_zero", psd0_dbchz=float(s("liu2025.pn_psd0_dbchz")),
                          f_pole_hz=float(s("liu2025.pn_f_pole_hz")),
                          f_zero_hz=float(s("liu2025.pn_f_zero_hz")),
                          apply=str(s("assumed.pn_apply_sides")))
    cfg = Mmw60Config(
        topology="upclock_zero_if",
        carrier_hz=float(s("liu2025.carrier_hz")),
        upclock_k=int(k),
        xo_ppm_tx=float(s("liu2025.xo_ppm_tx")),
        xo_ppm_rx=float(s("liu2025.xo_ppm_rx")),
        phy=PhyConfig(standard="11ac", bandwidth_hz=float(s("assumed.base_bandwidth_hz")),
                      mcs=int(mcs), packet_bytes=int(s("liu2025.packet_bytes")),
                      scrambler_seed=int(s("assumed.scrambler_seed"))),
        lo=LoConfig(scheme="zero_if", phase_noise=pn),
        frontend=FrontendConfig(pa=PaConfig(model="rapp_11ad",
                                            obo_db=float(s("liu2025.pa_obo_db")),
                                            obo_reference=str(s("assumed.pa_obo_reference")))),
        channel=ChannelConfig(model="tdl_exp", rms_delay_ns=float(s("assumed.cr_rms_delay_ns")),
                              los_k_db=float(s("assumed.cr_los_k_db"))),
        rx=RxConfig(cfo_estimation="stf_ltf", ce_smooth_tones=int(s("assumed.ce_smooth_tones"))),
        label=f"Liu2025 K={k} MCS{mcs}",
    )
    return dataclasses.replace(cfg, **top) if top else cfg


def wifi7_baseline_k1(mcs: int = 0) -> Mmw60Config:
    """K = 1, no mmWave stage: the WiFi row of the comparison table."""
    return Mmw60Config(topology="upclock_zero_if", carrier_hz=6.0e9, upclock_k=1,
                       phy=PhyConfig(mcs=mcs),
                       lo=LoConfig(phase_noise=PhaseNoiseConfig(apply="off")),
                       frontend=FrontendConfig(pa=PaConfig(model="ideal")),
                       channel=ChannelConfig(model="flat"),
                       label=f"WiFi K=1 MCS{mcs}")
