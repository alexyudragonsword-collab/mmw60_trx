"""The interface's compute layer (``mmw60.guiutil``): the form as a study, what each part of a
result reads, freshness, provenance, and the reports a page draws."""
from __future__ import annotations

import dataclasses as dc
import json
import math
from pathlib import Path

import pytest
import yaml
from config_trace import traced

from mmw60 import ENGINE_BANNER, arrayreport, calcheck, compare, guispec, spec
from mmw60 import guiutil as g
from mmw60.config import AY_WAVEFORMS
from mmw60.frontend import Frontend60

REPO = Path(__file__).resolve().parent.parent
B8 = "be_upclocked 11ac 20M K=8 @60.48 GHz"
B32 = "be_upclocked 11ac 20M K=32 @60.48 GHz"
K1 = "be 11ac 20M K=1 @6 GHz (WiFi 7 chain)"
A80 = "be 11be 80M IF extender @60.48 GHz"


# ------------------------------------------------------------------ the form as a study (iron rule 1)
def test_law1_a_study_sets_only_shared_form_fields_and_drops_preset_values():
    assert set(g.ROW_KNOBS) | set(g.SHARED_KNOBS) == {k.id for k in guispec.KNOBS}
    assert not set(g.ROW_KNOBS) & set(g.SHARED_KNOBS)
    st = g.study({"lo.phase_noise.psd0_dbchz": "-90", "frontend.pa.obo_db": 7.5, "rx.ce_smooth_auto": "false",
                  "rx.cpe_window_symbols": 33.0})
    # 7.5 dB is the preset: not an edit; strings are coerced; an integer knob stays an integer
    assert st == {"lo.phase_noise.psd0_dbchz": -90.0, "rx.ce_smooth_auto": False, "rx.cpe_window_symbols": 33}
    assert isinstance(st["rx.cpe_window_symbols"], int)
    assert g.study() == {} == g.study({})
    for bad in ({"upclock_k": 4}, {"topology": "if_extender"}, {"no.such.field": 1}):
        with pytest.raises(KeyError):
            g.study(bad)
    for bad in ({"frontend.pa.obo_db": 99}, {"channel.model": "tgn"}, {"rx.cpe_window_symbols": 2.5},
                {"xo_ppm_tx": float("nan")}, {"rx.ce_smooth_auto": "maybe"}):
        with pytest.raises(ValueError):
            g.study(bad)


def test_law1_applying_a_study_is_the_forms_own_config_from_form():
    st = g.study({"lo.phase_noise.psd0_dbchz": -90, "xo_ppm_tx": 10, "channel.model": "flat"})
    ref = g.reference_config()
    assert g.apply_study(ref, st) == guispec.config_from_form(st, ref)
    assert g.apply_study(ref, {}) is ref
    # every row of the table gets the study; the carrier is the matrix's argument, and the 6 GHz reference
    # row keeps its own
    sch = {s.label: s for s in g.schemes({"xo_ppm_tx": 10})}
    assert all(s.cfg.xo_ppm_tx == 10 for s in sch.values() if s.cfg is not None)
    moved = {s.label: s for s in g.schemes({"carrier_hz": 62.64e9})}
    assert moved["be 11ac 20M K=1 @6 GHz (WiFi 7 chain)"].cfg.carrier_hz == 6e9
    assert moved["be_upclocked 11ac 20M K=8 @62.64 GHz"].cfg.carrier_hz == 62.64e9
    assert g.frontend({"carrier_hz": 62.64e9}).lo.carrier_hz == 62.64e9


def test_law1_the_schemes_of_an_empty_study_are_example_04s_matrix():
    ours, theirs = g.schemes(), compare.default_matrix()
    assert [(s.label, s.status, s.cfg) for s in ours] == [(s.label, s.status, s.cfg) for s in theirs]
    assert sum(s.status == "built" for s in ours) == 21


def test_law5_the_spec_entry_behind_a_knob_is_its_preset_value():
    ref = g.reference_config()
    for knob_id, key in g.KNOB_SOURCE.items():
        assert g.KNOB[knob_id].default(ref) == spec.value(key), (knob_id, key)


def test_law5_a_value_changed_on_the_form_reads_assumed():
    assert g.knob_tag("lo.phase_noise.psd0_dbchz") == {"source": "spec", "edited": False, "was": "spec",
                                                        "key": "liu2025.pn_psd0_dbchz"}
    assert g.knob_tag("lo.phase_noise.psd0_dbchz", {"lo.phase_noise.psd0_dbchz": -90}) == {
        "source": "assumed", "edited": True, "was": "spec", "key": "liu2025.pn_psd0_dbchz"}
    # put back to the preset it is the source's again; a knob with no entry behind it has no label until it is edited
    assert g.knob_tag("frontend.pa.obo_db", {"frontend.pa.obo_db": 7.5})["source"] == "derived"
    assert g.knob_tag("channel.model")["source"] is None
    assert g.knob_tag("channel.model", {"channel.model": "flat"})["source"] == "assumed"
    f = g.form({"lo.phase_noise.psd0_dbchz": -90})
    assert len(f["knobs"]) == len(guispec.KNOBS) == 22
    assert sum(k["row_knob"] for k in f["knobs"]) == 4
    psd = next(k for k in f["knobs"] if k["id"] == "lo.phase_noise.psd0_dbchz")
    assert (psd["preset"], psd["value"], psd["tag"]["source"]) == (-93.0, -90.0, "assumed")
    assert "calibration.be" in psd["read_by"] and "thresholds.be" not in psd["read_by"]
    assert f["source_counts"] == {"spec": 116, "assumed": 82, "derived": 15, "survey": 4}
    json.dumps(f, allow_nan=False)


