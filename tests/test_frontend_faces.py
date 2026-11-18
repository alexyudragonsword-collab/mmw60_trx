"""ROADMAP D4 / C9: the receive front end, the TX-RX isolation and the two
antenna gains as faces of the shared ``Frontend60``.

Since 2026-11-18 (C9) the 60 GHz presets carry a 60 GHz receive front end
and that transceiver's antenna; the isolation stays off them, and the 6 GHz
K = 1 row keeps wifitrx's own ladder and an unspecified (0 dBi) antenna."""
import dataclasses as dc
import re

import numpy as np
import pytest

from conftest import REPO
from mmw60 import spec
from mmw60.config import (ChannelConfig, Mmw60Config, RxFrontConfig, ay_60ghz, if_extender_60ghz, liu2025_table2,
                          surveyed_antenna_gain_dbi, surveyed_frontend, surveyed_rx_front, unspecified_antenna,
                          wifi7_chain_k1, wifi7_rx_ladder, zero_if_60ghz)
from mmw60.frontend import Frontend60
from mmw60.frontend.rxfront import RxFront60
from mmw60.sim.link import LinkSim, evm_at
from mmw60.vendor.wifitrx.chain.agc import DEFAULT_LNA_STATES, rebalance_thresholds, select_lna_state
from mmw60.vendor.wifitrx.units import dbm_to_mw

FLAT = ChannelConfig(model="flat")


def anchored(cfg, **kw):
    return dc.replace(cfg, frontend=dc.replace(cfg.frontend, rx_front=RxFrontConfig(model="anchored", **kw)))


# ------------------------------------------------------------------ what the presets carry
def test_law2_presets_carry_the_60ghz_receive_front_end_and_antenna_and_not_the_isolation():
    """ROADMAP C9: every 60 GHz preset has one receive front end and one
    antenna (transmit and receive, a TDD link), both read from the spec
    entries; the isolation is not in the presets."""
    take = spec.value("assumed.preset_rx_front")
    pick = spec.value(take["from"])
    assert take["from"] == "assumed.frontend_faces_pick" and take["fields"] == ["rx_nf_db", "rx_iip3_dbm", "rx_gain_db"]
    want = RxFrontConfig(model="anchored", nf_db=pick["rx_nf_db"], iip3_dbm=pick["rx_iip3_dbm"],
                         gain_db=pick["rx_gain_db"])
    assert surveyed_rx_front() == want
    ant = spec.value("assumed.preset_antenna")
    assert (ant["from"], ant["field"]) == ("assumed.frontend_faces_pick", "antenna_gain_tx_dbi")
    assert surveyed_antenna_gain_dbi() == pick["antenna_gain_tx_dbi"]
    assert pick["antenna_gain_tx_dbi"] == spec.value("rx60.comm_asada2011")["antenna_gain_dbi"]
    presets = (zero_if_60ghz(k=8), zero_if_60ghz(k=4, standard="11be", bandwidth_hz=80e6), if_extender_60ghz(),
               if_extender_60ghz(k=4, bandwidth_hz=20e6), ay_60ghz("ay_sc"), ay_60ghz("ay_ofdm"))
    for cfg in presets:
        assert cfg.frontend.rx_front == want, cfg.label
        assert (cfg.frontend.antenna_gain_dbi, cfg.frontend.antenna_gain_rx_dbi, cfg.frontend.tx_rx_isolation_db) \
            == (pick["antenna_gain_tx_dbi"], None, None), cfg.label
    cfg = presets[0]
    fe = Frontend60.from_config(cfg)
    assert fe.rx_front.sourced and fe.rx_front.anchored_fields == ("nf_db", "iip3_dbm", "gain_db")
    assert (fe.rx_front.nf_db, fe.rx_front.iip3_dbm, fe.rx_front.gain_db) == \
        (pick["rx_nf_db"], pick["rx_iip3_dbm"], pick["rx_gain_db"])
    sim = LinkSim(cfg, frontend=fe)
    assert sim.rx.params.lna_states is fe.rx_front.states and sim.rx.params.lna_states != DEFAULT_LNA_STATES
    f = fe.faces()
    assert f["rx_front_sourced"] is True and f["tx_rx_isolation_db"] is None
    assert f["shared_antenna"] and f["antenna_gain_rx_dbi"] == f["antenna_gain_tx_dbi"] == cfg.frontend.antenna_gain_dbi
    assert f["antenna_gain_tx_dbi"] == pick["antenna_gain_tx_dbi"] > 0
    # the EIRP check and an array's elements read the same figure
    assert fe.describe()["eirp_avg_dbm"] == pytest.approx(fe.target_pout_dbm() + pick["antenna_gain_tx_dbi"])
    from mmw60.config import array_frontend
    from mmw60.frontend.array60 import Array60
    acfg = array_frontend(cfg, 16)
    arr = Array60.from_config(acfg, Frontend60.from_config(acfg))
    assert (arr.element_gain_tx_dbi, arr.element_gain_rx_dbi) == (pick["antenna_gain_tx_dbi"],) * 2
    assert fe.leakage_budget() is None and fe.tx_leak_at_rx_dbm() is None
    # the reports built on describe() keep their shape
    assert not {"rx_front", "rx_nf_db", "rx_iip3_dbm", "tx_rx_isolation_db", "antenna_gain_rx_dbi"} & set(fe.describe())
    # surveyed_frontend adds the isolation and leaves the receive front end and the gains as the presets have them
    full = surveyed_frontend(cfg)
    assert full.frontend.rx_front == want
    assert (full.frontend.antenna_gain_dbi, full.frontend.antenna_gain_rx_dbi, full.frontend.tx_rx_isolation_db) == \
        (pick["antenna_gain_tx_dbi"], pick["antenna_gain_rx_dbi"], pick["tx_rx_isolation_db"])


