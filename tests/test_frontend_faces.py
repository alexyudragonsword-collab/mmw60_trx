"""ROADMAP D4: the receive front end, the TX-RX isolation and the two antenna
gains as faces of the shared ``Frontend60``.

The presets do not use any of them: their chains are the ones they were
(the fingerprint guards the numbers; here the objects)."""
import dataclasses as dc
import re

import numpy as np
import pytest

from conftest import REPO
from mmw60 import spec
from mmw60.config import ChannelConfig, Mmw60Config, RxFrontConfig, surveyed_frontend, zero_if_60ghz
from mmw60.frontend import Frontend60
from mmw60.frontend.rxfront import RxFront60
from mmw60.sim.link import LinkSim, evm_at
from mmw60.vendor.wifitrx.chain.agc import DEFAULT_LNA_STATES, select_lna_state
from mmw60.vendor.wifitrx.units import dbm_to_mw

FLAT = ChannelConfig(model="flat")


def anchored(cfg, **kw):
    return dc.replace(cfg, frontend=dc.replace(cfg.frontend, rx_front=RxFrontConfig(model="anchored", **kw)))


# ------------------------------------------------------------------ the presets are untouched
def test_law2_presets_keep_the_wifitrx_ladder_and_say_it_is_not_a_60ghz_figure():
    cfg = zero_if_60ghz(k=8)
    assert cfg.frontend.rx_front == RxFrontConfig()
    assert (cfg.frontend.antenna_gain_rx_dbi, cfg.frontend.tx_rx_isolation_db) == (None, None)
    fe = Frontend60.from_config(cfg)
    assert fe.rx_front.model == "wifi7_ladder" and not fe.rx_front.sourced
    assert fe.rx_front.states is DEFAULT_LNA_STATES
    sim = LinkSim(cfg, frontend=fe)
    assert sim.rx.params.lna_states == DEFAULT_LNA_STATES
    f = fe.faces()
    assert f["rx_front_sourced"] is False and f["tx_rx_isolation_db"] is None
    assert f["shared_antenna"] and f["antenna_gain_rx_dbi"] == f["antenna_gain_tx_dbi"] == cfg.frontend.antenna_gain_dbi
    assert fe.leakage_budget() is None and fe.tx_leak_at_rx_dbm() is None
    # the reports built on describe() keep their shape
    assert not {"rx_front", "rx_nf_db", "rx_iip3_dbm", "tx_rx_isolation_db", "antenna_gain_rx_dbi"} & set(fe.describe())


def test_law2_the_chain_runs_on_the_shared_front_ends_ladder():
    """What the link's receiver uses is the front end's own ladder object, not a
    second table built from the same numbers."""
    cfg = surveyed_frontend(zero_if_60ghz(k=8))
    fe = Frontend60.from_config(cfg)
    sim = LinkSim(cfg, frontend=fe)
    assert sim.frontend is fe and sim.rx.params.lna_states is fe.rx_front.states
    assert sim.rx.params.lna_states[0].nf_db == fe.rx_front.nf_db != DEFAULT_LNA_STATES[0].nf_db


# ------------------------------------------------------------------ the anchored ladder
def test_anchored_ladder_is_the_wifitrx_ladder_moved_as_a_whole():
    top = DEFAULT_LNA_STATES[0]
    f = RxFront60.anchored(nf_db=top.nf_db + 2.5, iip3_dbm=top.iip3_dbm + 4.0, gain_db=top.gain_db - 3.0)
    assert (f.nf_db, f.iip3_dbm, f.gain_db) == (top.nf_db + 2.5, top.iip3_dbm + 4.0, top.gain_db - 3.0)
    assert f.sourced and f.anchored_fields == ("nf_db", "iip3_dbm", "gain_db")
    for a, b in zip(DEFAULT_LNA_STATES, f.states):
        assert b.nf_db == pytest.approx(a.nf_db + 2.5) and b.iip3_dbm == pytest.approx(a.iip3_dbm + 4.0)
        assert b.gain_db == pytest.approx(a.gain_db - 3.0)
        # hand-over: with the compression (IIP3), against the gain
        assert b.max_input_dbm == pytest.approx(a.max_input_dbm + 4.0 + 3.0)
    # the hand-over levels stay in order, so wifitrx's AGC walks the ladder as before
    assert [s.max_input_dbm for s in f.states] == sorted(s.max_input_dbm for s in f.states)


