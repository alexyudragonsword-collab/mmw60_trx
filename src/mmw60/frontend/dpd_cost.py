"""What a DPD costs at K× the sample rate: dsp_ip's ``dpd_poly`` synthesis numbers
(source survey) priced per sample with Halo_Serdes's op-energy coefficients
(Horowitz 45 nm, source survey in Halo) — the pJ/bit column of the comparison
table, until PA_DPD's bandwidth-dependent model arrives (ROADMAP D).

dsp_ip (alexyudragonsword-collab/dsp_ip@2887659, docs/results.md): ``dpd_poly``
P = 4 samples/clock, NanGate45 estimates — DDR-Volterra r = 1 (140 terms)
8.026 mm², GMP-510 (255 terms) 14.173 mm², both 682 MHz ⇒ 2727 MSPS.
Energy per sample is counted as one 16-bit multiply + one 16-bit add per
term (Horowitz: 3.1 pJ / 0.1 pJ at 32 bit, 45 nm; multiply ∝ width²,
add ∝ width), which is an upper-bound bookkeeping, not a measurement.
"""
from __future__ import annotations

from dataclasses import dataclass

from .. import spec


@dataclass(frozen=True)
class DpdCost:
    terms: int
    area_mm2_p4: float
    f_clk_mhz_p4: float
    name: str

    @property
    def msps_p4(self) -> float:
        return 4 * self.f_clk_mhz_p4

    def energy_pj_per_sample(self, width_bits: int = 16) -> float:
        mult = float(spec.value("survey.horowitz_mult32_pj")) * (width_bits / 32) ** 2
        add = float(spec.value("survey.horowitz_add32_pj")) * (width_bits / 32)
        return self.terms * (mult + add)

    def pj_per_bit(self, dpd_rate_hz: float, data_rate_bps: float) -> float:
        return self.energy_pj_per_sample() * dpd_rate_hz / data_rate_bps

    def instances_for(self, dpd_rate_hz: float) -> float:
        """How many P = 4 datapaths (or the parallelism multiple) the rate needs."""
        return dpd_rate_hz / (self.msps_p4 * 1e6)


def dsp_ip_models() -> dict[str, DpdCost]:
    t = spec.value("survey.dsp_ip_dpd_poly_p4")
    return {k: DpdCost(terms=int(v["terms"]), area_mm2_p4=float(v["area_mm2"]),
                       f_clk_mhz_p4=float(v["f_clk_mhz"]), name=k) for k, v in t.items()}
