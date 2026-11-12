"""The 60 GHz PA against measured 60 GHz CMOS PAs (data/spec: pa60.*):
``config.surveyed_pa`` and the Rapp smoothness ``frontend.pa.rapp_p``.

Since 2026-11-12 the topology A / B presets (``zero_if_60ghz`` and those built
on it) carry the measured PA; Liu's preset (``liu2025_table2``, examples 00 /
01, the fingerprint's configs) keeps the 11ad evaluation methodology's shape,
and ``tgad_em_pa`` puts that shape back on any config."""
import dataclasses as dc
import re

import numpy as np
import pytest

from conftest import REPO
from mmw60 import spec
from mmw60.config import (Mmw60Config, if_extender_60ghz, liu2025_table2, surveyed_pa, tgad_em_pa,
                          wifi7_chain_k1, zero_if_60ghz)
from mmw60.frontend import Frontend60
from mmw60.frontend.grid import pa_isolated_evm_db
from mmw60.pa.rapp import ModifiedRappPA
from mmw60.sim.link import LinkSim


def gap_db(m: ModifiedRappPA) -> float:
    return float(10 * np.log10(m.p_sat / m.p1db))


# ------------------------------------------------------------------ which preset carries which PA
def test_liu_preset_keeps_the_11ad_shape():
    cfg = liu2025_table2(k=8, mcs=0)
    assert cfg.frontend.pa.rapp_p is None
    beh = LinkSim(cfg)
    assert beh.pa.p == spec.value("tgad_em.pa_rapp_p")
    assert gap_db(beh.pa) == pytest.approx(spec.value("derived.rapp_p1db_below_psat_db"), abs=0.05)


def test_topology_a_and_b_presets_carry_the_measured_pa():
    for cfg in (zero_if_60ghz(k=8), zero_if_60ghz(k=4, standard="11be", bandwidth_hz=80e6), wifi7_chain_k1(),
                if_extender_60ghz()):
        assert cfg.frontend == surveyed_pa(cfg).frontend, cfg.label
    # Liu's back-off is kept, from Psat
    assert zero_if_60ghz(k=8).frontend.pa.obo_db == liu2025_table2(k=8).frontend.pa.obo_db
    assert zero_if_60ghz(k=8).frontend.pa.obo_reference == "psat"


def test_tgad_em_pa_is_the_presets_pa_before_the_switch():
    cfg = tgad_em_pa(zero_if_60ghz(k=8))
    fe = Frontend60.from_config(cfg)
    assert cfg.frontend.pa.rapp_p is None and fe.pa_model.p == spec.value("tgad_em.pa_rapp_p")
    assert (cfg.frontend.psat_dbm, cfg.frontend.pa_gain_db, cfg.frontend.pa_pae_max) == (
        spec.value("assumed.pa60_psat_dbm"), spec.value("assumed.pa60_gain_db"), spec.value("assumed.pa60_pae_max"))
    # the two helpers undo each other on the PA and touch nothing else
    back = surveyed_pa(cfg)
    assert back.frontend == zero_if_60ghz(k=8).frontend
    assert Mmw60Config.from_dict(cfg.to_dict()) == cfg


def test_the_behavioural_path_reads_the_smoothness_too():
    cfg = liu2025_table2(k=8, mcs=0)
    cfg = dc.replace(cfg, frontend=dc.replace(cfg.frontend, pa=dc.replace(cfg.frontend.pa, rapp_p=2.0)))
    assert LinkSim(cfg).pa.p == 2.0


# ------------------------------------------------------------------ the surveyed PA
def test_surveyed_pa_is_built_from_spec_entries_only():
    pick = spec.value("assumed.pa60_surveyed_pick")
    src = spec.value(pick["source"])
    base = liu2025_table2(k=8, mcs=0)
    cfg = surveyed_pa(base)
    fe = cfg.frontend
    assert (fe.psat_dbm, fe.pa_gain_db, fe.pa_pae_max) == (src["psat_dbm"], src["gain_db"], src["pae_peak"])
    assert fe.pa.rapp_p == spec.value(pick["rapp_p"])
    # back-off, reference, AM/PM and everything else stay the config's
    assert (fe.pa.obo_db, fe.pa.obo_reference, fe.pa.ampm) == (base.frontend.pa.obo_db, base.frontend.pa.obo_reference,
                                                               base.frontend.pa.ampm)
    same = dc.replace(fe, pa=base.frontend.pa, psat_dbm=base.frontend.psat_dbm, pa_gain_db=base.frontend.pa_gain_db,
                      pa_pae_max=base.frontend.pa_pae_max)
    assert dc.replace(cfg, frontend=same, label="") == dc.replace(base, label="")
    assert Mmw60Config.from_dict(cfg.to_dict()) == cfg


