"""Which ``Mmw60Config`` fields does a computation read?

Records attribute access on the config dataclasses while a callable runs and
returns the dotted paths (``lo.phase_noise.psd0_dbchz``).  The interface's
compute layer declares, per kind of result, the form knobs that result reads
(``guiutil.JOBS[...].reads``): a knob the code touches and the declaration
omits would show a stale result as fresh, so ``tests/test_guiutil.py`` runs
every kind of result under this tracer and requires traced <= declared.

A traced path is a field the code *looked at*, which is more than the fields
that move the result (``to_dict()``, ``describe()`` and ``dataclasses.replace``
touch every field of the object they are called on): the trace errs on the
side of declaring too much, the safe side.
"""
from __future__ import annotations

import dataclasses as dc
from contextlib import contextmanager

from mmw60 import config as C


def _paths() -> dict[type, str]:
    """Config dataclass -> its dotted prefix inside ``Mmw60Config`` ('' for the top)."""
    out: dict[type, str] = {}

    def walk(obj, prefix):
        out[type(obj)] = prefix
        for f in dc.fields(obj):
            v = getattr(obj, f.name)
            if dc.is_dataclass(v) and not isinstance(v, type):
                walk(v, f"{prefix}{f.name}.")
    walk(C.Mmw60Config(), "")
    return out


PREFIX = _paths()


@contextmanager
def tracing():
    """``with tracing() as seen:`` — ``seen`` is the set of dotted leaf and
    section paths read inside the block."""
    seen: set[str] = set()
    saved = {}
    for cls, prefix in PREFIX.items():
        names = {f.name for f in dc.fields(cls)}
        orig = cls.__getattribute__
        saved[cls] = orig

        def ga(self, name, _o=orig, _n=names, _p=prefix):
            if name in _n:
                seen.add(_p + name)
            return _o(self, name)
        cls.__getattribute__ = ga
    try:
        yield seen
    finally:
        for cls, orig in saved.items():
            cls.__getattribute__ = orig


def traced(fn) -> set[str]:
    with tracing() as seen:
        fn()
    return set(seen)
