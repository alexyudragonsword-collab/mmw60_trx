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
#: be = the sub-7 GHz WiFi waveform as it is (K = 1); be_upclocked = the same
#: waveform with the clock × K (topology B / Liu 2025); ay_ofdm / ay_sc =
#: 802.11ay's own numerologies on the zero-IF hardware (milestone 3 — named
#: now, refused until then, like topology A before milestone 1)
WAVEFORMS = ("be", "be_upclocked", "ay_ofdm", "ay_sc")
WAVEFORMS_BUILT = ("be", "be_upclocked")
CFO_MODES = ("off", "ltf", "stf_ltf", "extended")
PN_SIDES = ("off", "tx", "rx", "both")
#: pole_zero = the 11ad-EM one-pole / one-zero shape (Liu 2025's numbers);
#: wifitrx_wifi7 = the vendored WiFi 7 synthesizer profile (the sub-7 GHz chip's
#: own LO, for the K = 1 row); profile = a pllsim clock-profile YAML
#: (``profile_path``) moved to the carrier by 20·log10(f_c / f0) — the ×N
#: placeholder until pll_simulator's multiplier model (ROADMAP D2)
PN_MODELS = ("pole_zero", "wifitrx_wifi7", "profile", "off")
CHANNELS = ("flat", "tdl_exp", "tap_table")
#: if_extender_chain = topology A: the chip's chains at K = 1 with the 60 GHz
#: stage after / before them (``mmw60.ifext``)
FRONTEND_MODELS = ("behavioural", "zero_if_chain", "if_extender_chain")
#: LO scheme -> the multiplication from the PLL to the LO (zero_if: the LO is the carrier)
LO_SCHEMES = {"zero_if": 1, "fixed_lo_x3": 3, "fixed_lo_x4": 4}
#: topology A's chip: wifitrx = wifitrx's own transceiver, randomised and run
#: through its calibration sequence (the WiFi 7 chip as delivered); frontend =
#: the shared ``Frontend60``'s chain at 1× with its PA bypassed (the K = 1 row
#: of the comparison table, uncalibrated — and what ``ideal()`` selects)
IFEXT_CHIPS = ("wifitrx", "frontend")
DPD_OBSERVATIONS = ("chip", "mmw")


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
    #: OFDM symbols per packet when the base is not the coded VHT 20 MHz
    #: (EVM-only runs on wifitrx's random-QAM payload)
    evm_symbols: int = 16
    evm_qam_order: int = 16

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
    model: str = "pole_zero"          # one of PN_MODELS
    psd0_dbchz: float = -93.0
    f_pole_hz: float = 1.0e6
    f_zero_hz: float = 100.0e6
    apply: str = "both"               # off | tx | rx | both (data/spec: assumed.pn_apply_sides)
    #: model = profile: a pllsim clock-profile YAML (f0_hz, f_hz, l_dbc_hz);
    #: relative paths resolve against ``mmw60/data/clock_profiles``
    profile_path: str | None = None

    @property
    def enabled(self) -> bool:
        return self.model != "off" and self.apply != "off"


@dataclass(frozen=True)
class LoConfig:
    scheme: str = "zero_if"           # zero_if (topology B) | fixed_lo_x3 | fixed_lo_x4 (topology A)
    phase_noise: PhaseNoiseConfig = field(default_factory=PhaseNoiseConfig)
    #: topology A: the intermediate frequency the chip's channel sits at; the
    #: fixed LO is f_c − if_hz, from a PLL at (f_c − if_hz) / N (data/spec: assumed.ifext_if_hz)
    if_hz: float = 0.0

    @property
    def n_mult(self) -> int:
        return LO_SCHEMES[self.scheme]


