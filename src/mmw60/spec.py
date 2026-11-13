"""Specification / literature numbers with provenance (iron rule 5; d2d_link's ``spec`` method).

Every number the library takes from a standard, a paper or a regulation
carries a ``source`` tag; code reads it through :func:`survey` / :func:`value`
and never types the value itself.  ``source`` is one of

* ``spec``     — from the original text; needs ``quote`` and ``section``;
* ``survey``   — from a paper / talk / search hit, unverified (the note
  must say 未核实);
* ``assumed``  — the paper does not say; this library's own choice;
* ``derived``  — computed from the above (the cite is the formula).

Since 2026-11-13 (mmw60_trx#21) the numbers about the outside world live in
the shared library spec_sources, vendored at a full SHA under
``mmw60.vendor.spec_sources`` (its ``data/*.yaml``); this library's own
choices and outputs stay in ``data/spec/survey.yaml``.  This module is a
thin shim: :func:`all_entries` merges the two tables (a key in both is an
error), every public name it had is kept, :class:`SpecNumber` and
``SOURCES`` are the vendored ones (same fields, order, defaults and
checks), and :func:`ref` reads a field of an entry by reference.  The
Fig. 4 read-offs, the LDPC base matrices and the PER thresholds stay here
unchanged.  ``tests/test_spec_sources.py`` counts every tag in every table.
"""
from __future__ import annotations

import warnings
from pathlib import Path

import yaml

from .vendor import spec_sources as _shared
from .vendor.spec_sources import SOURCES, DeprecatedKeyWarning, SpecNumber  # noqa: F401  (re-exported)

DATA_DIR = Path(__file__).resolve().parent / "data" / "spec"
SURVEY_FILE = DATA_DIR / "survey.yaml"     # this library's table: its assumed / derived and 3 survey entries
FIG4_FILE = DATA_DIR / "liu2025_fig4.yaml"
LDPC_FILE = DATA_DIR / "ldpc_80211.yaml"
THRESHOLDS_FILE = DATA_DIR / "per_thresholds.yaml"


def load_table(path: Path = SURVEY_FILE) -> dict[str, SpecNumber]:
    """One table file (by default this library's own) through the shared reader."""
    return _shared.load_table(path)


_TABLE: dict[str, SpecNumber] | None = None


def all_entries() -> dict[str, SpecNumber]:
    """The vendored shared tables plus this library's table; a key that
    appears in both is an error."""
    global _TABLE
    if _TABLE is None:
        _TABLE = _shared.merge_tables(_shared.all_entries(), load_table())
    return _TABLE


def ref(reference: str):
    """A value, or a field of a mapping value, by reference (spec_sources'
    ``ref`` over the merged table)."""
    return _shared.ref(reference, all_entries())


def _resolve(key: str, stacklevel: int) -> SpecNumber:
    table = all_entries()
    if key in table:
        return table[key]
    alias = _shared.aliases().get(key)
    if alias is not None and alias.to in table:
        warnings.warn(f"spec key {key!r} is deprecated since {alias.since}: read {alias.to!r}",
                      DeprecatedKeyWarning, stacklevel=stacklevel)
        return table[alias.to]
    raise KeyError(f"no spec entry {key!r}; known: {sorted(table)}")


def survey(key: str) -> SpecNumber:
    """The entry for ``key`` (any source); KeyError names what exists.

    A key spec_sources has renamed (its tables' ``aliases:``, e.g. the 17
    of 0.2.0, mmw60_trx#23) still reads, with a ``DeprecatedKeyWarning``
    naming the new key, as spec_sources' own reader does; the entry's
    ``.key`` is the new name.  This library's tests turn that warning into
    an error (pyproject ``filterwarnings``), so no old name stays here."""
    return _resolve(key, stacklevel=3)


def value(key: str):
    return _resolve(key, stacklevel=3).value


def unverified() -> dict[str, SpecNumber]:
    return {k: e for k, e in all_entries().items() if e.source == "survey"}


def by_source(source: str) -> dict[str, SpecNumber]:
    return {k: e for k, e in all_entries().items() if e.source == source}


def fig4_readings() -> dict:
    """Liu 2025 Fig. 4 read-offs (``liu2025_fig4.yaml``), as the file holds them."""
    return yaml.safe_load(FIG4_FILE.read_text(encoding="utf-8"))


_LDPC: dict | None = None


def ldpc_document() -> dict:
    """The 802.11 LDPC base-matrix file (``ldpc_80211.yaml``) with its source tag."""
    global _LDPC
    if _LDPC is None:
        _LDPC = yaml.safe_load(LDPC_FILE.read_text(encoding="utf-8"))
    return _LDPC


def ldpc_base_matrices() -> dict:
    """``{n: {rate: base matrix (list of rows)}}`` for n = 648 / 1296 / 1944."""
    return ldpc_document()["matrices"]


_THRESHOLDS: dict | None = None


def per_threshold_document() -> dict:
    """The measured ideal-chain PER thresholds (``per_thresholds.yaml``,
    source derived: ``tools/measure_thresholds.py``) with their tag."""
    global _THRESHOLDS
    if _THRESHOLDS is None:
        _THRESHOLDS = yaml.safe_load(THRESHOLDS_FILE.read_text(encoding="utf-8"))
    return _THRESHOLDS


def per_threshold_db(standard: str, bandwidth_hz: float, mcs: int) -> float | None:
    """SNR per active subcarrier at PER 1e-2 of a 4096-byte packet on the
    ideal chain; None when the base has no coded data field or the MCS
    never reaches the target."""
    table = per_threshold_document()["thresholds_db"]
    return table.get(standard, {}).get(float(bandwidth_hz), {}).get(int(mcs))
