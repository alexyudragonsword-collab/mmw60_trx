"""The vendor tree is a checkable adapted copy (AGENTS.md hard rule): every file
carries the attribution header, the manifest matches the tree, drift is detected."""
import json
from pathlib import Path

import pytest

import vendor_check as vc          # tools/ is on sys.path (conftest)
from conftest import REPO

PIN = "a8edf503df74cf11d6069a6354c4c0ddbf6e82d1"
SPEC_SOURCES_PIN = "25b2c5eb25fae98027a190b9757e50056b776d81"
ARRAY_TX_PIN = "286609e99c495712e026a913d4a2a066be11352c"
PINS = {"wifi_trx_cal": PIN, "spec_sources": SPEC_SOURCES_PIN, "array_tx": ARRAY_TX_PIN}
SPEC_SOURCES_SIB = Path("/home/user/alexyudragonsword-collab/spec_sources")
ARRAY_TX_SIB = Path("/home/user/alexyudragonsword-collab/array_tx")


def test_every_vendored_file_has_the_header():
    files = vc.vendored_files()
    assert len(files) >= 100
    for f in files:
        first = f.read_text(encoding="utf-8").splitlines()[0]
        m = vc.HEADER.match(first)
        assert m, f"{f}: missing attribution header"
        assert m["repo"] in PINS and m["sha"] == PINS[m["repo"]], f
    # spec_sources: the reader and seven tables, YAML included in the check
    ss = sorted(str(f.relative_to(vc.VENDOR)) for f in files if f.relative_to(vc.VENDOR).parts[0] == "spec_sources")
    tables = ("energy", "frontend60", "ieee80211", "ieee802153c", "liu2025", "pa60", "regulatory")
    assert ss == ["spec_sources/__init__.py", *(f"spec_sources/data/{n}.yaml" for n in tables),
                  "spec_sources/reader.py"]
    # array_tx: only what this library imports -- the geometry and the beam maths (beam depends on
    # geometry alone).  No __init__.py: upstream's imports config and sim, i.e. the whole package, so
    # the directory is a PEP 420 namespace package and every vendored file stays verbatim.  Until
    # 2026-11-17 the whole package was copied (135 files with its nested polar_tx / padpd).
    at = sorted(str(f.relative_to(vc.VENDOR)) for f in files if f.relative_to(vc.VENDOR).parts[0] == "arraytx")
    assert at == ["arraytx/beam.py", "arraytx/geometry.py"]
    assert not (vc.VENDOR / "arraytx" / "__init__.py").exists()
    # it ships in the wheel: the package finder is told to take namespace packages (setuptools itself is
    # not in every test environment -- Python 3.12 does not bundle it -- so its finder is asked only if there)
    find = (REPO / "pyproject.toml").read_text().split("[tool.setuptools.packages.find]")[1].split("\n[")[0]
    assert [ln.split("#")[0].split() for ln in find.splitlines() if ln.startswith("namespaces")] \
        == [["namespaces", "=", "true"]]
    try:
        from setuptools.discovery import PEP420PackageFinder
    except ImportError:
        pass
    else:
        assert "mmw60.vendor.arraytx" in PEP420PackageFinder.find(where=str(REPO / "src"))
    import mmw60.vendor.arraytx.beam as beam                                                 # and it imports
    assert beam.ArrayGeometry.__module__ == "mmw60.vendor.arraytx.geometry"


def test_manifest_matches_tree_and_pin():
    manifest = json.loads((REPO / "tools" / "vendor_manifest.json").read_text())
    assert manifest["pins"] == PINS
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
    results = vc.check(vc.Siblings({"wifi_trx_cal": str(tmp_path / "nowhere"),
                                    "spec_sources": str(tmp_path / "nowhere"),
                                    "array_tx": str(tmp_path / "nowhere")}), {"files": {}})
    assert results and all(r.status == "skip" for r in results)
    assert vc.report(results, strict=False, fail_on_skip=True) == 1
    assert vc.report(results, strict=False, fail_on_skip=False) == 0


@pytest.mark.skipif(not (Path("/home/user/wifi_trx_cal") / ".git").exists(),
                    reason="sibling checkout not present")
def test_no_drift_against_sibling_and_injected_drift_is_caught(tmp_path, monkeypatch):
    roots = {"wifi_trx_cal": "/home/user/wifi_trx_cal"}
    if (SPEC_SOURCES_SIB / ".git").exists():
        roots["spec_sources"] = str(SPEC_SOURCES_SIB)
    if (ARRAY_TX_SIB / ".git").exists():
        roots["array_tx"] = str(ARRAY_TX_SIB)
    sib = vc.Siblings(roots)
    results = vc.check(sib, json.loads((REPO / "tools" / "vendor_manifest.json").read_text()))
    assert not [r for r in results if r.status == "DRIFT"]
    assert all(r.status in ("verbatim", "skip") for r in results)
    assert all(r.status == "verbatim" for r in results if r.repo == "wifi_trx_cal")
    if "array_tx" in roots:
        assert all(r.status == "verbatim" for r in results if r.repo == "array_tx")
    # inject: copy one file into a temporary vendor tree and edit a logic line
    tree = tmp_path / "vendor" / "wifitrx" / "waveform"
    tree.mkdir(parents=True)
    src = vc.VENDOR / "wifitrx" / "waveform" / "qam.py"
    (tree / "qam.py").write_text(src.read_text().replace("_SUPPORTED = (4,", "_SUPPORTED = (2, 4,"))
    monkeypatch.setattr(vc, "VENDOR", tmp_path / "vendor")
    bad = vc.check(sib, {"files": {}})
    assert [r.status for r in bad] == ["DRIFT"]


@pytest.mark.skipif(not (SPEC_SOURCES_SIB / ".git").exists(), reason="spec_sources checkout not present")
def test_a_vendored_table_is_checked_like_code(tmp_path, monkeypatch):
    """The YAML tables are compared against the pin too: a copied table
    reads verbatim, one edited number is DRIFT (mmw60_trx#21)."""
    sib = vc.Siblings({"spec_sources": str(SPEC_SOURCES_SIB)})
    tree = tmp_path / "vendor" / "spec_sources" / "data"
    tree.mkdir(parents=True)
    src = (vc.VENDOR / "spec_sources" / "data" / "pa60.yaml").read_text(encoding="utf-8")
    (tree / "pa60.yaml").write_text(src, encoding="utf-8")
    monkeypatch.setattr(vc, "VENDOR", tmp_path / "vendor")
    assert [r.status for r in vc.check(sib, {"files": {}})] == ["verbatim"]
    assert src.count("psat_dbm: 14.6") == 1
    (tree / "pa60.yaml").write_text(src.replace("psat_dbm: 14.6", "psat_dbm: 15.6"), encoding="utf-8")
    assert [r.status for r in vc.check(sib, {"files": {}})] == ["DRIFT"]
