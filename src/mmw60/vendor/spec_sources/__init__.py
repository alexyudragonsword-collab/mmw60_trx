# Vendored from spec_sources@8e5f2e26bc2084d324aaaabea49fab18174ecaf8: src/spec_sources/__init__.py
# Adapted-copy policy: see src/mmw60/vendor/__init__.py
"""spec_sources: numbers about the outside world -- specification clauses,
paper and datasheet figures, and what is derived from them alone -- each with
its provenance, plus the reader and the guards.  No simulation.

The reader is :mod:`.reader`; this module re-exports its public names, which
are a superset of mmw60_trx's ``mmw60.spec`` (``SpecNumber``, ``SOURCES``,
``load_table``, ``all_entries``, ``survey``, ``value``, ``unverified``,
``by_source``) plus :func:`ref`.  The package is vendored as it is: relative
imports only, data next to the code, PyYAML the only dependency.
"""
from .reader import (
    DATA_DIR,
    FIELDS,
    KEY_PATTERN,
    LEGACY_DIR,
    SOURCES,
    Alias,
    DeprecatedKeyWarning,
    SpecNumber,
    aliases,
    all_entries,
    audit_tags,
    by_source,
    data_files,
    legacy_keys,
    load_table,
    merge_tables,
    ref,
    survey,
    unverified,
    value,
)

#: the package version (pyproject.toml has the same); kept here, not in reader.py, so that a
#: consumer vendoring only reader.py and its tables sees no change from a version bump alone
__version__ = "0.4.0"

__all__ = ["SpecNumber", "SOURCES", "load_table", "all_entries", "survey", "value", "unverified", "by_source",
           "ref", "aliases", "Alias", "DeprecatedKeyWarning", "legacy_keys", "merge_tables", "audit_tags",
           "data_files", "FIELDS", "KEY_PATTERN", "DATA_DIR", "LEGACY_DIR", "__version__"]