def test_anchored_with_nothing_given_is_wifitrx_and_says_so():
    f = RxFront60.anchored()
    assert f.states == DEFAULT_LNA_STATES and not f.sourced and f.anchored_fields == ()
    only_nf = RxFront60.anchored(nf_db=6.0)
    assert only_nf.anchored_fields == ("nf_db",) and only_nf.iip3_dbm == DEFAULT_LNA_STATES[0].iip3_dbm


def test_state_for_is_wifitrx_agc_on_this_ladder():
    f = RxFront60.anchored(nf_db=8.0, iip3_dbm=-15.0)
    for p in (-90.0, -40.0, -30.0, -13.0, 0.0):
        i, st = f.state_for(p)
        assert i == select_lna_state(f.states, p) and st is f.states[i]
    assert f.state_for(-90.0)[0] == 0


def test_input_p1db_is_where_the_chains_own_nonlinearity_compresses_1_db():
    """The face says IIP3 − 9.6 dB (assumed.rx60_p1db_from_iip3_db); the chain's
    receiver at that level must lose 1 dB of gain."""
    cfg = surveyed_frontend(zero_if_60ghz(k=8))
    fe = Frontend60.from_config(cfg)
    rx = LinkSim(cfg, frontend=fe).rx
    nl = rx.params.nonlin_for_state(0)
    x = np.full(64, np.sqrt(dbm_to_mw(fe.rx_front.p1db_in_dbm)), dtype=complex)
    small = np.full(64, np.sqrt(dbm_to_mw(fe.rx_front.p1db_in_dbm - 60.0)), dtype=complex)
    gain = lambda v: 20 * np.log10(np.abs(nl.apply(v)[0]) / np.abs(v[0]))            # noqa: E731
    assert gain(small) - gain(x) == pytest.approx(1.0, abs=0.05)
    assert fe.rx_front.p1db_in_dbm == fe.rx_front.iip3_dbm - spec.value("assumed.rx60_p1db_from_iip3_db")


# ------------------------------------------------------------------ what the noise figure moves
def test_noise_figure_moves_the_sensitivity_db_for_db_and_not_the_evm_on_the_snr_axis():
    base = zero_if_60ghz(k=8)
    lo, hi = (dc.replace(anchored(base, nf_db=nf), channel=FLAT) for nf in (5.0, 11.0))
    s = [LinkSim(c).rx_input_dbm_for_snr(10.0) for c in (lo, hi)]
    assert s[1] - s[0] == pytest.approx(6.0, abs=1e-9)
    e = [evm_at(c, 10.0, n_packets=1)["evm_db"] for c in (lo, hi)]
    assert e[1] == pytest.approx(e[0], abs=0.02)


# ------------------------------------------------------------------ isolation and antennas
def test_leakage_budget_arithmetic():
    cfg = surveyed_frontend(zero_if_60ghz(k=8))
    fe = Frontend60.from_config(cfg)
    b = fe.leakage_budget()
    assert b["pout_dbm"] == fe.target_pout_dbm() and b["isolation_db"] == cfg.frontend.tx_rx_isolation_db
    assert b["leak_at_rx_dbm"] == b["pout_dbm"] - b["isolation_db"] == fe.tx_leak_at_rx_dbm()
    assert b["margin_to_p1db_db"] == fe.rx_front.p1db_in_dbm - b["leak_at_rx_dbm"]
    assert b["dmg_max_input_dbm"] == spec.value("survey.dmg_rx_max_input_dbm")
    assert b["margin_to_dmg_max_input_db"] == b["dmg_max_input_dbm"] - b["leak_at_rx_dbm"]
    assert fe.leakage_budget(pout_dbm=0.0)["leak_at_rx_dbm"] == -cfg.frontend.tx_rx_isolation_db
    more = dc.replace(fe, tx_rx_isolation_db=fe.tx_rx_isolation_db + 10.0).leakage_budget()
    assert more["margin_to_p1db_db"] == pytest.approx(b["margin_to_p1db_db"] + 10.0)


def test_receive_antenna_is_the_transmit_antenna_until_it_is_given():
    base = zero_if_60ghz(k=8)
    one = Frontend60.from_config(dc.replace(base, frontend=dc.replace(base.frontend, antenna_gain_dbi=5.0)))
    assert one.shared_antenna and one.antenna_gain_rx_resolved_dbi == one.antenna_gain_tx_dbi == 5.0
    two = Frontend60.from_config(dc.replace(base, frontend=dc.replace(base.frontend, antenna_gain_dbi=5.0,
                                                                     antenna_gain_rx_dbi=2.0)))
    assert not two.shared_antenna and (two.antenna_gain_tx_dbi, two.antenna_gain_rx_resolved_dbi) == (5.0, 2.0)
    # the EIRP check reads the transmit antenna only
    assert two.describe()["eirp_avg_dbm"] == one.describe()["eirp_avg_dbm"]


