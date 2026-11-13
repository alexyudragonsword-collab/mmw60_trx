"""The 802.11be (EHT) coded data field for the 11be bases: LDPC PPDU encoding
(codeword length / count, shortening, puncturing, repetition), the LDPC tone
mapper and the segment parser, QAM up to 4096 points — so a PER can be
measured on 20 / 40 / 80 / 160 / 320 MHz × K like the VHT 20 MHz base.

What is modelled, and from where (all ``source: survey`` — the standard's
text is not in this repository):

- MCS 0 … 13 (modulation, N_BPSCS, R): wifitrx's reviewed ``link/mcs.py``
  table; N_SD per bandwidth ``ieee80211be.n_sd`` (234 / 468 / 980 / 1960 /
  3920 — the 242 / 484 / 996 / 2×996 / 4×996-tone RUs less their pilots,
  which wifitrx's 78.125 kHz pilot table places);
- the LDPC PPDU encoding process of 802.11-2020 §19.3.11.7.5 (shared by
  11n / ac / ax / be), its thresholds in
  ``ieee80211.ldpc_ppdu_encoding_thresholds``, pre-FEC padding to whole
  symbols (``assumed.eht_prefec_padding``: the HT/VHT form, no a-factor and
  no packet extension — PER does not see them);
- the LDPC tone mapper, distance D_TM per RU (``ieee80211be.ldpc_tone_mapping_distance``:
  9 / 12 / 20), applied per 996-tone segment on 160 / 320 MHz after the
  segment parser (blocks of s = max(1, N_BPSCS/2) bits round-robin);
- the 7-bit scrambler of the VHT path (EHT's is 11-bit; the PER is
  indifferent to the scrambling sequence).

Not modelled: MU-RU, punctured 320 MHz, DCM, multiple streams, the EHT-SIG /
U-SIG fields (the preamble is the library's L-STF / L-LTF).
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

import numpy as np

from .. import spec
from ..vendor.wifitrx.link.mcs import MCS_TABLE
from . import ldpc, mapper, scrambler
from .mcs import N_SERVICE

N_SEGMENTS = {20e6: 1, 40e6: 1, 80e6: 1, 160e6: 2, 320e6: 4}


@dataclass(frozen=True)
class EhtMcs:
    index: int
    modulation: str
    qam_order: int
    rate: Fraction
    bandwidth_hz: float
    n_sd: int

    @property
    def n_bpscs(self) -> int:
        return int(round(np.log2(self.qam_order)))

    @property
    def n_cbps(self) -> int:
        return self.n_sd * self.n_bpscs

    @property
    def n_dbps_exact(self) -> Fraction:
        """N_SD · N_BPSCS · R.  Not an integer for MCS 9 / 11 on the 996-tone
        RUs (980 · 8 · 5/6 = 6533⅓): the standard carries the fraction and
        the LDPC pre-FEC padding absorbs it (``ldpc_encoding_params``)."""
        return Fraction(self.n_cbps) * self.rate

    @property
    def n_dbps(self) -> float:
        return float(self.n_dbps_exact)

    @property
    def rate_str(self) -> str:
        return f"{self.rate.numerator}/{self.rate.denominator}"

    @property
    def n_segments(self) -> int:
        return N_SEGMENTS[float(self.bandwidth_hz)]

    @property
    def n_sd_segment(self) -> int:
        return self.n_sd // self.n_segments

    @property
    def d_tm(self) -> int:
        return int(spec.value("ieee80211be.ldpc_tone_mapping_distance")[float(self.bandwidth_hz)])

    def n_symbols(self, psdu_bytes: int) -> int:
        return ldpc_encoding_params(N_SERVICE + 8 * int(psdu_bytes), self).n_sym

    def data_rate_bps(self, t_symbol_s: float) -> float:
        return float(self.n_dbps_exact) / t_symbol_s


def eht_mcs(index: int, bandwidth_hz: float) -> EhtMcs:
    bw = float(bandwidth_hz)
    table = spec.value("ieee80211be.n_sd")
    if bw not in table:
        raise ValueError(f"11be bandwidth must be one of {sorted(table)} Hz, got {bw}")
    if not 0 <= int(index) <= 13:
        raise ValueError(f"EHT MCS must be 0 … 13, got {index}")
    row = MCS_TABLE[int(index)]
    num, den = (int(v) for v in row.coding_rate.split("/"))
    return EhtMcs(index=int(index), modulation=row.modulation, qam_order=2 ** row.bits_per_symbol,
                  rate=Fraction(num, den), bandwidth_hz=bw, n_sd=int(table[bw]))


# ---------------------------------------------------------------- LDPC PPDU encoding process
@dataclass(frozen=True)
class LdpcParams:
    n_pld: int                 # payload bits after pre-FEC padding (= n_sym × N_DBPS)
    n_sym: int
    n_avbits: int              # coded bits available (= n_sym × N_CBPS)
    n_cw: int
    l_ldpc: int
    n_shrt: int
    n_punc: int
    n_rep: int
    extra_symbol: bool

    def per_codeword(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(shortening, puncturing, repetition) bits per codeword — the
        floor share to every codeword, one more to the first remainder ones."""
        def spread(total):
            base, rem = divmod(int(total), self.n_cw)
            return np.array([base + (1 if i < rem else 0) for i in range(self.n_cw)])
        return spread(self.n_shrt), spread(self.n_punc), spread(self.n_rep)


