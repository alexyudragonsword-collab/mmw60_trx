"""Coded PER for the 802.11ay waveforms (milestone 3, section 9d): the data
field's LDPC on the SC payload and on every OFDM payload (DCM included),
decoded from the equaliser's output.

What is built here:

* the DMG / EDMG codes of 672 bits from spec_sources#33 (iron rule 5):
  ``dmg_code`` lifts dmg.ldpc_matrices (z = 42, rates 1/2, 5/8, 3/4, 13/16)
  through ``phy.ldpc.qc_code``; its rate 7/8 is the 13/16 codeword with the
  first 48 parity bits not sent (dmg.ldpc_r7_8_punctured, 624 bits, 546 of
  information; the receiver puts zero LLRs in their place).  ``edmg_code``
  is the same except at 7/8, where EDMG has its own 672-bit code
  (edmg.ldpc_672_r7_8, 588 bits of information, two shifted identities in
  most cells);
* whole codewords on the payload's bits (SC: ``ay.units`` blocks of 448
  chips; OFDM: the data tones of ``ay.units`` symbols, in order, symbol
  after symbol, data/spec: assumed.ay_ofdm_tone_order); bits that do not
  fill a codeword are random padding the receiver ignores;
* OFDM's DCM MCS (1-10) through ``ay.dcm``: the static pairing of
  edmg.ofdm_modulation_mapping (spec_sources#43), the pair's two tones
  demapped jointly;
* max-log LLRs from the equalised chips or tones (``phy.mapper.llr``,
  ``ay.dcm.llr``).  No per-chip / per-tone weighting: the SC MMSE gives
  every chip the same SINR, OFDM's zero forcing on a flat channel every tone
  the same, and the normalised min-sum decoder is blind to the LLRs' common
  scale;
* the packet error: any information bit of any codeword wrong.

Not built: the scrambler and the padding / shortening rules of
dmg.data_encoding / edmg.sc_encoding (the payload's bits are random, so the
scrambler changes nothing a PER can see; a whole number of codewords stands
in for the padding), the 1344-bit codewords (edmg.ldpc_1344_lifting), the dynamic DCM pairing
(fed back by the receiver) and the 16 / 64-QAM in-symbol interleaver (its
permutation is not in the public documents).

SC MCS 1 (repetition 2) goes through ``RepetitionCode``: dmg.data_encoding's
rho = 2 codeword (spec_sources#43, sc_rho2_codeword / sc_rho2_pn).
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache

import numpy as np

from .. import spec
from . import dcm as _dcm
from ..phy import ldpc as _ldpc
from ..phy.mapper import llr as _llr

#: the DMG base matrices of the 672-bit codes (spec_sources#33)
DMG_LDPC_KEY = "dmg.ldpc_matrices"
#: DMG's rate 7/8: the 13/16 codeword punctured
DMG_R7_8_KEY = "dmg.ldpc_r7_8_punctured"
#: EDMG's own 672-bit rate-7/8 code
EDMG_R7_8_KEY = "edmg.ldpc_672_r7_8"
#: the SC repetition (rho = 2) codeword and its PN sequence
DATA_ENCODING_KEY = "dmg.data_encoding"
#: the LLR a known bit (the rho = 2 codeword's zero padding) is decoded with
KNOWN_BIT_LLR = 1.0e9

_RATE_KEYS = {"1/2": "r1_2", "5/8": "r5_8", "3/4": "r3_4", "13/16": "r13_16"}


@dataclass(frozen=True)
class PuncturedCode:
    """A mother code whose transmitter leaves bits ``drop`` out and whose
    receiver puts zero LLRs (1 and 0 equally likely) in their place.  The
    information bits stay first, as in the mother code."""
    mother: _ldpc.LdpcCode
    drop: tuple[int, ...]

    @property
    def keep(self) -> np.ndarray:
        mask = np.ones(self.mother.n, dtype=bool)
        mask[list(self.drop)] = False
        return np.flatnonzero(mask)

    @property
    def n(self) -> int:
        return self.mother.n - len(self.drop)

    @property
    def k(self) -> int:
        return self.mother.k

    @property
    def rate(self) -> str:
        f = Fraction(self.k, self.n)
        return f"{f.numerator}/{f.denominator}"

    def encode(self, info: np.ndarray) -> np.ndarray:
        """(n_cw, k) information bits → (n_cw, n) bits sent."""
        return self.mother.encode(info)[:, self.keep]

    def decode(self, llr: np.ndarray, max_iter: int | None = None) -> tuple[np.ndarray, int]:
        """(n_cw, n) LLRs of the bits sent → ((n_cw, n) hard bits, iterations run)."""
        llr = np.asarray(llr, dtype=np.float64).reshape(-1, self.n)
        full = np.zeros((llr.shape[0], self.mother.n))
        full[:, self.keep] = llr
        bits, iters = self.mother.decode(full, max_iter=max_iter)
        return bits[:, self.keep], iters


@dataclass(frozen=True)
class RepetitionCode:
    """dmg.data_encoding's rho = 2 codeword (SC MCS 1; spec_sources#43's
    sc_rho2_codeword and sc_rho2_pn): L_Z = n / 4 data bits b, the rate-1/2
    mother code over (b, L_Z zeros), then the zeros replaced by b XOR PN.
    PN is the data scrambler's sequence (x^7 + x^4 + 1) from the all-ones
    state, reset for every codeword, so every codeword uses the same L_Z
    bits.  Sent: (b, b XOR PN, the mother's n / 2 parity bits).  The receiver
    adds the two copies' LLRs (the copy's sign flipped where PN is 1) and
    decodes the mother code with the zeros known."""
    mother: _ldpc.LdpcCode
    pn: tuple[int, ...]

    @property
    def k(self) -> int:
        return len(self.pn)

    @property
    def n(self) -> int:
        return self.mother.n

    @property
    def rate(self) -> str:
        f = Fraction(self.k, self.n)
        return f"{f.numerator}/{f.denominator}"

    def encode(self, info: np.ndarray) -> np.ndarray:
        """(n_cw, k) data bits → (n_cw, n) bits sent."""
        info = np.asarray(info, dtype=np.uint8).reshape(-1, self.k)
        word = self.mother.encode(np.concatenate([info, np.zeros_like(info)], axis=1))
        word[:, self.k:2 * self.k] = info ^ np.asarray(self.pn, dtype=np.uint8)[None, :]
        return word

    def decode(self, llr: np.ndarray, max_iter: int | None = None) -> tuple[np.ndarray, int]:
        """(n_cw, n) LLRs of the bits sent → ((n_cw, n) hard bits of the bits sent, iterations run)."""
        llr = np.asarray(llr, dtype=np.float64).reshape(-1, self.n)
        k = self.k
        pn = np.asarray(self.pn, dtype=np.uint8)
        full = llr.copy()
        full[:, :k] = llr[:, :k] + (1.0 - 2.0 * pn)[None, :] * llr[:, k:2 * k]
        full[:, k:2 * k] = KNOWN_BIT_LLR                      # the zeros, known (LLR > 0 is a 0)
        bits, iters = self.mother.decode(full, max_iter=max_iter)
        bits = bits.copy()
        bits[:, k:2 * k] = bits[:, :k] ^ pn[None, :]
        return bits, iters


@lru_cache(maxsize=None)
def rho2_code() -> RepetitionCode:
    """SC MCS 1's code: the 672-bit rate-1/2 code with dmg.data_encoding's
    rho = 2 construction (168 data bits a codeword, rate 1/4)."""
    from ..phy.scrambler import scrambling_sequence
    enc = spec.value(DATA_ENCODING_KEY)
    mother = dmg_code("1/2")
    l_z = int(enc["l_cw"]) // 4
    if "all ones" not in str(enc["sc_rho2_pn"]) or mother.k != 2 * l_z:
        raise ValueError(f"{DATA_ENCODING_KEY}: the rho = 2 rule is not the one this code builds")
    return RepetitionCode(mother, tuple(int(b) for b in scrambling_sequence(l_z, seed=0x7F)))


@lru_cache(maxsize=None)
def dmg_code(rate: str):
    """The DMG LDPC code of ``rate`` (dmg.ldpc_matrices; 7/8 = dmg.ldpc_r7_8_punctured)."""
    tab = spec.value(DMG_LDPC_KEY)
    if rate == "7/8":
        p = spec.value(DMG_R7_8_KEY)
        mother = dmg_code(str(p["base_rate"]))
        drop = tuple(range(mother.k, mother.k + int(p["punctured_parity_bits"])))
        code = PuncturedCode(mother, drop)
        if (code.n, code.k) != (int(p["codeword_bits"]), int(p["info_bits"])):
            raise ValueError(f"the punctured 7/8 code is ({code.n}, {code.k}), {DMG_R7_8_KEY} says "
                             f"({p['codeword_bits']}, {p['info_bits']})")
        return code
    if rate not in _RATE_KEYS:
        raise ValueError(f"DMG LDPC rates are {sorted(_RATE_KEYS, key=_frac)} and 7/8, not {rate!r}")
    code = _ldpc.qc_code(tab[_RATE_KEYS[rate]], int(tab["z"]), rate)
    if code.n != int(tab["n"]):
        raise ValueError(f"{DMG_LDPC_KEY} {rate}: {code.n} bits, the table says {tab['n']}")
    return code


@lru_cache(maxsize=None)
def edmg_code(rate: str):
    """The EDMG 672-bit code of ``rate``: DMG's, except EDMG's own 7/8
    (edmg.ldpc_672_r7_8)."""
    if rate != "7/8":
        return dmg_code(rate)
    t = spec.value(EDMG_R7_8_KEY)
    code = _ldpc.qc_code(t["rows"], int(t["z"]), "7/8")
    if code.n != int(t["n"]):
        raise ValueError(f"{EDMG_R7_8_KEY}: {code.n} bits, the table says {t['n']}")
    return code


def _frac(r: str) -> float:
    a, b = r.split("/")
    return int(a) / int(b)


def _check_coded(sim) -> None:
    """The payloads built here: every SC MCS (repetition 1 or 2) and every OFDM MCS."""
    if int(sim.mcs.repetition) not in (1, 2):
        raise NotImplementedError(f"repetition {sim.mcs.repetition} is not an EDMG procedure")


def _is_dcm(sim) -> bool:
    return sim.cfg.waveform == "ay_ofdm" and sim.mcs.modulation.startswith("DCM")


def ay_code(sim):
    """The code of ``sim``'s EDMG MCS (``edmg_code`` at its rate; the 672-bit
    codes are the EDMG PHY's, SC and OFDM alike)."""
    _check_coded(sim)
    return _code_for(sim.mcs)