def test_law2_the_wifi7_ladder_is_still_wifitrx_own_on_the_k1_row_and_as_a_sensitivity_row():
    """The 6 GHz K = 1 row is the WiFi 7 chip and keeps the chip's ladder
    (assumed.preset_rx_front: k1_row_at_6ghz); ``wifi7_rx_ladder`` puts it
    back on a 60 GHz preset (the presets before 2026-11-18); Liu's preset
    never had a front-end ladder to change."""
    assert spec.value("assumed.preset_rx_front")["k1_row_at_6ghz"] == "wifi7_ladder"
    assert spec.value("assumed.preset_antenna")["k1_row_at_6ghz"].startswith("0 dBi")
    k1 = wifi7_chain_k1().frontend
    assert (k1.antenna_gain_dbi, k1.antenna_gain_rx_dbi) == (0.0, None)
    bare = unspecified_antenna(zero_if_60ghz(k=8))
    assert (bare.frontend.antenna_gain_dbi, bare.frontend.antenna_gain_rx_dbi) == (0.0, None)
    back = dc.replace(bare.frontend, antenna_gain_dbi=surveyed_antenna_gain_dbi())
    assert dc.replace(bare, label="", frontend=back) == dc.replace(zero_if_60ghz(k=8), label="")
    for cfg in (wifi7_chain_k1(), wifi7_rx_ladder(zero_if_60ghz(k=8)), wifi7_rx_ladder(ay_60ghz("ay_sc")),
                liu2025_table2()):
        assert cfg.frontend.rx_front == RxFrontConfig(), cfg.label
        fe = Frontend60.from_config(cfg)
        assert fe.rx_front.model == "wifi7_ladder" and not fe.rx_front.sourced
        assert fe.rx_front.states is DEFAULT_LNA_STATES
    cfg = wifi7_rx_ladder(zero_if_60ghz(k=8))
    sim = LinkSim(cfg)
    assert sim.rx.params.lna_states == DEFAULT_LNA_STATES
    # nothing else of the preset moves with the ladder
    assert dc.replace(cfg, label="", frontend=dc.replace(cfg.frontend, rx_front=surveyed_rx_front())) == \
        dc.replace(zero_if_60ghz(k=8), label="")


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
    # the hand-over levels stay in order, so wifitrx's AGC walks the ladder as before
    assert [s.max_input_dbm for s in f.states] == sorted(s.max_input_dbm for s in f.states)


