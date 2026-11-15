# Vendored from array_tx@5815c5a7ea43143fd58502d4894ac840b5b5fb86: src/arraytx/design.py
# Adapted-copy policy: see src/mmw60/vendor/__init__.py
"""Scan design helpers: the |1 + Gamma| backoff rule (ex19 / ex20 / ex21, and
the workbench's backoff-rule study through ``guiutil.rule_report``).

The design TARGETS are not here and not in the config: they are design
choices (source: assumed), passed in by the caller -- an example's constants
or the page's inputs."""
from __future__ import annotations

import math

import numpy as np


def meets(aclr1_db: float, evm_db: float, margin_db: float, aclr_target_dbc: float, evm_target_db: float) -> bool:
    """ACLR1 plus the DPD-table margin at or below the target, and EVM at or below its target."""
    return bool(aclr1_db + margin_db <= aclr_target_dbc and evm_db <= evm_target_db)


def backoff_rule(ms, bs, tol: float = 0.0):
    """backoff(m) from training pairs (m = mean |1 + Gamma| at an angle, b =
    the least backoff meeting the targets there): monotone (cumulative max in
    m), the nearest trained point at or above m - tol; above the range, the
    fitted dB per unit m, rounded up.  ``tol`` reads an m within tol of a
    trained point as that point (|1 + Gamma| repeats to ~0.002 across
    operating points; 0 = ex19's rule).  Returns (rule, sorted m, monotone
    backoffs, slope); rule(m) -> (backoff dB, extrapolated?)."""
    order = np.argsort(ms)
    m_sorted = np.asarray(ms, dtype=float)[order]
    b_mono = np.maximum.accumulate(np.asarray(bs, dtype=float)[order])
    slope = float(np.polyfit(m_sorted, b_mono, 1)[0]) if np.ptp(m_sorted) > 0 else 0.0

    def rule(m):
        i = int(np.searchsorted(m_sorted, m - tol - 1e-9))
        if i < len(m_sorted):
            return float(b_mono[i]), False
        return float(b_mono[-1] + math.ceil(max(slope, 0.0) * (m - tol - m_sorted[-1]) - 1e-9)), True
    return rule, m_sorted, b_mono, slope