def _code_for(e):
    """The code of an EDMG MCS entry: rho = 2 on its rate-1/2 code where it repeats, else edmg_code."""
    if int(e.repetition) == 2:
        return rho2_code()
    return edmg_code(f"{e.code_rate.numerator}/{e.code_rate.denominator}")


#: the SC-only name of ``ay_code`` (milestone 3, section 9d)
sc_code = ay_code


def payload_bits(sim) -> int:
    """The coded bits one packet of ``sim`` (an ``AyLinkSim``) carries: SC the
    data chips of every block, OFDM the data tones of every symbol."""
    _check_coded(sim)
    num = sim.phy.num
    per_unit = num.data_per_block if sim.cfg.waveform == "ay_sc" else len(num.data_tones)
    return int(per_unit * sim.n_symbols * np.log2(sim.mcs.order))


def codewords_for(packet_bytes: int, code) -> int:
    """The codewords a PSDU of ``packet_bytes`` takes (dmg.data_encoding's
    N_CW = ceil(Length·8 / (L_CW·R)) at repetition 1)."""
    return int(np.ceil(8 * int(packet_bytes) / code.k))


def coded_packet(sim, code, snr_db: float | None, rng: np.random.Generator,
                 max_iter: int | None = None, n_codewords: int | None = None) -> dict:
    """One coded packet through ``sim`` at an in-band SNR of ``snr_db``:
    ``{"packet_error", "bit_errors", "codewords", "iterations", "evm_db"}``.
    ``n_codewords`` (default: as many as the payload holds) codewords are
    sent; the rest of the payload is random padding.  SC's LLRs are not
    weighted per chip: its MMSE gives every chip the same SINR.  OFDM's are
    weighted per tone by |H|² of the channel estimate (``ay.ofdm_llr_weights``;
    until 2026-11-18 they were not, which is exact only for an exact estimate
    of a flat channel and cost up to 1 dB at the DCM BPSK thresholds)."""
    order = int(sim.mcs.order)
    n_bits = payload_bits(sim)
    n_cw = n_bits // code.n if n_codewords is None else int(n_codewords)
    if n_cw < 1 or n_cw * code.n > n_bits:
        raise ValueError(f"the payload ({n_bits} bits) does not hold {max(n_cw, 1)} {code.n}-bit codeword(s): "
                         "raise ay.units")
    info = rng.integers(0, 2, (n_cw, code.k), dtype=np.uint8)
    cw = code.encode(info).reshape(-1)
    bits = np.concatenate([cw, rng.integers(0, 2, n_bits - cw.size).astype(np.uint8)])
    ref, frame = sim.transmit(rng, bits=bits)
    y, _, _ = sim.impair(frame.x, rng, snr_db)
    res = sim.receive(y, ref, snr_db, keep_symbols=True)
    noise = 1.0 if snr_db is None else 10.0 ** (-float(snr_db) / 10.0)
    weight = 1.0 / noise
    eq = np.asarray(res.eq_symbols)
    if sim.cfg.waveform == "ay_ofdm" and sim.cfg.ay.ofdm_llr_weights == "estimate":
        # zero forcing leaves tone k the noise σ² / |H_k|²: the weight is |H_k|² of the estimate, on
        # the estimate's own scale.  With an exact estimate of a flat channel every tone gets the
        # same weight; with a noisy one a tone whose estimate came out small is told so, instead of
        # handing the decoder large, wrong LLRs on that tone in every symbol of the packet
        h2 = np.abs(np.asarray(sim.data_tone_estimate)) ** 2
        weight = np.broadcast_to(h2 / h2.mean() / noise, eq.shape)
    if _is_dcm(sim):   # the pair's two tones together (ay.dcm)
        llrs = _dcm.llr(eq, int(np.log2(order)), len(sim.phy.num.data_tones), weight)[:cw.size]
    else:
        llrs = _llr(eq.reshape(-1), order, np.reshape(weight, -1) if np.ndim(weight) else weight)[:cw.size]
    dec, iters = code.decode(llrs.reshape(n_cw, code.n), max_iter=max_iter)
    errors = int(np.count_nonzero(dec[:, :code.k] != info))
    return {"packet_error": errors > 0, "bit_errors": errors, "codewords": n_cw, "iterations": int(iters),
            "evm_db": float(res.evm_db)}


