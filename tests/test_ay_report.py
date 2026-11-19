"""Example 15's numbers as data (``mmw60.ay.report``): the pure helpers and the section-1 tables
(fast), and the quick run through ``build`` (slow) — JSON-safe, the progress contract, and the
example's printer writing the same text from the dict alone as it does while the report is built."""
import dataclasses as dc
import importlib.util
import json
import re
from fractions import Fraction

import numpy as np
import pytest

from conftest import REPO
from mmw60 import __version__, spec
from mmw60.ay import edmg, report
from mmw60.config import ay_60ghz

EXAMPLE = REPO / "examples" / "15_ay_on_the_shared_front_end.py"
ACCEPTED = REPO / "examples" / "expected" / "15_ay_on_the_shared_front_end.txt"


def _example():
    s = importlib.util.spec_from_file_location("example15", EXAMPLE)
    mod = importlib.util.module_from_spec(s)
    s.loader.exec_module(mod)
    return mod


def _accepted_lines() -> set:
    return {ln.rstrip() for ln in ACCEPTED.read_text(encoding="utf-8").splitlines()}


def _is_plain(x) -> bool:
    """Exactly the JSON types: no numpy scalar (``np.float64`` passes ``isinstance(x, float)``), no tuple."""
    if type(x) is dict:
        return all(type(k) is str and _is_plain(v) for k, v in x.items())
    if type(x) is list:
        return all(_is_plain(v) for v in x)
    return x is None or type(x) in (float, int, str, bool)


# ---------------------------------------------------------------- fast: the pure helpers
def test_the_backoff_a_limit_needs_is_interpolated_on_the_grid():
    cross = report.crossing_backoff_db
    grid, evm = [1.0, 3.0, 5.0, 7.0], [-10.0, -20.0, -30.0, -32.0]
    assert cross(grid, evm, -5.0) == 1.0                       # met at the smallest back-off: the grid's first point
    assert cross(grid, evm, -10.0) == 1.0
    assert cross(grid, evm, -15.0) == pytest.approx(2.0)       # linear in dB between two points
    assert cross(grid, evm, -20.0) == pytest.approx(3.0)       # exactly on a point
    assert cross(grid, evm, -31.0) == pytest.approx(6.0)
    assert cross(grid, evm, -32.5) is None                     # the floor stays above the limit
    # a curve that comes back up: the first crossing, the smallest back-off that meets the limit
    assert cross([1.0, 2.0, 3.0, 4.0], [-10.0, -20.0, -12.0, -25.0], -18.0) == pytest.approx(1.8)
    assert type(cross(np.array(grid), np.array(evm), -15.0)) is float


def test_plain_gives_json_types_and_spells_what_json_cannot_hold():
    x = report.plain({"a": np.float64(1.5), "b": np.int64(3), "c": np.bool_(True), "d": (1, 2.0, None),
                      "e": np.arange(3) / 2, "f": Fraction(13, 16), "g": float("nan"), "h": -np.inf, 7: "seven",
                      "i": {"deep": [np.float32(0.5), float("inf")]}, "j": True, "k": 9.1, "l": 1})
    assert x == {"a": 1.5, "b": 3, "c": True, "d": [1, 2.0, None], "e": [0.0, 0.5, 1.0], "f": "13/16", "g": "nan",
                 "h": "-inf", "7": "seven", "i": {"deep": [0.5, "inf"]}, "j": True, "k": 9.1, "l": 1}
    assert _is_plain(x) and type(x["l"]) is int and type(x["j"]) is bool and type(x["d"][0]) is int
    assert json.loads(json.dumps(x, allow_nan=False)) == x
    with pytest.raises(TypeError, match="no plain form"):
        report.plain({"z": 1 + 2j})


