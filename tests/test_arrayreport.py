"""The array layer's tables as data (``arrayreport.py``): what example 10 prints, as one plain dict."""
from __future__ import annotations

import ast
import importlib.util
import json

import numpy as np
import pytest

from conftest import REPO
from mmw60 import ENGINE_BANNER, __version__, spec
from mmw60 import arraylink as al
from mmw60 import arrayreport as rp
from mmw60.config import array_frontend
from mmw60.frontend.array60 import Array60

EXAMPLE = REPO / "examples" / "10_array_link_and_training.py"


def check_shape(rep: dict, events: list | None = None) -> None:
    """The report is JSON data with the documented keys; ``events`` (what ``progress`` saw) rebuild it."""
    assert json.loads(json.dumps(rep, allow_nan=False)) == rep
    assert tuple(rep) == rp.SECTIONS and set(rp.ROW_FIELDS) == set(rp.SECTIONS) - {"header"}
    assert tuple(sorted(rep["header"])) == tuple(sorted(rp.HEADER_FIELDS))
    for section, fields in rp.ROW_FIELDS.items():
        for row in rep[section]:
            assert tuple(row) == fields, section
    if events is None:
        return
    seen = {"header": {}}
    started = []
    for section, row in events:
        if row is None:
            assert section not in started, section
            started.append(section)
            seen.setdefault(section, [])
        elif section == "header":
            seen["header"].update(row)
        else:
            assert started[-1] == section               # a row belongs to the section that started last
            seen[section].append(row)
    assert started == [s for s in rp.SECTIONS if s in started]          # in the report's order
    assert seen == {k: v for k, v in rep.items() if k in seen}
    assert [s for s in rp.SECTIONS if s not in seen] == [s for s in rp.SECTIONS if rep[s] == []]


def test_plain_turns_numpy_values_into_json_data():
    got = rp.plain({"a": np.float64(1.5), 2: (np.int64(3), np.bool_(True), None, "x"), "n": float("nan"),
                    "i": np.array([np.inf, 2.0]), "b": False})
    assert got == {"a": 1.5, "2": [3, True, None, "x"], "n": None, "i": [None, 2.0], "b": False}
    assert type(got["a"]) is float and type(got["2"][0]) is int and type(got["2"][1]) is bool
    json.dumps(got, allow_nan=False)
    with pytest.raises(TypeError, match="not report data"):
        rp.plain({"x": object()})


def test_the_defaults_are_the_examples_inputs():
    labels = [lab for lab, _ in rp.default_schemes()]
    assert labels == ["B 11be 80M x4 (320 MHz)", "B 11ac 20M x8 (160 MHz)", "A 11be 80M (IF extender)"]
    assert all(c.channel == rp.FLAT for _, c in rp.default_schemes())
    assert [c.topology for _, c in rp.default_schemes()] == ["upclock_zero_if"] * 2 + ["if_extender"]
    ay = rp.default_ay_cfgs()
    assert list(ay) == list(rp.AY_COMMON_MCS) == ["ay_sc", "ay_ofdm"]
    assert all(c.waveform == wf and c.channel == rp.FLAT for wf, c in ay.items())
    assert [c.upclock_k for _, c in rp.default_squint_schemes()] == [4, 8, 32]
    q = rp.quick_kwargs()
    assert q["sizes"] == (1, 16) and q["sensitivity_n"] is None and max(q["two_stage_m"]) < max(q["sizes"])


