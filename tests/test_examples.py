"""Every example compiles, names only presets, and runs at smoke size (slow)."""
import py_compile
import subprocess
import sys

import pytest

from conftest import REPO

EXAMPLES = sorted((REPO / "examples").glob("[0-9][0-9]_*.py"))


def test_examples_exist_and_compile():
    assert [p.name[:2] for p in EXAMPLES] == ["00", "01", "02", "03", "04", "05"]
    for p in EXAMPLES:
        py_compile.compile(str(p), doraise=True)


def test_expected_outputs_exist_for_every_example():
    for p in EXAMPLES:
        assert (REPO / "examples" / "expected" / f"{p.stem}.txt").exists(), p.name


@pytest.mark.slow
@pytest.mark.parametrize("example", EXAMPLES, ids=[p.name for p in EXAMPLES])
def test_example_runs_at_smoke_size(example, tmp_path):
    r = subprocess.run([sys.executable, str(example), "--quick", "--jobs", "1"],
                       capture_output=True, text=True, cwd=REPO / "examples", timeout=900)
    assert r.returncode == 0, r.stderr[-2000:]
    assert r.stdout.splitlines()[0].startswith("engine:")


def test_external_check_cases_are_valid_configs():
    sys.path.insert(0, str(REPO / "tools"))
    import external_check
    from mmw60.sim.link import LinkSim
    cs = external_check.cases()
    assert len(cs) == 9
    for c in cs:
        LinkSim(c.cfg)
        assert c.tags["set"] == "impaired"