# ------------------------------------------------------------------ what each part reads (the dependency map)
def _knobs(paths: set[str]) -> set[str]:
    return paths & set(g.SHARED_KNOBS)


def _pick(*labels):
    by = {s.label: s for s in g.schemes()}
    return [by[lab] for lab in labels]


def test_parts_declare_every_knob_the_front_end_and_the_calibration_read():
    ref = g.reference_config()
    fe_reads = _knobs(traced(lambda: Frontend60.from_config(ref)))
    assert fe_reads and fe_reads <= g.PARTS["calibration.be"].reads
    fe = Frontend60.from_config(ref)
    # the calibration reads the front end and nothing else of the config
    assert not _knobs(traced(lambda: calcheck.run_cal_at(fe, 1, 20e6, standard="11ac", obo_db=fe.obo_db)))


def test_parts_declare_every_knob_the_tables_columns_read():
    ref = g.reference_config()

    def run(schemes, td):
        def fn():
            compare.build(schemes, Frontend60.from_config(ref), time_domain=td)
        return _knobs(traced(fn))
    zero_if = _pick(K1, B8, B32)
    analytic = run(zero_if, False)
    # ISI, CFO capture, CFO: the analytic columns read more than the front end
    assert {"channel.rms_delay_ns", "rx.cfo_estimation", "xo_ppm_tx"} <= analytic
    assert analytic <= g.PARTS["table.analytic"].reads
    # topology A builds the chip and runs its calibration even for the analytic columns
    assert run(_pick(A80), False) <= g.PARTS["table.analytic"].reads
    td = run(_pick(B8), True)
    assert td - analytic and td <= g.PARTS["table.td"].reads
    # the tracer sees a read: a knob left out of a part's declaration is one the trace never met
    assert "rx.cpe_window_symbols" in td and "rx.cpe_window_symbols" not in analytic


@pytest.mark.slow
def test_parts_declare_every_knob_the_ay_rows_read():
    ref = g.reference_config()
    ay = [s for s in g.schemes() if s.waveform in AY_WAVEFORMS and s.status == "built"]

    def fn():
        compare.build(ay, Frontend60.from_config(ref), time_domain=True)
    assert _knobs(traced(fn)) <= g.PARTS["table.ay"].reads


def test_a_knob_a_part_does_not_read_leaves_its_numbers_alone():
    def numbers(st):
        # everything but the config hash, which follows every field of the config by construction
        return [{k: v for k, v in r.items() if k != "cfg_sha"}
                for r in g.table_report(st, labels=[B8, B32], time_domain=False)["rows"]]
    base = numbers({})
    for st in ({"rx.cpe_window_symbols": 33}, {"rx.ce_smooth_auto": False}, {"phy.packet_bytes": 1000}):
        assert not set(st) & g.PARTS["table.analytic"].reads
        assert numbers(st) == base, st
    assert numbers({"channel.rms_delay_ns": 20})[1]["terms_db"]["isi"] != base[1]["terms_db"]["isi"]


def test_parts_form_a_chain_and_every_job_names_existing_parts():
    assert g.closure("table.analytic") == ["calibration.be", "thresholds.be", "table.analytic"]
    assert g.closure("table.td") == ["table.td"]
    for job in g.JOBS.values():
        assert set(job["parts"]) <= set(g.PARTS)
    assert {p.id for p in g.PARTS.values() if p.job is None} == set(g.STORED)
    for p in g.PARTS.values():
        assert p.reads <= set(g.SHARED_KNOBS) and set(p.upstream) <= set(g.PARTS)
        assert p.job is None or p.id in g.JOBS[p.job]["parts"]
    m = g.freshness_matrix()
    assert [k["id"] for k in m["knobs"]] == list(g.SHARED_KNOBS)
    json.dumps(m)


def test_signature_follows_only_the_knobs_a_part_reads():
    s0 = g.signature("table.analytic")
    assert g.signature("table.analytic", {"rx.cpe_window_symbols": 33}) == s0
    assert g.signature("table.analytic", {"frontend.pa.obo_db": 7.5}) == s0          # the preset is not an edit
    assert g.signature("table.analytic", {"frontend.pa.obo_db": 9.5}) != s0
    assert g.signature("table.td", {"rx.cpe_window_symbols": 33}) != g.signature("table.td")
    assert g.signature("table.td") != g.signature("table.ay")


# ------------------------------------------------------------------ freshness
def test_freshness_against_the_accepted_presets():
    f = g.freshness({})
    assert all(v["state"] == "fresh" and v["basis"] == "accepted presets" for v in f.values())
    # a receiver knob: the time-domain column, the ay rows and the be thresholds; the analytic columns only
    # through the thresholds
    f = g.freshness({"rx.cpe_window_symbols": 33})
    stale = {k for k, v in f.items() if v["state"] == "stale"}
    assert stale == {"table.td", "table.ay", "thresholds.be", "table.analytic", "array", "ay"}
    assert f["table.analytic"]["changed"] == [] and f["table.analytic"]["upstream"] == ["thresholds.be"]
    assert f["thresholds.be"]["recompute"] is None
    assert "measure_thresholds.py" in f["thresholds.be"]["stored"]["command"]
    states = g.field_states(f)
    assert states["table.analytic"] == "fresh" and states["table.analytic+thresholds.be"] == "stale"
    assert states["table.analytic+calibration.be"] == "fresh" and states["table.td"] == "stale"
    # the PA back-off: the calibration, and with it the calibrated columns; the thresholds stay
    f = g.freshness({"frontend.pa.obo_db": 9.5})
    assert f["calibration.be"]["state"] == "stale" and f["calibration.be"]["changed"] == ["frontend.pa.obo_db"]
    assert f["thresholds.be"]["state"] == f["thresholds.ay"]["state"] == "fresh"
    assert f["table.analytic"]["upstream"] == ["calibration.be"]
    assert f["table.analytic"]["changed"] == ["frontend.pa.obo_db"]
    # the channel alone: the calibration does not read it; the array link is line of sight on a flat channel
    # and meets multipath only through the stored ay thresholds
    f = g.freshness({"channel.rms_delay_ns": 20})
    assert f["calibration.be"]["state"] == "fresh" and f["table.analytic"]["state"] == "stale"
    assert f["array"]["changed"] == [] and f["array"]["upstream"] == ["thresholds.ay"]
    assert f["ay"]["changed"] == ["channel.rms_delay_ns"]                              # its multipath section