def test_rows_that_stand_alone_match_the_array_layer():
    fe = rp.default_frontend()
    base = rp.default_schemes()[0][1]
    one, four = rp.plain(rp.faces_row(base, fe, 1)), rp.plain(rp.faces_row(base, fe, 4))
    assert tuple(one) == rp.ROW_FIELDS["faces"]
    # one element is the front end itself: its antenna, one sector, no beamwidth (None, not NaN), no loss
    assert one["tx_gain_db"] == pytest.approx(fe.antenna_gain_tx_dbi) == pytest.approx(one["rx_gain_db"])
    assert one["sectors"] == 1 and one["beamwidth_3db_deg"] is None and abs(one["phase_loss_db"]) < 1e-9
    ar = Array60.from_config(array_frontend(base, 4), fe)
    assert four["tx_gain_db"] == ar.tx_gain_db(0.0, 0.0)[0] and four["rx_gain_db"] == ar.rx_gain_db(0.0, 0.0)[0]
    assert four["sectors"] == 4 and four["beamwidth_3db_deg"] == pytest.approx(25.4, abs=0.1)
    assert four["scan_rel_db"] == pytest.approx(20 * np.log10(np.cos(np.deg2rad(rp.SCAN_DEG))), abs=0.5)
    # squint: true time delay loses nothing, phase shifters lose more at the edge than on average
    lab, cfg = rp.default_squint_schemes()[2]
    phy = cfg.upclocked()
    row = rp.plain(rp.squint_row(lab, cfg, fe, 16, phy.base.active_tone_indices() * phy.scs_eff))
    assert tuple(row) == rp.ROW_FIELDS["squint"] and row["band"] == lab
    assert row["phase_edge_db"] > row["phase_mean_db"] > 0.01
    assert abs(row["ttd_mean_db"]) < 1e-6 and abs(row["ttd_edge_db"]) < 1e-6


def test_a_small_report_is_json_data_with_the_documented_keys():
    """``build`` end to end on one cheap scheme and no 802.11ay waveform (their calibrated chains are the
    slow part): every be section, the progress calls, and a few rows against ``arraylink`` itself."""
    events = []
    scheme = rp.default_schemes()[1]                    # 11ac 20 MHz x 8: 56 tones, the cheapest budget
    fe = rp.default_frontend()
    rep = rp.build(fe=fe, schemes=[scheme], ay_cfgs={}, sizes=(1, 4), trials=40, users=3, two_stage_m=(2,),
                   squint_sizes=(4,), sensitivity_n=4, progress=lambda s, r: events.append((s, r)))
    check_shape(rep, events)
    h = rep["header"]
    assert h["version"] == __version__ and h["engine"] == ENGINE_BANNER and h["sizes"] == [1, 4]
    assert h["oxygen_db_per_km"] == spec.value("assumed.oxygen_absorption") == h["oxygen_alphas_db_per_km"][2]
    assert h["pa_pout_dbm"] == fe.target_pout_dbm() and h["eirp_limit_dbm"] == fe.eirp.avg_dbm
    assert h["phase_shifter_mw"] == pytest.approx(spec.value("assumed.array_phase_shifter_power_mw"))
    assert (h["two_stage_n"], h["two_stage_m"], h["sensitivity_n"], h["squint_sizes"]) == (4, [2], 4, [4])
    # no 802.11ay waveform: its sections stay empty and never start
    assert rep["ay_operating_points"] == rep["ay"] == rep["ay_smallest"] == rep["ay_sweep"] == []
    assert h["ay_waveforms"] == [] and h["ay_sweep_threshold_db"] is None
    assert [r["n"] for r in rep["faces"]] == [1, 4] and rep["faces"][0]["beamwidth_3db_deg"] is None
    # the link rows are arraylink's budget
    lab, cfg = scheme
    c = array_frontend(cfg, 4)
    ar = Array60.from_config(c, fe)
    b = al.array_budget(c, fe, ar, lab)
    row = rep["link"][1]
    assert (row["scheme"], row["n"], row["cap_mcs"]) == (lab, 4, b.dec_mcs)
    assert (row["eirp_dbm"], row["rx_gain_db"], row["floor_db"]) == (b.eirp_dbm, b.g_rx_db, b.floor_db)
    assert row["path_loss_mcs0_db"] == b.eirp_dbm + b.g_rx_db - b.sens_by_mcs[0]
    assert row["range_mcs0_m"] == b.range_by_mcs[0] == pytest.approx(rep["oxygen"][1]["range_mcs0_by_alpha_m"][2])
    assert rep["oxygen"][1]["range_mcs0_by_alpha_m"][0] > row["range_mcs0_m"]          # free space alone
    # power: N = 1 has no phase shifter, N = 4 has eight; the alternatives bracket the preset
    p1, p4 = rep["power"]
    assert p1["phase_shifters_mw"] == 0.0 and p4["phase_shifters_mw"] == pytest.approx(8 * h["phase_shifter_mw"])
    assert p4["total_mw"] == pytest.approx(p4["pa_mw"] + p4["phase_shifters_mw"] + p4["rest_mw"])
    assert p4["pj_per_bit_alt"][0] < p4["pj_per_bit"] < p4["pj_per_bit_alt"][1]
    assert p1["pj_per_bit_alt"] == [p1["pj_per_bit"]] * 2
    # training: one sector has no sweep; the sensitivity's preset row is table 4's
    t1, t4 = rep["training"]
    assert t1["sweep"] is False and t1["req_tx_db"] is None and t1["tones"] == t4["tones"] == 56
    assert t4["sweep"] is True and t4["txss_minus_mcs0_db"] == pytest.approx(
        t4["path_loss_txss_db"] - row["path_loss_mcs0_db"])
    assert [x["combining"] for x in rep["training_repetitions"][0]["cells"]] == ["noncoherent", "coherent"]
    assert {r["target"] for r in rep["two_stage"]} == {"MCS0 edge", "cap"} and rep["two_stage"][0]["m"] == 2
    assert rep["two_stage"][0]["wide"]["elements"] == 2 and rep["two_stage"][0]["flat"]["sectors"] == 4
    s = rep["sensitivity"]
    assert len(s) == 10 and s[0]["input"] == "preset" and s[0]["req_tx_db"] == t4["req_tx_db"]
    assert h["sensitivity_preset_req_tx_db"] == t4["req_tx_db"] and h["sensitivity_scheme"] == lab
    assert s[2]["input"] == "phase shifters continuous" and s[2]["phase_loss_db"] < s[0]["phase_loss_db"]
    # sections whose N is not among the sizes are left empty
    small = rp.build(fe=fe, schemes=[scheme], ay_cfgs={}, sizes=(1,), trials=10, users=3, squint_sizes=())
    check_shape(small)
    assert small["two_stage"] == small["sensitivity"] == small["squint"] == small["training_repetitions"] == []
    assert small["header"]["two_stage_n"] is None and small["header"]["sensitivity_n"] is None


