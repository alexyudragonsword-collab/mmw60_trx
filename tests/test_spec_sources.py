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
    reading, and three survey entries spec_sources does not take (file names
    in this repository, a sibling's synthesis estimate)."""
    local = spec.load_table()
    assert {e.source for e in local.values()} == {"assumed", "derived", "survey"}
    assert sorted(k for k, e in local.items() if e.source != "assumed") == [
        "derived.irr_after_cal_measured_db", "derived.isi_beyond_gi_k16_db", "derived.pa60_obo_at_evm_limit_db",
        "survey.clock_profile_wu19", "survey.clock_profile_wu19_x10", "survey.dsp_ip_dpd_poly_p4"]
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


def test_a_renamed_key_still_reads_with_a_warning_and_none_is_used_here():
    """spec_sources 0.2.0 renamed 17 keys and keeps the old names as aliases
    until 0.3.0 (mmw60_trx#23).  Through this shim an old name reads the same
    entry, under its new key, with a DeprecatedKeyWarning pointing at the
    caller; pyproject's filterwarnings makes that warning an error in this
    test suite, so a call site still on an old name fails here."""
    aliases = ss.aliases()
    assert len(aliases) == 17
    table = spec.all_entries()
    for old, a in aliases.items():
        assert old not in table and a.to in table, old
        with pytest.warns(spec.DeprecatedKeyWarning, match=a.to) as rec:
            e = spec.survey(old)
        assert e is table[a.to] and e.key == a.to
        assert rec[0].filename == __file__                   # the warning names the caller, not the shim
        with pytest.warns(spec.DeprecatedKeyWarning):
            assert spec.value(old) == table[a.to].value
    with pytest.raises(spec.DeprecatedKeyWarning):           # the suite's filter: an old name is an error
        spec.value(next(iter(aliases)))
    with pytest.raises(KeyError, match="no spec entry"):
        spec.survey("survey.no_such_key")
