"""Diagnostic (ROADMAP milestone 3): what the ay OFDM receiver loses over the
in-band SNR on the ideal chain, term by term, next to SC.

The reading: 16-QAM 3/4 (OFDM MCS 13, SC MCS 14), the ideal chain, flat
channel, in-band SNR 13 dB; ``loss = EVM + SNR`` in dB (0 = the receiver
reads the noise it was given and nothing more).  cairn/ay.md 9d recorded SC
0.34 dB, OFDM 0.76 dB and OFDM with a noise-free channel estimate 0.31 dB.

Two causes were named there and this script takes them one at a time:

(a) the channel estimate's noise: the training field is a Golay pair sent at
    2.64 GHz, 355 / 512 = 69 % of whose energy lands on the used tones
    (assumed.ay_preamble);
(b) the common phase: each symbol's own 16 pilots.

**Expectations, written before the first run (2026-11-17).**

* baseline: SC 0.34, OFDM 0.76, OFDM with a noise-free estimate 0.31 dB
  (the recorded readings; +-0.05 dB for the packet count).
* (b) alone, the be rows' cross-symbol combining (window 17, C1): the
  per-symbol pilot phase has variance 1 / (2 N_p SNR_tone); with 16 pilots at
  13 dB that is 3 % of the noise power, 0.13 dB, and the estimate's own
  error on the pilot tones adds to it (9d put the whole term near 0.25 dB).
  Averaging 16 neighbours takes nearly all of it away.  So: OFDM 0.76 ->
  0.50-0.65 dB, and with the noise-free estimate 0.31 -> 0.05-0.20 dB.
* (a), a training field with all its energy on the used tones (EDMG-CEF, or
  the mixed-rate preamble; which, and its numbers, wait on spec_sources#48):
  not measured here.  What it can give is bounded by the noise-free row.
  The estimate's noise term is 0.76 - 0.31 = 0.45 dB (a factor 1.109 in
  power); putting the lost 31 % of the energy back scales the excess by
  355 / 512, to 0.32 dB.  So (a) alone should read about 0.63 dB, not the
  0.31 dB of the noise-free row, and (a) + (b) about 0.63 minus what (b)
  takes, 0.37-0.52 dB -- at SC's 0.34 dB or a little above.  The round's
  brief expected (a) alone near 0.3 dB; that is the noise-free bound, which
  no finite training field reaches.

A row whose reading falls outside its expectation is marked and has to be
explained, not tuned.

**What the first run showed (2026-11-18), and why three rows were outside.**
The expectations above are left as they were written.

* The noise-free rows read 0.28 and 0.17 dB at first, then 0.14 and 0.02 dB
  once the row was built properly.  The first version handed the noise-free
  run's estimate to the noisy run as it was; the ideal preset still runs
  wifitrx's chains (front-end model zero_if_chain), whose gain differs
  between the two runs by 1.1-1.5 % in amplitude, so every equalised point
  came out that much too large and the noise with it: 0.10-0.13 dB that the
  receiver never added.  The 0.31 dB recorded in cairn/ay.md 9d was read
  the same way and carries the same error.  The row now takes one complex
  scalar from the noisy run's own estimate.
* (b) takes 0.10 dB, not 0.25: the per-symbol pilot phase costs 0.12 dB
  (0.14 - 0.02, the first-principles 3 % of the noise), and 9d's "about
  0.25 dB" was the remainder of a split whose other half was 0.13 dB short.
* So the split of OFDM's 0.79 dB is: the channel estimate's noise 0.65 dB,
  the per-symbol pilot phase 0.12 dB, everything else 0.02 dB.  The gap to
  SC (0.49 dB here) is the channel estimate almost alone: the Golay pair's
  energy per used tone is 352 / 512 of the payload's and its impulse
  response is kept over 108 of 512 taps (the GI plus an eighth), a noise
  term of (108 / 512) / (2 x 352 / 512) = 0.153, 0.62 dB; SC keeps 72 of 512
  taps at full energy, 0.070, 0.29 dB.
* What (a) can give, revised: with all the training energy on the used
  tones the term is (108 / 512) / 2 = 0.105, 0.43 dB, so (a) + (b) should
  read about 0.45-0.50 dB against SC's 0.30 dB.  The 0.15-0.2 dB left is the
  longer window that the longer OFDM guard interval asks for.

    python tools/diag_ay_ofdm_receiver.py [--packets 24] [--snr 13]
"""
from __future__ import annotations

import argparse
import dataclasses as dc

import numpy as np

from mmw60 import __version__
from mmw60.ay import sc as ay_sc
from mmw60.config import ChannelConfig, ay_60ghz
from mmw60.sim.link import LinkSim

