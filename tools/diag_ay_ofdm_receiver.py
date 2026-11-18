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

**After spec_sources#48 (2026-11-18): the field is the EDMG-CEF, and what was
written down before the 24-packet run with it.**  (An 8-packet smoke run of
the new code had already read 0.68 dB per-symbol and 0.57 dB with the
window; the numbers below are the arithmetic, not those readings.)

* #48 confirmed that the data of an EDMG OFDM PPDU is channel-estimated on
  the EDMG-CEF: two OFDM symbols at 2.64 GHz, the same unit-modulus sequence
  on the 352 used tones, P = [+1, -1].  The mixed-rate (1.76 GHz) L-CEF
  serves the headers only, so (a) is built on the EDMG-CEF.
* The field alone changes nothing.  Its 352 tones carry all the energy, but
  the response is then only seen on 352 of 512 bins, and an exact
  least-squares fit of the 108 window taps to them leaves 108 / 352 of the
  noise: (108 / 352) / 2 = 0.153, the very number of the Golay pair.  The
  gain is in the estimator: 108 taps seen through 69 % of the band span
  about 108 x 352 / 512 = 74 directions (the singular values fall from 0.65
  at the 75th to 7e-5 at the 85th), and a fit that keeps those above 1e-3
  of the largest keeps 82: (82 / 352) / 2 = 0.1165, 0.48 dB in place of
  0.62 dB.
* So (a) alone: 0.79 - (0.62 - 0.48) = 0.65 dB (0.58-0.70), and (a) + (b):
  0.69 - 0.14 = 0.55 dB (0.48-0.60), against SC's 0.30 dB.  The brief's 0.3
  and 0.34 dB are not reachable, and the 0.45-0.50 dB written above was
  0.03-0.05 dB optimistic (it took 74 directions, the fit keeps 82).
* What is left between OFDM and SC, about 0.2 dB, is the field's length:
  the two EDMG-CEF symbols carry 2 x 512 samples at 2.64 GHz, 388 ns; the
  SC pair 2 x 512 chips at 1.76 GHz, 582 ns, half as much energy again at
  the same power, for a response of the same 41 ns (82 directions against
  72 taps).  0.1165 / 0.070 = 1.66 = 1.5 x 82 / 72.
* Per tone the fit is not even: the estimate's noise is the diagonal of its
  projector, 0.98 of the mean in mid-band, 1.85 times the mean over the 8
  tones at each edge, 4.0 times on the outermost tone.

    python tools/diag_ay_ofdm_receiver.py [--packets 24] [--snr 13]