def test_anchored_hand_over_levels_follow_wifitrx_balance_point_rule():
    """wifitrx re-solves the hand-over levels with ``rebalance_thresholds`` after
    a NF / IIP3 what-if; the anchored ladder's levels must move by what that
    rule moves them (its own rounding to 0.1 dB aside), and not with the gain."""
    top = DEFAULT_LNA_STATES[0]
    d_nf, d_ip3 = 2.5, 4.0
    f = RxFront60.anchored(nf_db=top.nf_db + d_nf, iip3_dbm=top.iip3_dbm + d_ip3)
    theirs_before = rebalance_thresholds(DEFAULT_LNA_STATES)
    theirs_after = rebalance_thresholds(f.states)
    for a, b, t0, t1 in zip(DEFAULT_LNA_STATES[:-1], f.states[:-1], theirs_before, theirs_after):
        assert b.max_input_dbm - a.max_input_dbm == pytest.approx((2 * d_ip3 + d_nf) / 3)
        assert b.max_input_dbm - a.max_input_dbm == pytest.approx(t1.max_input_dbm - t0.max_input_dbm, abs=0.11)
    # the last state's ceiling is kept, as theirs is
    assert f.states[-1].max_input_dbm == DEFAULT_LNA_STATES[-1].max_input_dbm == theirs_after[-1].max_input_dbm
    # the gain does not enter
    g = RxFront60.anchored(nf_db=top.nf_db + d_nf, iip3_dbm=top.iip3_dbm + d_ip3, gain_db=top.gain_db - 10.0)
    assert [s.max_input_dbm for s in g.states] == [s.max_input_dbm for s in f.states]


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
    x = np.full(64, np.sqrt(dbm_to_mw(fe.rx_front.p1db_inband_dbm)), dtype=complex)
    small = np.full(64, np.sqrt(dbm_to_mw(fe.rx_front.p1db_inband_dbm - 60.0)), dtype=complex)
    gain = lambda v: 20 * np.log10(np.abs(nl.apply(v)[0]) / np.abs(v[0]))            # noqa: E731
    assert gain(small) - gain(x) == pytest.approx(1.0, abs=0.05)
    assert fe.rx_front.p1db_inband_dbm == fe.rx_front.iip3_dbm - spec.value("assumed.rx60_p1db_from_iip3_db")


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
    assert b["margin_to_p1db_inband_db"] == fe.rx_front.p1db_inband_dbm - b["leak_at_rx_dbm"]
    assert b["dmg_max_input_dbm"] == spec.value("dmg.rx_max_input_dbm")
    assert b["margin_to_dmg_max_input_db"] == b["dmg_max_input_dbm"] - b["leak_at_rx_dbm"]
    assert fe.leakage_budget(pout_dbm=0.0)["leak_at_rx_dbm"] == -cfg.frontend.tx_rx_isolation_db
    more = dc.replace(fe, tx_rx_isolation_db=fe.tx_rx_isolation_db + 10.0).leakage_budget()
    assert more["margin_to_p1db_inband_db"] == pytest.approx(b["margin_to_p1db_inband_db"] + 10.0)