@dataclass(frozen=True)
class IfExtConfig:
    """Topology A's 60 GHz stage around the chip (data/spec: assumed.ifext_*, assumed.mlo_*).
    Ignored by topology B."""
    chip: str = "wifitrx"             # one of IFEXT_CHIPS
    chip_seed: int = 5                # which chip (wifitrx's randomised impairments)
    #: the chip PA's average output at the link's digital drive, set by the
    #: calibration's tx_power step; None = the chip's delivered gain code
    chip_pout_dbm: float | None = None
    with_dpd: bool = True
    #: where the DPD observes: the chip's own coupler (it linearises the chip PA
    #: only) or a 60 GHz coupler after the second PA, down-converted with the same LO
    dpd_observation: str = "chip"
    #: with the 60 GHz observation: how many indirect-learning passes wifitrx's DPD step may try;
    #: it keeps the best one its observation path reads (data/spec: assumed.ifext_dpd_max_iterations)
    dpd_max_iterations: int = 2
    filter_enabled: bool = True
    filter_bw_hz: float = 1.2e9
    filter_order: int = 5
    filter_ripple_db: float = 0.5
    filter_center_hz: float = 6.525e9
    image_rejection_db: float | None = 30.0
    #: CFO pre-compensation from the multi-link sub-7 GHz estimate × f_c / f_sub7
    mlo_enabled: bool = True
    mlo_sub7_hz: float = 5.5e9
    mlo_sub7_snr_db: float = 20.0


@dataclass(frozen=True)
class PaConfig:
    model: str = "rapp_11ad"          # rapp_11ad | ideal
    obo_db: float = 8.0
    #: what the back-off is counted from: "psat" (saturated output power, the
    #: literal OBO) or "p1db" (the 1 dB compression point; this Rapp's P1dB is
    #: 9.5 dB below Psat, so the two readings of "OBO 8 dB" differ by that)
    obo_reference: str = "psat"
    ampm: bool = True
    #: the Rapp smoothness p; None = the 11ad evaluation methodology's
    #: (tgad_em.pa_rapp_p = 0.81, which puts P1dB 9.5 dB below Psat).  A larger
    #: p compresses more abruptly; config.surveyed_pa sets it from a measured
    #: Psat − P1dB (data/spec: derived.pa60_rapp_p_asada_eumc2011).  The AM/PM
    #: stays the 11ad one either way.
    rapp_p: float | None = None

    @property
    def enabled(self) -> bool:
        return self.model != "ideal"


@dataclass(frozen=True)
class ArrayConfig:
    """Placeholder until milestone 2 (array_tx vendored then)."""
    n_elements: int = 1


@dataclass(frozen=True)
class ConverterConfig:
    """ENOB vs sample rate (data/spec: assumed.converter_*)."""
    enob_ref: float = 10.0
    fs_ref_hz: float = 1.0e9
    bits_per_octave: float = 0.5
    backoff_db: float = 12.0
    enabled: bool = False             # True: wifitrx DAC/ADC quantise at ENOB(fs_eff)


@dataclass(frozen=True)
class IqConfig:
    """Quadrature mismatch in wifitrx's units (data/spec: assumed.iq_mismatch)."""
    gain_db: float = 0.25
    phase_deg: float = 1.5
    gd_mismatch_ps: float = 150.0
    rail_ripple_db: float = 0.3
    rail_gd_ripple_ns: float = 0.12
    enabled: bool = False


RX_FRONT_MODELS = ("wifi7_ladder", "anchored")