def test_another_mcs_of_a_config_is_the_preset_of_that_mcs():
    """``build`` derives every link from the two configs it is given; on the presets that must be the
    preset of each MCS, field for field (label included), or the example's numbers would move."""
    cfgs = report.default_cfgs()
    assert cfgs == {wf: ay_60ghz(wf, m) for wf, m in report.PRESET_MCS.items()} and set(cfgs) == set(report.WAVEFORMS)
    for wf in report.WAVEFORMS:
        for e in edmg.mcs_table(wf):
            assert report.at_mcs(cfgs[wf], e.mcs) == ay_60ghz(wf, e.mcs), (wf, e.mcs)
        m = report.QAM16[wf]
        assert report.at_mcs(cfgs[wf], m, gi="long") == ay_60ghz(wf, m, gi="long")
        assert report.at_mcs(cfgs[wf], cfgs[wf].ay.mcs) == cfgs[wf]
    # a caller's change stays: the other MCS of a modified config is modified the same way
    mine = dc.replace(cfgs["ay_sc"], xo_ppm_tx=0.0, label="mine")
    other = report.at_mcs(mine, 7)
    assert (other.xo_ppm_tx, other.label, other.ay.mcs) == (0.0, "mine", 7)
    assert dc.replace(other, ay=mine.ay) == mine
    assert report.at_backoff(mine, 3).frontend.pa.obo_db == 3.0
    away = report.calibrated_away(mine)
    assert not away.frontend.iq.enabled and away.frontend.lo_leak_dbc is None and mine.frontend.iq.enabled


def test_the_matched_pairs_and_the_cap_on_a_floor():
    pairs = report.matched_pairs()
    assert pairs == [(12 + i, 11 + i) for i in range(10)]
    for sm, om in pairs:
        es, eo = edmg.mcs_entry("ay_sc", sm), edmg.mcs_entry("ay_ofdm", om)
        assert (es.order, es.code_rate) == (eo.order, eo.code_rate) and not eo.modulation.startswith("DCM")
    # a floor of -10.5 dB on every constellation: OFDM MCS 6 (limit -10) passes where MCS 4 / 5 do not
    assert report.best_passing_mcs("ay_ofdm", lambda order: -10.5).mcs == 6
    assert report.best_passing_mcs("ay_sc", lambda order: 0.0) is None
    # the floor is read per constellation: 64-QAM failing leaves the fastest 16-QAM MCS
    assert report.best_passing_mcs("ay_sc", lambda order: -60.0 if order < 64 else 0.0).mcs == 16


def test_section_1_is_the_accepted_output_and_json():
    n = report.numbers()
    assert _is_plain(n) and json.loads(json.dumps(n, allow_nan=False)) == n
    assert (n["channel"], n["gi"]) == (2, "normal")
    assert n["ofdm"]["pilots"] == list(edmg.ofdm_numerology(2).pilot_tones) and n["ofdm"]["pilot_tones"] == 16
    assert (n["sc"]["block_chips"], n["sc"]["gi_chips"], n["sc"]["data_chips_per_block"]) == (512, 64, 448)
    assert [(r["waveform"], r["mcs"]) for r in n["mcs"]] == [(wf, e.mcs) for wf in edmg.WAVEFORMS
                                                              for e in edmg.mcs_table(wf)]
    accepted = _accepted_lines()
    for r in n["mcs"]:                                         # the example's row of the MCS table
        line = (f"{r['waveform']:<8} {r['mcs']:>3}  {r['modulation']:<12} {r['code_rate']:>5} "
                f"{r['rate_bps'] / 1e6:8.1f} {r['evm_limit_db']:8.1f}")
        assert line in accepted, line
    o = n["ofdm"]
    assert any(ln.startswith(f"OFDM (edmg.ofdm_params [spec]): {o['fs_hz'] / 1e9:g} GS/s, {o['n_fft']}-point DFT, "
                             f"SCS {o['scs_hz'] / 1e6:.5f} MHz, {o['data_tones']} data + {o['pilot_tones']} pilot "
                             f"tones over ±{o['max_tone']}, GI {o['gi_samples']} samples; channel 2 pilots "
                             f"{o['pilots'][:3]} … {o['pilots'][-2:]}") for ln in accepted)


def test_the_sections_are_declared_once_and_the_printer_knows_no_other():
    assert len(set(report.SECTIONS)) == len(report.SECTIONS) and set(report.RECORDS) < set(report.SECTIONS)
    assert set(report.SOURCE_KEYS) <= set(spec.all_entries())
    ex = _example()
    hooks = [n for n in vars(ex.Printer) if n.startswith(("begin_", "row_", "end_"))]
    assert len(hooks) > 40
    for n in hooks:                                            # a misspelt hook would print nothing, silently
        assert n.split("_", 1)[1] in report.SECTIONS, n
    assert ex.floats({"a": ["nan", "x", 1.0, None], "b": "-inf"})["b"] == float("-inf")
    assert ex.floats(["never", "inf"]) == ["never", float("inf")]


