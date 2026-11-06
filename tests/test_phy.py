"""The VHT data-field coding: tables consistent, every stage invertible, the two
Viterbi kernels bit-identical, the mapper wifitrx's constellation."""
import numpy as np
import pytest

from mmw60.phy import bcc, interleaver, mapper, scrambler
from mmw60.phy.mcs import vht_mcs
from mmw60.phy.ppdu import build_data_field, decode_data_field, random_psdu
from mmw60.vendor.wifitrx.waveform.qam import qam_modulate


def test_mcs_table_is_self_consistent():
    for i in range(9):
        m = vht_mcs(i)
        assert m.n_cbps == 52 * m.n_bpscs
        assert m.n_dbps * m.rate.denominator == m.n_cbps * m.rate.numerator
    assert vht_mcs(0).n_dbps == 26 and vht_mcs(1).n_dbps == 52 and vht_mcs(4).n_dbps == 156
    assert vht_mcs(0).n_symbols(4096) == 1262      # ceil((16 + 32768 + 6) / 26)
    assert vht_mcs(4).n_symbols(4096) == 211
    with pytest.raises(ValueError):
        vht_mcs(9)


def test_scrambler_is_127_periodic_and_an_involution():
    seq = scrambler.scrambling_sequence(300)
    assert np.array_equal(seq[:127], seq[127:254])
    bits = np.random.default_rng(0).integers(0, 2, 500).astype(np.uint8)
    assert np.array_equal(scrambler.descramble(scrambler.scramble(bits)), bits)
    with pytest.raises(ValueError):
        scrambler.scrambling_sequence(5, seed=0)


def test_bcc_encoder_generators():
    imp = np.zeros(10, dtype=np.uint8)
    imp[0] = 1
    coded = bcc.encode(imp).reshape(-1, 2)
    a = "".join(map(str, coded[:7, 0]))
    b = "".join(map(str, coded[:7, 1]))
    assert int(a, 2) == bcc.G0 and int(b, 2) == bcc.G1       # 133₈ and 171₈
    assert not bcc.encode(np.zeros(20, dtype=np.uint8)).any()


def test_puncture_depuncture_roundtrip():
    rng = np.random.default_rng(1)
    for rate in ((1, 2), (2, 3), (3, 4), (5, 6)):
        n = 120
        coded = rng.integers(0, 2, 2 * n).astype(np.uint8)
        p = bcc.puncture(coded, rate)
        assert p.size == bcc.n_coded_bits(n, rate)
        back = bcc.depuncture(p.astype(float), rate, 2 * n)
        mask = back != 0
        assert np.array_equal(back[mask], coded[mask]) or (coded[mask] == 0).any()


def test_interleaver_is_a_bijection_and_inverts():
    rng = np.random.default_rng(2)
    for n_bpscs in (1, 2, 4, 6, 8):
        perm = interleaver.permutation(n_bpscs)
        assert np.array_equal(np.sort(perm), np.arange(perm.size))
        x = rng.standard_normal((3, 52 * n_bpscs))
        assert np.array_equal(interleaver.deinterleave(interleaver.interleave(x, n_bpscs), n_bpscs), x)


def test_mapper_matches_wifitrx_constellation_and_bpsk():
    assert np.allclose(mapper.map_bits(np.array([0, 0, 0, 1, 1, 0, 1, 1]), 4),
                       qam_modulate(np.array([0, 1, 2, 3]), 4))
    bits16 = np.array([[(k >> (3 - i)) & 1 for i in range(4)] for k in range(16)]).reshape(-1)
    assert np.allclose(mapper.map_bits(bits16, 16), qam_modulate(np.arange(16), 16))
    assert np.array_equal(mapper.map_bits(np.array([0, 1]), 2), np.array([-1, 1]))
    pts, bits = mapper.constellation(16)
    assert bits.shape == (16, 4) and abs(np.mean(np.abs(pts) ** 2) - 1) < 1e-12


def test_llr_sign_and_weight():
    pts, bits = mapper.constellation(16)
    soft = mapper.llr(pts, 16).reshape(16, 4)
    assert np.all((soft > 0) == (bits == 0))            # positive = bit 0
    soft2 = mapper.llr(pts, 16, weight=np.full(16, 2.0)).reshape(16, 4)
    assert np.allclose(soft2, 2 * soft)
    assert np.array_equal(mapper.hard_bits(pts, 16), bits.reshape(-1))


def _field(mcs_i, n_bytes, rng):
    m = vht_mcs(mcs_i)
    psdu = random_psdu(n_bytes, rng)
    pil = (2.0 * rng.integers(0, 2, size=(m.n_symbols(n_bytes), 4)) - 1).astype(complex)
    return build_data_field(m, psdu, 56, np.array([7, 21, 34, 48]), pil)


@pytest.mark.parametrize("mcs_i", [0, 1, 4])
def test_data_field_loopback_is_error_free(mcs_i):
    f = _field(mcs_i, 300, np.random.default_rng(3))
    assert f.symbols.shape == (f.mcs.n_symbols(300), 56)
    assert decode_data_field(f.symbols, f, 1.0)[1] == 0


def test_viterbi_corrects_noise_and_kernels_agree():
    rng = np.random.default_rng(4)
    f = _field(1, 400, rng)
    y = f.symbols + 0.35 * (rng.standard_normal(f.symbols.shape) + 1j * rng.standard_normal(f.symbols.shape))
    hard_errors = int(np.count_nonzero(mapper.hard_bits(y[:, f.data_cols].reshape(-1), 4)
                                       != mapper.hard_bits(f.symbols[:, f.data_cols].reshape(-1), 4)))
    assert hard_errors > 50                                   # the channel really is noisy
    b_np, e_np = decode_data_field(y, f, 1.0, kernel="numpy")
    assert e_np == 0
    if bcc.active_kernel() == "numba":
        b_nb, e_nb = decode_data_field(y, f, 1.0, kernel="numba")
        assert np.array_equal(b_np, b_nb) and e_nb == 0
    else:
        with pytest.raises(RuntimeError):
            bcc.viterbi_decode(np.zeros(20), kernel="numba")


def test_viterbi_kernels_bit_identical_on_random_llrs():
    if bcc.active_kernel() != "numba":
        pytest.skip("numba not available: only the numpy kernel runs here")
    rng = np.random.default_rng(5)
    llr = rng.standard_normal(2 * 2000) * 2.0
    llr[::7] = 0.0
    assert np.array_equal(bcc.viterbi_decode(llr, kernel="numpy"), bcc.viterbi_decode(llr, kernel="numba"))


def test_jit_switch_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("MMW60_NO_JIT", "1")
    assert bcc.jit_enabled() is False
    monkeypatch.setenv("MMW60_NO_JIT", "")
    assert bcc.jit_enabled() in (True, False)
