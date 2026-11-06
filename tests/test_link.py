"""The packet runner and the PER sweep: the AWGN anchor against the BCC union
bound (analytic / simulated cross-check), the sweep bookkeeping, the sensitivity
of the K = 16 symbol to the delay spread."""
import dataclasses as dc
import math

import numpy as np
import pytest

from mmw60.config import ChannelConfig, liu2025_table2
from mmw60.sim.curves import CurveSpec, run_curves, sweep_line
from mmw60.sim.link import LinkSim, per_sweep, snr_at_per


def _flat_ideal(k, mcs):
    return dc.replace(liu2025_table2(k=k, mcs=mcs).ideal(), channel=ChannelConfig(model="flat"))


def union_bound_per_bpsk_half(snr_tone_db: float, n_bits: int) -> float:
    """PER of the rate-1/2 K=7 BCC with BPSK on AWGN from the first terms of
    the union bound (d_free = 10; weight spectrum 11, 38, 193, 1331, 7275)."""
    es_n0 = 10 ** (snr_tone_db / 10)
    eb_n0 = es_n0 * 2                       # rate 1/2, 1 bit per symbol
    pb = 0.0
    for d, a_d in zip((10, 12, 14, 16, 18), (36, 211, 1404, 11633, 77433)):
        pb += a_d * 0.5 * math.erfc(math.sqrt(d * eb_n0 / 2))
    pb = min(pb, 0.5)
    return 1 - (1 - pb) ** n_bits


def test_awgn_mcs0_decoder_sits_on_the_union_bound():
    """Analytic / simulated cross-check of the decoder alone: genie CSI, no
    tracking, no CFO.  At the SNR where the bound says PER 1e-2 the
    simulated PER is below 0.1; 2 dB lower the link fails hard.  (The full
    receiver sits 2–3 dB to the right: per-symbol pilot CPE and LTF channel
    estimation — cairn/engineering-pitfalls.md.)"""
    from mmw60.config import RxConfig
    cfg = dc.replace(_flat_ideal(8, 0), rx=RxConfig(cfo_estimation="off", genie_csi=True,
                                                    cpe_tracking=False))
    snr_ub = next(s / 10 for s in range(0, 100) if union_bound_per_bpsk_half(s / 10, 32768) < 1e-2)
    sw = per_sweep(cfg, [snr_ub - 2.0, snr_ub + 0.3], max_packets=60, min_errors=8, seed=1)
    assert sw["per"][0] > 0.5
    assert sw["per"][1] < 0.1
    assert 1.5 < snr_ub < 3.0                # the bound itself is where the textbook puts it


def test_full_receiver_costs_a_known_amount_over_the_decoder():
    """The pilot-CPE tail and the LTF estimate move the MCS0 threshold right
    by 2–3.5 dB on a flat channel (what the LOG records against Liu 2025)."""
    from mmw60.config import RxConfig
    base = _flat_ideal(8, 0)
    genie = dc.replace(base, rx=RxConfig(cfo_estimation="off", genie_csi=True, cpe_tracking=False))
    a = per_sweep(genie, [2.0], max_packets=40, min_errors=40, seed=2)["per"][0]
    b = per_sweep(base, [2.0], max_packets=40, min_errors=40, seed=2)["per"][0]
    c = per_sweep(base, [5.5], max_packets=40, min_errors=40, seed=2)["per"][0]
    assert a < 0.3 and b > 0.8 and c < 0.2


def test_snr_at_per_interpolates_in_log_per():
    sw = {"snr_db": [1.0, 2.0, 3.0], "per": [1.0, 0.1, 0.001]}
    assert snr_at_per(sw, 1e-2) == pytest.approx(2.5)
    assert snr_at_per({"snr_db": [1.0], "per": [1.0]}, 1e-2) is None
    assert snr_at_per({"snr_db": [5.0, 6.0], "per": [0.005, 0.0]}, 1e-2) == 5.0


def test_sweep_stops_early_and_records_counts():
    cfg = _flat_ideal(8, 0)
    sw = per_sweep(cfg, [-5.0, 20.0, 25.0], max_packets=5, min_errors=2, stop_below=0.5, seed=0)
    assert sw["n_errors"][0] == 2 and sw["per"][0] == 1.0
    assert sw["n_errors"][1] == 0 and len(sw["snr_db"]) == 2      # stopped after the clean point


def test_run_curves_serial_and_parallel_agree():
    spec = CurveSpec("t", _flat_ideal(8, 0), [0.0, 20.0], max_packets=3, min_errors=1,
                     tags={"k": 8, "mcs": 0, "set": "x"})
    a = run_curves([spec], jobs=1, log=lambda s: None)
    b = run_curves([spec], jobs=2, log=lambda s: None)
    assert a[0]["sweep"] == b[0]["sweep"]
    assert "SNR@1e-2" in sweep_line(a[0])


def test_k16_symbol_is_hurt_by_a_long_delay_spread_and_not_by_the_assumed_one():
    """ISI beyond the 50 ns guard: 15 ns rms costs the K = 16 link an EVM
    floor near −14 dB; the assumed 7 ns stays below −25 dB (derived.isi_beyond_gi_k16_db)."""
    from mmw60.config import RxConfig
    base = dc.replace(liu2025_table2(k=16, mcs=0).ideal(), rx=RxConfig(ce_smooth_tones=1))
    out = {}
    for tau in (7.0, 15.0):
        cfg = dc.replace(base, channel=ChannelConfig(model="tdl_exp", rms_delay_ns=tau, los_k_db=None))
        sim = LinkSim(cfg)
        out[tau] = np.mean([sim.packet(None, np.random.default_rng(i)).rx.evm_db for i in range(3)])
    assert out[15.0] > -18 and out[7.0] < -25 and out[7.0] < out[15.0] - 8


def test_describe_reports_the_physics_of_the_link():
    d = LinkSim(liu2025_table2(k=8, mcs=4)).describe()
    assert d["cfo_subcarriers"] == pytest.approx(2.9376e6 / 2.5e6)
    assert d["pa_obo_reference"] == "psat" and d["channel"] == "tdl_exp" and d["mcs"] == 4
