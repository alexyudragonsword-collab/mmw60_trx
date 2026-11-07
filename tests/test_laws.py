"""The iron laws of AGENTS.md, each with its guard (law 5 is in test_spec_sources.py,
law 7 in test_fingerprint.py; laws 2 and 4 get their full tests in milestone 1 —
ROADMAP — and have their milestone-0 anchors here)."""
import ast
import dataclasses as dc

import numpy as np
import pytest

from conftest import REPO
from mmw60 import ENGINE_BANNER
from mmw60.config import (TOPOLOGIES, WAVEFORMS, WAVEFORMS_BUILT, Mmw60Config, liu2025_table2,
                          wifi7_baseline_k1, zero_if_60ghz)
from mmw60.guispec import KNOBS, config_from_form
from mmw60.impairments.cfo import CfoModel
from mmw60.sim.link import LinkSim


# ---------------------------------------------------------------- law 1
def test_law1_form_defaults_reproduce_config():
    vals = {k.id: k.default() for k in KNOBS}
    assert config_from_form(vals) == Mmw60Config()
    assert len({k.id for k in KNOBS}) == len(KNOBS)


def test_law1_yaml_configs_round_trip_to_the_presets():
    assert Mmw60Config.from_yaml(REPO / "configs" / "liu2025_table2.yaml") == liu2025_table2(k=8, mcs=0)
    assert Mmw60Config.from_yaml(REPO / "configs" / "wifi7_baseline_k1.yaml") == wifi7_baseline_k1(0)


def test_law1_both_topologies_are_named_and_the_unbuilt_one_refuses():
    assert set(TOPOLOGIES) == {"if_extender", "upclock_zero_if"}
    with pytest.raises(NotImplementedError, match="milestone 1"):
        LinkSim(Mmw60Config(topology="if_extender"))
    with pytest.raises(ValueError):
        Mmw60Config(topology="something_else")


def test_law1_waveform_enum_is_complete_and_ay_refuses():
    """Every scheme (topology × waveform) is named in the config now; the two
    802.11ay waveforms refuse to run until milestone 3."""
    assert set(WAVEFORMS) == {"be", "be_upclocked", "ay_ofdm", "ay_sc"}
    assert set(WAVEFORMS_BUILT) == {"be", "be_upclocked"}
    assert wifi7_baseline_k1().waveform == "be" and liu2025_table2().waveform == "be_upclocked"
    assert zero_if_60ghz().waveform == "be_upclocked"
    for wf in ("ay_ofdm", "ay_sc"):
        with pytest.raises(NotImplementedError, match="milestone 3"):
            LinkSim(Mmw60Config(waveform=wf))
    with pytest.raises(ValueError, match="waveform"):
        Mmw60Config(waveform="ad_sc")
    assert any(k.id == "waveform" for k in KNOBS)