@dataclass(frozen=True)
class RxFrontConfig:
    """The 60 GHz receive front end (LNA + mixer) in front of the baseband.

    ``wifi7_ladder`` (the default, and what every number up to ROADMAP D4 was
    produced with) is wifitrx's own eight-state gain ladder: a sub-7 GHz
    WiFi 7 chip's table, top state 37 dB / NF 3.5 dB / IIP3 −20 dBm.
    ``anchored`` keeps that ladder's shape and moves it so its top
    (maximum-gain) state reads ``nf_db`` / ``iip3_dbm`` / ``gain_db``: every
    state's NF, IIP3 and gain move by the same number of dB, the gain steps
    stay, and the hand-over levels follow wifitrx's own balance-point rule
    (data/spec: assumed.rx60_ladder_shape).  A field left None keeps
    wifitrx's value.

    The receiver has two input compression points and they are not the same
    number.  The in-band one comes from ``iip3_dbm`` (it is what a wanted
    signal, or a full-duplex link's leakage at the same carrier, meets).
    ``p1db_oob_dbm`` is the other: the stages before the baseband high-pass,
    measured with a tone below its corner — what an FMCW radar's transmit
    leakage meets, because its beat frequency falls there.  The chain does
    not consume it; None = not specified (no communication paper read so far
    gives it)."""
    model: str = "wifi7_ladder"
    nf_db: float | None = None
    iip3_dbm: float | None = None
    gain_db: float | None = None
    p1db_oob_dbm: float | None = None


@dataclass(frozen=True)
class FrontendConfig:
    #: behavioural = milestone-0 chain (PA → PN → channel → CFO → PN → AWGN);
    #: zero_if_chain = wifitrx TxChain / RxChain at fs_eff built from Frontend60
    model: str = "behavioural"
    pa: PaConfig = field(default_factory=PaConfig)
    pa_gain_db: float = 20.0           # data/spec: assumed.pa60_gain_db
    psat_dbm: float = 15.0             # data/spec: assumed.pa60_psat_dbm
    converters: ConverterConfig = field(default_factory=ConverterConfig)
    iq: IqConfig = field(default_factory=IqConfig)
    lo_leak_dbc: float | None = None   # data/spec: assumed.lo_leak_dbc
    rx_dc_dbc: float | None = None     # data/spec: assumed.rx_dc_dbc
    pa_pae_max: float = 0.20           # data/spec: assumed.pa60_pae_max (the power column only)
    #: transmit antenna gain; 0 is "not specified", not a statement about a part
    antenna_gain_dbi: float = 0.0
    #: receive antenna gain; None = the same antenna as the transmitter (a TDD link).
    #: A radar transmits and receives at once, on two antennas: it reads both.
    antenna_gain_rx_dbi: float | None = None
    #: TX-to-RX isolation in the same package (dB, positive); None = not specified.
    #: Nothing in a TDD link consumes it; the leakage budget and a radar do.
    tx_rx_isolation_db: float | None = None
    rx_front: RxFrontConfig = field(default_factory=RxFrontConfig)
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
    #: symbols the pilot common-phase estimate is combined over (rx/tracking.py):
    #: 1 = wifitrx's per-symbol estimator (the milestone-0 receiver); > 1 = the
    #: MMSE combination of each symbol's pilots with a window of neighbours
    #: (data/spec: assumed.cpe_window_symbols)
    cpe_window_symbols: int = 1
    #: choose the channel-estimate smoothing span per packet from the estimate's
    #: own tone autocorrelation, up to ``ce_smooth_max_tones`` (rx/tracking.py);
    #: False = the fixed ``ce_smooth_tones``
    ce_smooth_auto: bool = False
    ce_smooth_max_tones: int = 9      # data/spec: assumed.ce_smooth_max_tones
    #: diagnostic only: equalise with the true channel (flat channel: ones)
    #: instead of the L-LTF estimate, to separate decoder loss from CSI loss
    genie_csi: bool = False
    #: the 11be LDPC decoder (normalised min-sum; data/spec: assumed.ldpc_*)
    ldpc_max_iterations: int = 30
    ldpc_minsum_scale: float = 0.8
    #: digital DC removal before the CFO estimators (zero-IF chain model): the
    #: receiver measures its DC on a signal-free lead-in of the burst — what
    #: wifitrx's rx_dc_offset calibration measures with the input quiet — and
    #: subtracts it.  Off by default so the milestone-0 fingerprint stands;
    #: the zero-IF presets switch it on: without it the −25 dBc RX DC biases
    #: the L-STF autocorrelation by a subcarrier at SNR ≤ 10 dB
    #: (cairn/engineering-pitfalls.md).
    dc_removal: bool = False


