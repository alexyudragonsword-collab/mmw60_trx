"""Vendored sibling code: checkable adapted copies, never forks.

``mmw60.vendor.wifitrx`` is the whole ``src/wifitrx`` package of
``alexyudragonsword-collab/wifi_trx_cal`` at the commit named in every
file's first line (full SHA).  Policy (polar_tx CONTRIBUTING §3):

* every file keeps a two-line attribution header::

      # Vendored from wifi_trx_cal@<full sha>: src/wifitrx/<path>
      # Adapted-copy policy: see src/mmw60/vendor/__init__.py

* ``tools/vendor_check.py`` strips exactly those two lines and compares
  the body with ``git show <sha>:<path>`` in the sibling checkout.  A
  body that differs in anything but import lines must be declared in
  ``tools/vendor_manifest.json`` (``extended``) with a reason; an
  undeclared edit is DRIFT and fails CI.  The milestone-0 copy is
  entirely verbatim (the manifest is empty).
* upclocking (``upclock: K``), the Rapp PA, the VHT data-field coding,
  the L-STF coarse CFO estimator and everything else this library adds
  live in ``mmw60`` proper and wrap the vendored functions.  Anything
  wifitrx itself would need (a frequency multiplier model, PA bandwidth
  terms, a two-DUT cascade) is reported to its ROADMAP and re-pinned
  after it lands; the copy is not edited.
* wifitrx's own files already carry ``# Vendored from PA_DPD:…`` /
  ``pll_simulator`` comments (its PROVENANCE.md); those are part of the
  body and are compared as such.  PA_DPD is therefore not pinned a second
  time here: what wifitrx vendored from it arrives through this one pin.

Import only through ``mmw60.vendor.wifitrx...``; the package's internal
imports are all relative, so it runs unchanged under this path.

Pins:

* ``wifitrx`` — wifi_trx_cal, the SHA in every file's first line.
* ``spec_sources`` — ``alexyudragonsword-collab/spec_sources`` @
  ``25b2c5eb25fae98027a190b9757e50056b776d81`` (spec_sources#43, PR #46: the
  rho = 2 codeword; before: 563cff4 for #43's PR #44, a9af261 for its 0.6.0
  and mmw60_trx#63, 76ee72a for
  spec_sources#33 with its 0.5.0 and the
  7th batch, 3123b65 for spec_sources#29, 7aae876 for spec_sources#26, 8e5f2e2 for
  mmw60_trx#27, 9a443ba for #25, e573d4d for #23, d7b4d1e for #21): ``src/spec_sources/__init__.py``,
  ``reader.py`` and seven of its data tables (``liu2025``,
  ``ieee802153c``, ``ieee80211``, ``regulatory``, ``frontend60``,
  ``pa60``, ``energy``; not ``ucie``, ``radar_targets``, ``windows``,
  not ``legacy_keys/``).  The numbers about the outside world that this
  library reads; ``mmw60.spec`` merges them with this library's own table.
  The YAML files carry the same two-line header as ``#`` comments and are
  checked by ``tools/vendor_check.py`` like the code.
* ``arraytx`` — ``alexyudragonsword-collab/array_tx`` @
  ``5815c5a7ea43143fd58502d4894ac840b5b5fb86`` (milestone 2, the array
  layer): the whole ``src/arraytx`` package, its 135 ``.py`` files
  verbatim, its own vendored polar_tx (with polar_tx's PA_DPD and
  pll_simulator copies) included.  Its non-code assets (``data/`` clock
  profiles, ``webui/``) are not copied: this library uses only the linear
  array model — ``geometry``, ``beam`` (array factor, steering weights,
  squint, beamwidth), ``coupling`` — and puts its own shared
  ``Frontend60`` behind every element (iron rule 2), never arraytx's
  element chains.  One absolute name in it would not resolve under this
  path: ``lo.py`` looks up ``arraytx.data`` for its bundled clock profiles,
  a path this library does not take.  arraytx is a 28 GHz FR2 library; the
  60 GHz carrier is passed in (``ArrayGeometry(f0_hz=…)``), no arraytx
  ``Standard`` is used.
"""
