"""The EDMG (802.11ay) single-channel PHY numbers as the skeleton's types.

Every number is read through ``mmw60.spec`` from the entries spec_sources
added for spec_sources#29 (``edmg.*``, ``dmg.*``, ``ieee80211ay.*``; iron
rule 5).  What this library chooses itself is an ``assumed`` entry:

* ``assumed.ay_chain_rate`` — both waveforms run on one chain at one sample
  rate: OFDM's 2.64 GS/s × 2 = SC's 1.76 Gchip/s × 3 = 5.28 GS/s (one front-end
  instance, iron rule 2), with the chain's filters set for the 2.16 GHz
  channel width (the spacing of ``ieee80211ay.channel_centres_ghz``);
* ``assumed.ay_sc_pulse`` — the single-carrier pulse (root-raised-cosine; the
  standard gives a spectral mask, not a filter);
* ``assumed.ay_preamble`` — the training this library sends: a repeated
  Golay sequence for the CFO, a Golay pair behind cyclic prefixes for the
  channel, Golay guards (the principle of the DMG preamble and guard, not
  their sequences, which are not in spec_sources);
* ``assumed.ay_evm_payload`` — what the EVM-only payload carries;
* ``assumed.ay_sensitivity`` — the decoder threshold of an EDMG MCS for the
  range: spec_sources has no EDMG sensitivity, so an MCS whose DMG twin
  (same bits per symbol, code rate and repetition) is in the DMG tables
  takes that twin's minimum sensitivity, with the reference receiver's
  noise figure and implementation loss taken back out (the floor enters as
  a noise term, as for the be rows' measured thresholds); an MCS without a
  twin has no threshold.

The OFDM pilot tones move with the channel (``edmg.ofdm_pilot_tones_ncb1``),
so a numerology is built for the channel the carrier is on.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

import numpy as np

from .. import spec
from ..vendor.wifitrx.units import KT_DBM_HZ
from .ofdm import OfdmNumerology
from .sc import ScNumerology

GIS = ("short", "normal", "long")
WAVEFORMS = ("ay_ofdm", "ay_sc")


def channel_spacing_hz() -> float:
    """2.16 GHz: the spacing of the 802.11ay channel centres."""
    c = np.asarray(spec.value("ieee80211ay.channel_centres_ghz"), dtype=float)
    return float(np.round(np.diff(c).mean(), 6) * 1e9)


def channel_of(carrier_hz: float) -> int:
    """The EDMG channel number whose centre is ``carrier_hz``; ValueError otherwise."""
    tab = spec.value("edmg.ofdm_pilot_tones_ncb1")
    for ch, f in zip(tab["channel"], tab["fc_ghz"]):
        if abs(float(f) * 1e9 - float(carrier_hz)) < 1e3:
            return int(ch)
    raise ValueError(f"{carrier_hz / 1e9:g} GHz is not an EDMG channel centre "
                     f"({', '.join(f'{f:g}' for f in tab['fc_ghz'])} GHz; edmg.ofdm_pilot_tones_ncb1)")


def ofdm_numerology(channel: int = 2, gi: str = "normal") -> OfdmNumerology:
    """The single-channel EDMG OFDM plan on ``channel``: 512-point DFT at
    2.64 GS/s, 336 data + 16 pilot tones over ±177, 3 DC nulls, pilots where
    that channel puts them, P16 values of stream 1."""
    if gi not in GIS:
        raise ValueError(f"gi must be one of {GIS}")
    p = spec.value("edmg.ofdm_params")
    fs, n_fft = float(p["fs_hz"]), int(p["n_dft"])
    cp = int(round(float(p[f"gi_{gi}_s"]) * fs))
    half_dc = int(p["n_dc"]) // 2
    dc = set(range(-half_dc, half_dc + 1))
    pilots = [int(k) for k in spec.ref(f"edmg.ofdm_pilot_tones_ncb1#tones@channel={int(channel)}")]
    values = [complex(v) for v in spec.ref("edmg.ofdm_pilot_values_ncb1#p16@i_sts=1")]
    n_sr = int(p["n_sr"])
    data = [k for k in range(-n_sr, n_sr + 1) if k not in dc and k not in pilots]
    if len(data) != int(p["n_sd"]) or len(pilots) != int(p["n_sp"]):
        raise ValueError(f"channel {channel}: {len(data)} data / {len(pilots)} pilot tones, the table says "
                         f"{p['n_sd']} / {p['n_sp']}")
    return OfdmNumerology(n_fft=n_fft, cp=cp, fs_hz=fs, data_tones=tuple(data), pilot_tones=tuple(pilots),
                          pilot_values=tuple(values))


def sc_numerology(gi: str = "normal") -> ScNumerology:
    """The single-channel EDMG SC block: 512 chips at 1.76 Gchip/s, the GI
    at the front, π/2 rotation (the modulations are π/2-BPSK … π/2-64-QAM)."""
    if gi not in GIS:
        raise ValueError(f"gi must be one of {GIS}")
    p = spec.value("edmg.sc_params")
    return ScNumerology(block=int(p["block_chips"]), guard=int(p[f"gi_{gi}_chips"]),
                        fs_hz=float(p["chip_rate_hz"]), rotation_rad=np.pi / 2)


_ORDER = {"BPSK": 2, "QPSK": 4, "16-QAM": 16, "16QAM": 16, "64-QAM": 64, "64QAM": 64}


@dataclass(frozen=True)
class AyMcs:
    waveform: str
    mcs: int
    modulation: str          # as the table writes it
    order: int               # bits-per-symbol constellation (2 / 4 / 16 / 64)
    tone_order: int          # the points one tone / chip carries (DCM BPSK / QPSK put 4 / 16 per tone)
    code_rate: Fraction
    repetition: int
    evm_limit_db: float

    def rate_bps(self, gi: str = "normal") -> float:
        key = "edmg.ofdm_rate_mbps" if self.waveform == "ay_ofdm" else "edmg.sc_rate_mbps"
        return float(spec.ref(f"{key}#{gi}_gi_mbps@mcs={self.mcs}")) * 1e6


def _order_of(modulation: str) -> tuple[int, int]:
    name = modulation.replace("π/2-", "").replace("DCM ", "").strip()
    order = _ORDER[name]
    # dual-carrier modulation spreads a pair of symbols over two tones: each tone then
    # carries the next-larger square constellation (assumed.ay_evm_payload)
    tone = {2: 4, 4: 16}[order] if modulation.startswith("DCM") else order
    return order, tone


def mcs_table(waveform: str) -> list[AyMcs]:
    """Every single-channel EDMG MCS of ``waveform`` (edmg.ofdm_mcs / edmg.sc_mcs)."""
    if waveform not in WAVEFORMS:
        raise ValueError(f"waveform must be one of {WAVEFORMS}")
    t = spec.value("edmg.ofdm_mcs" if waveform == "ay_ofdm" else "edmg.sc_mcs")
    rep = t.get("repetition", [1] * len(t["mcs"]))
    out = []
    for i, m in enumerate(t["mcs"]):
        order, tone = _order_of(t["modulation"][i])
        out.append(AyMcs(waveform, int(m), t["modulation"][i], order, tone, Fraction(t["code_rate"][i]),
                         int(rep[i]), float(t["evm_db"][i])))
    return out


def mcs_entry(waveform: str, mcs: int) -> AyMcs:
    for e in mcs_table(waveform):
        if e.mcs == int(mcs):
            return e
    raise ValueError(f"{waveform} has no MCS {mcs} ({[e.mcs for e in mcs_table(waveform)]})")


def conformance_cap(floor_db: float, waveform: str, gi: str = "normal") -> dict:
    """The MCS a transmitter with EVM ``floor_db`` may send: every MCS whose
    TX EVM limit is at or above the floor passes; the limits are not
    monotonic in the index (EDMG OFDM MCS 6, DCM QPSK 1/2, allows −10 dB
    where MCS 5 allows −13), so the cap is the passing MCS with the highest
    rate, and the highest passing index is reported beside it."""
    ok = [e for e in mcs_table(waveform) if floor_db <= e.evm_limit_db]
    if not ok:
        return {"mcs": None, "rate_bps": 0.0, "highest_index": None, "limit_db": None}
    best = max(ok, key=lambda e: (e.rate_bps(gi), e.mcs))
    return {"mcs": best.mcs, "rate_bps": best.rate_bps(gi), "highest_index": max(e.mcs for e in ok),
            "limit_db": best.evm_limit_db, "modulation": best.modulation, "code_rate": str(best.code_rate)}


def dmg_twin(waveform: str, mcs: int) -> float | None:
    """The DMG MCS with the same bits per symbol, code rate and repetition as
    EDMG ``mcs`` (assumed.ay_sensitivity): SC against dmg.sc_mcs (modulation
    order from the name, the repetition column), OFDM against dmg.ofdm_mcs
    (its n_bpsc column: EDMG's DCM BPSK / DCM QPSK carry 1 / 2 coded bits per
    subcarrier as 11ad's SQPSK / QPSK do — the names edmg.ofdm_mcs's note says
    they had before 18/1152r0).  None when the DMG tables have no such MCS
    (7/8, BPSK 3/4 … in OFDM, 64-QAM 1/2 …; the extended DMG MCS 9.1 / 12.1–12.6
    are left out: their modulation and code rate are not in spec_sources)."""
    e = mcs_entry(waveform, mcs)
    if waveform == "ay_sc":
        t = spec.value("dmg.sc_mcs")
        rep = t.get("repetition", [1] * len(t["mcs"]))
        for i, m in enumerate(t["mcs"]):
            if (_order_of(t["modulation"][i])[0] == e.order and Fraction(t["code_rate"][i]) == e.code_rate
                    and int(rep[i]) == e.repetition):
                return m
        return None
    t = spec.value("dmg.ofdm_mcs")
    bpsc = int(spec.value("edmg.ofdm_mcs")["n_bpsc"][[x.mcs for x in mcs_table(waveform)].index(e.mcs)])
    for i, m in enumerate(t["mcs"]):
        if int(t["n_bpsc"][i]) == bpsc and Fraction(t["code_rate"][i]) == e.code_rate:
            return m
    return None


def ideal_threshold_db(waveform: str, mcs: int, occupied_bw_hz: float,
                       keep_implementation_loss: bool = False) -> float | None:
    """The in-band SNR an ideal decoder needs for EDMG ``mcs``
    (assumed.ay_sensitivity): its DMG twin's minimum sensitivity
    (dmg.rx_sensitivity_dbm) less kT·B over ``occupied_bw_hz`` and the
    reference receiver's noise figure and implementation loss
    (dmg.sensitivity_assumptions).  ``keep_implementation_loss`` leaves the
    5 dB in — the sensitivity row: this library's floor already holds the
    impairments the loss stands for, so keeping it counts them twice.
    None without a twin."""
    twin = dmg_twin(waveform, mcs)
    if twin is None:
        return None
    sens = float(spec.ref(f"dmg.rx_sensitivity_dbm#dbm@mcs={twin}"))
    ref = spec.value("dmg.sensitivity_assumptions")
    loss = 0.0 if keep_implementation_loss else float(ref["implementation_loss_db"])
    return float(sens - KT_DBM_HZ - 10.0 * np.log10(float(occupied_bw_hz)) - float(ref["nf_db"]) - loss)


def chain_rate() -> dict:
    """The one sample rate both waveforms run on (assumed.ay_chain_rate)."""
    a = spec.value("assumed.ay_chain_rate")
    fs_o = float(spec.value("edmg.ofdm_params")["fs_hz"]) * int(a["ofdm_oversampling"])
    fs_s = float(spec.value("edmg.sc_params")["chip_rate_hz"]) * int(a["sc_samples_per_chip"])
    if abs(fs_o - fs_s) > 1.0:
        raise ValueError(f"assumed.ay_chain_rate gives {fs_o / 1e9:g} and {fs_s / 1e9:g} GS/s: not one chain")
    return {"fs_hz": fs_o, "ofdm_oversampling": int(a["ofdm_oversampling"]),
            "sc_samples_per_chip": int(a["sc_samples_per_chip"])}


__all__ = ["GIS", "WAVEFORMS", "AyMcs", "channel_spacing_hz", "channel_of", "ofdm_numerology", "sc_numerology",
           "mcs_table", "mcs_entry", "conformance_cap", "chain_rate", "dmg_twin", "ideal_threshold_db"]
