"""802.11ay waveforms (milestone 3) — the number-agnostic skeleton.

Milestone 3 adds two waveforms on topology B's hardware: ``ay_ofdm`` and
``ay_sc``.  Their numerology, MCS tables, EVM limits and sensitivities are
spec numbers and come only through spec_sources (iron rule 5); they are
requested in spec_sources#29.  Until they land, this package holds the parts
whose code does not depend on any of those numbers, each taking its
numerology as a parameter and tested on synthetic numerologies:

* :mod:`.golay`  — Golay complementary pairs from a delay / weight vector
  (the construction; which vectors 802.11ad / ay use is a spec number);
* :mod:`.sc`     — single-carrier blocks with a known guard interval that
  doubles as the cyclic prefix, a pair-based channel estimate, and the
  frequency-domain equaliser with per-block phase tracking on the guard;
* :mod:`.ofdm`   — OFDM on an arbitrary tone plan (data / pilot indices),
  training-symbol channel estimate and pilot common-phase correction;
* :mod:`.papr`   — interpolation (ideal and root-raised-cosine), the PAPR
  CCDF, and the output back-off a waveform needs on a PA for an EVM target.

``config.WAVEFORMS_BUILT`` does not include the ay waveforms yet:
``LinkSim`` keeps refusing them (``tests/test_laws.py``) until the numbers
are wired, and nothing here touches the built schemes (fingerprint).
"""
from .golay import aperiodic_autocorr, golay_pair, is_complementary
from .ofdm import OfdmNumerology
from .papr import ccdf, interpolate, obo_for_evm, papr_db, rrc_taps, shape
from .sc import ScNumerology

__all__ = ["aperiodic_autocorr", "golay_pair", "is_complementary", "OfdmNumerology", "ScNumerology",
           "ccdf", "interpolate", "obo_for_evm", "papr_db", "rrc_taps", "shape"]
