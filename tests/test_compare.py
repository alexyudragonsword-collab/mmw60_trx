"""The comparison table (ROADMAP A3): iron rule 2's full test, the scheme
matrix, the power model, the EvmBudget reconciliation, the LO profile
options and the budget-report command line."""
import dataclasses as dc
import json
import sys

import numpy as np
import pytest

from conftest import REPO
from mmw60 import compare, spec
from mmw60.config import (PN_MODELS, TOPOLOGIES, WAVEFORMS, WAVEFORMS_BUILT, ChannelConfig, LoConfig, Mmw60Config,
                          PhaseNoiseConfig, wifi7_baseline_k1, wifi7_chain_k1, zero_if_60ghz)
from mmw60.frontend import Frontend60
from mmw60.frontend.dpd_cost import dsp_ip_models
from mmw60.impairments.phase_noise import PoleZeroPhase, load_clock_profile, make_profile, profile_at_carrier
from mmw60.power import PowerCoefficients, power_report
from mmw60.sim.link import LinkSim, evm_at
from mmw60.vendor.wifitrx.impairments.phase_noise import DEFAULT_WIFI7_LO_PROFILE

MATRIX = compare.scheme_matrix(ks=(1, 4, 8, 16, 32))
FLAT = ChannelConfig(model="flat")


# ---------------------------------------------------------------- law 2: the full test
def test_law2_matrix_names_every_topology_x_waveform_pair():
    """The table lists every scheme: numbers for the built ones, the
    milestone for the rest; nothing is silently left out."""
    keys = {s.key for s in MATRIX}
    assert keys == {(t, w) for t in TOPOLOGIES for w in WAVEFORMS}
    built = {s.key for s in MATRIX if s.status == "built"}
    assert built == {("upclock_zero_if", w) for w in WAVEFORMS_BUILT}
    for s in MATRIX:
        if s.status == "pending":
            assert "milestone" in s.reason and s.cfg is None
        elif s.status == "n/a":
            assert s.cfg is None
        else:
            assert s.cfg is not None and s.cfg.topology == s.topology and s.cfg.waveform == s.waveform
            LinkSim(s.cfg)
    # the pending ones refuse to run, which is why they have no numbers
    for s in MATRIX:
        if s.status == "pending":
            with pytest.raises(NotImplementedError):
                LinkSim(Mmw60Config(topology=s.topology, waveform=s.waveform))


@pytest.mark.parametrize("scheme", MATRIX, ids=[s.label for s in MATRIX])
def test_law2_every_scheme_on_the_shared_frontend_reads_the_k1_evm_when_ideal(scheme):
    """Iron rule 2, the milestone-1 form: one ``Frontend60`` instance for
    every scheme; with ppm = 0, ideal LO, ideal PA (and converters / IQ /
    leakage off) each scheme's EVM is the K = 1 chain's within 0.1 dB.
    Topology A and the ay waveforms skip with the milestone that builds them."""
    if scheme.status != "built":
        pytest.skip(scheme.reason)
    # the hardware is the instance, not the config: the ideal front end is
    # built once and every scheme runs on it
    fe = Frontend60.from_config(zero_if_60ghz(k=8).ideal())
    assert not fe.pa_enabled and not fe.converters_enabled and fe.lo.profile is None and not fe.tx_iq.enabled
    ref = evm_at(dc.replace(wifi7_chain_k1().ideal(), channel=FLAT), None, n_packets=1, frontend=fe)["evm_db"]
    sim = LinkSim(dc.replace(scheme.cfg.ideal(), channel=FLAT), frontend=fe)
    assert sim.frontend is fe and sim.frontend.eirp is fe.eirp and sim.frontend.lo is fe.lo
    e = evm_at(dc.replace(scheme.cfg.ideal(), channel=FLAT), None, n_packets=1, frontend=fe)["evm_db"]
    assert abs(e - ref) < 0.1 and e < -35, (scheme.label, e, ref)