def test_freshness_with_envelopes():
    st = {"frontend.pa.obo_db": 9.5}
    cal = g.envelope("calibration.be", st, {"x": 1}, seconds=1.5)
    assert cal["study"] == {"frontend.pa.obo_db": 9.5} and cal["signature"] == g.signature("calibration.be", st)
    assert cal["provenance"]["version"] and cal["provenance"]["engine"] == ENGINE_BANNER
    json.dumps(cal, allow_nan=False)
    f = g.freshness(st, {"calibration.be": cal})
    assert f["calibration.be"]["state"] == "fresh" and f["calibration.be"]["basis"] == "envelope"
    assert f["table.analytic"]["state"] == "stale" and f["table.analytic"]["upstream"] == []      # its own knob moved
    # a table built on that calibration says so (``built_on``); one that does not name it was built on the presets'
    tab = g.envelope("table.analytic", st, {}, built_on={"calibration.be": st})
    assert tab["upstream"] == {"calibration.be": g.signature("calibration.be", st),
                               "thresholds.be": g.signature("thresholds.be", st)}
    f = g.freshness(st, {"calibration.be": cal, "table.analytic": tab})
    assert f["table.analytic"]["state"] == "fresh"
    on_presets = g.envelope("table.analytic", st, {})
    assert on_presets["upstream"]["calibration.be"] == g.signature("calibration.be", {})
    f = g.freshness(st, {"calibration.be": cal, "table.analytic": on_presets})
    assert f["table.analytic"]["state"] == "stale" and f["table.analytic"]["upstream"] == ["calibration.be"]
    # the form moves on: both are stale again, with the knob named
    f = g.freshness({"frontend.pa.obo_db": 10.0}, {"calibration.be": cal, "table.analytic": tab})
    assert f["calibration.be"]["changed"] == f["table.analytic"]["changed"] == ["frontend.pa.obo_db"]
    # a table built before its calibration was redone stays stale until rebuilt on the new one
    old_tab = g.envelope("table.analytic", {}, {})
    f = g.freshness({}, {"calibration.be": g.envelope("calibration.be", {}, {}), "table.analytic": dict(
        old_tab, upstream={"calibration.be": "0" * 16, "thresholds.be": g.signature("thresholds.be")})})
    assert f["table.analytic"]["state"] == "stale" and f["table.analytic"]["upstream"] == ["calibration.be"]
    # another schema is never fresh
    f = g.freshness({}, {"table.td": dict(g.envelope("table.td", {}, {}), schema=g.SCHEMA + 1)})
    assert f["table.td"]["state"] == "stale"


# ------------------------------------------------------------------ provenance
def test_provenance_names_the_code_the_vendored_pins_and_the_tables():
    manifest = json.loads((REPO / "tools" / "vendor_manifest.json").read_text())["pins"]
    assert g.pins() == manifest
    v = g.vendored()
    assert v["wifitrx"]["pin"] == manifest["wifi_trx_cal"] and v["wifitrx"]["version"].count(".") == 2
    p = g.provenance()
    assert p["engine"] == ENGINE_BANNER and len(p["spec_digest"]) == 16 and p["schema"] == g.SCHEMA
    assert p["commit"] is None or len(p["commit"]) == 40
    ref = g.reference_config()
    assert len(g.config_sha(ref)) == 64 and g.config_sha(ref) == g.config_sha(g.reference_config())
    assert g.config_sha(dc.replace(ref, seed=1)) != g.config_sha(ref)


# ------------------------------------------------------------------ the comparison table
def test_table_report_is_compare_build_with_footing_and_hashes():
    rep = g.table_report(labels=[K1, B8, B32, A80], time_domain=False)
    assert rep["kind"] == "table" and rep["engine"] == ENGINE_BANNER and rep["ay_rows"] == []
    direct = compare.build(_pick(K1, B8, B32, A80), g.frontend(), time_domain=False)
    by = {r["label"]: r for r in rep["rows"]}
    for d in direct["rows"]:
        r = by[d["label"]]
        for k in ("floor_db", "floor_cal_db", "max_mcs", "max_mcs_cal", "rate_mbps", "dec_mcs", "irr_cal_db"):
            assert r[k] == d[k], (d["label"], k)
        assert r["power"]["pj_per_bit"] == d["power"]["pj_per_bit"]
    assert [by[lab]["footing"] for lab in (K1, B8, A80)] == ["be_zero_if", "be_zero_if", "be_if_extender"]
    assert set(rep["footing"]) == {"be_zero_if", "be_if_extender", "ay"}
    assert rep["footing"]["be_zero_if"]["calibration_run_on_this_chain"] is False
    assert rep["footing"]["ay"]["decoder_counted_in_pj"] is False
    assert by[B32]["cfg_sha"] == g.config_sha(_pick(B32)[0].cfg) and by[B32]["seed"] == 0
    assert by[B8]["td_evm_db"] is None and by[B8]["td_ok"] is None                    # no time-domain run asked
    assert rep["irr_table"]["from"] == "derived.irr_after_cal_measured_db"
    assert set().union(*map(set, rep["fields"].values())) <= set(by[B8]) | {"td_delta_db", "td_ok"}
    json.dumps(rep, allow_nan=False)
    with pytest.raises(KeyError):
        g.table_report(labels=["no such row"], time_domain=False)


