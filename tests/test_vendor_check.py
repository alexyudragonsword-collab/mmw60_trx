"""The vendor tree is a checkable adapted copy (AGENTS.md hard rule): every file
carries the attribution header, the manifest matches the tree, drift is detected."""
import json
from pathlib import Path

import pytest

import vendor_check as vc          # tools/ is on sys.path (conftest)
from conftest import REPO

PIN = "7b8d08eb9f11e426f9c99e079ebcbe06c2c64a02"


def test_every_vendored_file_has_the_header():
    files = vc.vendored_files()
    assert len(files) >= 100
    for f in files:
        first = f.read_text(encoding="utf-8").splitlines()[0]
        m = vc.HEADER.match(first)
        assert m, f"{f}: missing attribution header"
        assert m["repo"] == "wifi_trx_cal" and m["sha"] == PIN, f


def test_manifest_matches_tree_and_pin():
    manifest = json.loads((REPO / "tools" / "vendor_manifest.json").read_text())
    assert manifest["pins"]["wifi_trx_cal"] == PIN
    for rel in manifest["files"]:
        assert (vc.VENDOR / rel).exists(), f"manifest entry {rel} has no vendored file"


def test_strip_header_keeps_upstreams_own_comments():
    lines = ["# Vendored from wifi_trx_cal@abc: src/wifitrx/x.py", vc.POLICY_LINE,
             "# Vendored from PA_DPD:src/padpd/x.py (internal sibling repo)", "import numpy"]
    body = vc._strip_header(lines)
    assert body.startswith("# Vendored from PA_DPD")


def test_classify_distinguishes_import_rehoming_from_logic_edits():
    up = "import a\nx = 1\n"
    assert vc._classify("import a\nx = 1", up.rstrip("\n"))[0] == "verbatim"
    assert vc._classify("import b\nx = 1", up.rstrip("\n"))[0] == "adapted"
    assert vc._classify("import a\nx = 2", up.rstrip("\n"))[0] == "local"


def test_check_without_sibling_skips_and_fail_on_skip_is_red(tmp_path, capsys):
    results = vc.check(vc.Siblings({"wifi_trx_cal": str(tmp_path / "nowhere")}), {"files": {}})
    assert results and all(r.status == "skip" for r in results)
    assert vc.report(results, strict=False, fail_on_skip=True) == 1
    assert vc.report(results, strict=False, fail_on_skip=False) == 0


@pytest.mark.skipif(not (Path("/home/user/wifi_trx_cal") / ".git").exists(),
                    reason="sibling checkout not present")
def test_no_drift_against_sibling_and_injected_drift_is_caught(tmp_path, monkeypatch):
    sib = vc.Siblings({"wifi_trx_cal": "/home/user/wifi_trx_cal"})
    results = vc.check(sib, json.loads((REPO / "tools" / "vendor_manifest.json").read_text()))
    assert not [r for r in results if r.status == "DRIFT"]
    assert all(r.status == "verbatim" for r in results)
    # inject: copy one file into a temporary vendor tree and edit a logic line
    tree = tmp_path / "vendor" / "wifitrx" / "waveform"
    tree.mkdir(parents=True)
    src = vc.VENDOR / "wifitrx" / "waveform" / "qam.py"
    (tree / "qam.py").write_text(src.read_text().replace("_SUPPORTED = (4,", "_SUPPORTED = (2, 4,"))
    monkeypatch.setattr(vc, "VENDOR", tmp_path / "vendor")
    bad = vc.check(sib, {"files": {}})
    assert [r.status for r in bad] == ["DRIFT"]
