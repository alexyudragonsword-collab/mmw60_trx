# Vendored from array_tx@5815c5a7ea43143fd58502d4894ac840b5b5fb86: src/arraytx/report.py
# Adapted-copy policy: see src/mmw60/vendor/__init__.py
"""Printing helpers: the engine line every example prints, the disclaimer
that goes with an engine whose spur / IM numbers are not evidence (and
why), and small tables."""
from __future__ import annotations

from typing import Iterable

#: every disclaimer carries this phrase; tests and the page look for it
NOT_EVIDENCE = "不能背书"

#: the oversampling at which ex22 found the dtc_openloop numbers converged
#: (os 16 vs os 32 within 0.04 dB on every ACLR / sidelobe metric, polar topology)
CONVERGED_OVERSAMPLING = 16

#: why each engine's spur / IM numbers are not evidence (cairn/dtc-openloop-grid.md)
DISCLAIMERS = {
    "response": ("线性化引擎，不能背书：杂散 / 互调结论只做趋势比较 "
                 "(linearised engine: spur / IM conclusions are trend-only, not evidence)"),
    "dtc_openloop": ("采样网格未收敛（os < 16：ACLR2 偏高约 4.7 dB、DPD 后 ACLR1 偏高约 0.5 dB，ex22），不能背书："
                     "杂散 / 互调结论只做趋势比较 (grid not converged below os 16: spur / IM conclusions are "
                     "trend-only, not evidence)"),
    "dtc_openloop_unverified": ("这个拓扑在 os ≥ 16 的网格收敛没有验证过（ex22 只验了 polar），不能背书：杂散 / 互调结论只做趋势比较 "
                                "(grid convergence unverified for this topology: spur / IM conclusions are trend-only, not evidence)"),
    "rfdac": ("RF-DAC 模型只有失配、没有压缩，网格收敛也未验证，不能背书：杂散 / 互调结论只做趋势比较 "
              "(RF-DAC model has mismatch only and an unverified grid: spur / IM conclusions are trend-only, not evidence)"),
}
#: kept for callers that print the generic wording
DISCLAIMER = DISCLAIMERS["response"]
#: the line a converged dtc_openloop run carries instead of a disclaimer
CONVERGED_NOTE = (f"采样网格已收敛（os ≥ {CONVERGED_OVERSAMPLING}，ex22：os 16 与 os 32 差 ≤ 0.04 dB）"
                  f" (grid converged at os >= {CONVERGED_OVERSAMPLING}, ex22)")


def disclaimer_for(mode: str, topology: str, oversampling: int | None) -> str | None:
    """The disclaimer one engine's run needs, or None when its spur / IM
    numbers are evidence.  Only what ex22 checked is cleared: dtc_openloop,
    polar topology, at an oversampling of 16 or more.  An unknown grid
    (``oversampling=None``) is treated as not converged."""
    if mode == "dtc_openloop":
        if oversampling is None or oversampling < CONVERGED_OVERSAMPLING:
            return DISCLAIMERS["dtc_openloop"]
        return None if topology == "polar" else DISCLAIMERS["dtc_openloop_unverified"]
    return DISCLAIMERS.get(mode)


def engine_line(modes: Iterable[str], topology: str, oversampling: int | None = None) -> str:
    """One line naming the phase-modulation engine(s) the run used and the
    grid, with the reason its spur / IM numbers are not evidence when they
    are not (``disclaimer_for``)."""
    modes = sorted(set(str(m) for m in modes))
    grid = "" if oversampling is None else f", os {int(oversampling)}"
    s = f"engine: {', '.join(modes) or 'n/a'} (topology {topology}{grid})"
    notes = [d for d in dict.fromkeys(disclaimer_for(m, topology, oversampling) for m in modes) if d]
    if notes:
        s += " — " + " / ".join(notes)
    elif "dtc_openloop" in modes:
        s += " — " + CONVERGED_NOTE
    return s


def table(rows: list[dict], columns: list[str] | None = None, fmt: str = "{:>10}") -> str:
    """Fixed-width text table from dict rows (numbers to 2 decimals)."""
    if not rows:
        return "(empty)"
    cols = columns or list(rows[0].keys())

    def cell(v):
        if isinstance(v, float):
            return f"{v:.2f}"
        return str(v)
    widths = {c: max(len(c), *(len(cell(r.get(c, ""))) for r in rows)) for c in cols}
    line = "  ".join(c.rjust(widths[c]) for c in cols)
    out = [line, "  ".join("-" * widths[c] for c in cols)]
    for r in rows:
        out.append("  ".join(cell(r.get(c, "")).rjust(widths[c]) for c in cols))
    return "\n".join(out)