# ------------------------------------------------------------------ config (iron rule 1) and sources (iron rule 5)
def test_law1_surveyed_front_end_is_built_from_spec_entries_only():
    pick = spec.value("assumed.frontend_faces_pick")
    cfg = surveyed_frontend(zero_if_60ghz(k=8))
    fe = cfg.frontend
    assert (fe.rx_front.model, fe.rx_front.nf_db, fe.rx_front.iip3_dbm, fe.rx_front.gain_db) == \
        ("anchored", pick["rx_nf_db"], pick["rx_iip3_dbm"], None)
    assert (fe.tx_rx_isolation_db, fe.antenna_gain_dbi, fe.antenna_gain_rx_dbi) == \
        (pick["tx_rx_isolation_db"], pick["antenna_gain_tx_dbi"], pick["antenna_gain_rx_dbi"])
    # the pick is made of the surveyed figures it names, not of new ones
    comm = spec.value("survey.rx60_comm_asada2011")
    iso = spec.value("survey.tx_rx_isolation_tue2018")
    assert (pick["rx_nf_db"], pick["rx_iip3_dbm"]) == (comm["nf_db"], comm["iip3_dbm"])
    assert pick["tx_rx_isolation_db"] == iso["with_ebg_db"] - iso["improvement_max_db"]
    assert pick["antenna_gain_tx_dbi"] == pick["antenna_gain_rx_dbi"] == spec.value("survey.antenna60_okada2013_dbi")
    # everything else is the preset's
    assert dc.replace(cfg, frontend=zero_if_60ghz(k=8).frontend, label="") == dc.replace(zero_if_60ghz(k=8), label="")
    assert Mmw60Config.from_dict(cfg.to_dict()) == cfg


def test_law1_no_front_end_figure_is_typed_outside_the_spec_file():
    figures = ("6.1", "7.1", "-33", "9.6", "-12")
    whole = ("40", "20", "25")              # the isolation figures; frontend.py has an older "-20 / 20" of its own
    for rel, forbidden_here in (("examples/08_frontend_faces.py", figures + whole),
                                ("src/mmw60/frontend/rxfront.py", figures + whole),
                                ("src/mmw60/frontend/frontend.py", figures)):
        src = (REPO / rel).read_text()
        code = "\n".join(line.split("#")[0] for line in src.splitlines())
        for forbidden in forbidden_here:
            # a numeric literal, not a format width (":7.1f") or part of a longer number / name
            hit = re.search(rf"(?<![\w.:{{]){re.escape(forbidden)}(?![\w.])", code)
            assert hit is None, f"{rel} types a literature number: {forbidden}"


def test_law5_every_d4_literature_figure_is_marked_unverified():
    keys = ("survey.rx60_comm_asada2011", "survey.rx60_comm_iscas2015", "survey.dmg_sensitivity_assumptions",
            "survey.dmg_rx_max_input_dbm", "survey.rx60_radar_iwr6843", "survey.tx_rx_isolation_tue2018",
            "survey.antenna60_okada2013_dbi", "survey.antenna60_bgt60_an600_dbi")
    for k in keys:
        e = spec.survey(k)
        assert e.source == "survey" and "未核实" in e.note, k
    for k in ("assumed.rx60_ladder_shape", "assumed.rx60_p1db_from_iip3_db", "assumed.frontend_faces_pick"):
        assert spec.survey(k).source == "assumed", k


@pytest.mark.parametrize("front, message", [
    (RxFrontConfig(model="measured"), "rx_front.model"),
    (RxFrontConfig(nf_db=6.0), "anchored"),
    (RxFrontConfig(model="wifi7_ladder", iip3_dbm=-20.0), "anchored"),
])
def test_config_refuses_an_inconsistent_receive_front_end(front, message):
    base = zero_if_60ghz(k=8)
    with pytest.raises(ValueError, match=message):
        dc.replace(base, frontend=dc.replace(base.frontend, rx_front=front))


def test_config_refuses_a_negative_isolation_and_a_negative_noise_figure():
    base = zero_if_60ghz(k=8)
    with pytest.raises(ValueError, match="isolation"):
        dc.replace(base, frontend=dc.replace(base.frontend, tx_rx_isolation_db=-1.0))
    with pytest.raises(ValueError, match="nf_db"):
        RxFront60.anchored(nf_db=-0.5)