FLAT = ChannelConfig(model="flat")


def _ideal(waveform: str, mcs: int, window: int):
    c = dc.replace(ay_60ghz(waveform, mcs).ideal(), channel=FLAT)
    return dc.replace(c, rx=dc.replace(c.rx, cpe_window_symbols=int(window)))


def loss_db(waveform: str, mcs: int, snr_db: float, n_packets: int, window: int = 1, genie_ce: bool = False) -> float:
    """Mean over packets of EVM + SNR (dB) on the ideal chain."""
    sim = LinkSim(_ideal(waveform, mcs, window))
    real = ay_sc.pair_estimate
    out = []
    try:
        for seed in range(n_packets):
            if genie_ce:
                # the noise-free estimate of this very packet: run it without noise and keep what the
                # estimator returned, then hand its shape to the noisy run.  One complex scalar is taken
                # from the noisy run's own estimate (355 tones: 1/355 of the estimate's noise): the two
                # runs do not share a scale -- the first version of this row handed the noise-free estimate
                # over as it was and read the equalised points 1.1-1.5 % too large, which is 0.10-0.13 dB
                # of noise that the receiver never added (see the module docstring)
                kept = []
                ay_sc.pair_estimate = lambda *a, **k: (kept.append(real(*a, **k)) or kept[-1])       # noqa: E731
                sim.packet(None, np.random.default_rng(seed))
                h0 = kept[-1]

                def scaled(*a, h0=h0, **k):
                    own = real(*a, **k)
                    return h0 * (np.vdot(h0, own) / np.vdot(h0, h0))
                ay_sc.pair_estimate = scaled
            r = sim.packet(snr_db, np.random.default_rng(seed))
            out.append(10 ** (r.rx.evm_db / 10))
            ay_sc.pair_estimate = real
    finally:
        ay_sc.pair_estimate = real
    return float(10 * np.log10(np.mean(out)) + snr_db)


ROWS = (
    # label, waveform, mcs, window, genie CE, expected (lo, hi) dB
    ("SC, as it is", "ay_sc", 14, 1, False, (0.29, 0.39)),
    ("OFDM, per-symbol pilot phase (before)", "ay_ofdm", 13, 1, False, (0.71, 0.81)),
    ("OFDM, per-symbol, noise-free channel estimate", "ay_ofdm", 13, 1, True, (0.26, 0.36)),
    ("OFDM, (b) cross-symbol phase, window 17", "ay_ofdm", 13, 17, False, (0.50, 0.65)),
    ("OFDM, (b) with the noise-free channel estimate", "ay_ofdm", 13, 17, True, (0.05, 0.20)),
)
#: the rows that read outside what was written down, and the cause found (module docstring)
EXPLAINED = {
    ROWS[2][0]: "explained: 9d's 0.31 carried a 0.10-0.13 dB scale error of the noise-free row",
    ROWS[3][0]: "explained: the pilot phase costs 0.12 dB, not the 0.25 dB taken from 9d",
    ROWS[4][0]: "explained: the same scale error; the floor is 0.02 dB",
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--packets", type=int, default=24)
    ap.add_argument("--snr", type=float, default=13.0)
    a = ap.parse_args(argv)
    print(f"mmw60 {__version__}; ideal chain, flat, 16-QAM 3/4, in-band SNR {a.snr:g} dB, {a.packets} packets; "
          "loss = EVM + SNR (dB)")
    print(f"{'receiver':<48} {'loss':>6}   {'expected':>11}   verdict")
    got = {}
    for label, wf, mcs, window, genie, (lo, hi) in ROWS:
        v = loss_db(wf, mcs, a.snr, a.packets, window, genie)
        got[label] = v
        verdict = "as expected" if lo <= v <= hi else EXPLAINED.get(label, "OUTSIDE: explain")
        print(f"{label:<48} {v:6.2f}   {lo:4.2f}-{hi:4.2f}   {verdict}")
    sc_, before, bnow = got[ROWS[0][0]], got[ROWS[1][0]], got[ROWS[3][0]]
    print(f"\n(b) takes {before - bnow:.2f} dB off OFDM's loss; OFDM - SC {before - sc_:+.2f} -> {bnow - sc_:+.2f} dB")
    est = bnow - got[ROWS[4][0]]
    print(f"the channel estimate's noise still costs OFDM {est:.2f} dB with (b) on; a training field with all its "
          f"energy on the used tones scales that excess by 355/512: about "
          f"{10 * np.log10(1 + (10 ** (est / 10) - 1) * 355 / 512):.2f} dB (pending spec_sources#48)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
