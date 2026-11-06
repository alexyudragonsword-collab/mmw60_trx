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
"""