def test_law2_report_hands_one_instance_to_every_row_and_the_k1_row_is_the_anchor():
    fe = Frontend60.from_config(zero_if_60ghz(k=8))
    rep = compare.build(compare.scheme_matrix(ks=(1, 8)), fe, time_domain=True)
    assert rep["frontend_ids"]["frontend"] == id(fe) and rep["frontend_ids"]["eirp"] == id(fe.eirp)
    labels = [r["label"] for r in rep["rows"]]
    assert len(labels) == 3 and len(rep["pending"]) == 6 and len(rep["matrix"]) == 8
    # the K = 1 chain row reads what evm_at reads for the same config on the same instance
    k1 = next(r for r in rep["rows"] if r["waveform"] == "be")
    e = evm_at(dc.replace(wifi7_chain_k1(), channel=FLAT), None, n_packets=1, frontend=fe)["evm_db"]
    assert k1["td_evm_db"] == pytest.approx(e, abs=1e-9)
    # the shared LO: the sub-7 row's phase-noise term equals the 60 GHz rows' (same profile instance)
    k60 = next(r for r in rep["rows"] if r["k"] == 1 and r["waveform"] == "be_upclocked")
    assert k1["terms_db"]["phase_noise"] == pytest.approx(k60["terms_db"]["phase_noise"])
    # and the bit-exact anchor of milestone 0 is untouched
    r = LinkSim(wifi7_baseline_k1(4)).packet(None, np.random.default_rng(0))
    assert r.rx.evm_db < -100


# ---------------------------------------------------------------- the rows
def test_rows_cross_check_and_the_uncaught_cfo_row_is_flagged():
    fe = Frontend60.from_config(zero_if_60ghz(k=8))
    rep = compare.build(compare.scheme_matrix(ks=(1, 8, 32)), fe, time_domain=True)
    by = {r["label"]: r for r in rep["rows"]}
    k1_60 = by["be_upclocked 11ac 20M K=1 @60.48 GHz"]
    assert not k1_60["cfo_captured"] and k1_60["verdict"] == "不能" and "CFO" in k1_60["reason"]
    assert k1_60["cfo_subcarriers"] == pytest.approx(2.4192e6 / 312.5e3, rel=1e-3)
    for c in rep["cross_checks"]:
        r = by[c["label"]]
        if r["cfo_captured"]:
            assert c["td_ok"] is True, c
            assert abs(c["budget_delta_db"]) < 1.0, c
        else:
            assert c["td_ok"] is None
    k8 = by["be_upclocked 11ac 20M K=8 @60.48 GHz"]
    assert k8["cfo_captured"] and k8["max_mcs"] == 2 and k8["rate_mbps"] == pytest.approx(156, abs=1)
    assert k8["eirp"]["ok"] and k8["eirp"]["margin_avg_db"] == pytest.approx(33.0)
    k1_6 = by["be 11ac 20M K=1 @6 GHz (WiFi 7 chain)"]
    assert k1_6["eirp"] is None and k1_6["plan_ok"] is None
    # the EvmBudget's phase-noise convention is the optimistic one (no floor above 100 MHz, no 1–10 kHz)
    assert k8["evm_budget"]["pn_budget_db"] < k8["evm_budget"]["pn_ici_db"]
    assert 0 < k8["evm_budget"]["cpe_tracked_fraction"] < 1
    # IQcal uses example 03's measured residual at the row's bandwidth
    assert k8["irr_cal_db"] == 50.4 and k8["irr_cal_measured_at_hz"] == 160e6
    k32 = by["be_upclocked 11ac 20M K=32 @60.48 GHz"]
    assert k32["max_mcs_cal"] >= k32["max_mcs"]


def test_measured_irr_lookup_takes_the_largest_bandwidth_not_above():
    assert compare.measured_irr_after_cal_db(160e6) == (50.4, 160e6)
    assert compare.measured_irr_after_cal_db(200e6) == (50.4, 160e6)
    assert compare.measured_irr_after_cal_db(10e6) == (55.3, 20e6)
    assert compare.measured_irr_after_cal_db(5.12e9) == (38.4, 2560e6)