@dataclass(frozen=True)
class Mmw60Config:
    topology: str = "upclock_zero_if"
    waveform: str = "be_upclocked"
    carrier_hz: float = 60.0e9
    upclock_k: int = 1
    xo_ppm_tx: float = 0.0
    xo_ppm_rx: float = 0.0
    phy: PhyConfig = field(default_factory=PhyConfig)
    lo: LoConfig = field(default_factory=LoConfig)
    frontend: FrontendConfig = field(default_factory=FrontendConfig)
    channel: ChannelConfig = field(default_factory=ChannelConfig)
    rx: RxConfig = field(default_factory=RxConfig)
    ifext: IfExtConfig = field(default_factory=IfExtConfig)
    seed: int = 0
    label: str = ""

    def __post_init__(self):
        if self.topology not in TOPOLOGIES:
            raise ValueError(f"topology must be one of {TOPOLOGIES}, got {self.topology!r}")
        if self.waveform not in WAVEFORMS:
            raise ValueError(f"waveform must be one of {WAVEFORMS}, got {self.waveform!r}")
        if self.rx.cfo_estimation not in CFO_MODES:
            raise ValueError(f"rx.cfo_estimation must be one of {CFO_MODES}")
        if self.lo.phase_noise.apply not in PN_SIDES:
            raise ValueError(f"lo.phase_noise.apply must be one of {PN_SIDES}")
        if self.lo.phase_noise.model not in PN_MODELS:
            raise ValueError(f"lo.phase_noise.model must be one of {PN_MODELS}")
        if self.lo.phase_noise.model == "profile" and not self.lo.phase_noise.profile_path:
            raise ValueError("lo.phase_noise.model = profile needs profile_path")
        if self.channel.model not in CHANNELS:
            raise ValueError(f"channel.model must be one of {CHANNELS}")
        if int(self.upclock_k) < 1:
            raise ValueError("upclock_k must be >= 1")
        if self.frontend.pa.rapp_p is not None and not float(self.frontend.pa.rapp_p) > 0:
            raise ValueError("frontend.pa.rapp_p must be > 0")
        if self.frontend.pa.obo_reference not in ("psat", "p1db"):
            raise ValueError("frontend.pa.obo_reference must be psat | p1db")
        if self.frontend.model not in FRONTEND_MODELS:
            raise ValueError(f"frontend.model must be one of {FRONTEND_MODELS}")
        if self.lo.scheme not in LO_SCHEMES:
            raise ValueError(f"lo.scheme must be one of {tuple(LO_SCHEMES)}")
        if self.ifext.chip not in IFEXT_CHIPS:
            raise ValueError(f"ifext.chip must be one of {IFEXT_CHIPS}")
        if self.ifext.dpd_observation not in DPD_OBSERVATIONS:
            raise ValueError(f"ifext.dpd_observation must be one of {DPD_OBSERVATIONS}")
        if int(self.ifext.dpd_max_iterations) < 1:
            raise ValueError("ifext.dpd_max_iterations must be >= 1")
        rxf = self.frontend.rx_front
        if rxf.model not in RX_FRONT_MODELS:
            raise ValueError(f"frontend.rx_front.model must be one of {RX_FRONT_MODELS}")
        if rxf.model == "wifi7_ladder" and (rxf.nf_db, rxf.iip3_dbm, rxf.gain_db, rxf.p1db_oob_dbm) != (None,) * 4:
            raise ValueError("frontend.rx_front: nf_db / iip3_dbm / gain_db / p1db_oob_dbm only apply to "
                             "model 'anchored'")
        if self.frontend.tx_rx_isolation_db is not None and float(self.frontend.tx_rx_isolation_db) < 0:
            raise ValueError("frontend.tx_rx_isolation_db is an isolation in dB (positive)")

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
                  qam_order=(4 if self.coded else p.evm_qam_order))
        if p.standard == "11ac" and p.bandwidth_hz == 20e6:
            kw["tone_plan"] = contiguous(56)
        return OFDMConfig(**kw)

    def upclocked(self, n_symbols: int = 1) -> UpclockedPhy:
        return UpclockedPhy(self.base_ofdm(n_symbols), int(self.upclock_k))

    @property
    def coded(self) -> bool:
        """Bases with a coded (PER-capable) data field: the VHT 20 MHz base
        (BCC, ``phy/ppdu.py``) and every 11be base (LDPC, ``phy/eht.py``);
        the 11ac 40 / 80 / 160 MHz bases run EVM-only on wifitrx's
        random-QAM payload (their wider BCC interleavers are not built)."""
        if self.phy.standard == "11be":
            return True
        return self.phy.standard == "11ac" and self.phy.bandwidth_hz == 20e6

    @property
    def impairments_on(self) -> dict:
        fe = self.frontend
        return {"cfo": self.cfo_hz != 0.0, "phase_noise": self.lo.phase_noise.enabled,
                "pa": fe.pa.enabled, "converters": fe.converters.enabled, "iq": fe.iq.enabled,
                "lo_leak": fe.lo_leak_dbc is not None, "rx_dc": fe.rx_dc_dbc is not None}

    def ideal(self) -> "Mmw60Config":
        """The same link with CFO, phase noise and PA off (the paper's
        "without non-idealities"); channel and receiver unchanged."""
        return dataclasses.replace(
            self, xo_ppm_tx=0.0, xo_ppm_rx=0.0,
            lo=dataclasses.replace(self.lo, phase_noise=dataclasses.replace(
                self.lo.phase_noise, apply="off")),
            frontend=dataclasses.replace(
                self.frontend, pa=dataclasses.replace(self.frontend.pa, model="ideal"),
                converters=dataclasses.replace(self.frontend.converters, enabled=False),
                iq=dataclasses.replace(self.frontend.iq, enabled=False),
                lo_leak_dbc=None, rx_dc_dbc=None),
            # topology A: the chip without its own impairments is the shared front end's
            # chain at 1× (the K = 1 row); the IF filter and the image band go with them
            ifext=dataclasses.replace(self.ifext, chip="frontend", filter_enabled=False,
                                      image_rejection_db=None),
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
    (Mmw60Config, "rx"): RxConfig, (Mmw60Config, "ifext"): IfExtConfig,
    (LoConfig, "phase_noise"): PhaseNoiseConfig,
    (FrontendConfig, "pa"): PaConfig, (FrontendConfig, "array"): ArrayConfig,
    (FrontendConfig, "converters"): ConverterConfig, (FrontendConfig, "iq"): IqConfig,
    (FrontendConfig, "rx_front"): RxFrontConfig,
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
        rx=RxConfig(cfo_estimation="stf_ltf", ce_smooth_tones=int(s("assumed.ce_smooth_tones")),
                    ldpc_max_iterations=int(s("assumed.ldpc_max_iterations")),
                    ldpc_minsum_scale=float(s("assumed.ldpc_minsum_scale"))),
        label=f"Liu2025 K={k} MCS{mcs}",
    )
    return dataclasses.replace(cfg, **top) if top else cfg