def test_the_example_only_formats_the_report():
    """Example 10 computes nothing: it imports the report builder (and the preset of the shared front
    end, law 1), no numpy and nothing of the array layer."""
    tree = ast.parse(EXAMPLE.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported |= {f"{node.module}.{a.name}" for a in node.names}
    assert {m for m in imported if m.split(".")[0] not in ("__future__", "argparse", "os", "sys", "time", "pathlib")
            } == {"mmw60.ENGINE_BANNER", "mmw60.arrayreport", "mmw60.config.zero_if_60ghz",
                  "mmw60.frontend.Frontend60"}
    calls = [n.func for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    assert sorted(f.attr for f in calls if isinstance(f.value, ast.Name) and f.value.id == "arrayreport") == [
        "build", "quick_kwargs"]


@pytest.mark.slow
def test_the_quick_report_holds_the_numbers_the_example_prints(capsys):
    """The example's ``--quick`` path through ``build``, printed by the example's own printer: the report
    and the text agree with the quick run's numbers (meaningless as results, fixed by the seeds)."""
    mod_spec = importlib.util.spec_from_file_location("example10", EXAMPLE)
    ex = importlib.util.module_from_spec(mod_spec)
    mod_spec.loader.exec_module(ex)
    events = []
    out = ex.Printer(True)

    def progress(section, row):
        events.append((section, row))
        out(section, row)

    rep = rp.build(progress=progress, **rp.quick_kwargs())
    out.close()
    text = capsys.readouterr().out
    check_shape(rep, events)
    assert out.rep == {k: v for k, v in rep.items() if k in out.rep} and rep["sensitivity"] == []
    assert "== 6." not in text and text.count("\n== ") == 10

    def one(section, **where):
        rows = [r for r in rep[section] if all(r[k] == v for k, v in where.items())]
        assert len(rows) == 1, (section, where)
        return rows[0]

    b_be, ac = "B 11be 80M x4 (320 MHz)", "B 11ac 20M x8 (160 MHz)"
    h = rep["header"]
    assert h["sizes"] == [1, 16] and (h["trials"], h["users"], h["two_stage_n"], h["two_stage_m"]) == (200, 5, 16, [8])
    assert h["ay_sweep_threshold_db"] == pytest.approx(-11.48, abs=0.005) and h["ssw_frame_codewords"] == 2
    f = one("faces", n=16)
    assert (f["tx_gain_db"], f["rx_gain_db"]) == pytest.approx((25.94, 14.27), abs=0.005) and f["sectors"] == 16
    assert " 16    25.94    14.27    -3.25    6.3       16        0.19     0.33\n" in text
    assert "  1     2.00     2.00    -3.01    nan        1        0.00     0.00\n" in text
    r = one("link", scheme=b_be, n=16)
    assert r["cap_mcs"] == 5 and r["path_loss_mcs0_db"] == pytest.approx(131.0, abs=0.05)
    assert (r["range_mcs0_m"], r["range_cap_m"]) == pytest.approx((546, 132), abs=0.5)
    assert f"{b_be}     16    7.1   7.50   -21.1   33.0   14.3  -18.5  MCS5    131.0   112.5         546        132\n" \
        in text
    assert one("oxygen", scheme=b_be, n=16)["range_mcs0_by_alpha_m"] == pytest.approx([1401, 657, 546, 472], abs=0.5)
    p = one("power", scheme=ac, n=16)
    assert (p["pa_mw"], p["phase_shifters_mw"], p["total_mw"], p["pj_per_bit"]) == pytest.approx(
        (1194, 480, 1923, 6165), abs=0.5)
    assert [o["own_obo_db"] for o in rep["ay_operating_points"]] == pytest.approx([3.97, 7.02], abs=0.005)
    a = one("ay", waveform="ay_sc", point="preset", n=16)
    assert a["cap_mcs"] == 21 and (a["rate_mbps"], a["range_mcs1_m"], a["pj_per_bit"]) == pytest.approx(
        (8085, 344, 306), abs=0.5)
    assert "ay_ofdm  own     16    7.6   7.02   -21.0   33.5   14.3  -20.3 MCS17   5471     311       105" in text
    assert [(r["waveform"], r["point"], r["n"]) for r in rep["ay_smallest"]] == [
        ("ay_sc", "preset", 36), ("ay_sc", "own", 24), ("ay_ofdm", "preset", 36), ("ay_ofdm", "own", 34)]
    t = one("training", scheme=b_be, n=16)
    assert (t["tones"], t["req_tx_db"], t["req_rx_db"]) == (996, -11.0, -11.0)
    assert (t["txss_minus_mcs0_db"], t["sweep_us"]) == pytest.approx((-2.0, 220.8), abs=0.05)
    assert [(x["repetitions"], x["req_tx_db"]) for x in one("training_repetitions", scheme=ac)["cells"]] == [
        (16, -11.0), (8, -13.0)]
    two = one("two_stage", scheme=b_be, target="MCS0 edge")
    assert [(two[k]["sectors"], two[k]["repetitions"]) for k in ("flat", "wide", "narrow")] == [
        (16, 4), (8, 32), (2, 2)]
    assert two["two_stage_us"] == pytest.approx(1769, abs=0.5) and "8xR32 1742us      2xR2 27us     1769us\n" in text
    s = one("ay_sweep", n=16)
    assert (s["path_loss_txss_db"], s["ay_sweep_us"], s["be_sweep_us"]) == pytest.approx(
        (121.9, 509.1, 220.8), abs=0.05)
    assert [w["cap_mcs"] for w in s["waveforms"]] == [21, 18] and s["be_txss_minus_mcs0_db"] == t["txss_minus_mcs0_db"]
    q = one("squint", band="B 11be 80M x32 (2.56 GHz)")
    assert (q["phase_mean_db"], q["phase_edge_db"]) == pytest.approx((0.06, 0.19), abs=0.005)
    assert "B 11be 80M x32 (2.56 GHz)           16         0.06    0.19       0.00    0.00\n" in text