# ---------------------------------------------------------------- slow: the quick run
def _numbers(line: str) -> list:
    return [float(v) for v in re.findall(r"(?<![\w.])[-+]?\d+\.\d+", line)]


@pytest.mark.slow
def test_the_quick_report_is_json_and_the_example_prints_it(capsys):
    ex = _example()
    out, events = ex.Printer(), []

    def progress(section, row):
        events.append((section, row))
        out(section, row)

    rep = report.build(quick=True, progress=progress)
    out.close()
    streamed = capsys.readouterr().out

    # --- plain data: JSON takes it and gives it back unchanged
    assert _is_plain(rep)
    back = json.loads(json.dumps(rep, allow_nan=False))
    assert back == rep and tuple(rep) == report.SECTIONS
    for key, value in rep.items():
        assert type(value) is (dict if key in report.RECORDS else list), key

    # --- progress: each section starts once, in order; then its rows (a record: itself), the report's own
    assert [s for s, row in events if row is None] == list(report.SECTIONS)
    at = {s: i for i, (s, row) in enumerate(events) if row is None}
    for i, (s, row) in enumerate(events):
        nxt = min((j for j in at.values() if j > at[s]), default=len(events))
        assert at[s] <= i < nxt                                # sections do not interleave
    for key, value in rep.items():
        rows = [row for s, row in events if s == key and row is not None]
        assert rows == ([value] if key in report.RECORDS else value), key
        assert all(a is b for a, b in zip(rows, [value] if key in report.RECORDS else value))

    # --- the dict alone prints the example: the text from the JSON copy is the text streamed during the run
    ex.print_report(back)
    assert capsys.readouterr().out == streamed
    lines = streamed.splitlines()
    h = rep["header"]
    assert lines[0].startswith(f"mmw60 {__version__}; QUICK (numbers meaningless); channel 2 (60.48 GHz), normal GI; "
                               f"one front end for both: PA Psat {h['psat_dbm']:g} dBm at 7.5 dB from psat")
    assert h["quick"] is True and h["packets_per_point"] == 1 and h["multipath_packets"] == 4
    assert h["backoff_grid_db"] == [1.0, 3.0, 5.0, 7.0, 9.0, 11.0, 13.0, 15.0] and h["low_backoffs_db"] == [0.0]
    assert h["presets"]["ay_sc"]["mcs"] == 16 and h["sources"]["assumed.ay_cal_probe"] == "assumed"

    # --- what does not depend on the size of the run is the accepted full-size output, line for line:
    #     section 1, the PAPR rows (the quick run keeps the assumed roll-off), section 7, the threshold table
    accepted = _accepted_lines()

    def between(start, stop):
        i = next(k for k, ln in enumerate(lines) if ln.startswith(start))
        j = next(k for k, ln in enumerate(lines) if k > i and ln.startswith(stop))
        return [ln.rstrip() for ln in lines[i:j] if ln.strip()]

    same = (between("== 1.", "== 2.") + between("== 2.", "== 3.") + between("== 7.", "== 8.")
            + between("the DMG-derived thresholds", "== 10."))
    assert len(same) > 80
    for ln in same:
        assert ln in accepted, ln

    # --- a few values against the lines the quick run prints for them
    sec4 = between("== 4.", "== 5.")
    for r in rep["floors"]:
        ln = next(x for x in sec4 if x.startswith(f"{r['waveform']:<8} {r['payload']:<26} raw"))
        assert _numbers(ln) == pytest.approx([r["raw_evm_db"], r["calibrated_away_evm_db"]], abs=0.00501)
    cal = rep["calibration"]
    final = next(ln for ln in lines if ln.startswith("final check:"))
    assert _numbers(final)[:5] == pytest.approx(
        [cal["final"][k] for k in ("isolation_evm_db", "modem_evm_db", "tx_modem_evm_db", "rx_modem_evm_db",
                                   "pout_dbm")], abs=0.00501)
    assert [s["step"] for s in cal["steps"]][-1] == "final_loopback_evm" and len(cal["steps"]) > 8
    sec6 = between("== 6.", "== 7.")
    assert len(rep["best_rate_at_pout"]) == 15 == len(sec6) - 3
    for r, ln in zip(rep["best_rate_at_pout"], sec6[2:]):
        assert _numbers(ln)[:2] == pytest.approx([r["pout_dbm"], r["backoff_db"]], abs=0.00501)
        assert r["pout_dbm"] == h["psat_dbm"] - r["backoff_db"]
        assert f"(MCS{r['sc_mcs']})" in ln and f"(MCS{r['ofdm_mcs']})" in ln

    # --- the rows hang together
    assert len(rep["floors"]) == 8 == len(rep["calibrated_floors"]) == len(rep["evm_vs_backoff"])
    floor = {(r["waveform"], r["tone_order"]): r for r in rep["floors"]}
    order = {(r["waveform"], r["mcs"]): r["tone_order"] for r in rep["numbers"]["mcs"]}
    for r in rep["caps"] + rep["calibrated_caps"]:
        if r["mcs"] is not None and r["chain"] != "calibrated":
            f = floor[(r["waveform"], order[(r["waveform"], r["mcs"])])]
            assert f["raw_evm_db" if r["chain"] == "raw" else "calibrated_away_evm_db"] <= r["evm_limit_db"]
    assert [r["chain"] for r in rep["caps"]] == ["raw", "raw", "calibrated_away", "calibrated_away"]
    for c in rep["evm_vs_backoff"] + rep["calibrated_evm_vs_backoff"]:
        assert c["backoff_db"] == h["backoff_grid_db"] and len(c["evm_db"]) == 8
    for c in rep["range_evm_vs_backoff"]:
        assert c["backoff_db"] == h["low_backoffs_db"] + h["backoff_grid_db"] and len(c["pout_dbm"]) == 9
        assert all(p <= h["psat_dbm"] for p in c["pout_dbm"])
    need = {(r["waveform"], r["mcs"]): r["backoff_db"] for r in rep["backoff_per_mcs"]}
    assert len(need) == 41 == len(rep["rate_vs_range"]) and len(rep["same_modulation"]) == 10
    for r in rep["same_modulation"]:
        assert (r["sc_backoff_db"], r["ofdm_backoff_db"]) == (need[("ay_sc", r["sc_mcs"])],
                                                              need[("ay_ofdm", r["ofdm_mcs"])])
        if r["delta_pout_db"] is not None:
            assert r["delta_pout_db"] == r["ofdm_backoff_db"] - r["sc_backoff_db"]
    for r, r5 in zip(rep["same_modulation_calibrated"], rep["same_modulation"]):
        assert (r["sc_mcs"], r["ofdm_mcs"], r["delta_pout_section5_db"]) == (r5["sc_mcs"], r5["ofdm_mcs"],
                                                                            r5["delta_pout_db"])
    assert [r["backoff_db"] for r in rep["residuals"]] == [7.5, 15.0]
    for r in rep["residuals"]:
        assert [w["waveform"] for w in r["waveforms"]] == ["ay_sc", "ay_ofdm"]
        assert [x["freq_hz"] for x in r["direct"]["image_rejection"]] == list(report.IMAGE_FREQS_HZ)
        for w in r["waveforms"]:
            assert [a["item"] for a in w["alone"]] == list(report.RESIDUAL_ITEMS)
    for r in rep["rate_vs_range"]:
        if r["best_range_m"] is None:
            assert r["best_backoff_db"] is None and r["best_pout_dbm"] is None and not r["best_is_smallest_backoff"]
        elif r["range_at_preset_m"] is not None:
            assert r["best_range_m"] >= r["range_at_preset_m"] > 0
    assert set(rep["link_budget"]["smallest_landed_backoff_db"]) == {"ay_sc", "ay_ofdm"}
    assert [r["distance_m"] for r in rep["fastest_rate_at_distance"]] == list(report.DISTANCES_M)
    assert [(r["waveform"], r["mcs"]) for r in rep["sensitivity_rows"]] == list(report.SENSITIVITY_MCS.items())
    mp = rep["multipath_evm"]
    assert [r["waveform"] for r in mp] == ["ay_sc"] * 5 + ["ay_ofdm"] * 4
    for r in mp:
        assert [c["snr_db"] for c in r["evm"]] == [None, 20.0, 12.0]
        assert (r["delta_vs_flat_db"] == 0.0) == (r["channel"] == "flat")
        assert r["gi"] == ("long" if "long GI" in r["channel"] else "normal")
