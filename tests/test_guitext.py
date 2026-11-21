"""Every fixed sentence a report carries has its other language, and the pairs stay in step.

``mmw60.guitext`` pairs texts that live elsewhere (an example prints the Chinese verdicts, the job
notes were written in English).  A text added on one side without its other half fails here, so a
page never has to fall back to the other language without knowing it does.
"""
from __future__ import annotations

import re

import pytest

from mmw60 import calcheck, compare, guistore, guitext, guiutil
from mmw60.frontend.grid import REASON_ZH

CJK = re.compile(r"[㐀-鿿]")


def _is_en(text: str) -> bool:
    return bool(text.strip()) and CJK.search(text) is None


def _is_zh(text: str) -> bool:
    return CJK.search(text) is not None


def test_every_reason_and_verdict_has_its_english():
    assert set(guitext.REASON_EN) == set(REASON_ZH)
    assert all(_is_en(v) for v in guitext.REASON_EN.values())
    assert sum(_is_zh(v) for v in REASON_ZH.values()) >= 5    # the rest are acronyms (PA, CFO ...)
    assert len(set(guitext.REASON_EN.values())) == len(guitext.REASON_EN)     # two reasons never read alike
    assert set(guitext.VERDICT_EN) == {"能", "不能"} and all(_is_en(v) for v in guitext.VERDICT_EN.values())


def test_a_reason_is_translated_piece_by_piece_and_an_unknown_piece_is_an_error():
    zh = list(REASON_ZH.values())
    assert guitext.reason_en(zh[0]) == guitext.REASON_EN[list(REASON_ZH)[0]]
    both = guitext.reason_en(f"{zh[0]}, {zh[1]}")
    assert both == ", ".join(guitext.REASON_EN[k] for k in list(REASON_ZH)[:2])
    limited = guitext.reason_en(zh[1] + " 限 MCS")
    assert limited.endswith(" limits the MCS") and _is_en(limited)
    with pytest.raises(KeyError):
        guitext.reason_en("谁也不认识的原因")


def test_every_row_of_the_shipped_table_carries_both_languages():
    """The compute layer puts the pair into the report: no row with a Chinese reason and no English."""
    table = guistore.load_baseline()["table"]["report"]
    rows = table["rows"]
    assert rows
    for r in rows:
        assert r["verdict_en"] == guitext.VERDICT_EN[r["verdict"]]
        assert _is_en(r["reason_en"]) or r["reason"] in ("", None), r["label"]
        assert not r["reason"] or r["reason_en"] == guitext.reason_en(r["reason"])
    for p in table["pending"]:
        assert _is_en(p["reason"]) and _is_zh(p["reason_zh"])
    for kind, foot in table["footing"].items():
        assert _is_en(foot["raw_floor"]) and _is_zh(foot["raw_floor_zh"]), kind
        assert _is_en(foot["cal_floor"]) and _is_zh(foot["cal_floor_zh"]), kind


def test_the_reasons_a_cell_has_no_row_are_paired():
    assert set(guitext.PENDING_ZH) == {compare.NOT_A_SCHEME, compare.NOT_A_CHIP_CHANNEL}
    assert all(_is_zh(v) for v in guitext.PENDING_ZH.values())


def test_every_calibration_mechanism_has_its_english():
    assert set(guitext.MECHANISM_EN) == set(calcheck.MECHANISM)
    assert all(_is_en(v) for v in guitext.MECHANISM_EN.values())
    same_zh = {k for k, v in calcheck.MECHANISM.items() if v.startswith("同")}
    same_en = {k for k, v in guitext.MECHANISM_EN.items() if v.startswith("as ")}
    assert same_zh == same_en                                # "as above" on the same steps in both


def test_footing_job_notes_and_status_rule_are_paired():
    assert set(guitext.FOOTING_ZH) == set(guiutil.FOOTING)
    for kind, pair in guitext.FOOTING_ZH.items():
        assert set(pair) == {"raw_floor", "cal_floor"}
        assert all(_is_zh(v) for v in pair.values())
        assert all(_is_en(guiutil.FOOTING[kind][k]) for k in pair)
    assert set(guitext.SECONDS_NOTE_ZH) == set(guiutil.JOBS)
    assert set(guitext.STATUS_RULE_ZH) == {"status_wifitrx", "status_summary"}
    assert _is_en(guitext.EIRP_LAW["en"]) and _is_zh(guitext.EIRP_LAW["zh"])


@pytest.mark.parametrize("job", sorted(guiutil.JOBS))
def test_a_jobs_quoted_durations_are_the_ones_its_notes_explain(job):
    """``seconds`` is what a page shows; the notes say how each was taken.  A duration no note
    mentions (the table's list said 126 where both notes and the log say 106, until 2026-11-21) is a
    number nobody can trace."""
    spec = guiutil.JOBS[job]
    for lang, note in (("en", spec["seconds_note"]), ("zh", guitext.SECONDS_NOTE_ZH[job])):
        said = {int(n) for n in re.findall(r"(\d+) s\b", note)}
        assert set(spec["seconds"]) <= said, (job, lang, spec["seconds"], sorted(said))
    assert spec["seconds"] == sorted(spec["seconds"])


def test_sensitivity_notes_and_as_written_texts():
    noted = {k["name"] for k in compare.sensitivity_knobs() if k.get("source_note")}
    assert noted == set(guitext.SOURCE_NOTE_ZH)
    assert set(guitext.AS_WRITTEN.values()) <= {"en", "zh"}
    cal = guistore.load_baseline()["calibration_be"]["report"]
    assert cal["as_written"] == guitext.AS_WRITTEN
    details = [c["detail"] for s in cal["steps"] for c in s["cells"] if c.get("detail")]
    assert details and all(_is_en(d) for d in details)        # wifitrx writes them in English, as stated
    for s in cal["steps"]:
        assert s["mechanism_en"] == guitext.MECHANISM_EN[s["step"]] and _is_zh(s["mechanism_zh"])


def test_out_of_step_reasons_have_their_chinese_for_everything_the_store_can_say():
    """Every sentence ``guistore.stale_reasons`` can produce, produced, and translated."""
    base = guistore.load_baseline()["table"]
    off = dict(base, schema=guiutil.SCHEMA - 1, quick=True, study={"phy.packet_bytes": 1300},
               provenance=dict(base["provenance"], spec_digest="0" * 16,
                               vendored={k: dict(v, pin="0" * 40) for k, v in base["provenance"]["vendored"].items()}))
    reasons = guistore.stale_reasons(off)
    assert len(reasons) == 5                                  # one of each kind
    zh = guitext.out_of_step_zh(reasons)
    assert len(zh) == 5 and all(_is_zh(z) for z in zh)
    assert "1300" in zh[-1]                                   # the study it was computed for is kept
    assert guitext.out_of_step_zh([]) == []
    with pytest.raises(KeyError):
        guitext.out_of_step_zh(["something the store never said"])