def test_the_two_compression_points_are_separate_faces_and_one_never_stands_in_for_the_other():
    """A radar's leakage meets the stages before the baseband high-pass; a
    front end that does not state that figure has no margin to report for it —
    the in-band figure (from the IIP3) is a different number."""
    cfg = surveyed_frontend(zero_if_60ghz(k=8))
    fe = Frontend60.from_config(cfg)
    assert cfg.frontend.rx_front.p1db_oob_dbm is None and fe.rx_front.p1db_oob_dbm is None
    b = fe.leakage_budget()
    assert b["rx_p1db_oob_dbm"] is None and b["margin_to_p1db_oob_db"] is None
    assert b["margin_to_p1db_inband_db"] is not None
    assert fe.faces()["rx_p1db_oob_dbm"] is None and fe.faces()["rx_p1db_inband_dbm"] == fe.rx_front.p1db_inband_dbm
    # given, it is carried as given and does not touch the chain or the in-band figure
    radar = spec.value("rx60.radar_iwr6843")
    given = dc.replace(cfg, frontend=dc.replace(cfg.frontend, rx_front=dc.replace(
        cfg.frontend.rx_front, p1db_oob_dbm=radar["p1db_in_oob_dbm"])))
    fe2 = Frontend60.from_config(given)
    b2 = fe2.leakage_budget()
    assert b2["rx_p1db_oob_dbm"] == radar["p1db_in_oob_dbm"]
    assert b2["margin_to_p1db_oob_db"] == radar["p1db_in_oob_dbm"] - b2["leak_at_rx_dbm"]
    assert b2["margin_to_p1db_inband_db"] == b["margin_to_p1db_inband_db"]
    assert fe2.rx_front.states == fe.rx_front.states and "p1db_oob_dbm" in fe2.rx_front.anchored_fields
    assert Mmw60Config.from_dict(given.to_dict()) == given


def test_in_band_compression_moves_with_the_gain_state():
    fe = Frontend60.from_config(surveyed_frontend(zero_if_60ghz(k=8)))
    table = fe.rx_front.p1db_inband_by_gain()
    assert len(table) == len(fe.rx_front.states) and table[0] == (fe.rx_front.gain_db, fe.rx_front.p1db_inband_dbm)
    off = spec.value("assumed.rx60_p1db_from_iip3_db")
    assert [p for _, p in table] == [st.iip3_dbm - off for st in fe.rx_front.states]
    # lower gain, higher compression point: the direction the radar chip's datasheet figure shows
    assert [g for g, _ in table] == sorted((g for g, _ in table), reverse=True)
    assert [p for _, p in table] == sorted(p for _, p in table)
    fig = spec.value("rx60.radar_iwr6843_fig7_2")
    assert fig["gain_db"] == sorted(fig["gain_db"])
    assert fig["p1db_inband_dbm"] == sorted(fig["p1db_inband_dbm"], reverse=True)
    # the same chip's out-of-band figure is far above every in-band one
    assert spec.value("rx60.radar_iwr6843")["p1db_in_oob_dbm"] > max(fig["p1db_inband_dbm"]) + 10.0


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
        ("anchored", pick["rx_nf_db"], pick["rx_iip3_dbm"], pick["rx_gain_db"])
    assert (fe.tx_rx_isolation_db, fe.antenna_gain_dbi, fe.antenna_gain_rx_dbi) == \
        (pick["tx_rx_isolation_db"], pick["antenna_gain_tx_dbi"], pick["antenna_gain_rx_dbi"])
    # the pick is made of the figures it names, not of new ones: one communication
    # transceiver's receiver and antenna, read in the original
    comm = spec.survey("rx60.comm_asada2011")
    assert comm.source == "spec"
    assert (pick["rx_nf_db"], pick["rx_iip3_dbm"], pick["rx_gain_db"]) == \
        (comm.value["nf_db"], comm.value["iip3_dbm"], comm.value["gain_high_db"])
    assert pick["antenna_gain_tx_dbi"] == pick["antenna_gain_rx_dbi"] == comm.value["antenna_gain_dbi"]
    iso = spec.value("isolation.tx_rx_tue2018")
    assert pick["tx_rx_isolation_db"] == iso["with_ebg_db"] - iso["improvement_max_db"]
    # everything else is the preset's
    assert dc.replace(cfg, frontend=zero_if_60ghz(k=8).frontend, label="") == dc.replace(zero_if_60ghz(k=8), label="")
    assert Mmw60Config.from_dict(cfg.to_dict()) == cfg


