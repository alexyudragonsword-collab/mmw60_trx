"""Coded PER for the 802.11ay waveforms (milestone 3, section 9d): the data
field's LDPC on the single-carrier payload, decoded from the equaliser's
output.

What is built here:

* the DMG / EDMG codes of 672 bits from spec_sources#33 (iron rule 5):
  ``dmg_code`` lifts dmg.ldpc_matrices (z = 42, rates 1/2, 5/8, 3/4, 13/16)
  through ``phy.ldpc.qc_code``; its rate 7/8 is the 13/16 codeword with the
  first 48 parity bits not sent (dmg.ldpc_r7_8_punctured, 624 bits, 546 of
  information; the receiver puts zero LLRs in their place).  ``edmg_code``
  is the same except at 7/8, where EDMG has its own 672-bit code
  (edmg.ldpc_672_r7_8, 588 bits of information, two shifted identities in
  most cells);
* whole codewords on the SC payload's bits (the payload is ``ay.units``
  blocks of 448 chips; bits that do not fill a codeword are random padding
  the receiver ignores);
* max-log LLRs from the equalised chips (``phy.mapper.llr``).  No per-chip
  weighting: the SC MMSE gives every chip the same SINR, and the normalised
  min-sum decoder is blind to the LLRs' common scale;
* the packet error: any information bit of any codeword wrong.

Not built: the scrambler and the padding / shortening rules of
dmg.data_encoding / edmg.sc_encoding (the payload's bits are random, so the
scrambler changes nothing a PER can see; a whole number of codewords stands
in for the padding), the repetition (rho = 2, the MCS 1 procedure: zeros,
then the parity's second half replaced by the data XOR a PN sequence), the
1344-bit codewords (edmg.ldpc_1344_lifting) and the coded OFDM payload (DCM
pairs, tone mapping).
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache

import numpy as np

from .. import spec
from ..phy import ldpc as _ldpc
from ..phy.mapper import llr as _llr

#: the DMG base matrices of the 672-bit codes (spec_sources#33)
DMG_LDPC_KEY = "dmg.ldpc_matrices"
#: DMG's rate 7/8: the 13/16 codeword punctured
DMG_R7_8_KEY = "dmg.ldpc_r7_8_punctured"
#: EDMG's own 672-bit rate-7/8 code
EDMG_R7_8_KEY = "edmg.ldpc_672_r7_8"

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
    """The payloads built here: SC at repetition 1, OFDM without DCM."""
    m = sim.mcs
    if int(m.repetition) != 1:
        raise NotImplementedError("the repetition procedure (rho = 2, dmg.data_encoding) is not built")
    if sim.cfg.waveform == "ay_ofdm" and m.modulation.startswith("DCM"):
        raise NotImplementedError("a coded DCM payload is not built: the DCM pairing is not in spec_sources")


def ay_code(sim):
    """The code of ``sim``'s EDMG MCS (``edmg_code`` at its rate; the 672-bit
    codes are the EDMG PHY's, SC and OFDM alike)."""
    _check_coded(sim)
    r = sim.mcs.code_rate
    return edmg_code(f"{r.numerator}/{r.denominator}")


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
    sent; the rest of the payload is random padding.  The LLRs are not
    weighted per chip or tone: the SC MMSE gives every chip the same SINR,
    and on a flat channel OFDM's zero forcing gives every tone the same;
    under multipath OFDM would need per-tone weights (not built)."""
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
    llrs = _llr(np.asarray(res.eq_symbols).reshape(-1), order, 1.0 / noise)[:cw.size]
    dec, iters = code.decode(llrs.reshape(n_cw, code.n), max_iter=max_iter)
    errors = int(np.count_nonzero(dec[:, :code.k] != info))
    return {"packet_error": errors > 0, "bit_errors": errors, "codewords": n_cw, "iterations": int(iters),
            "evm_db": float(res.evm_db)}


#: the SC-only name of ``coded_packet`` (milestone 3, section 9d)
coded_sc_packet = coded_packet


def threshold_config(mcs: int, packet_bytes: int | None = None, waveform: str = "ay_sc"):
    """The chain the EDMG thresholds are measured on: ``ay_60ghz`` ideal
    (no CFO, ideal LO and PA, converters / IQ / leakage off), flat channel,
    ``ay.units`` (SC blocks or OFDM symbols) just long enough for the
    codewords of a ``packet_bytes`` PSDU (default: the preset's
    ``phy.packet_bytes``, 4096)."""
    import dataclasses as dc

    from ..config import ChannelConfig, ay_60ghz
    from . import edmg
    cfg = dc.replace(ay_60ghz(waveform, mcs).ideal(), channel=ChannelConfig(model="flat"))
    if packet_bytes is not None:
        cfg = dc.replace(cfg, phy=dc.replace(cfg.phy, packet_bytes=int(packet_bytes)))
    e = edmg.mcs_entry(waveform, mcs)
    code = edmg_code(f"{e.code_rate.numerator}/{e.code_rate.denominator}")
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


__all__ = ["DMG_LDPC_KEY", "DMG_R7_8_KEY", "EDMG_R7_8_KEY", "PuncturedCode", "dmg_code", "edmg_code", "ay_code",
           "sc_code", "payload_bits", "codewords_for", "coded_packet", "coded_sc_packet", "threshold_config",
           "sweep_packet", "per"]