def improved_rx(rx: RxConfig | None = None) -> RxConfig:
    """The receiver with milestone-0 findings C1 / C2 on: pilot common phase combined across
    ``assumed.cpe_window_symbols`` symbols and the channel-estimate smoothing
    span chosen per packet up to ``assumed.ce_smooth_max_tones``.  The Liu
    2025 preset keeps the milestone-0 receiver (its numbers are the external
    validation); the zero-IF presets take this one."""
    s = spec.value
    return dataclasses.replace(rx or RxConfig(), cpe_window_symbols=int(s("assumed.cpe_window_symbols")),
                               ce_smooth_auto=True, ce_smooth_max_tones=int(s("assumed.ce_smooth_max_tones")))


def zero_if_60ghz(k: int = 8, mcs: int = 0, standard: str = "11ac", bandwidth_hz: float = 20e6,
                  carrier_hz: float = 60.48e9, **top) -> Mmw60Config:
    """Topology B on the wifitrx zero-IF chain at fs_eff with the 60 GHz front
    end switched on (converters at ENOB(fs_eff), IQ mismatch, LO leakage, RX
    DC); Liu 2025's crystal / phase-noise numbers and back-off; carrier on an
    802.11ay channel centre inside 57–71 GHz (data/spec:
    ieee80211ay.channel_centres_ghz).

    The 60 GHz PA is a measured 60 GHz CMOS PA (since 2026-11-12, ROADMAP
    C10): its Psat, small-signal gain and peak PAE, and the Rapp smoothness
    that puts its P1dB as far below Psat as measured (data/spec:
    assumed.pa60_surveyed_pick).  Its operating point follows the rule the
    read 60 GHz transmitters are rated by — the highest output at which TX
    EVM meets the 802.11ad 16-QAM limit — applied to the PA alone on the OFDM
    waveform (data/spec: assumed.pa60_operating_rule,
    derived.pa60_obo_at_evm_limit_db): 7.5 dB from Psat, where Liu's preset
    keeps Liu's 8 dB.  The AM/PM is still the 11ad evaluation methodology's.
    The presets' PA and back-off before 2026-11-12 are ``tgad_em_pa(cfg)``."""
    s = spec.value
    base = liu2025_table2(k=k, mcs=mcs)
    pick = s("assumed.pa60_surveyed_pick")
    measured = s(pick["source"])
    fe = FrontendConfig(
        model="zero_if_chain",
        pa=dataclasses.replace(base.frontend.pa, rapp_p=float(s(pick["rapp_p"])),
                               obo_db=float(s("derived.pa60_obo_at_evm_limit_db"))),
        pa_gain_db=float(measured["gain_db"]), psat_dbm=float(measured["psat_dbm"]),
        pa_pae_max=float(measured["pae_peak"]),
        converters=ConverterConfig(enob_ref=float(s("assumed.converter_enob_ref")),
                                   bits_per_octave=float(s("assumed.converter_bits_per_octave")),
                                   backoff_db=float(s("assumed.converter_backoff_db")), enabled=True),
        iq=IqConfig(**{k2: float(v) for k2, v in s("assumed.iq_mismatch").items()}, enabled=True),
        lo_leak_dbc=float(s("assumed.lo_leak_dbc")), rx_dc_dbc=float(s("assumed.rx_dc_dbc")))
    cfg = dataclasses.replace(base, carrier_hz=float(carrier_hz), frontend=fe,
                              phy=dataclasses.replace(base.phy, standard=standard,
                                                      bandwidth_hz=float(bandwidth_hz)),
                              rx=improved_rx(dataclasses.replace(base.rx, dc_removal=True)),
                              label=f"zero-IF 60 GHz {standard} {bandwidth_hz / 1e6:g} MHz x{k} MCS{mcs}")
    return dataclasses.replace(cfg, **top) if top else cfg