def test_table_report_matches_the_accepted_example_04():
    """The same numbers the accepted output prints, formatted the way it prints them (one rounding)."""
    rep = g.table_report(labels=[B32], time_domain=False)
    r, d = rep["rows"][0], rep["display"]
    line = next(ln for ln in (REPO / "examples" / "expected" / "04_comparison_table.txt").read_text().splitlines()
                if ln.startswith(B32 + " "))
    f = line[len(B32):].split()
    assert f[5] == f"{r['floor_db']:.{d['floor_db']}f}" == "-16.5"
    assert (f[8], f[9]) == (f"MCS{r['max_mcs']}", f"MCS{r['max_mcs_cal']}") == ("MCS2", "MCS3")
    assert f[10] == f"{r['rate_mbps']:.{d['rate_mbps']}f}"
    assert f[12] == f"{r['power']['pj_per_bit']:.{d['pj_per_bit']}f}"
    assert r["dec_cap_display"] == "MCS3" and r["dominant"] == "iq_image" and r["footing"] == "be_zero_if"


def test_table_report_takes_a_calibration_results_irr_table():
    base = g.table_report(labels=[B32], time_domain=False)["rows"][0]
    worse = g.table_report(labels=[B32], time_domain=False, irr_table={"640000000.0": 30.0})
    r = worse["rows"][0]
    assert worse["irr_table"]["from"] == "calibration result" and r["irr_cal_db"] == 30.0
    assert r["floor_db"] == base["floor_db"] and r["floor_cal_db"] > base["floor_cal_db"]


@pytest.mark.slow
def test_table_report_full_run_has_the_time_domain_column_and_the_ay_rows():
    rep = g.table_report(quick=True)
    assert len(rep["ay_rows"]) == 2 and {r["footing"] for r in rep["ay_rows"]} == {"ay"}
    assert all(r["td_evm_db"] is not None for r in rep["rows"])
    ay = rep["ay_rows"][0]
    assert ay["floor_cal_worst_db"] < ay["floor_raw_worst_db"] and "frontend_id" not in ay
    json.dumps(rep, allow_nan=False)
    det = g.row_detail(rep, rep["ay_rows"][1]["label"])
    assert det["calibration_column"] is None and det["repro"]["config_sha256"] == rep["ay_rows"][1]["cfg_sha"]


# ------------------------------------------------------------------ the calibration runs (iron rule 4)
def test_law4_calibration_report_runs_the_sequence_and_keeps_two_verdicts():
    rep = g.calibration_report(plan=[(1, 20e6), (4, 20e6)])
    assert [c["label"] for c in rep["columns"]] == ["K=1 20M", "K=4 80M"]
    steps = {s["step"]: s["cells"] for s in rep["steps"]}
    assert list(steps)[0] == "tx_lpf_corner" and list(steps)[-1] == "final_loopback_evm" and len(steps) == 12
    # wifitrx calls the DC step ok at K = 4; the summary calls it degraded (more than 3 dB worse than the K = 1 column)
    dc_k1, dc_k4 = steps["rx_dc_offset"]
    assert (dc_k4["status_wifitrx"], dc_k4["status_summary"]) == ("ok", "degraded")
    assert dc_k4["value"] - dc_k1["value"] > rep["status_rule"]["degrade_db"]
    assert all(c["status_wifitrx"] == c["status_summary"] for c in (cells[0] for cells in steps.values()))
    # the IRR the comparison table's calibrated column reads: the accepted table, to its printed precision
    accepted = {float(k): v for k, v in spec.value("derived.irr_after_cal_measured_db").items()}
    got = {float(k): v for k, v in rep["irr_after_cal_db"].items()}
    assert {bw: round(v, 1) for bw, v in got.items()} == {bw: accepted[bw] for bw in got}
    col = rep["columns"][0]
    assert abs(col["backoff_db"] - rep["operating_point"]["obo_db"]) < 0.15 and col["three_views"]["isolation_db"] < -20
    json.dumps(rep, allow_nan=False)


def test_irr_after_cal_is_the_smaller_of_the_two_iq_steps():
    def run(bw, tx, rx):
        rows = [calcheck.StepRow(1, bw, 2 * bw, "tx_iq", "ok", "irr_min_db", tx),
                calcheck.StepRow(1, bw, 2 * bw, "rx_iq", "ok", "irr_min_db", rx),
                calcheck.StepRow(1, bw, 2 * bw, "tx_power", "ok")]
        return calcheck.CalRun(1, bw, 2 * bw, "w", rows=rows)
    assert calcheck.irr_after_cal([run(20e6, 53.6, 55.7), run(80e6, 56.7, 53.8)]) == {20e6: 53.6, 80e6: 53.8}
    assert calcheck.irr_after_cal([calcheck.CalRun(1, 20e6, 40e6, "w")]) == {}


