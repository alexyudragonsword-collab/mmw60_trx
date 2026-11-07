"""``Frontend60``: the one front-end object both topologies are handed (iron rule 2).

Built once from ``Mmw60Config`` (``Frontend60.from_config``), it produces
wifitrx ``TxParams`` / ``RxParams`` for a given effective bandwidth and
sample rate — the upclocked zero-IF chain — with every rate-dependent
quantity derived here: converter bits from the ENOB law, LPF corners from
wifitrx's own ``recommended_lpf_corner_hz`` at the K-scaled bandwidth,
the LO leakage from its dBc figure, the IQ mismatch in absolute ps / ns
(so the same part gets worse across a wider band).  The PA is the
Rapp at ``psat_dbm`` / ``gain_db``; ``set_vga_for_obo`` puts its average
output at Psat − OBO by trimming the analog VGA, never the digital drive
(the DAC must not clip to reach an operating point).
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

import numpy as np

from ..pa.rapp import ModifiedRappPA
from ..vendor.wifitrx.chain.params import RxParams, TxParams, recommended_lpf_corner_hz
from ..vendor.wifitrx.chain.rx import RxChain
from ..vendor.wifitrx.chain.tx import TxChain
from ..vendor.wifitrx.impairments.analog_filter import TunableLPF
from ..vendor.wifitrx.impairments.converters import ADCParams, DACParams
from ..vendor.wifitrx.impairments.iq_imbalance import FreqDepIQImbalance
from ..vendor.wifitrx.units import power_dbm
from .converters import ConverterLaw
from .eirp import EirpLimit
from .lo import Lo60
from .pa import ScaledRappPA


@dataclass(frozen=True)
class IqMismatch:
    """One part's quadrature error, in the units wifitrx's model takes.
    Defaults are the mid-points of wifitrx's ``TxParams.randomize`` ranges
    (data/spec: assumed.iq_mismatch)."""
    gain_db: float = 0.25
    phase_deg: float = 1.5
    gd_mismatch_ps: float = 150.0
    rail_ripple_db: float = 0.3
    rail_gd_ripple_ns: float = 0.12
    ripple_period_hz: float = 160e6
    enabled: bool = True

    def model(self) -> FreqDepIQImbalance:
        return FreqDepIQImbalance(gain_db=self.gain_db, phase_deg=self.phase_deg,
                                  gd_mismatch_ps=self.gd_mismatch_ps,
                                  rail_ripple_db=self.rail_ripple_db,
                                  rail_gd_ripple_ns=self.rail_gd_ripple_ns,
                                  ripple_period_hz=self.ripple_period_hz,
                                  enabled=self.enabled)


@dataclass
class Frontend60:
    lo: Lo60
    converters: ConverterLaw = field(default_factory=ConverterLaw)
    converters_enabled: bool = True
    tx_iq: IqMismatch = field(default_factory=IqMismatch)
    rx_iq: IqMismatch = field(default_factory=IqMismatch)
    eirp: EirpLimit | None = None
    pa_model: ModifiedRappPA | None = None
    pa_enabled: bool = True
    pa_gain_db: float = 20.0
    psat_dbm: float = 15.0
    obo_db: float = 8.0
    obo_reference: str = "psat"
    antenna_gain_dbi: float = 0.0
    seed: int = 0

    # ------------------------------------------------------------ build
    @classmethod
    def from_config(cls, cfg) -> "Frontend60":
        fe = cfg.frontend
        pn = cfg.lo.phase_noise
        lo = Lo60.from_pole_zero(cfg.carrier_hz, pn.psd0_dbchz, pn.f_pole_hz, pn.f_zero_hz,
                                 enabled=pn.enabled, tx_leak_dbc=fe.lo_leak_dbc,
                                 rx_dc_dbc=fe.rx_dc_dbc)
        conv = ConverterLaw(enob_ref=fe.converters.enob_ref, fs_ref_hz=fe.converters.fs_ref_hz,
                            bits_per_octave=fe.converters.bits_per_octave,
                            backoff_db=fe.converters.backoff_db)
        iq = IqMismatch(gain_db=fe.iq.gain_db, phase_deg=fe.iq.phase_deg,
                        gd_mismatch_ps=fe.iq.gd_mismatch_ps, rail_ripple_db=fe.iq.rail_ripple_db,
                        rail_gd_ripple_ns=fe.iq.rail_gd_ripple_ns, enabled=fe.iq.enabled)
        eirp = EirpLimit.fcc_15_255() if fe.eirp_limit_dbm is None else dataclasses.replace(
            EirpLimit.fcc_15_255(), avg_dbm=float(fe.eirp_limit_dbm))
        return cls(lo=lo, converters=conv, converters_enabled=fe.converters.enabled,
                   tx_iq=iq, rx_iq=iq, eirp=eirp,
                   pa_model=ModifiedRappPA(ampm=fe.pa.ampm) if fe.pa.enabled else None,
                   pa_enabled=fe.pa.enabled, pa_gain_db=fe.pa_gain_db, psat_dbm=fe.psat_dbm,
                   obo_db=fe.pa.obo_db, obo_reference=fe.pa.obo_reference,
                   antenna_gain_dbi=fe.antenna_gain_dbi, seed=cfg.seed)

    def scaled_pa(self) -> ScaledRappPA:
        return ScaledRappPA(self.pa_model or ModifiedRappPA(), self.pa_gain_db, self.psat_dbm)

    def tx_params(self, bw_eff_hz: float, fs_eff_hz: float, signal_dbm_at_modulator: float = -10.0) -> TxParams:
        bits = self.converters.bits(fs_eff_hz)
        return TxParams(bandwidth_hz=bw_eff_hz,
                        dac=DACParams(bits=bits, fs_conv_hz=fs_eff_hz, enabled=self.converters_enabled),
                        lpf=TunableLPF(fc_nominal_hz=recommended_lpf_corner_hz(bw_eff_hz, "tx")),
                        iq=self.tx_iq.model(),
                        lo_leak_dbm=self.lo.tx_leak_dbm(signal_dbm_at_modulator),
                        lo_leak_phase_deg=123.0,
                        lo=self.lo.lo_model(),
                        pa_gain_db=self.pa_gain_db, psat_dbm=self.psat_dbm,
                        pa_enabled=self.pa_enabled, seed=self.seed)

    def rx_params(self, bw_eff_hz: float, fs_eff_hz: float) -> RxParams:
        bits = self.converters.bits(fs_eff_hz)
        # LO self-mixing DC per gain state, scaled from wifitrx's randomize ladder
        # by the configured dBc figure against a nominal -20 dBm baseband signal
        dc = ()
        if self.lo.rx_dc_dbc is not None:
            ladder = (0.02, 0.014, 0.01, 0.007, 0.005, 0.004, 0.003, 0.002)
            ref = 0.02 / 10 ** (-20 / 20)                     # the ladder's top ≈ -20 dBc at -20 dBm
            scale = 10 ** (self.lo.rx_dc_dbc / 20) / ref
            dc = tuple(complex(s * scale * np.exp(1j * 0.6)) for s in ladder)
        return RxParams(bandwidth_hz=bw_eff_hz, iq=self.rx_iq.model(), dc_offset=dc,
                        lpf=TunableLPF(fc_nominal_hz=recommended_lpf_corner_hz(bw_eff_hz, "rx")),
                        adc=ADCParams(bits=bits, enabled=self.converters_enabled),
                        lo=self.lo.lo_model(), seed=self.seed + 1)

    def build_chains(self, bw_eff_hz: float, fs_eff_hz: float) -> tuple[TxChain, RxChain]:
        tx = TxChain(self.tx_params(bw_eff_hz, fs_eff_hz), fs_eff_hz,
                     pa=self.scaled_pa() if self.pa_enabled else None)
        if not self.pa_enabled:
            tx.params.pa_enabled = False
        rx = RxChain(self.rx_params(bw_eff_hz, fs_eff_hz), fs_eff_hz)
        return tx, rx

    # ------------------------------------------------------------ operating point
    def target_pout_dbm(self) -> float:
        pa = self.scaled_pa()
        ref = self.psat_dbm if self.obo_reference == "psat" else pa.p1db_out_dbm
        return ref - self.obo_db

    def set_vga_for_obo(self, tx: TxChain, x_digital: np.ndarray, tol_db: float = 0.02) -> float:
        """Trim ``tx.params.vga_gain_db`` so the PA's average output power is
        the OBO target for this waveform; returns the achieved Pout [dBm]."""
        if not self.pa_enabled:
            return power_dbm(tx(x_digital))
        target = self.target_pout_dbm()
        for _ in range(12):
            p = power_dbm(tx(x_digital))
            err = target - p
            if abs(err) < tol_db:
                break
            # compression makes dPout/dPin < 1: step a little more than the error
            tx.params.vga_gain_db += err * 1.2
        return power_dbm(tx(x_digital))

    def describe(self, fs_eff_hz: float | None = None) -> dict:
        d = {"carrier_hz": self.lo.carrier_hz, "pa": "rapp_11ad" if self.pa_enabled else "ideal",
             "psat_dbm": self.psat_dbm, "pa_gain_db": self.pa_gain_db, "obo_db": self.obo_db,
             "obo_reference": self.obo_reference, "pout_dbm": self.target_pout_dbm() if self.pa_enabled else None,
             "lo_ipn_dbc": self.lo.ipn_dbc(), "tx_leak_dbc": self.lo.tx_leak_dbc,
             "rx_dc_dbc": self.lo.rx_dc_dbc, "iq_enabled": self.tx_iq.enabled}
        if fs_eff_hz:
            d.update({f"converter_{k}": v for k, v in self.converters.describe(fs_eff_hz).items()})
        if self.eirp is not None and self.pa_enabled:
            d.update(self.eirp.check(self.target_pout_dbm(), self.antenna_gain_dbi))
        return d
