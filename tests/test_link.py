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


def test_run_curves_cache_resumes_with_the_same_numbers(tmp_path, monkeypatch):
    """A cached curve is what an uncached run gives; a second run reads it
    instead of simulating; another spec or another source is a miss."""
    import mmw60.sim.curves as curves
    spec = CurveSpec("t", _flat_ideal(8, 0), [0.0, 20.0], max_packets=3, min_errors=1,
                     tags={"k": 8, "mcs": 0, "set": "x"})
    plain = run_curves([spec], jobs=1, log=lambda s: None)
    first = run_curves([spec], jobs=1, log=lambda s: None, cache_dir=tmp_path)
    assert first[0]["sweep"] == plain[0]["sweep"]
    assert first[0]["snr_at_target"] == plain[0]["snr_at_target"]
    assert len(list(tmp_path.glob("*.json"))) == 1

    def boom(_):
        raise AssertionError("simulated although cached")
    monkeypatch.setattr(curves, "_run", boom)
    again = run_curves([spec], jobs=1, log=lambda s: None, cache_dir=tmp_path)
    assert again == first
    other = dc.replace(spec, snr_db=[0.0, 19.0])
    with pytest.raises(AssertionError, match="simulated although cached"):
        run_curves([other], jobs=1, log=lambda s: None, cache_dir=tmp_path)
    monkeypatch.setattr(curves, "_source_digest", lambda: "another source")
    with pytest.raises(AssertionError, match="simulated although cached"):
        run_curves([spec], jobs=1, log=lambda s: None, cache_dir=tmp_path)


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


def test_c12_receiver_diagnostics_are_off_by_default_and_each_does_what_it_says(monkeypatch):
    """ROADMAP C12's three receiver switches: the defaults are today's
    receiver; a single-LTF estimate equals the two-repeat one without noise
    and is twice as noisy with it; unweighted LLRs hand the decoder weight 1;
    hard decisions cost 16-QAM 3/4 about 3 dB and are BCC-only."""
    from mmw60.config import RxConfig, zero_if_60ghz
    from mmw60.rx import receiver
    from mmw60.vendor.wifitrx.waveform.preamble import channel_estimate
    rxc = RxConfig()
    assert rxc.ce_ltf_symbols == 2 and rxc.llr_channel_weighting and not rxc.hard_decision
    sim = LinkSim(_flat_ideal(8, 4))
    rng = np.random.default_rng(3)
    _, frame = sim.transmit(rng)
    clean = sim.impair(frame.x, rng, None)[0]
    h0 = channel_estimate(clean, frame)
    assert np.allclose(receiver._single_ltf_estimate(clean, frame), h0, atol=1e-9)
    e1, e2 = [], []
    for _ in range(20):
        y = sim.impair(frame.x, rng, 10.0)[0]
        e1.append(np.mean(np.abs(receiver._single_ltf_estimate(y, frame) - h0) ** 2))
        e2.append(np.mean(np.abs(channel_estimate(y, frame) - h0) ** 2))
    assert 1.6 < np.mean(e1) / np.mean(e2) < 2.5
    seen = {}

    def stub(eq, ref, weight, kernel=None, hard=False):
        seen["w"], seen["hard"] = weight, hard
        return None, 0
    monkeypatch.setattr(receiver, "decode_data_field", stub)
    for weighting in (True, False):
        c = dc.replace(_flat_ideal(8, 4), rx=dc.replace(_flat_ideal(8, 4).rx, llr_channel_weighting=weighting))
        LinkSim(c).packet(20.0, np.random.default_rng(0))
        assert (np.ndim(seen["w"]) == 1) is weighting and (weighting or seen["w"] == 1.0)
    monkeypatch.undo()
    # 16-QAM 3/4 on the flat ideal chain: soft decisions reach PER 1e-2 near 15.5 dB, hard ones
    # about 3 dB later (example 14); 1 dB over the soft threshold the hard decoder still fails
    soft = _flat_ideal(8, 4)
    hard = dc.replace(soft, rx=dc.replace(soft.rx, hard_decision=True))
    p_soft = per_sweep(soft, [16.5], max_packets=40, min_errors=40, seed=4)["per"][0]
    p_hard = per_sweep(hard, [16.5, 19.5], max_packets=40, min_errors=40, seed=4)["per"]
    assert p_soft < 0.05 and p_hard[0] > 0.15 and p_hard[1] < 0.05, (p_soft, p_hard)
    eht = zero_if_60ghz(k=4, mcs=4, standard="11be", bandwidth_hz=80e6).ideal()
    with pytest.raises(NotImplementedError, match="BCC"):
        LinkSim(dc.replace(eht, rx=dc.replace(eht.rx, hard_decision=True))).packet(20.0, np.random.default_rng(0))