"""
from __future__ import annotations

import argparse
import dataclasses as dc

import numpy as np

from mmw60 import __version__
from mmw60.ay import training
from mmw60.config import ChannelConfig, ay_60ghz
from mmw60.sim.link import LinkSim

FLAT = ChannelConfig(model="flat")


def _ideal(waveform: str, mcs: int, window: int, field: str = "edmg", rcond: float | None = None):
    c = dc.replace(ay_60ghz(waveform, mcs).ideal(), channel=FLAT)
    ay = dc.replace(c.ay, ofdm_training=field)
    if rcond is not None:
        ay = dc.replace(ay, ofdm_ce_rcond=rcond)
    return dc.replace(c, rx=dc.replace(c.rx, cpe_window_symbols=int(window)), ay=ay)


def run(waveform: str, mcs: int, snr_db: float, n_packets: int, window: int = 1, genie_ce: bool = False,
        field: str = "edmg", rcond: float | None = None) -> tuple[float, np.ndarray | None]:
    """(mean over packets of EVM + SNR in dB on the ideal chain; per used tone, the channel
    estimate's error power over the noise power of one data tone — OFDM only)."""
    sim = LinkSim(_ideal(waveform, mcs, window, field, rcond))
    out, err = [], []
    for seed in range(n_packets):
        if waveform == "ay_ofdm":
            # the noise-free estimate of this very packet, and the noisy run's own.  The two runs do
            # not share a scale (the ideal preset still runs wifitrx's chains, whose gain differs by
            # 1.1-1.5 % in amplitude between them), so one complex scalar is taken from the noisy
            # estimate (352 tones: 1/352 of its noise); the first version of the noise-free row
            # handed the estimate over as it was and read 0.10-0.13 dB that the receiver never added
            kept = []
            sim.ce_hook = lambda h: (kept.append(h) or h)                                  # noqa: E731
            sim.packet(None, np.random.default_rng(seed))
            h0 = kept[-1]

            def hook(own, h0=h0):
                ref = h0 * (np.vdot(h0, own) / np.vdot(h0, h0))
                err.append(np.abs(own - ref) ** 2 / (np.mean(np.abs(ref) ** 2) * 10 ** (-snr_db / 10)))
                return ref if genie_ce else own
            sim.ce_hook = hook
        r = sim.packet(snr_db, np.random.default_rng(seed))
        out.append(10 ** (r.rx.evm_db / 10))
    return float(10 * np.log10(np.mean(out)) + snr_db), (np.mean(err, axis=0) if err else None)


ROWS = (
    # label, waveform, mcs, window, genie CE, field, expected (lo, hi) dB
    ("SC, as it is", "ay_sc", 14, 1, False, "edmg", (0.29, 0.39)),
    ("OFDM before: Golay pair, per-symbol phase", "ay_ofdm", 13, 1, False, "golay_pair", (0.71, 0.81)),
    ("  the same, noise-free channel estimate", "ay_ofdm", 13, 1, True, "golay_pair", (0.26, 0.36)),
    ("OFDM (b) alone: Golay pair, window 17", "ay_ofdm", 13, 17, False, "golay_pair", (0.50, 0.65)),
    ("  the same, noise-free channel estimate", "ay_ofdm", 13, 17, True, "golay_pair", (0.05, 0.20)),
    ("OFDM (a) alone: EDMG-CEF, per-symbol phase", "ay_ofdm", 13, 1, False, "edmg", (0.58, 0.70)),
    ("OFDM (a) + (b): EDMG-CEF, window 17 (now)", "ay_ofdm", 13, 17, False, "edmg", (0.48, 0.60)),
)
#: the rows that read outside what was written down, and the cause found (module docstring)
EXPLAINED = {
    2: "explained: 9d's 0.31 carried a 0.10-0.13 dB scale error of the noise-free row",
    3: "explained: the pilot phase costs 0.12 dB, not the 0.25 dB taken from 9d",
    4: "explained: the same scale error; the floor is 0.02 dB",
}


def _edges(g: np.ndarray) -> str:
    m = g.mean()
    mid = g[g.size // 2 - 88:g.size // 2 + 88].mean()
    edge = np.concatenate([g[:8], g[-8:]]).mean()
    out = max(g[0], g[-1])
    return (f"mean {m:.4f} ({10 * np.log10(1 + m):.2f} dB)  mid-band {mid / m:.2f}x  8 edge tones {edge / m:.2f}x  "
            f"outermost {out / m:.2f}x")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--packets", type=int, default=24)
    ap.add_argument("--snr", type=float, default=13.0)
    a = ap.parse_args(argv)
    print(f"mmw60 {__version__}; ideal chain, flat, 16-QAM 3/4, in-band SNR {a.snr:g} dB, {a.packets} packets; "
          "loss = EVM + SNR (dB)")
    print(f"{'receiver':<46} {'loss':>6}   {'expected':>11}   verdict")
    got, errs = [], []
    for i, (label, wf, mcs, window, genie, field, (lo, hi)) in enumerate(ROWS):
        v, e = run(wf, mcs, a.snr, a.packets, window, genie, field)
        got.append(v)
        errs.append(e)
        verdict = "as expected" if lo <= v <= hi else EXPLAINED.get(i, "OUTSIDE: explain")
        print(f"{label:<46} {v:6.2f}   {lo:4.2f}-{hi:4.2f}   {verdict}")
    sc_, before, b_only, a_only, both = got[0], got[1], got[3], got[5], got[6]
    print(f"\nOFDM - SC: before {before - sc_:+.2f}, (b) alone {b_only - sc_:+.2f}, (a) alone {a_only - sc_:+.2f}, "
          f"(a) + (b) {both - sc_:+.2f} dB")

    print("\nthe channel estimate's noise per used tone, over the noise of one data tone (measured over the "
          "packets | the fit's projector):")
    num = LinkSim(_ideal("ay_ofdm", 13, 1)).phy.num
    keep, pre = num.cp, max(4, num.cp // 8)
    print(f"  Golay pair, 108 of 512 taps     measured  {_edges(errs[1])}")
    print(f"                                  arithmetic mean {108 / 704:.4f} on every tone")
    print(f"  EDMG-CEF, fit above 1e-3        measured  {_edges(errs[5])}")
    print(f"                                  projector {_edges(training.estimate_noise_gain(num, keep, pre, 1e-3))}")
    print("\nsensitivity to the fit's cut (assumed.ay_receiver ofdm_ce_rcond), EDMG-CEF, window 17:")
    for rc in (1e-1, 1e-3, 1e-6):
        u = training.window_basis(num, keep, pre, rc)
        v, _ = run("ay_ofdm", 13, a.snr, a.packets, 17, False, "edmg", rc)
        v0 = LinkSim(_ideal("ay_ofdm", 13, 17, "edmg", rc)).packet(None, np.random.default_rng(0)).rx.evm_db
        print(f"  rcond {rc:5.0e}: {u.shape[1]:3d} directions, loss {v:.2f} dB, EVM without noise {v0:.1f} dB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