def test_markdown_lists_every_scheme_and_json_round_trips(tmp_path):
    fe = Frontend60.from_config(zero_if_60ghz(k=8))
    sch = compare.scheme_matrix(ks=(8,))
    rep = compare.build(sch, fe, time_domain=False)
    md = compare.to_markdown(rep)
    for s in sch:
        assert s.label in md
    assert "milestone 3" in md and "A1" in md
    json.loads(json.dumps(compare.report_json(rep), default=str))


# ---------------------------------------------------------------- power model
def test_power_model_bookkeeping_matches_its_coefficients():
    cfg = zero_if_60ghz(k=8)
    fe = Frontend60.from_config(cfg)
    k = PowerCoefficients.from_spec()
    rep = power_report(cfg, fe, 156e6, k)
    names = [b.name for b in rep.blocks]
    assert names == ["pa", "lo", "converters", "dpd", "fft", "decoder"]
    assert rep.total_w == pytest.approx(sum(b.watts for b in rep.blocks))
    assert rep.pj_per_bit == pytest.approx(rep.total_w / 156e6 * 1e12)
    phy = cfg.upclocked()
    enob = fe.converters.enob(phy.fs_eff)
    assert rep.watts("converters") == pytest.approx(4 * 70e-15 * 2 ** enob * phy.fs_eff)
    assert rep.watts("lo") == pytest.approx(2 * 40e-3)
    # the DPD block is dpd_cost.py's number (example 02's column) at node scale 1
    m = dsp_ip_models()["ddr_r1_w16"]
    assert rep.pj("dpd") == pytest.approx(m.pj_per_bit(4 * phy.bandwidth_eff, 156e6))
    # one more ENOB bit doubles the converters (Walden), the digital blocks follow the node scale
    rep7 = power_report(cfg, fe, 156e6, k.with_(node_scale=0.175))
    assert rep7.watts("dpd") == pytest.approx(0.175 * rep.watts("dpd"))
    assert rep7.watts("fft") == pytest.approx(0.175 * rep.watts("fft"))
    assert rep7.watts("converters") == rep.watts("converters") and rep7.watts("pa") == rep.watts("pa")
    fe_more = dc.replace(fe, converters=dc.replace(fe.converters, enob_ref=fe.converters.enob_ref + 1))
    assert power_report(cfg, fe_more, 156e6, k).watts("converters") == pytest.approx(2 * rep.watts("converters"))
    # the 11be base has no decoder block and says so
    be = zero_if_60ghz(k=8, standard="11be", bandwidth_hz=80e6)
    r_be = power_report(be, fe, 1e9, k)
    assert "decoder" not in [b.name for b in r_be.blocks] and any("LDPC" in o for o in r_be.omitted)
    # ideal PA: no PA and no DPD block
    r_ideal = power_report(cfg.ideal(), Frontend60.from_config(cfg.ideal()), 156e6, k)
    assert {b.name for b in r_ideal.blocks} == {"lo", "fft", "decoder"}
    assert "class-B" in rep.blocks[0].note and rep.table().count("pJ/b") >= 7


def test_pa_pae_knob_flows_from_config_to_the_shared_pa():
    cfg = zero_if_60ghz(k=8)
    assert cfg.frontend.pa_pae_max == spec.value("assumed.pa60_pae_max")
    fe = Frontend60.from_config(dc.replace(cfg, frontend=dc.replace(cfg.frontend, pa_pae_max=0.3)))
    assert fe.scaled_pa().pae_max == 0.3
    assert fe.scaled_pa().pae(fe.psat_dbm) == pytest.approx(0.3)
    assert fe.scaled_pa().pae(fe.psat_dbm - 6.0) == pytest.approx(0.15, abs=1e-3)


def test_sensitivity_runs_every_knob_and_the_back_off_moves_the_cap():
    fe = Frontend60.from_config(zero_if_60ghz(k=8))
    sch = compare.scheme_matrix(ks=(8, 32))
    sens = compare.sensitivity(sch, fe)
    names = {e["knob"] for e in sens["knobs"]}
    assert names == {k["name"] for k in compare.sensitivity_knobs()} and len(names) == 7
    obo = [e for e in sens["knobs"] if e["knob"] == "PA back-off"]
    assert any(e["mcs_moved"] for e in obo), "±2 dB of back-off must move a PA-limited MCS cap"
    irr = next(e for e in sens["knobs"] if e["knob"] == "calibrated IRR")
    assert irr["value"] == 45.0
    walden = [e for e in sens["knobs"] if e["knob"] == "Walden FoM"]
    assert walden[0]["pj_ratio_max"] < 1 < walden[1]["pj_ratio_min"]
    assert "ranking" in sens["base"] and compare.sensitivity_markdown(sens).count("|") > 20


