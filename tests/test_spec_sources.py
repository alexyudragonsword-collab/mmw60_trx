"""Iron rule 5: every specification / literature number carries its source; the
unverified ones are grep-able."""
import subprocess

import pytest

from mmw60 import spec


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


def test_grep_lists_every_unverified_number():
    out = subprocess.run(["grep", "-c", "source: survey", str(spec.SURVEY_FILE)],
                         capture_output=True, text=True)
    assert int(out.stdout.strip()) == len(spec.unverified())


def test_grep_lists_every_assumed_number():
    out = subprocess.run(["grep", "-c", "source: assumed", str(spec.SURVEY_FILE)],
                         capture_output=True, text=True)
    assert int(out.stdout.strip()) == len(spec.by_source("assumed"))


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
    assert cfo == pytest.approx(s("derived.cfo_liu2025_hz"))
    assert 2 * cfo / (4 * 312.5e3) == pytest.approx(s("derived.k_threshold_stf"), abs=0.01)
    assert cfo / 156.25e3 == pytest.approx(s("derived.k_threshold_ltf_only"), abs=0.05)
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
