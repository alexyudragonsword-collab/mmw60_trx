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
  ``e573d4d99dcf0584b7245c4869aaaa8a84ada24c`` (0.2.0, its PR #5;
  mmw60_trx#23; first pinned at d7b4d1e for mmw60_trx#21): ``src/spec_sources/__init__.py``, ``reader.py`` and six
  of its data tables (``liu2025``, ``ieee80211``, ``regulatory``,
  ``frontend60``, ``pa60``, ``energy``; not ``ucie``, not
  ``legacy_keys/``).  The numbers about the outside world that this
  library reads; ``mmw60.spec`` merges them with this library's own table.
  The YAML files carry the same two-line header as ``#`` comments and are
  checked by ``tools/vendor_check.py`` like the code.
"""