def surveyed_pa(cfg: Mmw60Config) -> Mmw60Config:
    """``cfg`` with the 60 GHz PA taken from one measured 60 GHz CMOS PA
    (data/spec: assumed.pa60_surveyed_pick and the entries it names): Psat,
    small-signal gain, peak PAE, and the Rapp smoothness that puts P1dB as far
    below Psat as the paper measured.  The back-off and its reference stay the
    config's.  ``zero_if_60ghz`` (and the presets built on it) already carry
    this PA; this puts it on any other config."""
    pick = spec.value("assumed.pa60_surveyed_pick")
    src = spec.value(pick["source"])
    pa = dataclasses.replace(cfg.frontend.pa, rapp_p=float(spec.value(pick["rapp_p"])))
    fe = dataclasses.replace(cfg.frontend, pa=pa, psat_dbm=float(src["psat_dbm"]),
                             pa_gain_db=float(src["gain_db"]), pa_pae_max=float(src["pae_peak"]))
    return dataclasses.replace(cfg, frontend=fe, label=(cfg.label + " surveyed PA").strip())


def tgad_em_pa(cfg: Mmw60Config) -> Mmw60Config:
    """``cfg`` with the PA and operating point the topology A / B presets had
    until 2026-11-12: the 11ad evaluation methodology's Rapp shape
    (tgad_em.pa_rapp_p, P1dB 9.5 dB below Psat; Liu 2025's PA) at the assumed
    15 dBm Psat, 20 dB gain and 20 % peak PAE (data/spec: assumed.pa60_*),
    backed off Liu's 8 dB from Psat (liu2025.pa_obo_db).  A sensitivity row:
    what the tables read with Liu's PA."""
    s = spec.value
    pa = dataclasses.replace(cfg.frontend.pa, rapp_p=None, obo_db=float(s("liu2025.pa_obo_db")),
                             obo_reference="psat")
    fe = dataclasses.replace(cfg.frontend, pa=pa, psat_dbm=float(s("assumed.pa60_psat_dbm")),
                             pa_gain_db=float(s("assumed.pa60_gain_db")),
                             pa_pae_max=float(s("assumed.pa60_pae_max")))
    return dataclasses.replace(cfg, frontend=fe, label=(cfg.label + " 11ad EM PA").strip())


