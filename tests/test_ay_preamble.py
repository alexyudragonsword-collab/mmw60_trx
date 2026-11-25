"""The standard's Golay channel-estimation field (``mmw60.ay.preamble``) and the promise that the
module can be copied on its own (mmw60_trx#89: jcas60 vendors it).

The numbers of the standard come from spec_sources (``dmg.golay_sequences``,
``dmg.cef_golay_layout``); the properties are computed here, not quoted.
"""
from __future__ import annotations

import ast
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from mmw60 import spec
from mmw60.ay import edmg, golay, preamble

REPO = Path(__file__).resolve().parent.parent
AY = REPO / "src" / "mmw60" / "ay"
SEQ = spec.value("dmg.golay_sequences")
LAY = spec.value("dmg.cef_golay_layout")
GA, GB = np.asarray(SEQ["ga128"], dtype=float), np.asarray(SEQ["gb128"], dtype=float)
GU, GV = preamble.gu_gv(GA, GB, LAY["gu512"], LAY["gv512"])
ORDERS = {"ay_sc": LAY["sc_order"], "ay_ofdm": LAY["ofdm_order"]}


def test_the_module_imports_numpy_and_golay_and_nothing_else():
    """What makes it copyable.  Read from the syntax tree, so a comment cannot satisfy it and an
    import inside a function cannot hide."""
    for name, allowed in (("preamble.py", {"__future__", "numpy", ".golay"}), ("golay.py", {"__future__", "numpy"})):
        seen = set()
        for node in ast.walk(ast.parse((AY / name).read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                seen |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                seen.add("." * node.level + (node.module or ""))
        assert seen == allowed, (name, seen)


def test_copied_alone_into_another_package_it_builds_the_same_field(tmp_path):
    """The two files in a package of another name, in an interpreter that cannot import mmw60."""
    pkg = tmp_path / "elsewhere"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    for name in ("golay.py", "preamble.py"):
        shutil.copy(AY / name, pkg / name)
    code = (
        "import sys, json\n"
        "sys.modules['mmw60'] = None\n"                       # importing mmw60 would raise
        "from elsewhere import preamble as p\n"
        "ga, gb = p.pair_from_recursion(json.loads(sys.argv[1]), json.loads(sys.argv[2]))\n"
        "gu, gv = p.gu_gv(ga, gb, json.loads(sys.argv[3]), json.loads(sys.argv[4]))\n"
        "f = p.cef(gu, gv, json.loads(sys.argv[5]))\n"
        "print(json.dumps([[float(v.real), float(v.imag)] for v in f]))\n")
    import json
    args = [json.dumps(x) for x in (SEQ["d_128"], SEQ["w_128"], LAY["gu512"], LAY["gv512"], LAY["sc_order"])]
    r = subprocess.run([sys.executable, "-c", code, *args], capture_output=True, text=True, cwd=tmp_path,
                       env={"PYTHONPATH": str(tmp_path), "PATH": ""}, timeout=120)
    assert r.returncode == 0, r.stderr[-800:]
    theirs = np.array([complex(a, b) for a, b in json.loads(r.stdout)])
    assert np.array_equal(theirs, edmg.l_cef("ay_sc"))


@pytest.mark.parametrize("n", [128, 64, 32])
def test_the_recursion_read_backwards_is_the_pair_the_standard_lists(n):
    ga, gb = preamble.pair_from_recursion(SEQ[f"d_{n}"], SEQ[f"w_{n}"])
    assert np.array_equal(ga, np.asarray(SEQ[f"ga{n}"], dtype=float))
    assert np.array_equal(gb, np.asarray(SEQ[f"gb{n}"], dtype=float))
    assert golay.is_complementary(ga, gb)
    fwd_a, _ = golay.golay_pair(SEQ[f"d_{n}"], SEQ[f"w_{n}"])
    assert not np.array_equal(fwd_a, ga)                      # the reversal is not a no-op


def test_the_512_chip_sequences_and_both_orders_of_the_field():
    assert GU.size == GV.size == 4 * preamble.BLOCK == 512
    assert np.array_equal(GU, np.concatenate([-GB, -GA, GB, -GA]))
    assert np.array_equal(GV, np.concatenate([-GB, GA, -GB, -GA]))
    for wf, order in ORDERS.items():
        raw = preamble.cef(GU, GV, order, rotated=False)
        assert raw.size == int(LAY["cef_chips"]) == int(spec.value("edmg.sc_siso_preamble")["l_cef_chips"]) == 1152
        assert set(np.unique(raw)) == {-1.0, 1.0}
        # the short tail is what the entry says it is, in words: "first 128 of ... = -Gb128"
        assert np.array_equal(raw[-128:], -GB)
        assert np.array_equal(edmg.l_cef(wf, rotated=False), raw)
    sc = preamble.cef(GU, GV, ORDERS["ay_sc"], rotated=False)
    of = preamble.cef(GU, GV, ORDERS["ay_ofdm"], rotated=False)
    assert np.array_equal(sc[:1024], np.concatenate([GU, GV])) and np.array_equal(of[:1024], np.concatenate([GV, GU]))


def test_the_rotation_is_a_quarter_turn_per_chip_and_exact():
    raw = preamble.cef(GU, GV, ORDERS["ay_sc"], rotated=False)
    rot = preamble.cef(GU, GV, ORDERS["ay_sc"])
    n = np.arange(raw.size)
    assert np.array_equal(rot, raw * np.array([1, 1j, -1, -1j])[n % 4])           # no exp(): no 1e-16 residue
    assert np.allclose(rot, raw * np.exp(1j * np.pi * n / 2), atol=1e-12)          # and it is the entry's formula
    assert np.array_equal(np.abs(rot), np.ones(raw.size))
    # counted from another index it is the same turn shifted: the prefix continues the field backwards
    assert np.array_equal(preamble.rotate(raw[:8], -128), preamble.rotate(raw[:8], 0))
    assert np.array_equal(preamble.rotate(raw[:8], 1), 1j * preamble.rotate(raw[:8], 0))


@pytest.mark.parametrize("wf", sorted(ORDERS))
def test_with_its_prefix_the_field_reads_a_clean_impulse_within_128_chips(wf):
    """The property the field exists for, measured: 1 at lag 0, exactly 0 at every other lag within
    +-128 chips; not zero right outside."""
    order = ORDERS[wf]
    prefix = preamble.cyclic_prefix(GU, GV, order)
    assert np.array_equal(preamble.cyclic_prefix(GU, GV, order, rotated=False), -GA)   # both orders: -Ga128
    assert np.array_equal(prefix, edmg.l_cef_prefix(wf))
    x = np.concatenate([prefix, preamble.cef(GU, GV, order)])
    lags = np.arange(-160, 161)
    r = preamble.correlate(x, GU, GV, order, prefix.size, lags)
    inside = np.abs(lags) <= 128
    assert r[lags == 0][0] == 1.0
    assert np.count_nonzero(r[inside & (lags != 0)]) == 0                          # exact zeros, 256 lags
    assert np.count_nonzero(r[~inside]) > 0
    # without the prefix the negative lags are no longer clean
    bare = preamble.correlate(x[prefix.size:], GU, GV, order, 0, lags)
    assert np.count_nonzero(bare[(lags < 0) & inside]) > 0 and np.count_nonzero(bare[(lags > 0) & inside]) == 0


def test_the_two_long_sequences_alone_are_not_a_complementary_pair():
    """So nobody quotes them as one: the clean zone comes from the prefix and the suffix."""
    assert golay.is_complementary(GA, GB)
    assert not golay.is_complementary(GU, GV)


def test_through_a_channel_the_correlation_reads_the_taps():
    order = ORDERS["ay_sc"]
    prefix = preamble.cyclic_prefix(GU, GV, order)
    tx = np.concatenate([prefix, preamble.cef(GU, GV, order)])
    taps = {0: 1.0 + 0.0j, 7: -0.4 + 0.3j, 101: 0.2j, 128: 0.05 - 0.05j}
    rx = np.zeros(tx.size + 200, dtype=complex)
    for delay, gain in taps.items():
        rx[delay:delay + tx.size] += gain * tx
    lags = np.arange(0, 129)
    h = preamble.correlate(rx, GU, GV, order, prefix.size, lags)
    want = np.array([taps.get(int(lag), 0.0) for lag in lags])
    assert np.allclose(h, want, atol=1e-12)
    # a tap past the zone is not read cleanly: the reason the zone is stated as a number
    late = np.zeros_like(rx)
    late[140:140 + tx.size] = tx
    assert np.max(np.abs(preamble.correlate(late, GU, GV, order, prefix.size, lags))) > 1e-3


def test_a_wrong_block_name_or_order_is_an_error_not_a_guess():
    with pytest.raises(ValueError, match="not '\\+NAME' or '-NAME'"):
        preamble.compose({"Ga128": GA, "Gb128": GB}, ["-Gb128", "Ga128"])            # a sign is not optional
    with pytest.raises(ValueError, match="not '\\+NAME' or '-NAME'"):
        preamble.compose({"Ga128": GA, "Gb128": GB}, ["-Gc128"])
    with pytest.raises(ValueError, match="Gu<chips>"):
        preamble.cef(GU, GV, ["Gw512"])
    with pytest.raises(ValueError, match="asks for 1024 chips"):
        preamble.cef(GU, GV, ["Gu1024"])
    with pytest.raises(ValueError, match="both full sequences"):
        preamble.correlate(np.zeros(2000), GU, GV, ["Gu512", "Gu512", "Gv128"], 128, [0])
    with pytest.raises(ValueError, match="waveform must be one of"):
        edmg.l_cef("be")


def test_the_librarys_caller_checks_the_entry_against_itself(monkeypatch):
    ga, gb = edmg.golay_pair_128()
    assert np.array_equal(ga, GA) and np.array_equal(gb, GB)
    real = spec.value

    def tampered(key):
        v = real(key)
        if key == "dmg.golay_sequences":
            v = dict(v, ga128=[-x for x in v["ga128"]])
        return v
    monkeypatch.setattr(spec, "value", tampered)
    with pytest.raises(ValueError, match="not what d_128 / w_128 generate"):
        edmg.golay_pair_128()
