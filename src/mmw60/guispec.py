"""Form-field declarations for a future desktop / Android front end (polar_tx ``guispec`` method).

No GUI exists in milestone 0; this is the contract it will draw from.  Every
``Knob`` names one ``Mmw60Config`` field by a dotted path, its kind, range
and bilingual label, and the default is **read from the dataclass**, never
typed here (``tests/test_laws.py::test_law1_form_defaults_reproduce_config``):
a form filled with the defaults must build the config bit for bit.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from .config import CFO_MODES, PN_SIDES, Mmw60Config

GROUPS = {
    "link": ("链路", "link"),
    "lo": ("本振", "LO"),
    "frontend": ("前端", "front end"),
    "channel": ("信道", "channel"),
    "rx": ("接收机", "receiver"),
}


@dataclass(frozen=True)
class Knob:
    id: str                 # dotted path into Mmw60Config
    kind: str               # int | float | bool | choice
    zh: str
    en: str
    unit: str = ""
    group: str = "link"
    lo: float | None = None
    hi: float | None = None
    step: float | None = None
    choices: tuple = ()
    help_zh: str = ""
    help_en: str = ""

    def default(self, cfg: Mmw60Config | None = None):
        return get_path(cfg or Mmw60Config(), self.id)

    def as_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["default"] = self.default()
        return d


KNOBS: tuple[Knob, ...] = (
    Knob("topology", "choice", "拓扑", "topology", choices=("if_extender", "upclock_zero_if")),
    Knob("carrier_hz", "float", "载频", "carrier", "Hz", lo=57e9, hi=75e9, step=1e6),
    Knob("upclock_k", "int", "时钟倍数 K", "upclock factor K", lo=1, hi=32, step=1),
    Knob("xo_ppm_tx", "float", "TX 晶振误差", "TX crystal error", "ppm", lo=0, hi=50, step=1),
    Knob("xo_ppm_rx", "float", "RX 晶振误差", "RX crystal error", "ppm", lo=0, hi=50, step=1),
    Knob("phy.mcs", "int", "MCS", "MCS", lo=0, hi=8, step=1),
    Knob("phy.packet_bytes", "int", "包长", "packet length", "B", lo=64, hi=65535, step=1),
    Knob("lo.phase_noise.psd0_dbchz", "float", "相噪 PSD0", "phase-noise PSD0", "dBc/Hz",
         group="lo", lo=-120, hi=-70, step=1),
    Knob("lo.phase_noise.f_pole_hz", "float", "相噪极点", "pole frequency", "Hz", group="lo",
         lo=1e4, hi=1e8, step=1e4),
    Knob("lo.phase_noise.f_zero_hz", "float", "相噪零点", "zero frequency", "Hz", group="lo",
         lo=1e6, hi=1e10, step=1e6),
    Knob("lo.phase_noise.apply", "choice", "相噪加在", "phase noise at", group="lo",
         choices=PN_SIDES),
    Knob("frontend.pa.model", "choice", "PA 模型", "PA model", group="frontend",
         choices=("rapp_11ad", "ideal")),
    Knob("frontend.pa.obo_db", "float", "PA 回退", "PA back-off", "dB", group="frontend",
         lo=0, hi=20, step=0.5),
    Knob("frontend.pa.obo_reference", "choice", "回退参考", "back-off reference",
         group="frontend", choices=("psat", "p1db")),
    Knob("channel.model", "choice", "信道", "channel", group="channel",
         choices=("flat", "tdl_exp")),
    Knob("channel.rms_delay_ns", "float", "rms 时延", "rms delay spread", "ns",
         group="channel", lo=0, hi=100, step=1),
    Knob("rx.cfo_estimation", "choice", "CFO 估计", "CFO estimation", group="rx",
         choices=CFO_MODES),
    Knob("rx.ce_smooth_tones", "int", "信道估计平滑", "channel-estimate smoothing", "tones",
         group="rx", lo=1, hi=17, step=2),
)


def get_path(cfg, path: str):
    obj = cfg
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


def set_path(cfg, path: str, value):
    """A new config with the dotted field replaced (nested frozen dataclasses)."""
    parts = path.split(".")
    if len(parts) == 1:
        return dataclasses.replace(cfg, **{parts[0]: value})
    child = getattr(cfg, parts[0])
    return dataclasses.replace(cfg, **{parts[0]: set_path(child, ".".join(parts[1:]), value)})


def config_from_form(values: dict, base: Mmw60Config | None = None) -> Mmw60Config:
    cfg = base or Mmw60Config()
    known = {k.id for k in KNOBS}
    for k, v in values.items():
        if k not in known:
            raise KeyError(f"unknown form field {k!r}")
        cfg = set_path(cfg, k, v)
    return cfg


def form_fields() -> list[dict]:
    return [k.as_dict() for k in KNOBS]
