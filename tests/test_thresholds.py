"""The measured ideal-chain PER thresholds and the decoder cap built on them."""
import dataclasses as dc

import numpy as np
import pytest

from mmw60 import spec
from mmw60.config import ChannelConfig, zero_if_60ghz
from mmw60.frontend import Frontend60
from mmw60.frontend.grid import decoder_cap, decoder_floor_db, evaluate_cell, max_mcs_for_floor
from mmw60.sim.link import per_sweep

BE_BWS = (20e6, 40e6, 80e6, 160e6, 320e6)


def test_threshold_file_is_tagged_complete_and_monotonic():
    doc = spec.per_threshold_document()
    assert doc["source"] == "derived" and "measure_thresholds.py" in doc["cite"] and doc["note"]
    assert doc["packet_bytes"] == 4096 and doc["target_per"] == 1e-2
    t = doc["thresholds_db"]
    assert set(t) == {"11ac", "11be"} and set(t["11ac"]) == {20e6} and set(t["11be"]) == set(BE_BWS)
    assert set(t["11ac"][20e6]) == set(range(9))
    for bw in BE_BWS:
        row = t["11be"][bw]
        assert set(row) == set(range(14))
        vals = [row[i] for i in range(14)]
        # up to 1024-QAM every MCS reaches PER 1e-2 on the ideal chain; 4096-QAM
        # (MCS 12 / 13) may not — the ideal chain has its own −40 dB floor (LPF
        # group delay + 3-tone smoothing), and a None says so instead of a guess
        assert all(v is not None for v in vals[:12]), (bw, vals)
        got = [v for v in vals if v is not None]
        # a higher MCS never needs less SNR (0.3 dB of measurement scatter allowed)
        assert all(b > a - 0.3 for a, b in zip(got, got[1:])), (bw, vals)
        assert -2 < vals[0] < 3 and 25 < vals[11] < 40
    # same code, same receiver: the bandwidths agree.  With the milestone-0
    # receiver the wide ones were up to 2 dB better (8 pilots at 20 MHz, 64 at
    # 320 MHz: the per-symbol pilot CPE estimate was less noisy with more
    # pilots); the cross-symbol CPE combining of C1 took that difference away,
    # and what is left is within the 0.5 dB grid of the measurement
    for i in (0, 4, 7):
        spread = [t["11be"][bw][i] for bw in BE_BWS]
        assert max(spread) - min(spread) < 1.5, (i, spread)
        assert spread[-1] < spread[0] + 0.5, (i, spread)
    assert spec.per_threshold_db("11ac", 40e6, 0) is None and spec.per_threshold_db("11be", 80e6, 14) is None


def test_one_threshold_reproduces_from_the_code():
    """The file is this receiver's measurement: 1.5 dB under the recorded
    threshold the link fails, 1 dB over it it holds (11be 80 MHz MCS4)."""
    t = spec.per_threshold_db("11be", 80e6, 4)
    cfg = dc.replace(zero_if_60ghz(k=4, mcs=4, standard="11be", bandwidth_hz=80e6).ideal(),
                     channel=ChannelConfig(model="flat"))
    sw = per_sweep(cfg, [t - 1.5, t + 1.0], max_packets=40, min_errors=8, seed=5)
    assert sw["per"][0] > 0.5 and sw["per"][1] < 0.05, (t, sw["per"])


def test_decoder_cap_arithmetic_and_margin():
    t4 = spec.per_threshold_db("11be", 80e6, 4)
    d = decoder_cap(-(t4 + 3.0), "11be", 80e6)                 # floor exactly at the 3 dB margin of MCS4
    assert d["mcs"] >= 4
    exact = decoder_cap(-(t4 + 3.0), "11be", 80e6, margin_db=3.0)
    at4 = {"t": t4, "req": -10 * np.log10(10 ** (-t4 / 10) - 10 ** (-(t4 + 3.0) / 10))}
    if exact["mcs"] == 4:
        assert exact["required_snr_db"] == pytest.approx(at4["req"])
        assert exact["penalty_db"] == pytest.approx(3.02, abs=0.02)
    assert decoder_cap(-(t4 + 2.9), "11be", 80e6)["mcs"] < decoder_cap(-(t4 + 3.0), "11be", 80e6)["mcs"] + 1
    assert decoder_cap(-(t4 + 0.5), "11be", 80e6, margin_db=0.0)["mcs"] >= 4
    assert decoder_cap(5.0, "11be", 80e6)["mcs"] is None        # a floor above the signal carries nothing
    assert decoder_cap(-60.0, "11be", 80e6)["mcs"] >= 11 and decoder_cap(-60.0, "11ac", 20e6)["mcs"] == 8
    assert decoder_cap(-30.0, "11ac", 80e6)["mcs"] is None      # EVM-only base: no thresholds
    # a lower floor never lowers the cap
    caps = [decoder_cap(-f, "11be", 160e6)["mcs"] or -1 for f in np.arange(0, 45, 0.5)]
    assert all(b >= a for a, b in zip(caps, caps[1:]))


def test_decoder_cap_sits_above_the_conformance_cap_where_example_05_measured_it():
    """Example 05's finding as a guard: on 11be 80 MHz × 4 the transmitter-
    conformance cap is MCS2 while the decoder reaches PER 1e-2 at MCS4; the
    decoder cap must say MCS4 or better there and never be below conformance."""
    fe = Frontend60.from_config(zero_if_60ghz(k=8))
    for std, bw, k in (("11be", 80e6, 4), ("11be", 80e6, 8), ("11be", 20e6, 16), ("11ac", 20e6, 8)):
        c = evaluate_cell(zero_if_60ghz(k=k, standard=std, bandwidth_hz=bw), fe, time_domain=False)
        conf = max_mcs_for_floor(c.floor_db, std)
        assert c.dec_coded and c.dec_mcs is not None and c.dec_mcs >= conf, (std, bw, k, conf, c.dec_mcs)
        assert c.dec_mcs_cal >= c.dec_mcs and c.dec_rate_mbps > 0
    c4 = evaluate_cell(zero_if_60ghz(k=4, standard="11be", bandwidth_hz=80e6), fe, time_domain=False)
    assert c4.max_mcs == 2 and c4.dec_mcs >= 4
    wide = evaluate_cell(zero_if_60ghz(k=8, standard="11ac", bandwidth_hz=80e6), fe, time_domain=False)
    assert not wide.dec_coded and wide.dec_mcs is None and " n/a " in wide.row()


def test_decoder_cap_takes_the_worse_of_the_analytic_and_the_time_domain_floor():
    """The analytic power sum is optimistic once the IQ image is no small
    perturbation; where the cell's time-domain EVM was run and reads worse,
    the cap is computed from it (example 05: the decoder follows it)."""
    assert decoder_floor_db(-11.2, None) == -11.2
    assert decoder_floor_db(-11.2, -10.2) == -10.2 and decoder_floor_db(-11.2, -12.0) == -11.2
    assert decoder_floor_db(-11.2, +3.0, cfo_captured=False) == -11.2     # an uncaptured CFO's EVM is no floor
    fe = Frontend60.from_config(zero_if_60ghz(k=8))
    cfg = zero_if_60ghz(k=16, standard="11be", bandwidth_hz=80e6)
    quick = evaluate_cell(cfg, fe, time_domain=False)
    full = evaluate_cell(cfg, fe, time_domain=True, isolate=False)
    assert quick.dec_floor_db == quick.floor_db
    assert full.dec_floor_db == max(full.floor_db, full.td_evm_db)
    assert full.dec_mcs <= quick.dec_mcs and full.dec_mcs_cal == quick.dec_mcs_cal