def test_row_detail_points_a_row_at_the_calibration_that_ran_on_its_chain():
    tab = g.table_report(labels=[B8, B32, A80], time_domain=False)
    cal = {"columns": [{"label": "K=8 160M", "k": 8, "bw_eff_hz": 160e6},
                       {"label": "K=32 640M", "k": 32, "bw_eff_hz": 640e6}]}
    d = g.row_detail(tab, B32, cal)
    assert d["calibration_column"] == "K=32 640M" == d["irr_looked_up_from_column"]
    assert d["repro"]["seed"] == 0 and len(d["repro"]["config_sha256"]) == 64 and len(d["repro"]["commands"]) == 2
    assert g.row_detail(tab, A80, cal)["calibration_column"] is None       # the chip calibrates itself at build
    with pytest.raises(KeyError):
        g.row_detail(tab, "no such row")
    json.dumps(d, allow_nan=False)


# ------------------------------------------------------------------ the array page
def test_array_inputs_follow_the_study_except_the_channel():
    base = g.array_inputs()
    assert [lab for lab, _ in base["schemes"]] == [lab for lab, _ in arrayreport.default_schemes()]
    assert all(cfg == ref for (_, cfg), (_, ref) in zip(base["schemes"], arrayreport.default_schemes()))
    assert base["ay_cfgs"] == arrayreport.default_ay_cfgs() and g.array_inputs(ay=False)["ay_cfgs"] == {}
    moved = g.array_inputs({"frontend.pa.obo_db": 9.5, "channel.model": "flat", "channel.rms_delay_ns": 20})
    assert moved["fe"].obo_db == 9.5 and all(c.frontend.pa.obo_db == 9.5 for _, c in moved["schemes"])
    # line of sight on a flat channel, whatever the form's channel says
    assert moved["schemes"] == g.array_inputs({"frontend.pa.obo_db": 9.5})["schemes"]
    assert all(c.channel.model == "flat" for _, c in moved["schemes"])
    assert not {"channel.model", "channel.rms_delay_ns"} & g.PARTS["array"].reads


def test_eirp_limit_binds_from_the_smallest_array_that_reaches_it():
    inp = g.array_inputs()
    lim = g.eirp_limit_report(inp["fe"], inp["schemes"][0][1])
    assert lim["limit_avg_dbm"] == spec.value("fcc15255.eirp_avg_dbm") == 40.0
    assert abs(lim["single_element_eirp_dbm"] - 9.1) < 1e-9 and lim["binds_from_n"] == 36      # 9.1 + 20 log10 N >= 40
    deeper = g.array_inputs({"frontend.pa.obo_db": 12.5})
    assert g.eirp_limit_report(deeper["fe"], deeper["schemes"][0][1])["binds_from_n"] > 36


def test_single_antenna_ranges_join_the_array_rows_to_the_table():
    array = {"table_row_of": {"B x": "row b", "ay_sc": "row sc", "C y": None},
             "link": [{"scheme": "B x", "n": 1, "range_mcs0_m": 21.0}, {"scheme": "B x", "n": 4, "range_mcs0_m": 134.0},
                      {"scheme": "C y", "n": 1, "range_mcs0_m": 5.0}],
             "ay": [{"waveform": "ay_sc", "point": "preset", "n": 1, "range_mcs1_m": 9.0},
                    {"waveform": "ay_sc", "point": "own", "n": 1, "range_mcs1_m": 14.0}]}
    assert g.single_antenna_ranges(array) == {"row b": {"range_mcs0_m": 21.0}, "row sc": {"range_mcs1_m": 9.0}}


@pytest.mark.slow
def test_array_report_is_example_10s_numbers_on_the_studys_inputs_and_declares_its_reads():
    small = dict(sizes=(1, 4), trials=50, users=3, squint_sizes=(4,), two_stage_m=(2,), sensitivity_n=None)
    ref = g.reference_config()
    inp = g.array_inputs()

    def fn():
        arrayreport.build(Frontend60.from_config(ref), inp["schemes"], inp["ay_cfgs"],
                          squint_schemes=inp["squint_schemes"], **small)
    # the flat channel object is read; the form's channel knobs never reach it (the test above)
    assert _knobs(traced(fn)) - {"channel.model", "channel.rms_delay_ns"} <= g.PARTS["array"].reads
    rep = g.array_report(ay=False, **small)
    assert rep["kind"] == "array" and rep["eirp_limit"]["binds_from_n"] == 36
    assert rep["table_row_of"] == {"B 11be 80M x4 (320 MHz)": "be_upclocked 11be 80M K=4 @60.48 GHz",
                                   "B 11ac 20M x8 (160 MHz)": "be_upclocked 11ac 20M K=8 @60.48 GHz",
                                   "A 11be 80M (IF extender)": "be 11be 80M IF extender @60.48 GHz"}
    one = g.single_antenna_ranges(rep)["be_upclocked 11be 80M K=4 @60.48 GHz"]
    assert f"{one['range_mcs0_m']:.0f}" == "21" and one["cap_mcs"] == 5              # example 10 section 2-3, N = 1
    json.dumps(rep, allow_nan=False)


# ------------------------------------------------------------------ SC against OFDM
def test_ay_inputs_are_example_15s_presets_with_the_study_applied():
    from mmw60.ay import report as ayreport
    base = g.ay_inputs()
    assert base["cfgs"] == ayreport.default_cfgs() and set(base["cfgs"]) == {"ay_sc", "ay_ofdm"}
    moved = g.ay_inputs({"frontend.pa.obo_db": 9.5})
    assert moved["fe"].obo_db == 9.5 and all(c.frontend.pa.obo_db == 9.5 for c in moved["cfgs"].values())


