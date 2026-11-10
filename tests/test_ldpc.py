"""The 802.11 LDPC codes: the base-matrix file and its structure, encoder
validity, the decoder's two kernels (bit-identical), and the PPDU encoding
process of the 11be data field."""
from fractions import Fraction

import numpy as np
import pytest

from mmw60 import spec
from mmw60.phy import eht, ldpc, mapper, scrambler
from mmw60.phy.ppdu import random_psdu

CODES = [(n, r) for n in ldpc.LENGTHS for r in ldpc.RATES]


def test_base_matrix_file_is_tagged_and_structured_like_80211():
    doc = spec.ldpc_document()
    assert doc["source"] == "survey" and "未核实" in doc["note"]
    assert "simgunz" in doc["cite"] and "tavildar" in doc["cite"]
    mats = spec.ldpc_base_matrices()
    assert set(mats) == {648, 1296, 1944}
    for n, by_rate in mats.items():
        assert set(by_rate) == set(ldpc.RATES)
        z = n // 24
        for r, rows in by_rate.items():
            a = np.asarray(rows)
            m_b = {"1/2": 12, "2/3": 8, "3/4": 6, "5/6": 4}[r]
            assert a.shape == (m_b, 24) and a.max() < z and a.min() == -1
            kb = 24 - m_b
            col = a[:, kb]
            nz = np.flatnonzero(col >= 0)
            # the 802.11 parity structure: first parity column 1 / 0 / 1 at
            # top / middle / bottom, then a dual diagonal of zeros
            assert nz.tolist()[0] == 0 and nz.tolist()[-1] == m_b - 1 and nz.size == 3
            assert col[0] == 1 and col[-1] == 1 and col[nz[1]] == 0
            for i in range(m_b - 1):
                assert a[i, kb + 1 + i] == 0 and (i == 0 or a[i, kb + i] == 0)


@pytest.mark.parametrize("n,rate", CODES, ids=[f"{n}-{r}" for n, r in CODES])
def test_every_code_encodes_to_valid_codewords(n, rate):
    c = ldpc.code(n, rate)
    assert c.n == n and c.k == int(round(n * ldpc.rate_fraction(rate))) and c.m == n - c.k
    assert c.n_edges == int((c.base >= 0).sum()) * c.z
    rng = np.random.default_rng(n + len(rate))
    info = rng.integers(0, 2, (4, c.k)).astype(np.uint8)
    cw = c.encode(info)
    assert cw.shape == (4, n) and np.array_equal(cw[:, :c.k], info)
    assert not c.syndrome(cw).any()
    bad = cw.copy()
    bad[0, 5] ^= 1
    assert c.syndrome(bad)[0].any() and not c.syndrome(bad)[1:].any()


def test_decoder_corrects_noise_and_the_kernels_are_bit_identical():
    rng = np.random.default_rng(7)
    for n, rate in ((648, "1/2"), (1944, "3/4"), (1944, "5/6")):
        c = ldpc.code(n, rate)
        cw = c.encode(rng.integers(0, 2, (3, c.k)).astype(np.uint8))
        sigma = {"1/2": 1.2, "3/4": 0.9, "5/6": 0.8}[rate]
        llr = (1 - 2.0 * cw) * 2.0 + rng.standard_normal(cw.shape) * sigma
        assert ((llr < 0) != cw).sum() > 20                       # the channel really flipped bits
        b_np, it_np = c.decode(llr, kernel="numpy")
        assert np.array_equal(b_np, cw), (n, rate)
        assert 1 <= it_np <= 30
        if ldpc.active_kernel() == "numba":
            b_nb, it_nb = c.decode(llr, kernel="numba")
            assert np.array_equal(b_np, b_nb) and it_np == it_nb
        else:
            with pytest.raises(RuntimeError):
                c.decode(llr, kernel="numba")
    # a hopeless input stops at the iteration cap and still returns hard decisions
    c = ldpc.code(648, "1/2")
    noise = rng.standard_normal((2, 648))
    b, it = c.decode(noise, max_iter=5, kernel="numpy")
    assert it == 5 and b.shape == (2, 648)
    with pytest.raises(ValueError):
        ldpc.code(1000, "1/2")


def test_kernels_identical_on_random_llrs_including_known_bit_magnitudes():
    if ldpc.active_kernel() != "numba":
        pytest.skip("numba not available: only the numpy kernel runs here")
    rng = np.random.default_rng(8)
    c = ldpc.code(1296, "2/3")
    llr = rng.standard_normal((5, c.n)) * 3.0
    llr[:, 100:160] = ldpc.KNOWN_LLR
    llr[:, 900:905] = 0.0
    a = c.decode(llr, max_iter=12, kernel="numpy")
    b = c.decode(llr, max_iter=12, kernel="numba")
    assert np.array_equal(a[0], b[0]) and a[1] == b[1]