def surveyed_frontend(cfg: Mmw60Config) -> Mmw60Config:
    """``cfg`` with the three faces of ROADMAP D4 filled from the surveyed
    figures (data/spec: assumed.frontend_faces_pick and the survey entries it
    names): a receive front end anchored at a 60 GHz communication
    transceiver's noise figure / IIP3, the TX-RX isolation, and a transmit
    and a receive antenna gain.  The presets do not call this: their numbers
    are the ones produced with wifitrx's ladder, a 0 dBi antenna and no
    isolation figure.  The receiver and antenna figures are one 60 GHz
    communication transceiver's, read from its paper; the isolation is a
    subtraction of two numbers in one abstract (data/spec says which
    entries were read in the original and which only as a search snippet)."""
    pick = spec.value("assumed.frontend_faces_pick")
    fe = dataclasses.replace(
        cfg.frontend,
        rx_front=RxFrontConfig(model="anchored", nf_db=float(pick["rx_nf_db"]), iip3_dbm=float(pick["rx_iip3_dbm"]),
                               gain_db=float(pick["rx_gain_db"])),
        tx_rx_isolation_db=float(pick["tx_rx_isolation_db"]),
        antenna_gain_dbi=float(pick["antenna_gain_tx_dbi"]), antenna_gain_rx_dbi=float(pick["antenna_gain_rx_dbi"]))
    return dataclasses.replace(cfg, frontend=fe, label=(cfg.label + " surveyed front end").strip())