def test_sc_vs_ofdm_headline_is_computed_from_the_array_rows():
    """The conclusion's two headline products from the accepted example 10 rows (N = 64, preset back-off):
    16-QAM 3/4 SC 322 m / OFDM 316 m, decoder caps MCS21 153 m / MCS20 148 m — SC ahead by 8 % and 9 %."""
    def row(wf, n, common, cap_mcs, cap):
        return {"waveform": wf, "point": "preset", "n": n, "eirp_dbm": 40.0, "cap_mcs": cap_mcs,
                "range_common_m": common, "range_cap_m": cap}
    array = {"ay": [row("ay_sc", 64, 322.0, 21, 153.0), row("ay_ofdm", 64, 316.0, 20, 148.0),
                    row("ay_sc", 16, 108.0, 21, 39.0), row("ay_ofdm", 16, 101.0, 18, 46.0)]}
    h = g.sc_vs_ofdm_headline(array)
    same, cap = h["same_modulation_16qam_3_4"], h["own_decoder_cap"]
    assert h["n"] == 64 and same["mcs"] == {"ay_sc": 14, "ay_ofdm": 13} and cap["mcs"] == {"ay_sc": 21, "ay_ofdm": 20}
    assert (same["ay_sc"]["rate_bps"], same["ay_ofdm"]["rate_bps"]) == (4.62e9, 4.37684e9)
    assert (cap["ay_sc"]["rate_bps"], cap["ay_ofdm"]["rate_bps"]) == (8.085e9, 7.65947e9)
    assert round(same["sc_advantage_pct"]) == 8 and round(cap["sc_advantage_pct"]) == 9
    assert g.sc_vs_ofdm_headline(array, n=16)["own_decoder_cap"]["mcs"]["ay_ofdm"] == 18
    with pytest.raises(ValueError):
        g.sc_vs_ofdm_headline({"ay": []})
    json.dumps(h, allow_nan=False)


@pytest.mark.slow
def test_ay_report_is_example_15s_numbers_on_the_studys_inputs_and_declares_its_reads():
    from mmw60.ay import report as ayreport
    inp = g.ay_inputs()
    cfgs = inp["cfgs"]

    def fn():
        ayreport.build(ayreport.default_frontend(cfgs), cfgs, quick=True)
    assert _knobs(traced(fn)) <= g.PARTS["ay"].reads
    rep = g.ay_report(quick=True)
    assert rep["kind"] == "sc_vs_ofdm" and rep["header"]["engine"] == ENGINE_BANNER
    assert {"impairments_alone", "calibration", "rate_vs_range", "same_modulation"} <= set(rep)
    json.dumps(rep, allow_nan=False)