# ---------------------------------------------------------------- the 11be data field
def test_eht_mcs_table_is_self_consistent_and_sized_by_bandwidth():
    fractional = set()
    for bw, n_sd in ((20e6, 234), (40e6, 468), (80e6, 980), (160e6, 1960), (320e6, 3920)):
        for i in range(14):
            m = eht.eht_mcs(i, bw)
            assert m.n_sd == n_sd and m.n_cbps == n_sd * m.n_bpscs
            assert m.n_dbps_exact == Fraction(m.n_cbps) * m.rate
            if m.n_dbps_exact.denominator != 1:
                fractional.add((bw, i))
            assert m.n_sd_segment % m.d_tm == 0
    # 980 · 8 · 5/6 and 980 · 10 · 5/6 are not integers: the standard's own fractional N_DBPS
    assert fractional == {(bw, i) for bw in (80e6, 160e6, 320e6) for i in (9, 11)}
    assert eht.eht_mcs(0, 80e6).n_dbps == 490 and eht.eht_mcs(13, 80e6).n_dbps == 9800
    p9 = eht.ldpc_encoding_params(16 + 8 * 4096, eht.eht_mcs(9, 80e6))
    assert p9.n_pld <= p9.n_sym * 6533.4 and p9.n_pld >= 16 + 8 * 4096 and p9.n_avbits == p9.n_sym * 7840
    assert eht.eht_mcs(13, 320e6).qam_order == 4096 and eht.eht_mcs(13, 320e6).n_segments == 4
    with pytest.raises(ValueError):
        eht.eht_mcs(14, 80e6)
    with pytest.raises(ValueError):
        eht.eht_mcs(0, 60e6)