def ldpc_encoding_params(n_payload_bits: int, mcs: EhtMcs) -> LdpcParams:
    """§19.3.11.7.5 steps (a)–(e) for ``n_payload_bits`` (SERVICE + PSDU)."""
    th = spec.value("ieee80211.ldpc_ppdu_encoding_thresholds")
    r = float(mcs.rate)
    d = mcs.n_dbps_exact
    n_sym = -(-Fraction(int(n_payload_bits)) // d)              # ceil(bits / N_DBPS)
    n_sym = int(n_sym)
    n_pld = int(n_sym * d)                                      # floor: whole payload bits in those symbols
    n_av = n_sym * mcs.n_cbps
    if n_av <= 648:
        n_cw, length = 1, (1296 if n_av >= n_pld + th["l1296_over_648"] * (1 - r) else 648)
    elif n_av <= 1296:
        n_cw, length = 1, (1944 if n_av >= n_pld + th["l1944_over_1296"] * (1 - r) else 1296)
    elif n_av <= 1944:
        n_cw, length = 1, 1944
    elif n_av <= 2592:
        n_cw, length = 2, (1944 if n_av >= n_pld + th["l1944_over_1296_two_cw"] * (1 - r) else 1296)
    else:
        n_cw, length = -(-n_pld // int(round(1944 * r))), 1944
    k = int(round(length * r))
    n_shrt = max(0, n_cw * k - n_pld)
    n_punc = max(0, n_cw * length - n_av - n_shrt)
    extra = False
    parity = n_cw * (length - k)
    if (n_punc > th["punc_frac_a"] * parity and n_shrt < th["shrt_ratio_b"] * n_punc * r / (1 - r)) \
            or n_punc > th["punc_frac_c"] * parity:
        n_av += mcs.n_cbps
        n_sym += 1
        n_punc = max(0, n_cw * length - n_av - n_shrt)
        extra = True
    n_rep = max(0, n_av - n_cw * (length - k) - n_pld)
    return LdpcParams(n_pld=n_pld, n_sym=n_sym, n_avbits=n_av, n_cw=n_cw, l_ldpc=length, n_shrt=n_shrt,
                      n_punc=n_punc, n_rep=n_rep, extra_symbol=extra)


def ldpc_encode_payload(bits: np.ndarray, p: LdpcParams, c: ldpc.LdpcCode) -> np.ndarray:
    """Payload bits (n_pld) → coded bits (n_avbits): per codeword shorten,
    encode, drop the shortened zeros, puncture the last parity bits, repeat
    the first bits."""
    bits = np.asarray(bits, dtype=np.uint8)
    assert bits.size == p.n_pld, (bits.size, p.n_pld)
    shrt, punc, rep = p.per_codeword()
    k = c.k
    out = []
    pos = 0
    for i in range(p.n_cw):
        n_info = k - int(shrt[i])
        info = np.zeros(k, dtype=np.uint8)
        info[:n_info] = bits[pos:pos + n_info]
        pos += n_info
        cw = c.encode(info)[0]
        cw = np.concatenate([cw[:n_info], cw[k:]])               # drop the shortened zeros
        if punc[i]:
            cw = cw[:cw.size - int(punc[i])]
        if rep[i]:
            cw = np.concatenate([cw, cw[:int(rep[i])]])
        out.append(cw)
    coded = np.concatenate(out)
    assert coded.size == p.n_avbits, (coded.size, p.n_avbits)
    return coded


def ldpc_decode_payload(llr: np.ndarray, p: LdpcParams, c: ldpc.LdpcCode, max_iter=None, alpha=None,
                        kernel: str | None = None) -> tuple[np.ndarray, int]:
    """Coded LLRs (n_avbits) → payload bits (n_pld); shortened bits enter
    as known zeros, punctured as erasures, repeated copies are summed."""
    llr = np.asarray(llr, dtype=float)
    shrt, punc, rep = p.per_codeword()
    k, n = c.k, c.n
    full = np.zeros((p.n_cw, n))
    pos = 0
    for i in range(p.n_cw):
        n_info = k - int(shrt[i])
        n_par = (n - k) - int(punc[i])
        seg = llr[pos:pos + n_info + n_par + int(rep[i])]
        pos += seg.size
        full[i, :n_info] = seg[:n_info]
        full[i, n_info:k] = ldpc.KNOWN_LLR
        full[i, k:k + n_par] = seg[n_info:n_info + n_par]
        if rep[i]:
            full[i, :int(rep[i])] += seg[n_info + n_par:]
    hard, iters = c.decode(full, max_iter=max_iter, alpha=alpha, kernel=kernel)
    out = np.concatenate([hard[i, :k - int(shrt[i])] for i in range(p.n_cw)])
    return out.astype(np.uint8), iters


# ---------------------------------------------------------------- tone mapper and segment parser
def tone_mapper_permutation(n_sd_segment: int, d_tm: int) -> np.ndarray:
    """perm[k] = data tone of the k-th constellation point in a segment:
    t = D_TM · (k mod N_SD/D_TM) + floor(k · D_TM / N_SD)."""
    if n_sd_segment % d_tm:
        raise ValueError(f"N_SD {n_sd_segment} is not a multiple of D_TM {d_tm}")
    k = np.arange(n_sd_segment)
    t = d_tm * (k % (n_sd_segment // d_tm)) + (k * d_tm) // n_sd_segment
    if np.unique(t).size != n_sd_segment:
        raise AssertionError("tone mapper is not a bijection")
    return t


def segment_parser_permutation(n_cbps: int, n_bpscs: int, n_segments: int) -> np.ndarray:
    """perm[b] = position of coded bit b in the concatenation of the
    segments' bit streams (segment j occupies [j·n_cbps/n_seg, (j+1)·…)):
    blocks of s = max(1, N_BPSCS/2) bits go to the segments in turn."""
    if n_segments == 1:
        return np.arange(n_cbps)
    s = max(1, n_bpscs // 2)
    per_seg = n_cbps // n_segments
    b = np.arange(n_cbps)
    blk = b // s
    seg = blk % n_segments
    within = (blk // n_segments) * s + b % s
    perm = seg * per_seg + within
    if np.unique(perm).size != n_cbps:
        raise AssertionError("segment parser is not a bijection")
    return perm


def symbol_point_permutation(mcs: EhtMcs) -> np.ndarray:
    """perm[q] = data-tone column (0 … N_SD−1, increasing frequency) of the
    q-th constellation point of a symbol after segment parsing and tone
    mapping; the data columns are split into contiguous segments."""
    n_sd_seg = mcs.n_sd_segment
    tm = tone_mapper_permutation(n_sd_seg, mcs.d_tm)
    q = np.arange(mcs.n_sd)
    seg = q // n_sd_seg
    return seg * n_sd_seg + tm[q % n_sd_seg]


# ---------------------------------------------------------------- the data field
@dataclass(frozen=True)
class EhtDataField:
    mcs: EhtMcs
    params: LdpcParams
    psdu: np.ndarray
    tx_bits: np.ndarray           # scrambled payload (SERVICE + PSDU + pad), n_pld
    symbols: np.ndarray           # (n_symbols, n_active) incl. pilots
    data_cols: np.ndarray
    pilot_cols: np.ndarray
    pilots: np.ndarray
    scrambler_seed: int

    @property
    def n_symbols(self) -> int:
        return int(self.symbols.shape[0])

    @property
    def psdu_bytes(self) -> int:
        return int(self.psdu.size // 8)

    def decode(self, eq_symbols: np.ndarray, weight=1.0, kernel: str | None = None,
               max_iter=None, alpha=None) -> tuple[np.ndarray, int]:
        return decode_eht_data_field(eq_symbols, self, weight, kernel, max_iter, alpha)


def build_eht_data_field(mcs: EhtMcs, psdu_bits: np.ndarray, n_active: int, pilot_cols: np.ndarray,
                         pilots: np.ndarray, scrambler_seed: int = scrambler.DEFAULT_SEED) -> EhtDataField:
    psdu_bits = np.asarray(psdu_bits, dtype=np.uint8)
    pilot_cols = np.asarray(pilot_cols, dtype=int)
    data_cols = np.setdiff1d(np.arange(n_active), pilot_cols)
    if data_cols.size != mcs.n_sd:
        raise ValueError(f"{data_cols.size} data tones in the plan, the 11be table expects {mcs.n_sd}")
    p = ldpc_encoding_params(N_SERVICE + psdu_bits.size, mcs)
    bits = np.zeros(p.n_pld, dtype=np.uint8)
    bits[N_SERVICE:N_SERVICE + psdu_bits.size] = psdu_bits
    tx_bits = scrambler.scramble(bits, scrambler_seed)
    c = ldpc.code(p.l_ldpc, mcs.rate_str)
    coded = ldpc_encode_payload(tx_bits, p, c).reshape(p.n_sym, mcs.n_cbps)
    sp = segment_parser_permutation(mcs.n_cbps, mcs.n_bpscs, mcs.n_segments)
    parsed = np.empty_like(coded)
    parsed[:, sp] = coded
    pts = mapper.map_bits(parsed.reshape(-1), mcs.qam_order).reshape(p.n_sym, mcs.n_sd)
    perm = symbol_point_permutation(mcs)
    pilots = np.asarray(pilots, dtype=complex)
    if pilots.shape != (p.n_sym, pilot_cols.size):
        raise ValueError(f"pilots must be ({p.n_sym}, {pilot_cols.size}), got {pilots.shape}")
    symbols = np.empty((p.n_sym, n_active), dtype=complex)
    symbols[:, data_cols[perm]] = pts
    symbols[:, pilot_cols] = pilots
    return EhtDataField(mcs=mcs, params=p, psdu=psdu_bits, tx_bits=tx_bits, symbols=symbols,
                        data_cols=data_cols, pilot_cols=pilot_cols, pilots=pilots, scrambler_seed=scrambler_seed)


def decode_eht_data_field(eq_symbols: np.ndarray, field: EhtDataField, weight=1.0,
                          kernel: str | None = None, max_iter=None, alpha=None) -> tuple[np.ndarray, int]:
    """Equalised (n_symbols, n_active) points → (decoded PSDU bits, bit errors);
    ``weight`` per data tone (length N_SD, |H|²) or scalar."""
    mcs, p = field.mcs, field.params
    perm = symbol_point_permutation(mcs)
    y = np.asarray(eq_symbols, dtype=complex)[:, field.data_cols[perm]]     # (n_sym, n_sd) in point order
    n_sym = y.shape[0]
    w = np.asarray(weight, dtype=float)
    if w.ndim:
        w = np.broadcast_to(w.reshape(-1)[perm][None, :], (n_sym, mcs.n_sd)).reshape(-1)
    soft = mapper.llr(y.reshape(-1), mcs.qam_order, w).reshape(n_sym, mcs.n_cbps)
    sp = segment_parser_permutation(mcs.n_cbps, mcs.n_bpscs, mcs.n_segments)
    llr_coded = soft[:, sp].reshape(-1)
    c = ldpc.code(p.l_ldpc, mcs.rate_str)
    dec, _ = ldpc_decode_payload(llr_coded, p, c, max_iter, alpha, kernel)
    desc = scrambler.descramble(dec, field.scrambler_seed)
    psdu_hat = desc[N_SERVICE:N_SERVICE + field.psdu.size]
    errors = int(np.count_nonzero(psdu_hat != field.psdu))
    return psdu_hat, errors


def ldpc_decoder_ops_per_info_bit(rate_str: str, l_ldpc: int = 1944, iterations: int | None = None) -> float:
    """Bookkeeping for the power column: add-equivalent operations per
    information bit of a normalised min-sum decoder — two per edge per
    iteration (one check-node compare / min, one variable-node add)."""
    c = ldpc.code(l_ldpc, rate_str)
    it = int(spec.value("assumed.ldpc_max_iterations")) if iterations is None else int(iterations)
    return it * c.n_edges * 2 / c.k
