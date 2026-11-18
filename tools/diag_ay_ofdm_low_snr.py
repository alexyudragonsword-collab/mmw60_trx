"""Diagnostic (ROADMAP milestone 3): where the OFDM receiver's low-SNR loss is.

After the 2026-11-18 round (EDMG-CEF fit, common phase over 17 symbols) the
measured thresholds of DCM QPSK and 16 / 64-QAM sit 0.0-0.4 dB over SC's at
the same modulation and code rate, but the five DCM BPSK MCS hardly moved:
MCS 1 (rate 1/2) 1.65 -> 1.28 dB against SC MCS 2's 0.12 dB.  On a flat
channel DCM BPSK is BPSK with the energy of two tones per bit, the same
Eb/N0 as SC's pi/2-BPSK, so the 1.2 dB is this library's receiver at an
in-band SNR near 1 dB, not the modulation.

This script takes the receiver's estimates away one at a time on OFDM MCS 1
(the ideal chain, flat channel, the thresholds' own configuration and
packet) and reads where the packet error rate crosses 0.1 on a 0.5 dB grid
(the curves fall from 1 to 0 inside 1.5 dB, so the shift at 0.1 is the
shift at 0.01 to about 0.1 dB, and it needs a tenth of the packets):

* the channel estimate: the noise-free estimate of the same packet, scaled
  by one complex number taken from the noisy one (``AyLinkSim.ce_hook``);
* the CFO estimate: off (the ideal chain has no CFO, so off is the truth);
* the common phase: no tracking (no CFO and an ideal LO: nothing to track).

**Expectations, written before the first run (2026-11-18).**

* With all three taken away the receiver is a demapper and a decoder behind
  AWGN.  What is left against SC is the in-band SNR's convention: OFDM's
  SNR counts the 16 pilots (352 used tones for 336 data tones,
  10 log10(352 / 336) = 0.20 dB), and SC's own receiver is not ideal
  either (0.2-0.3 dB of EVM).  So that row should land within +-0.2 dB of
  SC MCS 2.  If it does not, the cause is in the demapper or the code, not
  in the estimates, and this script has found it by exclusion.
* Which estimate carries the 1.2 dB is not known.  First-order arithmetic
  says none should: the estimate's noise is 0.1165 of a tone's (0.48 dB,
  and only its phase half touches PSK), the pilot phase over 17 symbols is
  under 0.01 dB, and the STF's CFO error is 0.014 of a subcarrier at 1 dB
  (inter-carrier interference 6e-4 of the signal).  Together about 0.3 dB.
  So either one of them is far from its first-order number at 1 dB, or the
  first expectation fails.

**What the first run showed (2026-11-18, the demapper with uniform weights).**
PER 0.1 crossings: SC -0.24 dB; OFDM as it was +0.41 (+0.65 over SC); with
the noise-free channel estimate -0.50 (0.25 under SC); no CFO estimate
+0.41; no CFO estimate and no phase tracking +0.41; all three -0.54.

* The first expectation held, a little better than written: behind AWGN the
  OFDM demapper and decoder are 0.29 dB ahead of SC's whole receiver.
* The CFO estimate and the phase tracking cost nothing (the tracking is
  needed: with the STF's CFO error left in and no tracking nothing decodes).
* The whole gap is the channel estimate, 0.9 dB where the first-order
  arithmetic said 0.25, and the curve has a tail: the thresholds' own sweep
  reads 13/200 at 0.5 dB, 45/3000 at 1.0 dB, 22/3000 at 1.5 dB, where SC
  falls from 60/2089 to 1/3000 in half a dB.  A tail is a per-packet event,
  and the estimate is the only thing drawn once per packet: at 1 dB its
  error is 0.12 / 1.26 = 9 % of a tone's power on average and 4.4 times
  that on the outermost tone (a relative error of 0.6), fixed for the
  packet.  The demapper took zero-forced points with one weight for every
  tone, so a tone whose estimate came out small handed the decoder large,
  wrong LLRs in every symbol and every codeword.

**(c) The demapper's weights follow the estimate — written before the run.**
Zero forcing leaves tone k the noise sigma^2 / |H_k|^2, so its LLRs are
weighted by |H_k|^2 of the estimate (``ay.ofdm_llr_weights: estimate``;
``uniform`` is the demapper before).  Expected: the tail goes, and what is
left of the estimate's noise is its first-order cost, about 0.25-0.3 dB
over the noise-free row: a crossing of -0.25 to -0.1 dB, level with SC's
-0.24 dB to within 0.2 dB.  At the higher thresholds (6 dB and up) the
estimate's relative error is four times smaller and the change should be
under 0.1 dB.

**What the second run showed.**  With the weights the crossing is +0.05 dB
(0.29 over SC, before 0.65) and the errors at 0.5 dB go from 8/120 to
0/120; the noise-free row is where it was (-0.49).  That is outside what
was written (-0.25 .. -0.1): the estimate's noise still costs 0.54 dB over
the noise-free row, its whole first-order 0.48 dB.  The expectation took
only the phase half of the estimate's error to touch PSK; near 0 dB the
error is 12 % of a tone's power, the weights are noisy with it, and the
split into a harmless amplitude half does not hold.  Not chased further:
it is the estimate's own noise, and the field's length sets it.

    python tools/diag_ay_ofdm_low_snr.py [--packets 120] [--jobs 4] [--rows 0 1 7 8]
"""
from __future__ import annotations