def test_surveyed_pa_reads_the_papers_psat_p1db_and_gain_in_dbm():
    src = spec.value("pa60.asada_eumc2011")
    fe = Frontend60.from_config(zero_if_60ghz(k=8))
    pa = fe.scaled_pa()
    assert pa.psat_dbm == src["psat_dbm"] and pa.gain_db == src["gain_db"]
    assert pa.p1db_out_dbm == pytest.approx(src["p1db_dbm"], abs=0.02)
    # small-signal gain read off the AM/AM, far below compression
    assert float(pa.am_am(-60.0)) - (-60.0) == pytest.approx(src["gain_db"], abs=0.01)


def test_derived_smoothness_follows_its_formula():
    src = spec.value("pa60.asada_eumc2011")
    p = spec.value("derived.pa60_rapp_p_asada_eumc2011")
    assert gap_db(ModifiedRappPA(p=p)) == pytest.approx(src["psat_dbm"] - src["p1db_dbm"], abs=0.01)
    # larger p, more abrupt compression: P1dB closer to Psat
    assert gap_db(ModifiedRappPA(p=p + 0.2)) < gap_db(ModifiedRappPA(p=p)) < gap_db(ModifiedRappPA())


def test_at_the_presets_back_off_the_measured_shape_is_the_more_linear_one():
    """8 dB from Psat puts the 11ad shape above its P1dB and the measured one
    below; counted from P1dB instead, the two shapes are within 1.5 dB."""
    obo = zero_if_60ghz(k=8).frontend.pa.obo_db
    p = spec.value("derived.pa60_rapp_p_asada_eumc2011")
    preset, measured = ModifiedRappPA(), ModifiedRappPA(p=p)
    assert pa_isolated_evm_db(measured, obo, "psat") < pa_isolated_evm_db(preset, obo, "psat") - 3.0
    assert abs(pa_isolated_evm_db(measured, obo, "p1db") - pa_isolated_evm_db(preset, obo, "p1db")) < 1.5


def test_config_refuses_a_non_positive_smoothness():
    base = zero_if_60ghz(k=8)
    with pytest.raises(ValueError, match="rapp_p"):
        dc.replace(base, frontend=dc.replace(base.frontend, pa=dc.replace(base.frontend.pa, rapp_p=0.0)))


# ------------------------------------------------------------------ sources (iron rules 1 and 5)
def test_pa_figures_read_in_the_original_carry_their_quote():
    for key, figures in (("pa60.asada_eumc2011", ("23.2 dB", "10 dBm", "14.6 dBm", "16.3 %", "7.9 %")),
                         ("pa60.wu_asscc2012", ("13.2 dBm", "10.2 dBm", "15.0%")),
                         ("pa60.ning_elex2011", ("11.7 dBm", "9.4 dBm", "14.3%", "12.0%")),
                         ("rx60.comm_asada2011", ("16 dB", "5.4 dBm"))):
        e = spec.survey(key)
        assert e.source == "spec" and e.section, key
        for f in figures:
            assert f in e.quote, (key, f)
    t1 = spec.value("pa60.eumc2011_table1")
    this = dict(zip(t1["columns"], t1["rows"][-1]))
    a = spec.value("pa60.asada_eumc2011")
    assert (this["gain_db"], this["p1db_dbm"], this["psat_dbm"]) == (a["gain_db"], a["p1db_dbm"], a["psat_dbm"])
    assert this["pae_peak_pct"] == pytest.approx(100 * a["pae_peak"])
    assert spec.survey("assumed.pa60_surveyed_pick").source == "assumed"
    assert spec.survey("derived.pa60_rapp_p_asada_eumc2011").source == "derived"


def test_law1_no_pa_figure_is_typed_outside_the_spec_file():
    for rel in ("examples/09_pa_against_the_literature.py", "src/mmw60/config.py"):
        code = "\n".join(line.split("#")[0] for line in (REPO / rel).read_text().splitlines())
        for forbidden in ("14.6", "23.2", "16.3", "1.286", "13.2", "11.7"):
            hit = re.search(rf"(?<![\w.:{{]){re.escape(forbidden)}(?![\w.])", code)
            assert hit is None, f"{rel} types a literature number: {forbidden}"