# ------------------------------------------------------------------ the system block diagram
def _params(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "params":
                yield from v
            else:
                yield from _params(v)
    elif isinstance(node, list):
        for v in node:
            yield from _params(v)


def test_system_description_types_no_number():
    """Every parameter of the diagram names where its value comes from; none is written down."""
    doc = yaml.safe_load(g.SYSTEM_FILE.read_text(encoding="utf-8"))
    ps = list(_params(doc))
    assert len(ps) > 60
    for p in ps:
        assert sum(k in p for k in ("spec", "v", "text")) == 1, p
        assert "value" not in p and {"zh", "en"} <= set(p), p
        if "knob" in p:
            assert p["knob"] in g.SHARED_KNOBS, p


def test_system_report_resolves_every_parameter_and_its_source():
    rep = g.system_report()
    entries = spec.all_entries()
    for p in _params(rep):
        assert "value" in p, p
        if "source_key" in p:
            assert p["source"] == entries[p["source_key"]].source, p
    tx_b = {b["id"]: b for b in rep["topology_b_chain"]["tx"]}
    pa = {p["en"]: p for p in tx_b["pa60"]["params"]}
    assert (pa["Psat"]["value"], pa["Psat"]["source"]) == (14.6, "spec")
    assert (pa["back-off"]["value"], pa["back-off"]["source"]) == (7.5, "derived")
    assert pa["Pout"]["source"] == "derived" and abs(pa["Pout"]["value"] - 7.1) < 1e-9
    tx_a = {b["id"]: b for b in rep["topology_a_chain"]["tx"]}
    assert {p["en"]: p["value"] for p in tx_a["fixed_lo"]["params"]}["f_LO"] == 54.0e9
    assert {p["en"]: p["value"] for p in tx_a["mixer"]["params"]}["image sideband"] == 47.52e9
    assert {p["en"]: p["value"] for p in rep["between"]["cfo"]["params"]}["CFO"] == 2419200.0
    # shared blocks are the same ids on both topologies
    shared_b = {b["id"] for side in ("tx", "rx") for b in rep["topology_b_chain"][side] if b.get("shared")}
    shared_a = {b["id"] for side in ("tx", "rx") for b in rep["topology_a_chain"][side] if b.get("shared")}
    assert shared_a == {"pa60", "ant_tx", "lna60"} and shared_a <= shared_b
    json.dumps(rep, allow_nan=False)


def test_system_report_maps_every_evm_term_of_the_table_to_a_block():
    rep = g.system_report()
    ids = {b["id"] for chain in ("topology_a_chain", "topology_b_chain") for side in ("tx", "rx")
           for b in rep[chain][side]}
    ids |= {"channel"} | {sb["id"] for b in rep["topology_a_chain"]["tx"] for sb in b.get("sub_blocks", [])}
    for term, m in rep["evm_term_to_block"].items():
        assert set(m["blocks"]) <= ids, term
    tab = g.table_report(labels=[B32, A80], time_domain=False)
    terms = set().union(*(set(r["terms_db"]) for r in tab["rows"]))
    assert terms - {"lo_leak", "rx_dc", "if_filter", "image_noise"} <= set(rep["evm_term_to_block"]), terms


def test_system_report_draws_the_x_k_clock_domain_differently_on_the_two_topologies():
    up = g.system_report()["upclock_scope"]
    a, b = up["topology_a"], up["topology_b"]
    assert a["clock_domain_blocks"] == ["chip_digital"] and {"dac", "adc", "tx_lpf"} <= set(b["clock_domain_blocks"])
    assert (a["source_key"], a["source"]) == ("assumed.ifext_upclock", "assumed")
    assert a["chip_channels_hz"] == [20e6, 40e6, 80e6, 160e6, 320e6]
    built = [s.label for s in g.schemes() if s.key == ("if_extender", "be_upclocked") and s.status == "built"]
    assert a["rows_in_comparison_table"] == built and len(built) == 4
    assert a["rows_without_numbers"] == ["be_upclocked 11ac 20M K=32 IF extender @60.48 GHz"]
    assert up["same_bandwidth_three_ways"]["rows"] == [
        "be 11be 320M IF extender @60.48 GHz", "be_upclocked 11be 80M K=4 IF extender @60.48 GHz",
        "be_upclocked 11be 80M K=4 @60.48 GHz"]
    chip = g.system_report()["topology_a_chain"]["tx"][0]
    halves = [(sb["id"], sb["clock_x_k"]) for sb in chip["sub_blocks"]]
    assert halves == [("chip_digital", True), ("chip_analog", False)]


def test_system_report_follows_the_study_and_marks_what_was_edited():
    rep = g.system_report({"frontend.pa.obo_db": 9.5, "lo.phase_noise.psd0_dbchz": -90})
    pa = {p["en"]: p for p in next(b for b in rep["topology_b_chain"]["tx"] if b["id"] == "pa60")["params"]}
    bo = pa["back-off"]
    assert (bo["value"], bo["source"], bo["source_was"]) == (9.5, "assumed", "derived")
    assert abs(pa["Pout"]["value"] - 5.1) < 1e-9 and "edited" not in pa["Pout"]
    lo = {p["en"]: p for p in next(b for b in rep["topology_b_chain"]["tx"] if b["id"] == "lo60")["params"]}
    assert lo["PSD0"]["edited"] and lo["PSD0"]["value"] == -90.0 and "edited" not in lo["pole"]


def test_law6_every_report_carries_the_engine_line():
    assert g.system_report()["engine"] == ENGINE_BANNER
    assert g.table_report(labels=[B8], time_domain=False)["engine"] == ENGINE_BANNER
    assert "not endorsed" in g.system_report()["engine_caveat"]["en"]


def test_sources_report_every_entry_with_its_label():
    all_ = g.sources()
    assert len(all_) == 217 and all_["fcc15255.eirp_avg_dbm"]["source"] == "spec"
    some = g.sources(["assumed.oxygen_absorption"])
    oxy = some["assumed.oxygen_absorption"]
    assert oxy["value"] == 15.0 and oxy["source"] == "assumed"
    json.dumps(all_, allow_nan=False)


# ------------------------------------------------------------------ what the page work turned up (2026-11-19)
def test_a_knobs_preset_is_the_preset_whatever_the_study_says():
    f = g.form({"carrier_hz": 62.64e9, "frontend.pa.obo_db": 9.5})
    by = {k["id"]: k for k in f["knobs"]}
    assert by["carrier_hz"]["preset"] == g.PRESET_CARRIER_HZ and by["carrier_hz"]["value"] == 62.64e9
    assert by["frontend.pa.obo_db"]["preset"] == 7.5 and by["frontend.pa.obo_db"]["value"] == 9.5
    assert all(k["preset"] == p["preset"] for k, p in zip(f["knobs"], g.form({})["knobs"]))


def test_the_front_end_report_carries_the_receive_fronts_numbers():
    """They read None for a round: the report asked ``faces()`` for keys it does not have."""
    fe = g.frontend({})
    rx = g.front_end_report(fe)["rx_front"]
    top = fe.rx_front.states[0]
    assert rx == {"gain_db": top.gain_db, "nf_db": top.nf_db, "iip3_dbm": top.iip3_dbm}
    assert rx["nf_db"] == spec.value("rx60.comm_asada2011")["nf_db"]
    lna = next(b for b in _walk(g.system_report({})["topology_b_chain"]) if b.get("id") == "lna60")
    assert [p["value"] for p in lna["params"][:3]] == [top.gain_db, top.nf_db, top.iip3_dbm]


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def test_freshness_reads_missing_for_a_part_nothing_is_stored_for_when_the_host_asks():
    f = g.freshness({}, {}, accepted=False)
    assert {p for p, v in f.items() if v["state"] == "missing"} == {p for p, part in g.PARTS.items() if part.job}
    assert f["thresholds.be"]["state"] == "fresh" and f["array"]["recompute"] == "array"
    assert g.field_states(f)["table.analytic"] == "missing"
    # a stored table on a missing calibration is judged by what it says it was built on
    tab = g.envelopes_of(g.job_result("table", {}, {}))
    f = g.freshness({}, tab, accepted=False)
    assert f["calibration.be"]["state"] == "missing" and f["table.analytic"]["state"] == "fresh"
    f = g.freshness({"frontend.pa.obo_db": 9.5}, g.envelopes_of(g.job_result("table", {"frontend.pa.obo_db": 9.5}, {})),
                    accepted=False)
    assert f["table.analytic"]["state"] == "stale" and f["table.analytic"]["upstream"] == ["calibration.be"]
    assert g.freshness({}, {}) == g.freshness({}, {}, accepted=True)             # the default is unchanged


def test_a_calibration_reading_carries_its_unit_and_the_table_its_absent_threshold():
    assert [g.metric_unit(m) for m in ("irr_min_db", "lo_leak_dbc", "worst_dc_dbfs", "fc_err_pct", "delay_ns",
                                       "error_ps", "evm", None)] == ["dB", "dBc", "dBFS", "%", "ns", "ps", None, None]
    rep = g.table_report(labels=[B32], time_domain=False)
    assert rep["absent_below_db"] == compare.ABSENT_DB == -150.0
    assert g.row_detail(rep, B32)["absent_below_db"] == compare.ABSENT_DB


# ------------------------------------------------------------------ the data the page lacked (2026-11-20)
def test_a_rows_terms_add_up_to_its_floor_so_their_shares_are_well_defined():
    rep = g.table_report(labels=[B32, B8, A80, K1], time_domain=False)
    for r in rep["rows"]:
        present = {k: v for k, v in r["terms_db"].items() if v >= compare.ABSENT_DB}
        total_db = 10 * math.log10(sum(10 ** (v / 10) for v in present.values()))
        assert total_db == pytest.approx(r["floor_db"], abs=1e-9), r["label"]
        share = r["terms_share"]
        assert set(share) == set(r["terms_db"])
        assert sum(v for v in share.values() if v is not None) == pytest.approx(1.0)
        assert {k for k, v in share.items() if v is None} == set(r["terms_db"]) - set(present)
        assert max(present, key=present.get) == r["dominant"] == max((k for k in present), key=lambda k: share[k])
    assert "terms_share" in rep["fields"]["table.analytic"]


def test_a_row_says_whether_its_chain_is_usable_and_carries_the_power_at_its_calibrated_decoder_cap():
    stuck = "be_upclocked 11ac 20M K=1 @60.48 GHz"                 # 60 GHz CFO against a 312.5 kHz spacing
    rep = g.table_report(labels=[B32, stuck], time_domain=False)
    by = {r["label"]: r for r in rep["rows"]}
    assert by[B32]["usable"] is True and by[B32]["verdict"] == "能" and by[B32]["usable_cal"] is True
    assert by[stuck]["usable"] is False and by[stuck]["cfo_captured"] is False and by[stuck]["verdict"] == "不能"
    assert by[stuck]["usable_cal"] is False                        # calibration does not catch a CFO
    # a row whose raw IQ image blocks every MCS is unusable raw and usable (here: the fastest) once calibrated
    wide = g.table_report(labels=["be_upclocked 11be 80M K=32 @60.48 GHz"], time_domain=False)["rows"][0]
    assert (wide["usable"], wide["usable_cal"], wide["max_mcs"]) == (False, True, None) and wide["max_mcs_cal"] == 2
    assert "usable_cal" in rep["fields"]["table.analytic+calibration.be"]
    r = by[B32]
    assert r["dec_mcs_cal"] > r["dec_mcs"] and r["power_dec_cal"]["bit_rate_bps"] == r["dec_rate_cal_mbps"] * 1e6
    assert r["power_dec_cal"]["pj_per_bit"] < r["power_dec"]["pj_per_bit"]          # a faster MCS on the same blocks
    for group in ("table.analytic+calibration.be", "table.analytic+thresholds.be"):
        assert "power_dec_cal" in rep["fields"][group]                             # stale with either upstream
    assert "usable" in rep["fields"]["table.analytic"] and rep["sensitivity"] is None


def test_sensitivity_report_says_which_guesses_move_a_cap_or_the_ranking():
    sch = [s for s in g.schemes({}) if s.label in (B32, B8)]
    sens = g.sensitivity_report(sch, g.frontend({}))
    assert sens["base_ranking"] and set(sens["base_ranking"]) == {B32, B8}
    names = [k["knob"] for k in sens["knobs"]]
    assert names == [k["name"] for k in compare.sensitivity_knobs() for _ in k["values"]]
    for k in sens["knobs"]:
        assert k["source_keys"] and all(key in spec.all_entries() for key in k["source_keys"]), k["knob"]
        assert k["value_text"] == compare.knob_value_text(k["value"])
        assert k["mode"] in ("absolute", "relative", "scale") and k["knob_zh"] and isinstance(k["unit"], str)
        for moved in k["mcs_moved"] + k["dec_mcs_moved"]:
            assert moved["label"] in (B32, B8) and moved["from"] != moved["to"]
    by = {k["knob"]: k for k in sens["knobs"]}
    # an end says how it reads: the back-off's are +-2 dB around the front end's own, whose source is the presets'
    assert (by["PA back-off"]["mode"], by["PA back-off"]["unit"]) == ("relative", "dB")
    assert by["PA back-off"]["source_keys"] == [g.KNOB_SOURCE["frontend.pa.obo_db"]]
    assert by["synthesizer power"]["mode"] == "scale" and len(by["synthesizer power"]["source_keys"]) == 2
    assert by["calibrated IRR"]["source_note"] and by["Walden FoM"]["source_note"] is None
    # which knobs move a cap and which change the ranking are two lists (one "decides" list said nothing:
    # on the full matrix every knob but three changes the ranking)
    backoff = [k for k in sens["knobs"] if k["knob"] == "PA back-off"]
    assert any(k["mcs_moved"] or k["dec_mcs_moved"] for k in backoff) and "PA back-off" in sens["moves_a_cap"]
    assert "Walden FoM" not in sens["moves_a_cap"] and set(sens["changes_ranking"]) <= set(names)
    assert set(sens["decoder_basis"]) == {"zh", "en"} and "decides" not in sens
    json.dumps(sens, allow_nan=False)
