"""Iron rule 5: every specification / literature number carries its source; the
unverified ones are grep-able.

Since mmw60_trx#21 the numbers about the outside world are in the vendored
spec_sources tables and this library's own choices and outputs in
``data/spec/survey.yaml``; ``spec.all_entries()`` merges the two, and every
tag is counted in every table."""
import subprocess
from pathlib import Path

import pytest

from mmw60 import spec
from mmw60.vendor import spec_sources as ss

SHARED_DATA = Path(spec.__file__).resolve().parent / "vendor" / "spec_sources" / "data"


def test_every_entry_is_tagged_and_cited():
    table = spec.all_entries()
    assert len(table) >= 40
    for key, e in table.items():
        assert e.source in spec.SOURCES, key
        assert e.cite, key
        if e.source == "survey":
            assert "未核实" in e.note, f"{key}: a survey entry's note must say it is unverified"
        if e.source == "assumed":
            assert e.note, f"{key}: an assumed entry must say why"


def _grep_count(tag: str, path) -> int:
    out = subprocess.run(["grep", "-c", f"source: {tag}", str(path)], capture_output=True, text=True)
    return int(out.stdout.strip() or 0)


def test_grep_counts_every_tag_in_every_table():
    """``grep -c "source: <tag>"`` on each table file lists its entries of
    that tag exactly, for all four tags (a comment or header line written as
    "tag word + colon" would be counted; ``audit_tags`` names it)."""
    tables = [(spec.SURVEY_FILE, spec.load_table()),
              *((f, ss.load_table(f)) for f in ss.data_files(SHARED_DATA))]
    assert len(tables) == 7
    for path, table in tables:
        for tag in spec.SOURCES:
            assert _grep_count(tag, path) == sum(e.source == tag for e in table.values()), (path.name, tag)
        assert ss.audit_tags(path) == [], path
    # and the files together hold the merged table, nothing else
    assert sum(len(t) for _, t in tables) == len(spec.all_entries())
    assert sum(_grep_count("survey", p) for p, _ in tables) == len(spec.unverified())
    assert sum(_grep_count("assumed", p) for p, _ in tables) == len(spec.by_source("assumed"))


def test_the_local_table_keeps_only_this_librarys_choices_and_outputs():
    """What stays in ``data/spec/survey.yaml`` after the move to spec_sources:
    the assumed entries, three derived ones that use them or an example's
    reading, and four survey entries spec_sources does not take (file names
    in this repository, a sibling's synthesis estimate)."""
    local = spec.load_table()
    assert {e.source for e in local.values()} == {"assumed", "derived", "survey"}
    assert sorted(k for k, e in local.items() if e.source != "assumed") == [
        "derived.irr_after_cal_measured_db", "derived.isi_beyond_gi_k16_db", "derived.pa60_obo_at_evm_limit_db",
        "survey.clock_profile_wu19", "survey.clock_profile_wu19_x10", "survey.clock_profile_wu19_x9",
        "survey.dsp_ip_dpd_poly_p4"]
    shared = ss.load_table(SHARED_DATA)
    assert not set(local) & set(shared)
    assert set(spec.all_entries()) == set(local) | set(shared)
    # the shared tables are the vendored ones, not an installed copy
    assert Path(ss.__file__).resolve().parent == SHARED_DATA.parent
    with pytest.raises(ValueError, match="two tables"):
        ss.merge_tables(shared, {"liu2025.pa_obo_db": local["assumed.base_bandwidth_hz"]})
    # ref() reads across both tables: a shared mapping's field, a local one, a plain value
    assert spec.ref("pa60.asada_eumc2011#psat_dbm") == spec.value("pa60.asada_eumc2011")["psat_dbm"]
    rule = spec.value("assumed.pa60_operating_rule")
    assert spec.ref("assumed.pa60_operating_rule#evm_limit_db") == rule["evm_limit_db"]
    assert spec.ref("derived.pa60_obo_at_evm_limit_db") == spec.value("derived.pa60_obo_at_evm_limit_db")


def test_spec_source_needs_a_quote_and_survey_needs_unverified():
    with pytest.raises(ValueError, match="quoted"):
        spec.SpecNumber("x", 1, "u", "spec", "cite")
    with pytest.raises(ValueError, match="source"):
        spec.SpecNumber("x", 1, "u", "rumour", "cite")
    with pytest.raises(ValueError, match="未核实"):
        spec.SpecNumber("x", 1, "u", "survey", "cite", note="fine")
    ok = spec.SpecNumber("x", 1, "u", "spec", "cite", quote="the text", section="3.1")
    assert ok.verified and not spec.survey("liu2025.carrier_hz").verified


