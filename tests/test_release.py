"""Cutting a release: the check that says a tree is the version it claims, the notes, and the one
workflow that may write to the repository.

``tools/release_check.py`` is the list of things done by hand for 0.3.0, as code; each test below
breaks one of them in a copy of the files it reads and expects that one named.  The workflow is
held to its rules from text, as the other workflows are (``tests/test_android.py``)."""
import importlib.util
import json
import re
import shutil
from pathlib import Path

import pytest

import mmw60

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("release_check", ROOT / "tools" / "release_check.py")
rc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rc)
V = mmw60.__version__


@pytest.fixture()
def tree(tmp_path):
    """A copy of just the files the check reads."""
    for rel in ("pyproject.toml", "src/mmw60/__init__.py", "android/app/build.gradle.kts", "CHANGELOG.md"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, tmp_path / rel)
    for rel in ("src/mmw60/data/gui/baseline", "examples/expected"):
        shutil.copytree(ROOT / rel, tmp_path / rel)
    return tmp_path


def _edit(path: Path, old: str, new: str):
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, (path.name, old)             # the mutation really lands
    path.write_text(text.replace(old, new), encoding="utf-8")


def test_this_tree_states_one_version_everywhere(tree):
    assert rc.problems(V, ROOT, dry_run=True) == []
    assert rc.problems(V, tree, tags=set()) == []
    assert rc.problems("v" + V, tree, tags=set()) == [f"'v{V}' is not a version like 0.3.0"]


def test_each_place_that_states_the_version_is_checked(tree):
    cases = {
        "pyproject.toml": (f'version = "{V}"', 'version = "9.9.9"', "pyproject.toml: version is 9.9.9"),
        "src/mmw60/__init__.py": (f'__version__ = "{V}"', '__version__ = "9.9.9"', "__version__ is 9.9.9"),
        "android/app/build.gradle.kts": (f'versionName = "{V}"', 'versionName = "9.9.9"', "versionName is 9.9.9"),
    }
    for rel, (old, new, said) in cases.items():
        original = (tree / rel).read_text(encoding="utf-8")
        _edit(tree / rel, old, new)
        found = rc.problems(V, tree, tags=set())
        assert len(found) == 1 and said in found[0], (rel, found)
        (tree / rel).write_text(original, encoding="utf-8")
    assert rc.problems(V, tree, tags=set()) == []                # restored: green again


def test_changelog_must_head_with_the_version_and_leave_nothing_unreleased(tree):
    log = tree / "CHANGELOG.md"
    original = log.read_text(encoding="utf-8")
    _edit(log, "## 未发布\n", "## 未发布\n\n### something merged after the release notes were written\n- a line\n")
    found = rc.problems(V, tree, tags=set())
    assert len(found) == 1 and "under 未发布" in found[0]
    log.write_text(original.replace(f"## {V} ", "## 9.9.9 ", 1), encoding="utf-8")
    found = rc.problems(V, tree, tags=set())
    assert len(found) == 1 and f"newest versioned heading of CHANGELOG.md is not {V}" in found[0]


def test_the_shipped_baseline_and_the_accepted_outputs_must_carry_the_version(tree):
    path = tree / "src/mmw60/data/gui/baseline/array.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["provenance"]["version"] = "0.2.0"
    path.write_text(json.dumps(data), encoding="utf-8")
    one = sorted((tree / "examples/expected").glob("*.txt"))[4]
    _edit(one, f"\nmmw60 {V};", "\nmmw60 0.2.0;")
    found = rc.problems(V, tree, tags=set())
    assert len(found) == 2
    assert "array.json was computed at 0.2.0" in found[0] and f"{one.name}: line 2" in found[1]


def test_a_released_version_is_not_released_twice_but_a_rehearsal_does_not_ask(tree):
    assert rc.problems(V, tree, tags={f"v{V}", "v0.1.0"}) == [
        f"the tag v{V} already exists on origin: this version was released"]
    assert rc.problems(V, tree, tags={"v0.1.0"}) == []
    assert rc.problems(V, tree, dry_run=True, tags={f"v{V}"}) == []


def test_notes_are_the_changelogs_heading_opening_and_entry_titles():
    text = rc.notes(V, ROOT)
    log = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    head, body, _ = rc.changelog_section(log, V)
    titles = [ln[4:].strip() for ln in body.splitlines() if ln.startswith("### ")]
    assert text.startswith(f"# mmw60 {V}\n") and head[3:].strip() in text and len(titles) >= 1
    assert all(f"- {t}" in text for t in titles)
    older = [ln for ln in log.splitlines() if ln.startswith("### ") and ln[4:].strip() not in titles]
    assert older and not any(ln[4:].strip() in text for ln in older)       # nothing from older versions
    assert f"mmw60-{V}-debug.apk" in text and "调试签名" in text and "没有验证" in text


def _code(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def test_only_the_release_workflows_last_job_may_write_and_only_when_dispatched_on_main():
    flows = {p.name: _code(p.read_text(encoding="utf-8")) for p in (ROOT / ".github/workflows").glob("*.yml")}
    assert {name for name, text in flows.items() if re.search(r":\s*write\b", text)} == {"release.yml"}
    rel = flows["release.yml"]
    assert len(re.findall(r":\s*write\b", rel)) == 1 and "\npermissions:\n  contents: read\n" in rel
    publish = rel[rel.index("\n  publish:"):]
    assert "contents: write" in publish and "needs: [check, package, apk]" in publish
    # one publishing command, guarded, after everything else in the job
    assert rel.count("gh release create") == 1
    step = publish[publish.index("- name: Tag v"):]
    assert "if: github.event_name == 'workflow_dispatch'" in step[:step.index("gh release create")]
    assert '--target "$GITHUB_SHA"' in step and "out/*" in step
    # dispatched runs are refused off main, and run the check without --dry-run
    check = rel[rel.index("\n  check:"):rel.index("\n  package:")]
    assert 'if [ "$GITHUB_REF" != "refs/heads/main" ]' in check and "exit 1" in check
    assert 'python tools/release_check.py check "$VERSION"\n' in check
    # the version reaches the shell through the environment, never by interpolation into a script:
    # the input is named once, on an env line
    assert [ln.strip() for ln in rel.splitlines() if "inputs.version" in ln] == ["ASKED: ${{ inputs.version }}"]
    triggers = rel[rel.index("\non:"):rel.index("\nconcurrency:")]
    assert "workflow_dispatch:" in triggers and "pull_request:" in triggers and "push:" not in triggers


def test_the_release_runs_the_android_workflow_itself_and_attaches_what_it_built():
    rel = _code((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))
    android = _code((ROOT / ".github/workflows/android.yml").read_text(encoding="utf-8"))
    assert "uses: ./.github/workflows/android.yml" in rel and re.search(r"^  workflow_call:", android, flags=re.M)
    name = re.search(r"name: (mmw60-debug-apk)\n\s+path: (\S+)", android)
    assert name and f"name: {name.group(1)}" in rel and Path(name.group(2)).name == "app-debug.apk"
    assert 'mv apk/app-debug.apk "out/mmw60-$VERSION-debug.apk"' in rel
    assert "python -m build --outdir dist ." in rel and "-m mmw60.appbridge" in rel
    assert 'cd "$RUNNER_TEMP"' in rel[:rel.index("-m mmw60.appbridge")]          # the installed wheel, not the tree