def test_law1_examples_build_their_links_from_the_presets_only():
    """No example types a carrier, a ppm, a PSD or an OBO: they call the presets."""
    for p in sorted((REPO / "examples").glob("[0-9][0-9]_*.py")):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        calls = {n.func.id for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        assert calls & {"liu2025_table2", "zero_if_60ghz"}, p.name
        src = p.read_text(encoding="utf-8")
        for forbidden in ("73.44e9", "-93", "2.94e6", "obo_db=8"):
            assert forbidden not in src, f"{p.name} types a literature number: {forbidden}"


# ---------------------------------------------------------------- law 2 (anchor)
def test_law2_k1_chain_is_the_unmodified_wifitrx_chain():
    """K = 1, no impairments, flat channel, no noise: the receiver returns the
    transmitted constellation exactly and the decoder is error-free."""
    sim = LinkSim(wifi7_baseline_k1(4))
    r = sim.packet(None, np.random.default_rng(0), keep_symbols=True)
    assert r.rx.bit_errors == 0 and r.rx.evm_db < -100
    tx = sim.transmit(np.random.default_rng(0))[0].symbols
    assert np.allclose(r.rx.eq_symbols, tx, atol=1e-9)
    assert sim.phy.fs_eff == sim.phy.fs_base


# ---------------------------------------------------------------- law 3
def test_law3_cfo_term_is_exactly_zero_at_zero_ppm():
    m = CfoModel(60e9, 0.0, 0.0)
    assert m.cfo_hz == 0.0
    x = np.exp(1j * np.linspace(0, 1, 50))
    assert m.apply(x, 1e9) is not None and np.array_equal(m.apply(x, 1e9), x)
    cfg = liu2025_table2(k=8, mcs=0).with_(xo_ppm_tx=0.0, xo_ppm_rx=0.0)
    assert cfg.cfo_hz == 0.0 and LinkSim(cfg).cfo.cfo_hz == 0.0


def test_law3_cfo_is_crystal_error_times_carrier():
    cfg = liu2025_table2(k=8, mcs=0)
    assert cfg.cfo_hz == pytest.approx(40e-6 * 73.44e9)
    assert CfoModel(60e9, 20, 20).cfo_hz == pytest.approx(2.4e6)


def test_law3_topology_b_declares_how_it_catches_the_cfo():
    """Topology B relies on the STF/LTF estimators; at 40 ppm × 73.44 GHz the
    estimate is within one LTF-fine step for K = 8 and 16, and aliased at K = 4."""
    for k, ok in ((4, False), (8, True), (16, True)):
        sim = LinkSim(liu2025_table2(k=k, mcs=0).ideal().with_(xo_ppm_tx=20, xo_ppm_rx=20))
        r = sim.packet(30.0, np.random.default_rng(1))
        err = abs(r.rx.cfo_hat_hz - r.cfo_true_hz)
        assert (err < 0.05 * sim.phy.scs_eff) == ok, (k, err)


# ---------------------------------------------------------------- law 4 (anchor)
def test_law4_calibration_steps_are_importable_from_the_vendor_tree():
    """Milestone 1 runs wifitrx's full sequence on both topologies; the order
    constraints it will use must be the vendored ones."""
    from mmw60.vendor.wifitrx.cal.deps import STEP_REQUIRES, validate_order
    assert "dpd" in STEP_REQUIRES and callable(validate_order)


# ---------------------------------------------------------------- law 6
def test_law6_every_example_prints_the_engine_banner_first():
    for p in sorted((REPO / "examples").glob("[0-9][0-9]_*.py")):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
        first = main.body[0]
        assert isinstance(first, ast.Expr) and isinstance(first.value, ast.Call), p.name
        assert first.value.func.id == "print" and first.value.args[0].id == "ENGINE_BANNER", p.name
    assert "not endorsed" in ENGINE_BANNER and "linearised" in ENGINE_BANNER


def test_law6_banner_is_the_first_line_at_run_time(tmp_path):
    import subprocess
    import sys
    out = subprocess.run([sys.executable, "-c",
                          "import runpy, sys; sys.argv=['x','--help']; "
                          "runpy.run_path(sys.argv[0] if False else "
                          f"{str(REPO / 'examples' / '00_liu2025_per_vs_snr.py')!r}, run_name='__main__')"],
                         capture_output=True, text=True)
    assert out.stdout.splitlines()[0] == ENGINE_BANNER


# ---------------------------------------------------------------- the ideal() switch
def test_ideal_turns_every_impairment_off_and_nothing_else():
    cfg = liu2025_table2(k=16, mcs=4)
    i = cfg.ideal()
    assert not any(i.impairments_on.values())
    on = cfg.impairments_on
    assert on["cfo"] and on["phase_noise"] and on["pa"] and not on["iq"] and not on["converters"]
    z = zero_if_60ghz(k=8)
    assert all(z.impairments_on.values()) and not any(z.ideal().impairments_on.values())
    assert i.channel == cfg.channel and i.rx == cfg.rx and i.upclock_k == 16 and i.phy == cfg.phy
    assert dc.replace(i, label=cfg.label) != cfg