#: the SC-only name of ``coded_packet`` (milestone 3, section 9d)
coded_sc_packet = coded_packet


#: the channels a threshold is measured on: flat, or the preset's multipath (the CR stand-in)
THRESHOLD_CHANNELS = ("flat", "multipath")


def threshold_config(mcs: int, packet_bytes: int | None = None, waveform: str = "ay_sc", channel: str = "flat"):
    """The chain the EDMG thresholds are measured on: ``ay_60ghz`` ideal
    (no CFO, ideal LO and PA, converters / IQ / leakage off), flat channel,
    ``ay.units`` (SC blocks or OFDM symbols) just long enough for the
    codewords of a ``packet_bytes`` PSDU (default: the preset's
    ``phy.packet_bytes``, 4096).

    ``channel="multipath"`` keeps the same ideal chain and puts the
    preset's channel in place of the flat one: the CR stand-in (exponential
    PDP, assumed.cr_rms_delay_ns, assumed.cr_los_k_db), one realisation per
    packet.  The in-band SNR is still the received signal over the noise,
    packet by packet, so the threshold moves by what the frequency
    selectivity costs the equaliser and the code, not by a fading margin."""
    import dataclasses as dc

    from ..config import ChannelConfig, ay_60ghz
    from . import edmg
    if channel not in THRESHOLD_CHANNELS:
        raise ValueError(f"channel must be one of {THRESHOLD_CHANNELS}")
    preset = ay_60ghz(waveform, mcs)
    cfg = dc.replace(preset.ideal(), channel=ChannelConfig(model="flat") if channel == "flat" else preset.channel)
    if packet_bytes is not None:
        cfg = dc.replace(cfg, phy=dc.replace(cfg.phy, packet_bytes=int(packet_bytes)))
    e = edmg.mcs_entry(waveform, mcs)
    code = _code_for(e)
    if waveform == "ay_sc":
        per_unit = edmg.sc_numerology().data_per_block
    else:
        per_unit = len(edmg.ofdm_numerology(edmg.channel_of(cfg.carrier_hz)).data_tones)
    units = int(np.ceil(codewords_for(cfg.phy.packet_bytes, code) * code.n / (per_unit * np.log2(e.order))))
    return dc.replace(cfg, ay=dc.replace(cfg.ay, units=units))


def sweep_packet(sim, snr_db: float, rng: np.random.Generator) -> tuple[bool, float]:
    """``per_sweep``'s packet hook: one PSDU of ``phy.packet_bytes`` in
    ``ay_code(sim)``'s codewords."""
    code = ay_code(sim)
    r = coded_packet(sim, code, snr_db, rng, n_codewords=codewords_for(sim.cfg.phy.packet_bytes, code))
    return r["packet_error"], r["evm_db"]


def per(sim, code, snr_db: float, n_packets: int, rng: np.random.Generator,
        max_iter: int | None = None) -> float:
    """The packet error rate over ``n_packets`` coded packets."""
    return float(np.mean([coded_packet(sim, code, snr_db, rng, max_iter)["packet_error"]
                          for _ in range(int(n_packets))]))


__all__ = ["DMG_LDPC_KEY", "DMG_R7_8_KEY", "EDMG_R7_8_KEY", "DATA_ENCODING_KEY", "KNOWN_BIT_LLR", "PuncturedCode",
           "RepetitionCode", "rho2_code", "dmg_code", "edmg_code", "ay_code",
           "sc_code", "payload_bits", "codewords_for", "coded_packet", "coded_sc_packet", "threshold_config",
           "sweep_packet", "per"]