# ---------------------------------------------------------------- LO models
def test_lo_profile_models_load_scale_and_refuse_bad_input():
    pz = make_profile(PhaseNoiseConfig(), 60e9)
    assert isinstance(pz, PoleZeroPhase) and pz.psd0_dbchz == -93.0
    assert make_profile(PhaseNoiseConfig(model="wifitrx_wifi7"), 6e9) is DEFAULT_WIFI7_LO_PROFILE
    assert make_profile(PhaseNoiseConfig(apply="off"), 60e9) is None
    prof = load_clock_profile("bench_wu19_spll_frac_52m_6p253g.yaml")
    assert prof["f0_hz"] == pytest.approx(spec.value("survey.clock_profile_wu19")["f0_hz"], rel=1e-6)
    f = np.array([1e4, 1e6, 1e8])
    at_f0 = profile_at_carrier(prof, prof["f0_hz"]).psd(f)
    at_60 = profile_at_carrier(prof, 8 * prof["f0_hz"]).psd(f)
    assert np.allclose(10 * np.log10(at_60 / at_f0), 20 * np.log10(8))
    with pytest.raises(ValueError, match="profile_path"):
        Mmw60Config(lo=LoConfig(phase_noise=PhaseNoiseConfig(model="profile")))
    with pytest.raises(ValueError, match="phase_noise.model"):
        Mmw60Config(lo=LoConfig(phase_noise=PhaseNoiseConfig(model="leeson")))
    assert set(PN_MODELS) == {"pole_zero", "wifitrx_wifi7", "profile", "off"}
    cfg = dc.replace(zero_if_60ghz(k=8), lo=LoConfig(phase_noise=PhaseNoiseConfig(
        model="profile", profile_path="bench_wu19_spll_frac_52m_6p253g.yaml")))
    fe = Frontend60.from_config(cfg)
    assert fe.describe()["lo_profile"].startswith("profile:") and -40 < fe.lo.ipn_dbc() < -25
    assert LinkSim(cfg).describe()["frontend"]["lo_profile"] == fe.describe()["lo_profile"]


def test_wifi7_chain_k1_preset_is_the_zero_if_chain_at_1x_with_the_wifi7_lo():
    c = wifi7_chain_k1()
    assert c.upclock_k == 1 and c.waveform == "be" and c.carrier_hz == 6e9
    assert c.frontend.model == "zero_if_chain" and c.frontend.converters.enabled and c.frontend.iq.enabled
    assert c.lo.phase_noise.model == "wifitrx_wifi7"
    assert c.cfo_hz == pytest.approx(40e-6 * 6e9)
    assert Frontend60.from_config(c).describe()["lo_profile"] == "wifi7_lo"


# ---------------------------------------------------------------- the command line
def test_budget_report_cli_writes_markdown_and_json(tmp_path):
    sys.path.insert(0, str(REPO / "tools"))
    import budget_report
    md, js = tmp_path / "t.md", tmp_path / "t.json"
    assert budget_report.main(["--k", "1,8", "--no-time-domain", "-o", str(md), "--json", str(js)]) == 0
    text = md.read_text(encoding="utf-8")
    assert "be_upclocked 11ac 20M K=8 @60.48 GHz" in text and "pending" in text and "pJ/bit" in text
    d = json.loads(js.read_text(encoding="utf-8"))
    assert len(d["rows"]) == 3 and len(d["pending"]) == 6 and "_rows" not in d
    with pytest.raises(ValueError, match="unique"):
        compare.build(compare.scheme_matrix(ks=(8, 8)), time_domain=False)
    assert budget_report.parse_base("11be:80e6") == ("11be", 80e6)
