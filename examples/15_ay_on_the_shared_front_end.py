"""Example 15 — the two 802.11ay waveforms on topology B's hardware (milestone 3, stage 1: EVM only).

Single channel (channel 2, 60.48 GHz, the presets' carrier), normal GI, the
EDMG numerology and MCS table from spec_sources (``edmg.*``, spec_sources#29),
the preset front end (``zero_if_60ghz``'s: the measured 60 GHz PA at 7.5 dB
from Psat, converters, IQ mismatch, LO leakage, RX DC, phase noise, the
crystals' CFO) — one instance for both waveforms, one chain at 5.28 GS/s
(data/spec: assumed.ay_chain_rate).  The question (ROADMAP milestone 3): the
single carrier's lower PAPR buys output power from the same PA; is that
worth more than what the OFDM numerology gives — at the EVM limits the
standard sets for each?

1. the numbers read from spec_sources;
2. PAPR of the transmitted payloads at 5.28 GS/s (SC with the assumed
   root-raised-cosine pulse, 0.15 / 0.35 roll-off as sensitivity rows);
3. each impairment alone on the ideal chain, at the preset back-off (no noise);
4. the floor with everything on — the raw chain, and with the IQ mismatch
   and the TX LO leakage taken as calibrated away (wifitrx's sequence has
   not been run on the ay waveforms yet: milestone 3 stage 2) — and the
   conformance cap it allows at the preset back-off;
5. EVM against back-off on the chain (IQ / LO leakage off), the back-off
   every MCS's TX EVM limit needs, and SC against OFDM at matching
   modulation and code rate;
6. at each PA output power, the best EVM-limited rate of each waveform;
7. wifitrx's calibration sequence run on the ay chain (iron rule 4;
   ``calcheck.run_cal_ay``, the probe of data/spec: assumed.ay_cal_probe);
8. the floors, caps and matched-pair back-offs again on the chains that
   sequence calibrated, the sequence run anew at every back-off — the
   check of section 4's "calibrated away"; one row shows what a single
   calibration at the preset back-off reads at 15 dB (the link re-trims the
   VGA through wifitrx's set_gain, which keeps the TX LO-leak null);
8b. what the single carrier loses on the calibrated chain, item by item:
   each calibration residual (TX IQ, TX LO leak, RX IQ, RX DC) alone on the
   calibrated chain with every other impairment off — the isolation reading,
   not everything-minus-one — and two direct readings: the leak left after
   dc_pre and the TX image rejection across the band;
9. rate against range, one element, line of sight, the calibrated chain at
   every back-off: each MCS's decoder threshold measured on the ideal chain
   with the EDMG codes (data/spec/ay_per_thresholds.yaml; SC MCS 1's
   repetition and OFDM's DCM through spec_sources#43; the DMG twin's
   sensitivity, data/spec: assumed.ay_sensitivity, is a sensitivity row),
   the floor as a noise term, the
   shared front end's noise figure, free space plus oxygen; per MCS the back-off that reaches
   farthest while the transmitter meets its EVM limit, and the fastest rate
   each waveform keeps at each distance.  Sensitivity rows: the reference
   receiver's implementation loss kept in, the surveyed 60 GHz front end
   (ROADMAP D4), and the thresholds against this library's measured 11be
   LDPC ones;
10. under multipath: the CR stand-in channel (data/spec:
   assumed.cr_rms_delay_ns / cr_los_k_db, one realisation per packet) on the
   calibrated chain, EVM without noise and at two in-band SNRs against the
   flat channel; sensitivity rows: a longer delay spread, the long GI, and
   zero forcing for SC.

The computation is ``mmw60.ay.report.build``: one JSON-safe dict, the same
numbers a graphical interface reads.  This file names the presets and prints
that dict, section by section, as it is filled.

    python examples/15_ay_on_the_shared_front_end.py [--quick]
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from mmw60 import ENGINE_BANNER                                    # noqa: E402
from mmw60.ay import report                                       # noqa: E402
from mmw60.config import ay_60ghz                                 # noqa: E402

#: the report keeps a number that is not finite as the string Python prints for it (JSON has none)
NONFINITE = {"nan": float("nan"), "inf": float("inf"), "-inf": float("-inf")}


def floats(x):
    """A row of the report with its non-finite numbers as floats again, for the format specs."""
    if isinstance(x, dict):
        return {k: floats(v) for k, v in x.items()}
    if isinstance(x, list):
        return [floats(v) for v in x]
    return NONFINITE.get(x, x) if isinstance(x, str) else x


def fmt(v, f="{:6.2f}", none="  —   "):
    return none if v is None else f.format(v)


def rate_cell(rate_bps, mcs) -> str:
    return "—" if mcs is None else f"{rate_bps / 1e9:.3f} (MCS{mcs})"


def cap_text(r) -> str:
    if r["mcs"] is None:
        return "none"
    return (f"MCS{r['mcs']} {r['modulation']} {r['code_rate']} (limit {r['evm_limit_db']:g} dB), "
            f"{r['rate_bps'] / 1e9:.3f} Gb/s")


class Printer:
    """The text of the example from the report of ``mmw60.ay.report.build``, as its ``progress``: a
    section's heading when the section starts (``begin_<section>``), a line per row as the rows arrive
    (``row_<section>``), and its table or footnote when the next section starts (``end_<section>``).
    Formatting only: every number is in the rows, and the settings the headings and footnotes quote
    are in the ``header`` record, which arrives first."""

    def __init__(self):
        self.h = {}                 # the header record
        self.section = None
        self.rows = []              # the rows of the section being printed

    def __call__(self, section, row):
        if row is None:
            self.close()
            self.section, self.rows = section, []
            getattr(self, f"begin_{section}", lambda: None)()
        else:
            row = floats(row)
            self.rows.append(row)
            getattr(self, f"row_{section}", lambda r: None)(row)

    def close(self):
        """The section being printed is complete."""
        if self.section is not None:
            getattr(self, f"end_{self.section}", lambda: None)()
        self.section = None

    def tag(self, key: str) -> str:
        return f"{key} [{self.h['sources'][key]}]"

    # ---------------------------------------------------------------- header
    def row_header(self, h):
        self.h = h
        print(f"mmw60 {h['version']}; {'QUICK (numbers meaningless)' if h['quick'] else 'full size'}; channel "
              f"{h['channel']} ({h['carrier_hz'] / 1e9:g} GHz), {h['gi']} GI; one "
              f"front end for both: PA Psat {h['psat_dbm']:g} dBm at {h['preset_backoff_db']:g} dB from "
              f"{h['backoff_reference']} "
              f"(Pout {h['pout_dbm']:.1f} dBm), chain at {h['chain_fs_hz'] / 1e9:g} GS/s with the filters of a "
              f"{h['channel_spacing_hz'] / 1e9:g} GHz channel; CFO {h['cfo_hz'] / 1e6:.2f} MHz; flat channel; "
              f"no noise unless a section says")

    # ---------------------------------------------------------------- 1. the numbers
    def begin_numbers(self):
        print("\n== 1. the EDMG single-channel numbers (spec_sources#29) ==")

    def row_numbers(self, n):
        o, s, tag = n["ofdm"], n["sc"], self.tag
        print(f"OFDM ({tag('edmg.ofdm_params')}): {o['fs_hz'] / 1e9:g} GS/s, {o['n_fft']}-point DFT, "
              f"SCS {o['scs_hz'] / 1e6:.5f} MHz, "
              f"{o['data_tones']} data + {o['pilot_tones']} pilot tones over ±{o['max_tone']}, GI {o['gi_samples']} "
              f"samples; channel {n['channel']} pilots {o['pilots'][:3]} … {o['pilots'][-2:]} "
              f"({tag('edmg.ofdm_pilot_tones_ncb1')})")
        print(f"SC ({tag('edmg.sc_params')}): {s['fs_hz'] / 1e9:g} Gchip/s, {s['block_chips']}-chip blocks, GI "
              f"{s['gi_chips']} chips, "
              f"{s['data_chips_per_block']} data chips per block, π/2 rotation")
        print(f"{'wf':<8} {'MCS':>3}  {'modulation':<12} {'rate':>5} {'Mb/s':>8} {'EVM lim':>8}")
        for e in n["mcs"]:
            print(f"{e['waveform']:<8} {e['mcs']:>3}  {e['modulation']:<12} {e['code_rate']:>5} "
                  f"{e['rate_bps'] / 1e6:8.1f} {e['evm_limit_db']:8.1f}")
        print(f"(rates: {tag('edmg.sc_rate_mbps')}, {tag('edmg.ofdm_rate_mbps')}; limits: {tag('edmg.sc_mcs')}, "
              f"{tag('edmg.ofdm_mcs')})")

    # ---------------------------------------------------------------- 2. PAPR
    def begin_papr(self):
        print("\n== 2. PAPR of the transmitted payload at 5.28 GS/s (dB above the mean, exceeded by 1e-3 / 1e-4 "
              "of the samples) ==")

    def row_papr(self, r):
        note = "" if r["rolloff"] is None else f"roll-off {r['rolloff']:g}"
        print(f"{r['waveform']:<8} {r['payload']:<26} {note:<14} {r['papr_1e3_db']:6.2f} {r['papr_1e4_db']:6.2f}")

    def end_papr(self):
        print(f"(roll-off {self.h['sc_rolloff_assumed']:g} is {self.tag('assumed.ay_sc_pulse')}; the others "
              f"are sensitivity rows)")

    # ---------------------------------------------------------------- 3. isolation
    def begin_impairments_alone(self):
        p = self.h["presets"]            # the presets' own payloads (the heading said 64-QAM for SC until 2026-11-20)
        print(f"\n== 3. each impairment alone on the ideal chain, at the preset back-off "
              f"{self.h['preset_backoff_db']:g} dB (EVM dB, "
              f"no noise; payload {p['ay_sc']['modulation']} for SC, {p['ay_ofdm']['modulation']} for OFDM) ==")

    def row_impairments_alone(self, r):
        o_txt = f"{r['ay_ofdm_evm_db']:7.2f}" if r["ay_ofdm_evm_db"] is not None else "      —"
        print(f"{r['impairment']:<34} SC {r['ay_sc_evm_db']:7.2f}   OFDM {o_txt}")

    def end_impairments_alone(self):
        tag = self.tag
        print(f"(TX LO leakage {self.h['tx_lo_leak_dbc']:g} dBc ({tag('assumed.lo_leak_dbc')}): the receiver removes "
              f"the DC it "
              f"measures on its quiet lead-in, which takes the leak out exactly while there is no CFO; with the CFO "
              f"the leak arrives turning at +CFO, averages out on the lead-in, and is DC again after the CFO "
              f"correction — on "
              f"OFDM's three empty DC tones, on every SC chip.  The IQ terms are the uncalibrated mismatch, "
              f"{tag('assumed.iq_mismatch')}.  SC tracks the phase between the guards ({tag('assumed.ay_receiver')}); "
              f"'one phase per block' is the sensitivity row)")

    # ---------------------------------------------------------------- 4. floors and caps at the preset back-off
    def begin_floors(self):
        print("\n== 4. the floor with everything on, at the preset back-off, and the conformance cap it allows ==")

    def row_floors(self, r):
        print(f"{r['waveform']:<8} {r['payload']:<26} raw {r['raw_evm_db']:7.2f}   "
              f"IQ + LO leak calibrated away {r['calibrated_away_evm_db']:7.2f}")

    def row_caps(self, r):
        print(f"cap, {'raw chain' if r['chain'] == 'raw' else 'IQ + LO leak calibrated away':<28} "
              f"{r['waveform']:<8} {cap_text(r)}")

    def end_caps(self):
        print("(cap = the passing MCS with the highest rate; an MCS passes when the floor of its payload's "
              "constellation is at or under its TX EVM limit)")

    # ---------------------------------------------------------------- 5. back-off per MCS limit
    def begin_evm_vs_backoff(self):
        print("\n== 5. EVM against back-off from Psat on the chain (IQ + LO leak calibrated away), and the back-off "
              "each MCS's limit needs ==")

    def end_evm_vs_backoff(self):
        curves = self.rows
        print("back-off  " + "  ".join(f"{c['waveform'][3:] + ' ' + c['payload'][:12]:>20}" for c in curves))
        for i, ob in enumerate(self.h["backoff_grid_db"]):
            print(f"{ob:8.1f}  " + "  ".join(f"{c['evm_db'][i]:20.2f}" for c in curves))

    def begin_backoff_per_mcs(self):
        print(f"\n{'wf':<8} {'MCS':>3}  {'modulation':<12} {'rate':>5} {'Gb/s':>6} {'limit':>6} {'back-off':>9} "
              f"{'Pout dBm':>9}")

    def row_backoff_per_mcs(self, r):
        print(f"{r['waveform']:<8} {r['mcs']:>3}  {r['modulation']:<12} {r['code_rate']:>5} "
              f"{r['rate_bps'] / 1e9:6.3f} "
              f"{r['evm_limit_db']:6.1f} {fmt(r['backoff_db'], '{:9.2f}', '    never')} "
              f"{fmt(r['pout_dbm'], '{:9.2f}', '        —')}")

    def end_backoff_per_mcs(self):
        grid = self.h["backoff_grid_db"]
        print(f"(the grid runs {grid[0]:g}–{grid[-1]:g} dB; 'never' = the floor stays above the limit there; at "
              f"{grid[0]:g} dB = met at the smallest back-off on the grid)")

    def begin_same_modulation(self):
        print("\nSC against OFDM at the same modulation and code rate (ΔPout = SC − OFDM; Δrate = SC / OFDM):")
        print(f"{'modulation':<10} {'rate':>5}  {'SC MCS':>6} {'limit':>6} {'back-off':>8}   {'OFDM MCS':>8} "
              f"{'limit':>6} "
              f"{'back-off':>8}   {'ΔPout':>6} {'Δrate':>6}")

    def row_same_modulation(self, r):
        print(f"{r['modulation']:<10} {r['code_rate']:>5}  {r['sc_mcs']:>6} {r['sc_evm_limit_db']:6.1f} "
              f"{fmt(r['sc_backoff_db'], '{:8.2f}', '   never')}"
              f"   {r['ofdm_mcs']:>8} {r['ofdm_evm_limit_db']:6.1f} "
              f"{fmt(r['ofdm_backoff_db'], '{:8.2f}', '   never')}   {fmt(r['delta_pout_db'], '{:6.2f}')} "
              f"{r['rate_ratio']:6.3f}")

    # ---------------------------------------------------------------- 6. rate at each output power
    def begin_best_rate_at_pout(self):
        print("\n== 6. the best EVM-limited rate at each PA output power (Gb/s; same PA, same chain) ==")
        print(f"{'Pout dBm':>8} {'back-off':>8} {'SC':>14} {'OFDM':>14}")

    def row_best_rate_at_pout(self, r):
        print(f"{r['pout_dbm']:8.2f} {r['backoff_db']:8.1f} {rate_cell(r['sc_rate_bps'], r['sc_mcs']):>14} "
              f"{rate_cell(r['ofdm_rate_bps'], r['ofdm_mcs']):>14}")

    def end_best_rate_at_pout(self):
        g = self.h["tx_antenna_gain_dbi"]
        print(f"(single element at {g:g} dBi: EIRP = Pout + {g:g} dB, "
              f"far under the regulatory cap; with an "
              f"array the cap binds first and the SC power margin becomes fewer elements or less DC power — stage 2)")

    # ---------------------------------------------------------------- 7. calibration on the ay chain
    def begin_calibration(self):
        print("\n== 7. wifitrx's calibration sequence on the ay chain (2.16 GHz, 5.28 GS/s), PA at the preset "
              "back-off ==")

    def row_calibration(self, c):
        print(f"probe: {c['probe']} ({self.tag('assumed.ay_cal_probe')}); no DPD (as the be rows)")
        for r in c["steps"]:
            print(f"  {r['step']:<22} {r['status']:<9} {r['metric']:<16} {fmt(r['value'], '{:8.2f}', '       —')}")
        v = c["final"]
        print(f"final check: isolation reading {v['isolation_evm_db']:.2f} dB; "
              f"modem reading {v['modem_evm_db']:.2f} dB "
              f"(TX {v['tx_modem_evm_db']:.2f}, RX {v['rx_modem_evm_db']:.2f}); PA output "
              f"{v['pout_dbm']:.2f} dBm.  (Until wifitrx 0.7.46 the isolation reading here was −7.63 dB: the capture "
              f"alignment left 3.3 samples of delay at 5.28 GS/s, wifi_trx_cal#7)")

    # ---------------------------------------------------------------- 8. on the calibrated chains
    def begin_calibrated_floors(self):
        print("\n== 8. on the chains the sequence calibrated: floors at the preset back-off, against section 4 ==")

    def row_calibrated_floors(self, r):
        print(f"{r['waveform']:<8} {r['payload']:<26} calibrated {r['calibrated_evm_db']:7.2f}   section 4: raw "
              f"{r['raw_evm_db']:7.2f}, calibrated away {r['calibrated_away_evm_db']:7.2f}")

    def row_calibrated_caps(self, r):
        print(f"cap, calibrated chain {r['waveform']:<8} {cap_text(r)}")

    def row_one_calibration_reused(self, r):
        print(f"\none calibration at {r['calibrated_at_backoff_db']:g} dB, run at {r['run_at_backoff_db']:g} dB "
              f"(drive re-trimmed, {r['payload']}): {r['evm_db']:.2f} dB; "
              f"the same without the CFO {r['evm_without_cfo_db']:.2f} dB; calibrated at "
              f"{r['run_at_backoff_db']:g} dB {r['evm_calibrated_there_db']:.2f} dB — the VGA "
              f"re-trim goes through wifitrx's set_gain, which rescales dc_pre with the gain (0.7.41, B43), so the TX "
              f"LO-leak null found at one gain state holds at another (before it, a bare VGA assignment un-nulled it "
              f"and the CFO carried the DC past the receiver's DC removal)")

    def begin_same_modulation_calibrated(self):
        print("\nSC against OFDM at the same modulation and code rate on the calibrated chains (back-off from Psat; "
              "ΔPout = SC − OFDM; section 5's ΔPout beside it):")
        print(f"{'modulation':<10} {'rate':>5}  {'SC':>6} {'OFDM':>6}  {'ΔPout':>6}   {'sec. 5':>6}")

    def row_same_modulation_calibrated(self, r):
        print(f"{r['modulation']:<10} {r['code_rate']:>5}  {fmt(r['sc_backoff_db'], '{:6.2f}', ' never')} "
              f"{fmt(r['ofdm_backoff_db'], '{:6.2f}', ' never')}  "
              f"{fmt(r['delta_pout_db'], '{:6.2f}')}   {fmt(r['delta_pout_section5_db'], '{:6.2f}')}")

    # ---------------------------------------------------------------- 8b. the residual, item by item
    def begin_residuals(self):
        print("\n== 8b. what the single carrier loses on the calibrated chain, item by item: each calibration "
              "residual "
              "alone on the calibrated chain, every other impairment off (converters, phase noise, receiver noise; the "
              "PA switched off after the VGA was trimmed with it in), the CFO on (EVM dB, 16-QAM payloads) ==")

    def row_residuals(self, r):
        print(f"back-off {r['backoff_db']:g} dB:")
        for w in r["waveforms"]:
            wf = w["waveform"]
            print(f"  {wf:<8} none {w['none_evm_db']:7.2f}  "
                  + "  ".join(f"{a['label']} {a['evm_db']:7.2f}" for a in w["alone"])
                  + f"  TX LO leak without the CFO {w['tx_leak_without_cfo_evm_db']:7.2f}, without the lead-in DC "
                    f"removal {w['tx_leak_without_dc_removal_evm_db']:7.2f};  "
                    f"calibrated away {w['calibrated_away_evm_db']:7.2f} + these = "
                    f"{w['power_sum_evm_db']:7.2f}, the calibrated chain {w['calibrated_chain_evm_db']:7.2f}")
            print(f"  {wf:<8} the whole calibrated chain with the sequence's dc_pre / with dc_pre solved to cancel "
                  f"the leak exactly: "
                  + ";  ".join(f"{d['label']} {d['sequence_evm_db']:7.2f} / {d['exact_evm_db']:7.2f}"
                               for d in w["dc_pre"]))
        d = r["direct"]
        irr = d["image_rejection"]
        print(f"  direct (DAC off): TX LO leak left after dc_pre {d['tx_leak_after_dc_pre_dbc']:.1f} dBc "
              f"(without dc_pre {d['tx_leak_without_dc_pre_dbc']:.1f}); TX image rejection at "
              + ", ".join(f"{x['freq_hz'] / 1e9:g}" for x in irr) + " GHz: "
              + ", ".join(f"{x['irr_db']:.1f}" for x in irr)
              + " dB (uncorrected " + ", ".join(f"{x['irr_uncorrected_db']:.1f}" for x in irr)
              + "; the probe spans ±0.86 GHz, the SC payload ±1.10 GHz)")

    def end_residuals(self):
        print("isolation: one residual at a time, read directly (contributions do not add up as powers in general; "
              "the "
              "power sum is a check, not a decomposition).  The leak left after dc_pre (wifitrx 0.7.41: the step reads "
              "its offset on the FFT grid, B42, and the link's VGA re-trim keeps the null, B43) is read with the DAC "
              "off: through the 9-bit DAC a zero input rounds dc_pre away.  The sequence's dc_pre and one solved to "
              "cancel the leak exactly read alike on the whole chain, with and without the CFO; what SC still loses "
              "over 'calibrated away' is the IQ residual.  OFDM puts the leak on its three empty DC tones")

    # ---------------------------------------------------------------- 9. rate against range
    def begin_range_evm_vs_backoff(self):
        tag = self.tag
        print("\n== 9. rate against range: one element, line of sight, the calibrated chain at every back-off; the "
              "decoder thresholds measured on the ideal chain with spec_sources#33's codes "
              "(data/spec/ay_per_thresholds.yaml, tools/measure_ay_thresholds.py; OFDM's bits on the data tones in "
              f"order, {tag('assumed.ay_ofdm_tone_order')}; the DCM MCS through spec_sources#43's static pairing, SC "
              "MCS 1 through its rho = 2 codeword); the DMG twin's sensitivity "
              f"({tag('assumed.ay_sensitivity')}) is a sensitivity row; the floor as a noise term; the multipath "
              "column: SC's thresholds measured on the CR stand-in, OFDM's flat ones plus "
              f"{self.h['ofdm_multipath_margin_db']:g} dB "
              f"({tag('assumed.ay_ofdm_multipath_margin_db')}) ==")

    def begin_rate_vs_range(self):
        print(f"{'wf':<8} {'MCS':>3}  {'modulation':<12} {'rate':>5} {'Gb/s':>6} {'DMG':>4} {'T[dB]':>6} {'src':>3}  "
              f"{'@preset m':>9}  {'best m':>7} {'back-off':>8} {'Pout':>6} {'floor':>6}  {'T mp':>6} {'mp m':>7}")

    def row_rate_vs_range(self, r):
        edge = "*" if r["best_is_smallest_backoff"] else " "
        print(f"{r['waveform']:<8} {r['mcs']:>3}  {r['modulation']:<12} {r['code_rate']:>5} "
              f"{r['rate_bps'] / 1e9:6.3f} "
              f"{str(r['dmg_twin'] or '—'):>4} {r['threshold_db']:6.2f} "
              f"{r['threshold_source'][0]:>3}  "
              f"{fmt(r['range_at_preset_m'], '{:9.2f}', '        —')}  "
              f"{fmt(r['best_range_m'], '{:7.2f}', '      —')} "
              f"{fmt(r['best_backoff_db'], '{:7.2f}', '      —')}{edge} "
              f"{fmt(r['best_pout_dbm'], '{:6.1f}', '     —')} "
              f"{fmt(r['floor_at_best_db'], '{:6.2f}', '     —')}  "
              f"{fmt(r['multipath_threshold_db'], '{:6.2f}', '     —')} "
              f"{fmt(r['multipath_best_range_m'], '{:7.2f}', '      —')}")

    def row_link_budget(self, b):
        lands = ", ".join(f"{wf[3:]} {v:.2f}" for wf, v in b["smallest_landed_backoff_db"].items())
        print(f"(EIRP = Pout + {b['tx_antenna_gain_dbi']:g} dBi, receive {b['rx_antenna_gain_dbi']:g} dBi, the "
              f"preset's 60 GHz receive front end: NF "
              f"{b['rx_nf_db']:.1f} dB at the sensitivity's AGC state (assumed.preset_rx_front); "
              f"oxygen {b['oxygen_db_per_km']:g} dB/km; '—' at the preset = the floor misses the TX EVM limit there; "
              f"the grid asks {', '.join(f'{v:g}' for v in b['low_backoffs_db'])} dB and then "
              f"{b['grid_first_db']:g}–{b['grid_last_db']:g} dB in "
              f"{b['grid_step_db']:g} dB steps; back-off / Pout = where the PA landed, which the distances use; "
              f"* = the smallest back-off the PA reaches (asked {b['smallest_asked_backoff_db']:g} dB, lands at "
              f"{lands} dB on the "
              f"lowest-order payload): the best is the PA's limit, not a point inside the grid; "
              f"src = m measured / t the DMG twin's; T mp / mp m = the threshold on the CR stand-in and the best "
              f"distance with it (SC measured, OFDM flat + "
              f"{b['ofdm_multipath_margin_db']:g} dB); the floors are the flat chain's)")

    def begin_fastest_rate_at_distance(self):
        wfs = report.WAVEFORMS
        print("\nthe fastest rate each waveform keeps at each distance (Gb/s, MCS; each MCS at its best back-off; "
              "flat, then with the multipath thresholds):")
        print(f"{'m':>5} " + " ".join(f"{wf:>16}" for wf in wfs) + " " + " ".join(f"{wf + ' mp':>16}" for wf in wfs))

    def row_fastest_rate_at_distance(self, r):
        cells = [rate_cell(r[f"{k}_rate_bps"], r[f"{k}_mcs"]) for k in ("sc", "ofdm", "sc_multipath", "ofdm_multipath")]
        print(f"{r['distance_m']:5.1f} " + " ".join(f"{c:>16}" for c in cells))

    def begin_multipath_same_modulation(self):
        print("\nthe multipath columns are not like for like — SC's cost is measured per MCS, OFDM's is one assumed "
              f"number ({self.h['ofdm_multipath_margin_db']:g} dB) for every MCS.  At the same modulation and code "
              f"rate (dB over flat; metres at "
              "each MCS's best back-off):")
        print(f"{'modulation':<10} {'rate':>5}  {'SC cost':>7} {'SC mp m':>8}  {'OFDM cost':>9} {'OFDM mp m':>9}  "
              f"{'OFDM m at SC cost':>17}")

    def row_multipath_same_modulation(self, r):
        print(f"{r['modulation']:<10} {r['code_rate']:>5}  "
              f"{fmt(r['sc_cost_db'], '{:7.2f}')} {fmt(r['sc_multipath_range_m'], '{:8.2f}', '       —')}  "
              f"{r['ofdm_cost_db']:9.2f} "
              f"{fmt(r['ofdm_multipath_range_m'], '{:9.2f}', '        —')}  "
              f"{fmt(r['ofdm_range_at_sc_cost_m'], '{:17.2f}', '                —')}")

    def end_multipath_same_modulation(self):
        print("(OFDM m at SC cost = OFDM's distance if its threshold moved by what SC's measured one does at that "
              "modulation and code rate: a sensitivity reading, not an OFDM measurement)")

    def begin_sensitivity_rows(self):
        caps = self.h["sensitivity_mcs"]
        print("\nsensitivity rows, at the preset back-off, for the comparison table's calibrated caps "
              f"(SC MCS{caps['ay_sc']}, OFDM MCS{caps['ay_ofdm']}; metres):")

    def row_sensitivity_rows(self, r):
        twin_txt = f"the DMG twin's threshold (rule twin) {r['twin_threshold_range_m']:.2f}; "
        print(f"  {r['waveform']:<8} MCS{r['mcs']}: preset {r['preset_range_m']:.2f}; {twin_txt}the twin's with its "
              f"implementation loss kept in "
              f"{r['twin_with_implementation_loss_range_m']:.2f}; the 0 dBi antennas the presets had until 2026-11-18 "
              f"({r['unspecified_antenna_tx_gain_dbi']:g} + {r['unspecified_antenna_rx_gain_dbi']:g} dBi, "
              f"config.unspecified_antenna) {r['unspecified_antenna_range_m']:.2f}; the WiFi 7 receive ladder they "
              f"had until the same day "
              f"(NF {r['wifi7_rx_ladder_nf_db']:.1f} dB at its AGC state, config.wifi7_rx_ladder) "
              f"{r['wifi7_rx_ladder_range_m']:.2f}")

    def begin_threshold_comparison(self):
        print("the DMG-derived thresholds against this library's measured ones at the same modulation and code rate: "
              "the EDMG codes on both waveforms (data/spec/ay_per_thresholds.yaml) and the 11be LDPC "
              "(data/spec/per_thresholds.yaml, 80 MHz; its SNR is per active subcarrier):")
        print(f"  {'':<10} {'':<8} {'':<4} {'twin':>7} {'measured':>8} {'11be':>7}  twin - meas twin - 11be")

    def row_threshold_comparison(self, r):
        print(f"  {r['label']:<12} {r['waveform']:<8} MCS{r['mcs']:<2} {r['twin_threshold_db']:6.2f} "
              f"{fmt(r['measured_threshold_db'], '{:8.2f}', '       —')} "
              f"{fmt(r['be_threshold_db'], '{:7.2f}', '      —')}  "
              f"{fmt(r['twin_minus_measured_db'], '{:+8.2f}', '       —')}  "
              f"{fmt(r['twin_minus_be_db'], '{:+11.2f}', '          —')}")

    # ---------------------------------------------------------------- 10. multipath
    def begin_multipath_evm(self):
        h = self.h
        cr = h["multipath_channel"]
        print(f"\n== 10. under multipath: the CR stand-in (exponential PDP, rms {cr['rms_delay_ns']:g} ns, K "
              f"{cr['los_k_db']:g} dB, one realisation per packet; {self.tag('assumed.cr_rms_delay_ns')}), the "
              f"calibrated chain "
              f"at the preset back-off, 16-QAM payloads; EVM dB over {h['multipath_packets']} packets, mean (90th "
              f"percentile) ==")
        print(f"{'waveform':<8} {'channel':<26} "
              + " ".join(f"{('no noise' if v is None else f'SNR {v:g} dB'):>16}" for v in h["multipath_snrs_db"])
              + f" {'12 dB vs flat':>14}")

    def row_multipath_evm(self, r):
        cells = [f"{c['mean_evm_db']:7.2f} ({c['p90_evm_db']:6.2f})" for c in r["evm"]]
        print(f"{r['waveform']:<8} {r['channel']:<26} " + " ".join(f"{x:>16}" for x in cells)
              + f" {r['delta_vs_flat_db']:+14.2f}", flush=True)

    def end_multipath_evm(self):
        gi = self.h["gi_ns"]
        print(f"(the in-band SNR is the received signal over the noise in the occupied band; SC equalises with the "
              f"unbiased MMSE on the channel estimate's scale, OFDM zero-forces per tone; the GI is "
              f"{gi['normal']:.1f} ns normal, "
              f"{gi['long']:.1f} ns long)")


def print_report(rep: dict) -> None:
    """Print a finished report (``build``'s return value, or that dict read back from JSON): the same
    text ``Printer`` writes while the report is being built."""
    out = Printer()
    for section, value in rep.items():
        out(section, None)
        for row in ([value] if isinstance(value, dict) else value):
            out(section, row)
    out.close()


def main(argv=None) -> int:
    print(ENGINE_BANNER)
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--jobs", type=int, default=1, help="accepted for symmetry; this example is serial")
    a = ap.parse_args(argv)
    quick = a.quick or os.environ.get("MMW60_SMOKE") == "1"
    t0 = time.time()
    # the presets, named here (iron rule 1); the report builds every link from these two configs
    cfgs = {wf: ay_60ghz(wf, mcs) for wf, mcs in report.PRESET_MCS.items()}
    out = Printer()
    report.build(fe=report.default_frontend(cfgs), cfgs=cfgs, quick=quick, progress=out)
    out.close()
    print(f"\n[{time.time() - t0:.0f}s]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