def test_derived_entries_follow_their_formulas():
    s = spec.value
    cfo = (s("liu2025.xo_ppm_tx") + s("liu2025.xo_ppm_rx")) * 1e-6 * s("liu2025.carrier_hz")
    assert cfo == pytest.approx(s("liu2025.cfo_from_ppm_hz"))
    assert 2 * cfo / (4 * 312.5e3) == pytest.approx(s("liu2025.k_threshold_stf"), abs=0.01)
    assert cfo / 156.25e3 == pytest.approx(s("liu2025.k_threshold_ltf_only"), abs=0.05)
    import numpy as np
    assert 10 * np.log10(np.exp(-50.0 / s("assumed.cr_rms_delay_ns"))) == pytest.approx(
        s("derived.isi_beyond_gi_k16_db"), abs=0.1)


def test_fig4_readings_cover_all_nine_curves():
    ref = spec.fig4_readings()
    assert ref["source"] == "survey" and "未核实" in ref["note"]
    keys = {(c["k"], c["mcs"]) for c in ref["curves"]}
    assert keys == {(k, m) for k in (4, 8, 16) for m in (0, 1, 4)}
    for c in ref["curves"]:
        if c["k"] == 4:
            assert c["per_at_1e-2_snr_db"] is None
        else:
            assert 0 < c["per_at_1e-2_snr_db"] < 30


def test_unknown_key_names_what_exists():
    with pytest.raises(KeyError, match="liu2025.carrier_hz"):
        spec.survey("liu2025.nonexistent")


def test_ldpc_base_matrix_file_is_a_tagged_survey_document():
    doc = spec.ldpc_document()
    assert doc["source"] == "survey" and "未核实" in doc["note"] and doc["cite"]
    assert sum(len(v) for v in spec.ldpc_base_matrices().values()) == 12


# the 17 keys spec_sources 0.2.0 renamed (mmw60_trx#23); 0.3.0 retired their aliases (#25)
RETIRED_0_2_0 = (
    "survey.horowitz_mult32_pj", "survey.horowitz_add32_pj", "survey.walden_fom_fj", "survey.walden_fom_range_fj",
    "survey.node_scale_45_to_7nm", "survey.n_sd_11ac", "survey.n_sd_11be", "survey.eht_tone_mapper_dtm",
    "survey.ldpc_ppdu_encoding_thresholds", "survey.rx60_comm_iscas2015", "survey.dmg_sensitivity_assumptions",
    "survey.antenna60_okada2013_dbi", "derived.cfo_liu2025_hz", "derived.k_threshold_stf",
    "derived.k_threshold_ltf_only", "derived.rapp_p1db_below_psat_db", "derived.pa60_rapp_p_asada_eumc2011")


def test_retired_names_are_gone_and_the_shim_still_resolves_an_alias(monkeypatch):
    """spec_sources 0.2.0 renamed 17 keys and kept the old names as aliases
    (mmw60_trx#23); 0.3.0 retired them (#25), so an old name is a KeyError
    now.  The shim keeps the alias path for the next rename: an alias the
    shared tables declare reads the new entry, under its new key, with a
    DeprecatedKeyWarning pointing at the caller, and pyproject's
    filterwarnings makes that warning an error in this test suite."""
    assert len(RETIRED_0_2_0) == 17 and ss.aliases() == {}
    table = spec.all_entries()
    for old in RETIRED_0_2_0:
        assert old not in table, old
        with pytest.raises(KeyError, match="no spec entry"):
            spec.survey(old)
    # the alias path, on an alias the shared tables could declare
    fake = ss.Alias(old="survey.example_old_name", to="ieee80211ac.n_sd", since="9.9.9")
    monkeypatch.setattr(spec._shared, "aliases", lambda: {fake.old: fake})
    with pytest.warns(spec.DeprecatedKeyWarning, match="ieee80211ac.n_sd") as rec:
        e = spec.survey(fake.old)
    assert e is table[fake.to] and e.key == fake.to
    assert rec[0].filename == __file__                       # the warning names the caller, not the shim
    with pytest.raises(spec.DeprecatedKeyWarning):           # the suite's filter: an old name is an error
        spec.value(fake.old)


def test_key_names_cited_in_the_local_table_are_live_keys():
    """A key named in a local entry's cite or note (``tgad_em.pn_sides``,
    ``pa60.asada_eumc2011_rapp_p`` …) must exist in the merged table: a
    rename in spec_sources (#23) or a retirement (#25) that leaves a dangling
    reference here fails this test instead of rotting silently."""
    import re
    table = spec.all_entries()
    prefixes = sorted({k.split(".")[0] for k in table})
    pat = re.compile(r"(?<![\w./])((?:" + "|".join(map(re.escape, prefixes)) + r")\.[a-z0-9_]+)(?![\w])")
    cited = {(k, tok) for k, e in spec.load_table().items() for fld in ("cite", "note")
             for tok in pat.findall(getattr(e, fld) or "")}
    assert len(cited) >= 10                                  # the check reads something
    assert [(k, tok) for k, tok in sorted(cited) if tok not in table] == []
