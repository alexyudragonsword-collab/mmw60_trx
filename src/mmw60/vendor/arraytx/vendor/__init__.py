# Vendored from array_tx@5815c5a7ea43143fd58502d4894ac840b5b5fb86: src/arraytx/vendor/__init__.py
# Adapted-copy policy: see src/mmw60/vendor/__init__.py
"""Adapted copies of the sibling libraries arraytx builds on.

This tree is a VERIFIABLE COPY, not a fork (polar_tx CONTRIBUTING 3): every
file carries an attribution header naming its upstream repository, commit and
path, and ``tools/vendor_check.py --strict`` re-derives the relationship on
every CI run.  Code outside this tree imports only through
``arraytx.vendor.polartx...``.

Pins
----
* ``polartx/`` — polar_tx @ ``b007e60477bac68806138db733cbafd0c0761282`` (polar_tx
  ``main``), ``src/polartx`` minus its GUI surface (``guiutil.py``,
  ``appbridge.py``, ``guispec.py``, ``webhost.py``, ``webui/``) and the
  ``py.typed`` packaging marker (meaningful only at the root of polar_tx's own
  distribution).  No non-GUI module imports the GUI surface (only two comments
  name ``guiutil``).  Everything else is verbatim, package ``__init__``
  included.  polar_tx's own nested vendor tree comes along unchanged, with
  ITS attribution headers, and is checked against ITS upstreams:
  - ``polartx/vendor/padpd/`` — PA_DPD @ ``44cbcb3`` (``pa/thermal.py`` and
    ``gain_modulation.py`` @ ``08b9725595748b290c76d1b70355f7e6014a709e``),
    ``pa/presets.py`` is polar_tx's extraction (manifest-pinned);
  - ``polartx/vendor/pllsim/`` — pll_simulator @ ``5564c64``, the whole tree
    (polar_tx's C5: ``arch/adpll.py`` is polar_tx's extension of upstream's
    kernel -- ``mod_freq_dp`` and the ``dp_cal`` step kernel -- and
    ``arch/frac.py`` its extraction of ``FracConfig``; both manifest-pinned,
    no pin held back any more).  ``core/jit.py`` uses numba when it is
    installed and falls back to plain Python otherwise; arraytx builds no
    ADPLL chain, so neither path runs here.
* ``polartx/vendor/pllsim/export/clock_profile.py`` — pll_simulator @
  ``5564c6430279036a78eea6829f4fecb13adac233``, the same commit as the rest of
  the nested pllsim tree.  polar_tx does not vendor pllsim's ``export``
  package; this one file is taken and placed inside the nested tree so its
  ``..core`` relative imports resolve.  The ``export/__init__.py`` is
  arraytx's.

Local changes
-------------
None in any ``.py`` body.  The only arraytx-authored lines are the two-line
attribution headers on polar_tx's own files and the ``export/__init__.py``
above.  A change to a vendored body goes upstream first, then gets
re-vendored; if it cannot, it is declared in ``tools/vendor_manifest.json``
with a reason, or it does not happen.
"""
