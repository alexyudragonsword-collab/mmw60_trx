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
#: interval widths of the refined table (2026-11-15: median 0.12 dB, widest 1.00 dB off the floor)
WIDTH_MAX_DB, WIDTH_MEDIAN_DB = 1.2, 0.2
#: cells whose PER curve flattens near 1e-2 on the ideal chain's own floor (11be 20 MHz MCS11: PER 1–2.6 %
#: from 31.5 to 33.5 dB; MCS12 of the same base never gets there) — the crossing is ill-defined and the
#: interval says so (2.78 dB wide); declared here, not detected
ON_OWN_FLOOR = {("11be", 20e6, 11)}


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


def test_every_threshold_carries_its_interval_from_the_refined_counts():
    """ROADMAP C6: the two points bracketing PER 1e-2 run on to 60 errors (or
    3000 packets) and the file records the 95 % bootstrap interval next to
    every threshold; the cap reads the point, the interval says how far the
    point can be trusted."""
    doc = spec.per_threshold_document()
    assert "60 errors or 3000 packets" in doc["cite"] and "ci_db" in doc["cite"]
    widths = []
    for std, by_bw in doc["thresholds_db"].items():
        for bw, by_mcs in by_bw.items():
            for mcs, v in by_mcs.items():
                ci = spec.per_threshold_ci_db(std, bw, mcs)
                if v is None:
                    assert ci is None, (std, bw, mcs)
                    continue
                assert ci is not None, (std, bw, mcs)
                lo, hi = ci
                assert lo <= v <= hi, (std, bw, mcs, v, ci)
                if (std, bw, mcs) in ON_OWN_FLOOR:
                    assert hi - lo > WIDTH_MAX_DB, (std, bw, mcs, ci)     # still flat: re-check the declaration
                    continue
                widths.append(hi - lo)
    assert len(widths) >= 9 + 5 * 12 - len(ON_OWN_FLOOR)
    # with the bracketing points at 60 errors the counting statistics are a
    # tenth of a dB wide, inside the 0.5 dB grid the crossing is interpolated
    # on (the interval does not include that interpolation); the widest
    # (0.5–1.0 dB) are cells where an unrefined 200-packet neighbour also
    # sits near 1e-2 and a bootstrap replicate crosses there first
    assert max(widths) < WIDTH_MAX_DB and float(np.median(widths)) < WIDTH_MEDIAN_DB, (max(widths), np.median(widths))
    assert spec.per_threshold_ci_db("11ac", 40e6, 0) is None


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
    conformance cap sits below MCS4 while the decoder reaches PER 1e-2 at
    MCS4; the decoder cap must say MCS4 or better there and never be below
    conformance.  (Which conformance MCS it is moves with the preset PA and
    its operating point: MCS2 with the 11ad EM PA, MCS3 with the measured PA
    at 8 dB, MCS2 again at the rule's 7.5 dB.)"""
    fe = Frontend60.from_config(zero_if_60ghz(k=8))
    for std, bw, k in (("11be", 80e6, 4), ("11be", 80e6, 8), ("11be", 20e6, 16), ("11ac", 20e6, 8)):
        c = evaluate_cell(zero_if_60ghz(k=k, standard=std, bandwidth_hz=bw), fe, time_domain=False)
        conf = max_mcs_for_floor(c.floor_db, std)
        assert c.dec_coded and c.dec_mcs is not None and c.dec_mcs >= conf, (std, bw, k, conf, c.dec_mcs)
        assert c.dec_mcs_cal >= c.dec_mcs and c.dec_rate_mbps > 0
    c4 = evaluate_cell(zero_if_60ghz(k=4, standard="11be", bandwidth_hz=80e6), fe, time_domain=False)
    assert c4.max_mcs < 4 <= c4.dec_mcs
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


def test_decoder_cap_gives_the_caps_at_the_interval_ends_and_the_margin_to_the_next_line():
    """ROADMAP C6: where a floor sits on an MCS line inside the threshold's
    95 % interval the cap reads both MCS (example 02 / 04 print MCS5–6), and
    the margin to the next MCS line says how close every cap is."""
    from mmw60.frontend.grid import format_cap
    m = float(spec.value("assumed.decoder_cap_margin_db"))
    t6, (lo6, hi6) = spec.per_threshold_db("11be", 80e6, 6), spec.per_threshold_ci_db("11be", 80e6, 6)
    inside = -((lo6 + hi6) / 2 + m)                       # MCS6 reachable at the interval's low end only
    d = decoder_cap(inside, "11be", 80e6)
    assert d["mcs_range"] == (5, 6) and d["mcs_range"][0] <= d["mcs"] <= d["mcs_range"][1]
    assert format_cap(d["mcs"], d["mcs_range"]) == "MCS5–6"
    clear = decoder_cap(-(hi6 + m + 0.2), "11be", 80e6)    # over the interval's top: MCS6 at both ends
    assert clear["mcs"] == 6 and clear["mcs_range"] == (6, 6) and format_cap(6, clear["mcs_range"]) == "MCS6"
    below = decoder_cap(-(lo6 + m - 0.01), "11be", 80e6)   # 0.01 dB under the interval: MCS5, and the margin shows it
    assert below["mcs"] == 5 and below["mcs_range"] == (5, 5)
    assert below["next_margin_db"] == pytest.approx((lo6 + m - 0.01) - (t6 + m))
    assert -0.2 < below["next_margin_db"] < 0
    # the top of the table has no next line; no MCS at all reads the margin to MCS0
    assert decoder_cap(-60.0, "11ac", 20e6)["next_margin_db"] is None
    none = decoder_cap(5.0, "11be", 80e6)
    assert none["mcs"] is None and none["mcs_range"] == (None, None) and format_cap(None, none["mcs_range"]) == "—"
    assert none["next_margin_db"] == pytest.approx(-5.0 - (spec.per_threshold_db("11be", 80e6, 0) + m))
