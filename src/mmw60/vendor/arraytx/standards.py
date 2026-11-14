# Vendored from array_tx@5815c5a7ea43143fd58502d4894ac840b5b5fb86: src/arraytx/standards.py
# Adapted-copy policy: see src/mmw60/vendor/__init__.py
"""Radio standards the array can transmit (invariant 1: numbers come from the
config's ``standard`` key, and every external number here carries a source).

Two coexist from day one:

* ``sub6_nr100`` — polar_tx's own FR1 preset (``nr_dtc(bw=100e6)``), used as
  the "bit-identical to one polar_tx chain" regression anchor.  Nothing here
  is re-derived: the preset factory and its waveform maker are polar_tx's.
* ``fr2_nr400`` — 5G NR FR2, 28 GHz carrier, 400 MHz channel, 120 kHz SCS.
  polar_tx's ``nr_dtc`` carries the FR2 element chain (28 GHz, 120 kHz,
  64-QAM, mmWave LO) and, since polar_tx@008cc90, the 400 MHz numerology
  row too; the waveform is polar_tx's own ``nr_waveform``.

Sources are listed per number; ``survey`` means read from the cited spec
clause (the clause text itself could not be re-opened from this environment,
which the LOG records), ``derived`` means computed from survey numbers.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from .vendor.polartx import nr_dtc
from .vendor.polartx.presets import TxPreset
from .vendor.polartx.waveforms.base import Waveform
from .vendor.polartx.waveforms.ofdm import NR_NUMEROLOGY, nr_waveform

TS38101_2 = "3GPP TS 38.101-2 (NR UE radio transmission and reception; Part 2: Range 2 Standalone)"


@dataclass(frozen=True)
class Sourced:
    """A number with its provenance."""
    value: Any
    source: str          # survey | derived | assumed | measured
    ref: str = ""

    def __post_init__(self):
        if self.source not in ("survey", "derived", "assumed", "measured"):
            raise ValueError(f"bad source {self.source!r}")
        if self.source in ("survey", "measured") and not self.ref:
            raise ValueError(f"source {self.source!r} needs a ref")


@dataclass(frozen=True)
class Standard:
    name: str
    carrier_hz: Sourced
    bandwidth_hz: Sourced
    scs_hz: Sourced
    fft_size: Sourced
    n_rb: Sourced
    qam: Sourced
    oversampling: Sourced
    evm_limit_pct: Sourced
    polartx_native: bool = False   # waveform and preset come from polar_tx as-is
    oversampling_overridden: bool = False   # set by with_oversampling (config sim.oversampling)
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def fs_hz(self) -> float:
        return float(self.fft_size.value * self.scs_hz.value * self.oversampling.value)

    @property
    def n_active_tones(self) -> int:
        return int(12 * self.n_rb.value)

    def numbers(self) -> dict[str, Sourced]:
        return {k: getattr(self, k) for k in
                ("carrier_hz", "bandwidth_hz", "scs_hz", "fft_size", "n_rb",
                 "qam", "oversampling", "evm_limit_pct")}

    def with_oversampling(self, k: int) -> "Standard":
        """This standard on a k-times oversampled grid (config ``sim.oversampling``):
        the same symbols and numerology, fs = FFT x SCS x k.  The value is a study
        setting, so it is labelled assumed."""
        k = int(k)
        if self.polartx_native:
            # the anchor's waveform is polar_tx's own preset waveform: an override
            # would not reach it, and a silently ignored setting is worse than none
            raise ValueError(f"{self.name}: sim.oversampling cannot override the polar_tx-native anchor")
        if k < 1:
            raise ValueError(f"oversampling must be >= 1, got {k}")
        return replace(self, oversampling=Sourced(k, "assumed", "config sim.oversampling (study setting)"),
                       oversampling_overridden=True)

    # ------------------------------------------------------- construction
    def preset(self, **overrides) -> TxPreset:
        """polar_tx's ``nr_dtc`` preset for this standard.

        ``overrides`` are forwarded (``cfr_papr_db``, ``dpa``, ``lo_pn`` ...).
        For the native sub-6 anchor the defaults are polar_tx's own.
        """
        kw: dict[str, Any] = dict(bw=float(self.bandwidth_hz.value))
        if not self.polartx_native:
            kw.update(scs=float(self.scs_hz.value), qam=int(self.qam.value),
                      fout=float(self.carrier_hz.value),
                      oversampling=int(self.oversampling.value))
        kw.update(overrides)
        return nr_dtc(**kw)

    def make_waveform(self, n_symbols: int, seed: int) -> Waveform:
        if self.polartx_native:
            return self.preset().make_waveform(n_symbols=n_symbols, seed=seed)
        # polar_tx@008cc90 carries the 400 MHz @ 120 kHz row, so the FR2
        # waveform is polar_tx's own nr_waveform; the table's FFT / RB must
        # agree with this standard's sourced numbers (tested).
        fft, n_rb = NR_NUMEROLOGY[(float(self.bandwidth_hz.value), float(self.scs_hz.value))]
        if (fft, n_rb) != (int(self.fft_size.value), int(self.n_rb.value)):
            raise ValueError(f"{self.name}: polar_tx numerology {(fft, n_rb)} disagrees with "
                             f"the standard's {(self.fft_size.value, self.n_rb.value)}")
        return nr_waveform(float(self.bandwidth_hz.value), float(self.scs_hz.value),
                           int(self.qam.value), n_symbols=int(n_symbols),
                           oversampling=int(self.oversampling.value), seed=int(seed))


FR2_NR400 = Standard(
    name="fr2_nr400",
    carrier_hz=Sourced(28e9, "survey", f"{TS38101_2} Table 5.2-1: n257 26.5-29.5 GHz, n261 27.5-28.35 GHz; 28 GHz is inside both"),
    bandwidth_hz=Sourced(400e6, "survey", f"{TS38101_2} Table 5.3.5-1: 400 MHz channel bandwidth for 120 kHz SCS"),
    scs_hz=Sourced(120e3, "survey", f"{TS38101_2} Table 5.3.5-1: 120 kHz SCS supports 400 MHz"),
    fft_size=Sourced(4096, "derived", "smallest power of two above N_RB*12 = 3168 tones (same convention as polar_tx nr_waveform / 38.104)"),
    n_rb=Sourced(264, "survey", f"{TS38101_2} Table 5.3.2-1: N_RB = 264 for 400 MHz at 120 kHz SCS (cross-checked against the 9860 kHz minimum guardband in Table 5.3.3-1)"),
    qam=Sourced(64, "survey", f"{TS38101_2} Table 6.4.2.1-1: FR2 UE EVM limit given up to 64-QAM (polar_tx's nr_dtc FR2 branch uses the same)"),
    oversampling=Sourced(4, "derived", "fs >= 4.9*BW is what aclr_multi needs for ACLR2 (polar_tx metrics/aclr_ext.py); 4 x 491.52 = 1966.08 MS/s"),
    evm_limit_pct=Sourced(8.0, "survey", f"{TS38101_2} Table 6.4.2.1-1: 64-QAM EVM 8 %"),
    notes=("Relative bandwidth 400 MHz / 28 GHz = 1.43 %: wide enough for squint and wideband coupling to show.",
           "The FR2 element chain is polar_tx nr_dtc's bw>100 MHz branch (open-loop DTC, -100 dBc/Hz @ 1 MHz LO)."),
)

SUB6_NR100 = Standard(
    name="sub6_nr100",
    carrier_hz=Sourced(3.5e9, "survey", "polar_tx presets.py nr_dtc FR1 default (n78)"),
    bandwidth_hz=Sourced(100e6, "survey", "polar_tx presets.py nr_dtc default"),
    scs_hz=Sourced(30e3, "survey", "polar_tx presets.py nr_dtc FR1 default"),
    fft_size=Sourced(4096, "survey", "polar_tx waveforms/ofdm.py NR_NUMEROLOGY[(100e6, 30e3)]"),
    n_rb=Sourced(273, "survey", "polar_tx waveforms/ofdm.py NR_NUMEROLOGY[(100e6, 30e3)]"),
    qam=Sourced(256, "survey", "polar_tx presets.py nr_dtc FR1 default"),
    oversampling=Sourced(4, "survey", "polar_tx waveforms/ofdm.py nr_waveform default"),
    evm_limit_pct=Sourced(3.5, "survey", "polar_tx presets.py nr_dtc docstring: 256-QAM 3.5 %"),
    polartx_native=True,
    notes=("Regression anchor: waveform and chain are polar_tx's nr_dtc() verbatim; one element with S = 0 must reproduce it bit for bit.",),
)

STANDARDS: dict[str, Standard] = {s.name: s for s in (FR2_NR400, SUB6_NR100)}


def get_standard(name: str) -> Standard:
    try:
        return STANDARDS[name]
    except KeyError:
        raise KeyError(f"unknown standard {name!r}; one of {sorted(STANDARDS)}") from None
