"""Coded PER for the 802.11ay waveforms (milestone 3, section 9d): the data
field's LDPC on the single-carrier payload, decoded from the equaliser's
output.

What is built here:

* any quasi-cyclic code (``phy.ldpc.qc_code``: the 802.11 codes and the DMG /
  EDMG ones are lifted the same way, the latter from a 16-column base matrix
  with z = 42);
* whole codewords on the SC payload's bits (the payload is ``ay.units``
  blocks of 448 chips; bits that do not fill a codeword are random padding
  the receiver ignores);
* max-log LLRs from the equalised chips (``phy.mapper.llr``).  No per-chip
  weighting: the SC MMSE gives every chip the same SINR, and the normalised
  min-sum decoder is blind to the LLRs' common scale;
* the packet error: any information bit of any codeword wrong.

What waits for spec_sources#33 (iron rule 5): the DMG / EDMG LDPC base
matrices (``dmg_code``), the rate-7/8 puncturing, the scrambler and the
padding / shortening rules.  Until they are vendored ``dmg_code`` raises
``PendingSpec`` and no PER of an EDMG MCS is printed; the machinery is
checked with an 802.11 code standing in (``tests/test_ay_link.py``).  The
key name is a placeholder until spec_sources names it.  Not built: the coded
OFDM payload (DCM pairs, tone mapping).
"""
from __future__ import annotations

import numpy as np

from .. import spec
from ..phy import ldpc as _ldpc
from ..phy.mapper import llr as _llr

#: where the DMG / EDMG base matrices are expected (requested in spec_sources#33)
DMG_LDPC_KEY = "dmg.ldpc_base_matrices"


class PendingSpec(LookupError):
    """A spec number this library asked spec_sources for has not arrived."""


def dmg_code(rate: str) -> _ldpc.LdpcCode:
    """The DMG / EDMG LDPC code of ``rate`` (codeword 672 bits), from the
    base matrices spec_sources#33 is asked for; ``PendingSpec`` until then."""
    if DMG_LDPC_KEY not in spec.all_entries():
        raise PendingSpec(f"the DMG / EDMG LDPC base matrices are not in spec_sources yet ({DMG_LDPC_KEY!r}, "
                          "requested in spec_sources#33)")
    tab = spec.value(DMG_LDPC_KEY)
    return _ldpc.qc_code(tab[rate], int(tab["z"]), rate)


def payload_bits(sim) -> int:
    """The coded bits one SC packet of ``sim`` (an ``AyLinkSim``) carries."""
    if sim.cfg.waveform != "ay_sc":
        raise NotImplementedError("a coded OFDM payload (DCM, tone mapping) is not built: SC only")
    return int(sim.phy.num.data_per_block * sim.n_symbols * np.log2(sim.mcs.order))


def coded_sc_packet(sim, code: _ldpc.LdpcCode, snr_db: float | None, rng: np.random.Generator,
                    max_iter: int | None = None) -> dict:
    """One coded SC packet through ``sim`` at an in-band SNR of ``snr_db``:
    ``{"packet_error", "bit_errors", "codewords", "iterations", "evm_db"}``."""
    order = int(sim.mcs.order)
    n_bits = payload_bits(sim)
    n_cw = n_bits // code.n
    if n_cw < 1:
        raise ValueError(f"the payload ({n_bits} bits) holds no {code.n}-bit codeword: raise ay.units")
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


def per(sim, code: _ldpc.LdpcCode, snr_db: float, n_packets: int, rng: np.random.Generator,
        max_iter: int | None = None) -> float:
    """The packet error rate over ``n_packets`` coded SC packets."""
    return float(np.mean([coded_sc_packet(sim, code, snr_db, rng, max_iter)["packet_error"]
                          for _ in range(int(n_packets))]))


__all__ = ["DMG_LDPC_KEY", "PendingSpec", "dmg_code", "payload_bits", "coded_sc_packet", "per"]
