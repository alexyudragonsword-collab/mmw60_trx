"""The pJ/bit column of the comparison table, in Halo_Serdes example 41's terms.

Every coefficient is a public figure or a stated assumption
(``data/spec/survey.yaml``: Horowitz 45 nm arithmetic energies, the Murmann
survey's Walden FoM, DeepScaleTool's node factor, this library's PA PAE and
synthesizer powers), so the model is for **ratios between schemes** — K = 1
against K = 8 against K = 32, the same hardware — not for an absolute budget.
``sensitivity`` in :mod:`mmw60.compare` reruns the table at each
coefficient's range ends to show which conclusions survive.

What it counts, per link direction (one transmitter and one receiver):

- ``pa``: the PA's DC power at its operating point, ``Pout / PAE(Pout)``
  with the shared front end's back-off law (``frontend/pa.py``: class-B,
  PAE ∝ sqrt(Pout / Psat));
- ``lo``: the two synthesizers (TX and RX) as fixed powers — the 60 GHz
  figure above 10 GHz carriers, the sub-7 GHz one below;
- ``converters``: I and Q DAC on the transmitter, I and Q ADC on the
  receiver, each at ``P = FoM_W · 2^ENOB(fs_eff) · fs_eff`` with the same
  ENOB law the EVM floor uses (``ConverterLaw``) — the K× rate enters
  twice, through fs and through the ENOB it leaves;
- ``dpd``: dsp_ip's P = 4 polynomial DPD (``DpdCost``) at
  ``assumed.dpd_rate_over_bw × BW_eff``, counted only when the PA is on;
- ``fft``: the transmitter's IFFT and the receiver's FFT at the **base**
  size (the digital PHY is unchanged, its clock is ×K): (N/2)·log2 N
  radix-2 butterflies per symbol, each a complex multiply (4 mult + 2 add)
  and two complex adds (4 add), at ``assumed.dsp_word_bits``;
- ``decoder``: the soft-decision Viterbi of the coded 11ac 20 MHz base (64
  states, two branch-metric adds and one compare per state per
  information bit), or the normalised min-sum LDPC decoder of the 11be
  bases (two add-equivalents per edge per iteration, at the maximum
  iteration count — an upper bound; early stopping is not credited).  The
  EVM-only 11ac 40–160 MHz bases have no decoder and the table says so.

Not counted (the same omissions as Halo's model): pipeline registers,
clock trees, memories, the LNA / mixer / baseband filters, and the
parallelism a 20 GS/s datapath needs — digital blocks are a lower bound.
Digital energy is at 45 nm by default (consistent with ``dpd_cost.py`` and
example 02); ``node_scale`` moves all digital blocks to 7 nm.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np

from . import spec
from .frontend.dpd_cost import dsp_ip_models
from .vendor.wifitrx.units import dbm_to_mw

#: K = 7 convolutional code of the VHT data field (phy/bcc.py): 2^(K-1) states
BCC_STATES = 64
#: per state and information bit: two branch-metric adds and one compare
VITERBI_OPS_PER_STATE = 3
#: a radix-2 butterfly: one complex multiply (4 real mult + 2 add) + two complex adds (4 add)
BUTTERFLY_MULT, BUTTERFLY_ADD = 4, 6


@dataclass(frozen=True)
class PowerCoefficients:
    """Coefficients of the power model, read from the spec table by
    :meth:`from_spec`; every field names its entry."""
    walden_fom_j: float            # survey.walden_fom_fj
    mult32_j: float                # survey.horowitz_mult32_pj
    add32_j: float                 # survey.horowitz_add32_pj
    pll60_w: float                 # assumed.pll60_power_mw
    pll_sub7_w: float              # assumed.pll_sub7_power_mw
    word_bits: int = 16            # assumed.dsp_word_bits
    node_scale: float = 1.0        # 1.0 = 45 nm as published; survey.node_scale_45_to_7nm for 7 nm
    dpd_model: str = "ddr_r1_w16"  # survey.dsp_ip_dpd_poly_p4 key
    mmwave_above_hz: float = 10e9  # which synthesizer figure a carrier takes

    @classmethod
    def from_spec(cls, **over) -> "PowerCoefficients":
        s = spec.value
        kw = dict(walden_fom_j=float(s("survey.walden_fom_fj")) * 1e-15,
                  mult32_j=float(s("survey.horowitz_mult32_pj")) * 1e-12,
                  add32_j=float(s("survey.horowitz_add32_pj")) * 1e-12,
                  pll60_w=float(s("assumed.pll60_power_mw")) * 1e-3,
                  pll_sub7_w=float(s("assumed.pll_sub7_power_mw")) * 1e-3,
                  word_bits=int(s("assumed.dsp_word_bits")))
        kw.update(over)
        return cls(**kw)

    def with_(self, **kw) -> "PowerCoefficients":
        return replace(self, **kw)

    # --- primitives (Halo analysis/power.py) ---------------------------------
    def mult_j(self, bits: int | None = None) -> float:
        b = self.word_bits if bits is None else bits
        return self.mult32_j * (b * b) / 1024.0 * self.node_scale

    def add_j(self, bits: int | None = None) -> float:
        b = self.word_bits if bits is None else bits
        return self.add32_j * b / 32.0 * self.node_scale

    def converter_w(self, fs_hz: float, enob: float) -> float:
        """One converter at ``fs_hz`` and ``enob`` (Walden: 2× per bit)."""
        return self.walden_fom_j * 2.0 ** enob * fs_hz

    def describe(self) -> dict:
        return {"walden_fom_fj": self.walden_fom_j * 1e15, "mult32_pj": self.mult32_j * 1e12,
                "add32_pj": self.add32_j * 1e12, "pll60_mw": self.pll60_w * 1e3,
                "pll_sub7_mw": self.pll_sub7_w * 1e3, "word_bits": self.word_bits,
                "node_scale": self.node_scale, "dpd_model": self.dpd_model}


@dataclass(frozen=True)
class PowerBlock:
    name: str
    watts: float
    note: str = ""


@dataclass(frozen=True)
class PowerReport:
    blocks: tuple[PowerBlock, ...]
    bit_rate: float          # [bit/s] at the scheme's MCS cap
    omitted: tuple[str, ...] = ()

    @property
    def total_w(self) -> float:
        return float(sum(b.watts for b in self.blocks))

    @property
    def pj_per_bit(self) -> float:
        return math.inf if self.bit_rate <= 0 else self.total_w / self.bit_rate * 1e12

    def watts(self, prefix: str = "") -> float:
        return float(sum(b.watts for b in self.blocks if b.name.startswith(prefix)))

    def pj(self, prefix: str = "") -> float:
        return math.inf if self.bit_rate <= 0 else self.watts(prefix) / self.bit_rate * 1e12

    def as_dict(self) -> dict:
        return {"bit_rate_bps": self.bit_rate, "total_w": self.total_w, "pj_per_bit": self.pj_per_bit,
                "blocks": {b.name: {"watts": b.watts, "pj_per_bit": self.pj(b.name), "note": b.note}
                           for b in self.blocks},
                "omitted": list(self.omitted)}

    def table(self) -> str:
        rows = [f"  {b.name:<12} {1e3 * b.watts:9.2f} mW {self.pj(b.name):9.1f} pJ/b  {b.note}" for b in self.blocks]
        rows.append(f"  {'total':<12} {1e3 * self.total_w:9.2f} mW {self.pj_per_bit:9.1f} pJ/b")
        if self.omitted:
            rows.append("  not counted: " + "; ".join(self.omitted))
        return "\n".join(rows)


def power_report(cfg, fe, bit_rate_bps: float, coeffs: PowerCoefficients | None = None,
                 phy=None, mcs_index: int | None = None) -> PowerReport:
    """The blocks of one scheme (``cfg`` on the shared ``fe``) per link
    direction, priced per bit at ``bit_rate_bps`` (the rate at its MCS cap);
    ``mcs_index`` is the MCS that rate belongs to (the LDPC decoder's work
    per information bit depends on its code rate), default ``cfg.phy.mcs``."""
    k = coeffs or PowerCoefficients.from_spec()
    phy = cfg.upclocked() if phy is None else phy
    fs, bw = phy.fs_eff, phy.bandwidth_eff
    blocks: list[PowerBlock] = []
    omitted: list[str] = []
    # PA
    if fe.pa_enabled and cfg.frontend.pa.enabled:
        pa = fe.scaled_pa()
        pout_dbm = fe.target_pout_dbm()
        pae = float(pa.pae(pout_dbm))
        blocks.append(PowerBlock("pa", dbm_to_mw(pout_dbm) * 1e-3 / max(pae, 1e-6),
                                 f"Pout {pout_dbm:.1f} dBm, PAE {100 * pae:.1f} % (class-B law from {100 * pa.pae_max:.0f} %)"))
    else:
        omitted.append("PA ideal (no DC power counted)")
    topo_a = cfg.topology == "if_extender"
    # topology A: the chip's own PA drives the 60 GHz stage (measured on the calibrated chip)
    if topo_a and cfg.ifext.chip == "wifitrx":
        from .ifext import chip_facts
        f = chip_facts(cfg, bw, fs)
        blocks.append(PowerBlock("chip_pa", f["pa_dc_w"],
                                 f"the chip's PA as the driver: Pout {f['pout_dbm']:.1f} dBm, average PAE {100 * f['pa_pae']:.1f} %"))
    # synthesizers
    mm = cfg.carrier_hz >= k.mmwave_above_hz
    p_lo = k.pll60_w if mm else k.pll_sub7_w
    if topo_a:
        blocks.append(PowerBlock("lo", 2 * (k.pll60_w + k.pll_sub7_w),
                                 f"per link end the chip's synthesizer ({1e3 * k.pll_sub7_w:.0f} mW) and the fixed LO "
                                 f"({1e3 * k.pll60_w:.0f} mW), TX + RX"))
    else:
        blocks.append(PowerBlock("lo", 2 * p_lo, f"TX + RX synthesizer at {1e3 * p_lo:.0f} mW each ({'60 GHz' if mm else 'sub-7'} figure)"))
    # converters: I/Q DAC + I/Q ADC at ENOB(fs_eff)
    if topo_a:
        # the chip's own converters, priced by the same law at the chip's rate
        enob = fe.converters.enob(fs)
        blocks.append(PowerBlock("converters", 4 * k.converter_w(fs, enob),
                                 f"the chip's 2 DAC + 2 ADC at {fs / 1e9:.2f} GS/s, ENOB {enob:.1f} by the same law, "
                                 f"Walden {k.walden_fom_j * 1e15:.0f} fJ"))
    elif fe.converters_enabled and cfg.frontend.converters.enabled:
        enob = fe.converters.enob(fs)
        blocks.append(PowerBlock("converters", 4 * k.converter_w(fs, enob),
                                 f"2 DAC + 2 ADC at {fs / 1e9:.2f} GS/s, ENOB {enob:.1f}, Walden {k.walden_fom_j * 1e15:.0f} fJ"))
    else:
        omitted.append("converters ideal")
    # DPD
    if fe.pa_enabled and cfg.frontend.pa.enabled:
        m = dsp_ip_models()[k.dpd_model]
        rate = float(spec.value("assumed.dpd_rate_over_bw")) * bw
        e_sample = m.terms * (k.mult_j() + k.add_j())
        blocks.append(PowerBlock("dpd", e_sample * rate,
                                 f"{m.terms} terms at {rate / 1e9:.2f} GS/s ({m.instances_for(rate):.1f} P=4 datapaths)"))
    # FFT / IFFT at the base size, symbol rate × K
    n = int(phy.base.fft_size)
    sym_rate = 1.0 / phy.t_symbol_eff
    bfly = (n / 2) * math.log2(n)
    e_sym = bfly * (BUTTERFLY_MULT * k.mult_j() + BUTTERFLY_ADD * k.add_j())
    blocks.append(PowerBlock("fft", 2 * e_sym * sym_rate,
                             f"IFFT + FFT, N = {n}, {sym_rate / 1e6:.2f} Msym/s, {k.word_bits} bit"))
    # decoder
    if cfg.coded and cfg.phy.standard == "11be":
        from .phy.eht import eht_mcs, ldpc_decoder_ops_per_info_bit
        m = eht_mcs(cfg.phy.mcs if mcs_index is None else mcs_index, cfg.phy.bandwidth_hz)
        ops = ldpc_decoder_ops_per_info_bit(m.rate_str)
        blocks.append(PowerBlock("decoder", ops * k.add_j() * bit_rate_bps,
                                 f"LDPC min-sum, 1944 R={m.rate_str}, {ops:.0f} add-equiv per info bit at the max iterations"))
    elif cfg.coded:
        e_bit = BCC_STATES * VITERBI_OPS_PER_STATE * k.add_j()
        blocks.append(PowerBlock("decoder", e_bit * bit_rate_bps,
                                 f"soft Viterbi, {BCC_STATES} states × {VITERBI_OPS_PER_STATE} ops per info bit"))
    else:
        omitted.append("decoder (EVM-only base: no coded data field)")
    return PowerReport(tuple(blocks), float(bit_rate_bps), tuple(omitted))


def pj_per_bit_breakdown(rep: PowerReport) -> dict:
    return {b.name: rep.pj(b.name) for b in rep.blocks}


def mw(x: float) -> float:
    return float(np.round(1e3 * x, 3))