def test_law1_no_front_end_figure_is_typed_outside_the_spec_file():
    figures = ("6.1", "7.1", "-33", "9.6", "-12")
    # the isolation and gain figures; frontend.py has an older "-20 / 20" of its own
    whole = ("40", "20", "25", "27", "17")
    for rel, forbidden_here in (("examples/08_frontend_faces.py", figures + whole),
                                ("src/mmw60/frontend/rxfront.py", figures + whole),
                                ("src/mmw60/frontend/frontend.py", figures)):
        src = (REPO / rel).read_text()
        code = "\n".join(line.split("#")[0] for line in src.splitlines())
        for forbidden in forbidden_here:
            # a numeric literal, not a format width (":7.1f") or part of a longer number / name
            hit = re.search(rf"(?<![\w.:{{]){re.escape(forbidden)}(?![\w.])", code)
            assert hit is None, f"{rel} types a literature number: {forbidden}"


def test_law5_d4_figures_are_all_read_in_the_original_and_carry_the_quote():
    # dmg.sensitivity_assumptions: read in the original since spec_sources#29 (2026-11-16); the ISCAS 2015
    # receiver and the Okada antenna since spec_sources 0.6.0 (mmw60_trx#63), values unchanged
    read = ("rx60.comm_asada2011", "rx60.radar_iwr6843", "rx60.radar_iwr6843_fig7_2", "isolation.tx_rx_tue2018",
            "dmg.rx_max_input_dbm", "dmg.sensitivity_assumptions", "rx60.comm_iscas2015", "antenna60.okada2013_dbi")
    # withdrawn by the party that supplied it: the application note it cited holds no antenna gain
    assert "survey.antenna60_bgt60_an600_dbi" not in spec.all_entries()
    for k in read:
        e = spec.survey(k)
        assert e.source == "spec" and e.quote and e.section, k
    # the quoted text holds the figures the entry carries
    comm = spec.survey("rx60.comm_asada2011").quote
    assert "6.1 dB" in comm and "27 dB" in comm and "2dBi" in comm
    assert "−33 dBm" in spec.survey("dmg.rx_max_input_dbm").quote
    assert "40 dB" in spec.survey("isolation.tx_rx_tue2018").quote
    assert "12 dB" in spec.survey("rx60.radar_iwr6843").quote
    sens = spec.survey("dmg.sensitivity_assumptions")
    assert "5 dB implementation loss" in sens.quote and "10 dB noise factor" in sens.quote
    assert sens.value == {"nf_db": 10.0, "implementation_loss_db": 5.0}
    # the ISCAS 2015 figure is a double-sideband NF of a superheterodyne receiver: example 08 says so and adds
    # the single-sideband row (assumed.rx_nf_dsb_to_ssb_db)
    iscas = spec.survey("rx60.comm_iscas2015")
    assert "double-side-band NF of 7.1dB" in iscas.quote and iscas.value["nf_db"] == 7.1
    for k in ("assumed.rx60_ladder_shape", "assumed.rx60_p1db_from_iip3_db", "assumed.frontend_faces_pick"):
        assert spec.survey(k).source == "assumed", k


@pytest.mark.parametrize("front, message", [
    (RxFrontConfig(model="measured"), "rx_front.model"),
    (RxFrontConfig(nf_db=6.0), "anchored"),
    (RxFrontConfig(model="wifi7_ladder", iip3_dbm=-20.0), "anchored"),
    (RxFrontConfig(p1db_oob_dbm=-12.0), "anchored"),
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