import argparse
import dataclasses as dc
from multiprocessing import get_context

import numpy as np

TARGET = 0.1
GRID = (-1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0, 2.5)

#: label, waveform, mcs, genie channel estimate, CFO estimate on, phase tracking on, LLR weights
ROWS = (
    ("SC MCS 2 (pi/2-BPSK 1/2), as it is", "ay_sc", 2, False, True, True, "estimate"),
    ("OFDM MCS 1 (DCM BPSK 1/2), uniform LLR weights", "ay_ofdm", 1, False, True, True, "uniform"),
    ("  noise-free channel estimate", "ay_ofdm", 1, True, True, True, "uniform"),
    ("  no CFO estimate", "ay_ofdm", 1, False, False, True, "uniform"),
    ("  no phase tracking", "ay_ofdm", 1, False, True, False, "uniform"),
    ("  no CFO estimate, no phase tracking", "ay_ofdm", 1, False, False, False, "uniform"),
    ("  all three: demapper and decoder behind AWGN", "ay_ofdm", 1, True, False, False, "uniform"),
    ("OFDM MCS 1, (c) weights from the estimate (now)", "ay_ofdm", 1, False, True, True, "estimate"),
    ("  noise-free channel estimate", "ay_ofdm", 1, True, True, True, "estimate"),
)


def _point(job: tuple) -> tuple:
    row, snr_db, n_packets = job
    from mmw60.ay import coding
    from mmw60.sim.link import LinkSim
    _, wf, mcs, genie, cfo, cpe, weights = ROWS[row]
    cfg = coding.threshold_config(mcs, waveform=wf)
    cfg = dc.replace(cfg, ay=dc.replace(cfg.ay, ofdm_llr_weights=weights))
    rx = dc.replace(cfg.rx, cpe_tracking=cpe, **({} if cfo else {"cfo_estimation": "off"}))
    sim = LinkSim(dc.replace(cfg, rx=rx))
    code = coding.ay_code(sim)
    n_cw = coding.codewords_for(cfg.phy.packet_bytes, code)
    errors = 0
    for seed in range(n_packets):
        if genie:
            kept = []
            sim.ce_hook = lambda h: (kept.append(h) or h)                                      # noqa: E731
            coding.coded_packet(sim, code, None, np.random.default_rng(seed), n_codewords=n_cw)
            h0 = kept[-1]
            sim.ce_hook = lambda own, h0=h0: h0 * (np.vdot(h0, own) / np.vdot(h0, h0))         # noqa: E731
        r = coding.coded_packet(sim, code, snr_db, np.random.default_rng(seed), n_codewords=n_cw)
        errors += int(r["packet_error"])
    return row, snr_db, errors


def crossing(snr: list, per: list, target: float = TARGET) -> float | None:
    """Log-linear interpolation of the first crossing of ``target`` from above."""
    for i in range(len(per) - 1):
        if per[i] >= target > per[i + 1]:
            lo, hi = np.log10(max(per[i], 1e-6)), np.log10(max(per[i + 1], 1e-6))
            return float(snr[i] + (snr[i + 1] - snr[i]) * (lo - np.log10(target)) / (lo - hi))
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--packets", type=int, default=120)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--rows", type=int, nargs="*", help="row numbers to run (default: all)")
    a = ap.parse_args(argv)
    from mmw60 import __version__
    print(f"mmw60 {__version__}; ideal chain, flat, 4096-byte PSDU, {a.packets} packets per point; "
          f"packet errors on the grid and the PER {TARGET:g} crossing (dB)")
    rows = list(range(len(ROWS))) if not a.rows else sorted(set(a.rows) | {0})
    jobs = [(i, s, a.packets) for i in rows for s in GRID]
    with get_context("fork").Pool(a.jobs) as pool:
        got = {(i, s): e for i, s, e in pool.imap_unordered(_point, jobs)}
    print(f"{'receiver':<48} " + " ".join(f"{s:>5g}" for s in GRID) + "   crossing   vs SC")
    ref = None
    for i in rows:
        row = ROWS[i]
        errs = [got[(i, s)] for s in GRID]
        x = crossing(list(GRID), [e / a.packets for e in errs])
        ref = x if i == 0 else ref
        d = "" if x is None or ref is None or i == 0 else f"{x - ref:+.2f}"
        print(f"{row[0]:<48} " + " ".join(f"{e:>5d}" for e in errs)
              + f"   {'never' if x is None else f'{x:6.2f}'}     {d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