def wifi7_chain_k1(mcs: int = 0, standard: str = "11ac", bandwidth_hz: float = 20e6,
                   carrier_hz: float = 6.0e9) -> Mmw60Config:
    """The K = 1 row of the comparison table on the same ``Frontend60`` (iron
    rule 2): the zero-IF chain at the base rate, converters / IQ / leakage as
    the 60 GHz part would have them at 1×, the same Rapp at the same OBO,
    but the sub-7 GHz carrier and the WiFi 7 synthesizer's own phase-noise
    profile (wifitrx's ``DEFAULT_WIFI7_LO_PROFILE``, the LO a 4096-QAM chip
    ships with) — "the WiFi 7 chip as delivered, measured on our bench"."""
    cfg = zero_if_60ghz(k=1, mcs=mcs, standard=standard, bandwidth_hz=bandwidth_hz,
                        carrier_hz=carrier_hz)
    return dataclasses.replace(
        cfg, waveform="be",
        lo=dataclasses.replace(cfg.lo, phase_noise=dataclasses.replace(
            cfg.lo.phase_noise, model="wifitrx_wifi7")),
        label=f"WiFi 7 chain K=1 {standard} {bandwidth_hz / 1e6:g} MHz MCS{mcs}")


def if_extender_60ghz(mcs: int = 0, standard: str = "11be", bandwidth_hz: float = 80e6,
                      carrier_hz: float = 60.48e9, **top) -> Mmw60Config:
    """Topology A: the WiFi 7 chip at K = 1 on a 6 GHz-band IF, then the 60 GHz
    stage.  Crystal, LO phase-noise numbers, the 60 GHz PA and its back-off,
    EIRP limit, channel and receiver are topology B's (``zero_if_60ghz``) — the
    shared ``Frontend60`` (iron rule 2).  The baseband converters / IQ / LO
    leakage / RX DC are the chip's own (wifitrx's, calibrated by its sequence),
    so the front-end switches for those are off here."""
    s = spec.value
    b = zero_if_60ghz(k=1, mcs=mcs, standard=standard, bandwidth_hz=bandwidth_hz, carrier_hz=carrier_hz)
    fe = dataclasses.replace(b.frontend, model="if_extender_chain",
                             converters=dataclasses.replace(b.frontend.converters, enabled=False),
                             iq=dataclasses.replace(b.frontend.iq, enabled=False),
                             lo_leak_dbc=None, rx_dc_dbc=None)
    flt = s("assumed.ifext_filter")
    mlo = s("assumed.mlo_sub7")
    cfg = dataclasses.replace(
        b, topology="if_extender", waveform="be", frontend=fe,
        phy=dataclasses.replace(b.phy, oversampling=int(s("assumed.ifext_chip_oversampling"))),
        lo=dataclasses.replace(b.lo, scheme=str(s("assumed.ifext_lo_scheme")), if_hz=float(s("assumed.ifext_if_hz"))),
        ifext=IfExtConfig(chip="wifitrx", chip_seed=int(s("assumed.ifext_chip_seed")),
                          dpd_max_iterations=int(s("assumed.ifext_dpd_max_iterations")),
                          filter_bw_hz=float(flt["bandwidth_hz"]), filter_order=int(flt["order"]),
                          filter_ripple_db=float(flt["ripple_db"]), filter_center_hz=float(flt["center_hz"]),
                          image_rejection_db=float(s("assumed.ifext_image_rejection_db")),
                          mlo_sub7_hz=float(mlo["carrier_hz"]), mlo_sub7_snr_db=float(mlo["snr_db"])),
        label=f"IF extender 60 GHz {standard} {bandwidth_hz / 1e6:g} MHz MCS{mcs}")
    return dataclasses.replace(cfg, **top) if top else cfg


def wifi7_baseline_k1(mcs: int = 0) -> Mmw60Config:
    """K = 1, no impairments at all: iron rule 2's bit-exact anchor (the
    unmodified wifitrx chain; ``test_law2_k1_chain_is_the_unmodified_wifitrx_chain``)."""
    return Mmw60Config(topology="upclock_zero_if", waveform="be", carrier_hz=6.0e9, upclock_k=1,
                       phy=PhyConfig(mcs=mcs),
                       lo=LoConfig(phase_noise=PhaseNoiseConfig(apply="off")),
                       frontend=FrontendConfig(pa=PaConfig(model="ideal")),
                       channel=ChannelConfig(model="flat"),
                       label=f"WiFi K=1 MCS{mcs}")