def test_ldpc_ppdu_encoding_process_picks_length_shortening_and_puncturing():
    m = eht.eht_mcs(0, 80e6)
    p = eht.ldpc_encoding_params(16 + 8 * 4096, m)
    assert p.n_sym == 67 and p.n_pld == 67 * 490 and p.n_avbits == 67 * 980
    assert p.l_ldpc == 1944 and p.n_cw == -(-p.n_pld // 972) == 34
    assert p.n_shrt == 34 * 972 - p.n_pld and p.n_punc == 34 * 1944 - p.n_avbits - p.n_shrt and p.n_rep == 0
    shrt, punc, rep = p.per_codeword()
    assert shrt.sum() == p.n_shrt and punc.sum() == p.n_punc and shrt.max() - shrt.min() <= 1
    # small payloads take the short codes
    tiny = eht.eht_mcs(0, 20e6)
    # 96 bits → 1 symbol of 117 → 234 avbits → 648 code, 207 shortened, 207 punctured: more than
    # 10 % of the parity with little shortening, so step (d) adds a symbol and repeats instead
    p1 = eht.ldpc_encoding_params(16 + 8 * 10, tiny)
    assert p1.n_cw == 1 and p1.l_ldpc == 648 and p1.n_sym == 2 and p1.extra_symbol
    assert p1.n_shrt == 207 and p1.n_punc == 0 and p1.n_rep == 27
    p2 = eht.ldpc_encoding_params(16 + 8 * 100, tiny)         # 816 bits → 7 symbols → 1638 avbits
    assert p2.n_cw == 1 and p2.l_ldpc == 1944
    # the repetition branch: many available bits, little payload — 32 bits in a
    # 1960-bit symbol: 3 codewords, 956 shortened and 956 punctured, which step
    # (d) refuses (> 10 % of the parity, too little shortening): one more symbol,
    # no puncturing, 2964 repeated bits
    m6 = eht.eht_mcs(0, 320e6)                                # N_DBPS 1960, N_CBPS 3920
    p3 = eht.ldpc_encoding_params(16 + 8 * 2, m6)
    assert p3.n_sym == 2 and p3.extra_symbol and p3.n_cw == 3 and p3.n_shrt == 956
    assert p3.n_punc == 0 and p3.n_rep == 7840 - 3 * 972 - 1960
    rng = np.random.default_rng(1)
    for params, mcs in ((p, m), (p1, tiny), (p3, m6)):
        c = ldpc.code(params.l_ldpc, mcs.rate_str)
        bits = rng.integers(0, 2, params.n_pld).astype(np.uint8)
        coded = eht.ldpc_encode_payload(bits, params, c)
        assert coded.size == params.n_avbits
        back, _ = eht.ldpc_decode_payload((1 - 2.0 * coded) * 4.0, params, c, kernel="numpy")
        assert np.array_equal(back, bits)


def test_tone_mapper_and_segment_parser_are_bijections():
    for n_sd, d in ((234, 9), (468, 12), (980, 20)):
        t = eht.tone_mapper_permutation(n_sd, d)
        assert np.array_equal(np.sort(t), np.arange(n_sd))
        assert t[1] - t[0] == d                                   # consecutive points D_TM tones apart
    with pytest.raises(ValueError):
        eht.tone_mapper_permutation(100, 9)
    for n_bpscs in (1, 2, 4, 6, 8, 10, 12):
        for n_seg in (1, 2, 4):
            n_cbps = 980 * n_seg * n_bpscs
            perm = eht.segment_parser_permutation(n_cbps, n_bpscs, n_seg)
            assert np.array_equal(np.sort(perm), np.arange(n_cbps))
    perm = eht.segment_parser_permutation(4 * 1960, 4, 2)        # s = 2 bits per block, round robin
    assert perm[:6].tolist() == [0, 1, 3920, 3921, 2, 3]
    m = eht.eht_mcs(7, 160e6)
    sp = eht.symbol_point_permutation(m)
    assert np.array_equal(np.sort(sp), np.arange(m.n_sd))


def _field(mcs_i, bw, n_bytes, rng):
    from mmw60.config import Mmw60Config, PhyConfig
    from mmw60.vendor.wifitrx.waveform.pilots import pilot_positions
    base = Mmw60Config(phy=PhyConfig(standard="11be", bandwidth_hz=bw, mcs=mcs_i)).base_ofdm()
    pc = pilot_positions(base)
    m = eht.eht_mcs(mcs_i, bw)
    pil = (2.0 * rng.integers(0, 2, size=(m.n_symbols(n_bytes), pc.size)) - 1).astype(complex)
    return eht.build_eht_data_field(m, random_psdu(n_bytes, rng), base.n_active, pc, pil)


@pytest.mark.parametrize("mcs_i,bw,n_bytes", [(0, 20e6, 300), (5, 40e6, 500), (13, 80e6, 4096), (9, 80e6, 1000),
                                               (7, 160e6, 2000), (0, 320e6, 4096)])
def test_eht_data_field_loopback_is_error_free(mcs_i, bw, n_bytes):
    f = _field(mcs_i, bw, n_bytes, np.random.default_rng(mcs_i + 1))
    assert f.symbols.shape == (f.mcs.n_symbols(n_bytes), f.data_cols.size + f.pilot_cols.size)
    assert abs(np.mean(np.abs(f.symbols[:, f.data_cols]) ** 2) - 1) < 0.05
    assert f.decode(f.symbols, 1.0, kernel="numpy")[1] == 0


def test_eht_decoder_corrects_noise_and_kernels_agree():
    rng = np.random.default_rng(11)
    f = _field(3, 80e6, 1500, rng)                                 # 16-QAM 1/2
    y = f.symbols + 0.25 * (rng.standard_normal(f.symbols.shape) + 1j * rng.standard_normal(f.symbols.shape))
    hard = int(np.count_nonzero(mapper.hard_bits(y[:, f.data_cols].reshape(-1), 16)
                                != mapper.hard_bits(f.symbols[:, f.data_cols].reshape(-1), 16)))
    assert hard > 100
    b_np, e_np = f.decode(y, 1.0, kernel="numpy")
    assert e_np == 0
    if ldpc.active_kernel() == "numba":
        b_nb, e_nb = f.decode(y, 1.0, kernel="numba")
        assert np.array_equal(b_np, b_nb) and e_nb == 0
    # the scrambler round trip is part of the field
    assert np.array_equal(scrambler.descramble(f.tx_bits, f.scrambler_seed)[16:16 + f.psdu.size], f.psdu)


def test_big_qam_llr_is_the_exact_separable_form():
    rng = np.random.default_rng(12)
    for order in (64, 256, 1024, 4096):
        pts, bits = mapper.constellation(order)
        y = pts[rng.integers(0, order, 300)] + 0.02 * (rng.standard_normal(300) + 1j * rng.standard_normal(300))
        a, b = mapper.llr(y, order), mapper.llr_full_search(y, order)
        assert np.allclose(a, b, atol=1e-12, rtol=0)
        assert np.all((mapper.llr(pts, order).reshape(order, -1) > 0) == (bits == 0))
    assert mapper.SEPARABLE_ABOVE == 256                            # the milestone-0 orders keep their arithmetic
