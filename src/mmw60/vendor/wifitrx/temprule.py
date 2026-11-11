# Vendored from wifi_trx_cal@7b8d08eb9f11e426f9c99e079ebcbe06c2c64a02: src/wifitrx/temprule.py
# Adapted-copy policy: see src/mmw60/vendor/__init__.py
"""The temperature rules a residual can carry, and how to evaluate them.

A cal-state file's residual surface is measured at one temperature.
Schema 1.2 lets each ``role="impairment"`` key carry a ``temperature``
record — a few sampled points, the name of the interpolation that
connects them, and what a recalibration at the target temperature is
guaranteed to leave (``after_recal``) — and this module is the one
place that turns such a record into a number at a temperature.  The
study that produced the rules (:mod:`wifitrx.link.temp_residual_study`)
and the replay that consumes them (:mod:`wifitrx.handoff.replay`) both
import *this*, so the fit the study validated and the fit the consumer
runs cannot be two implementations that agree by luck.

It deliberately imports nothing from the model (no ``chain``, no
``cal``): the replay must stay a consumer's view.

Interpolation kinds (``interp``):

* ``linear`` — ``a + b (T - 25)``, least squares over the points.
* ``vee_dbc`` — a nulled amplitude drifting linearly: ``20 log10
  max(|a (T - 25)|, floor)``, one slope from the off-null points, the
  floor from the on-null point.  The LO leak after its amplitude-matched
  null; measured 0.59 dB over 10 validation points where the exact
  complex-null parabola misfit by 1.81 dB (the drift is exponential in
  dB/degC, not linear in amplitude).
* ``null_irr`` — residual image power ``|r0 + b (T - 25)|^2`` as an
  exact three-point parabola, read as IRR ``-10 log10 P``.
* ``null_evm`` — the same exact parabola of an error power, read the
  other way up, ``+10 log10 P``: an EVM-like figure whose error vector
  is a floor plus a part that drifts linearly with temperature.  The
  DPD residual once the driver gain has a tempco: the predistorter is
  the inverse at the calibration drive and mismatches it either way
  (measured on a -0.02 dB/degC part: 0.17 dB over the validation points,
  where a linear rule misses by 1.4 dB).
* ``null_irr_tones`` — ``null_irr`` applied to every tone of a per-tone
  IRR array, the shipped minimum then taken over the predicted tones.
  The minimum over tones switches tone with temperature and no single
  null follows it (1.0 / 2.0 dB measured); each tone is a real null
  (0.006 / 0.75 dB).  Points carry ``tones`` as well as ``value``.
* ``hold`` — the calibrated-temperature value everywhere: today's
  behaviour, and what a key with no temperature path gets.
"""
from __future__ import annotations

import numpy as np

CAL_TEMP_C = 25.0

INTERP_KINDS = ("linear", "vee_dbc", "null_irr", "null_evm", "null_irr_tones",
                "hold")

#: how each power-parabola kind reads its dB value: an IRR is -10 log P
#: of the residual image power, an EVM +10 log P of the error power
_POWER_SIGN = {"null_irr": -1.0, "null_evm": +1.0}


# ------------------------------------------------------------ fitting
def _to_power(v: np.ndarray, kind: str = "null_irr") -> np.ndarray:
    return 10.0 ** (_POWER_SIGN[kind] * np.asarray(v, dtype=float) / 10.0)


def _from_power(p: np.ndarray, kind: str = "null_irr") -> np.ndarray:
    return _POWER_SIGN[kind] * 10.0 * np.log10(np.maximum(p, 1e-30))


def fit(kind: str, temps_c, values) -> dict:
    """Coefficients of ``kind`` through the points, in x = T - 25.

    ``values`` is one number per temperature, or for ``null_irr_tones``
    a (n_temps, n_tones) array.
    """
    t = np.asarray(temps_c, dtype=float)
    x = t - CAL_TEMP_C
    v = np.asarray(values, dtype=float)
    if kind == "hold":
        if CAL_TEMP_C not in t:
            raise ValueError("hold needs the calibrated-temperature point")
        return {"value": float(v[t == CAL_TEMP_C][0])}
    if kind == "linear":
        a = np.stack([np.ones_like(x), x], axis=1)
        sol, *_ = np.linalg.lstsq(a, v, rcond=None)
        return {"a": float(sol[0]), "b_per_c": float(sol[1])}
    if kind == "vee_dbc":
        # one slope, least squares on the off-null points (|A| = |a x|),
        # the on-null point as the floor
        amp = 10.0 ** (v / 20.0)
        off = x != 0.0
        if off.sum() == 0:
            raise ValueError("the V needs at least one off-null point")
        a = float(np.sum(np.abs(amp[off]) * np.abs(x[off]))
                  / np.sum(x[off] ** 2))
        floor = float(np.min(amp))
        return {"slope_amp_per_c": a, "floor_amp": floor,
                "floor_dbc": float(20.0 * np.log10(max(floor, 1e-30)))}
    if kind in _POWER_SIGN:
        # |r0 + b x|^2 = c0 + c1 x + c2 x^2: three unknowns, three
        # points, so the fit is exact and every validation point is a
        # genuine prediction.  c2 = |b|^2 is the drift rate squared,
        # c0 = |r0|^2 the 25 degC residual power.
        if t.size != 3:
            raise ValueError(f"{kind} is an exact three-point fit")
        p = _to_power(v, kind)
        c = np.linalg.solve(np.stack([np.ones_like(x), x, x ** 2], axis=1), p)
        c0, c1, c2 = (float(ci) for ci in c)
        return {"c0": c0, "c1": c1, "c2": c2,
                "drift_amp_per_c": float(np.sqrt(max(c2, 0.0))),
                "null_temp_c": (CAL_TEMP_C - c1 / (2.0 * c2)) if c2 > 0 else None,
                "shape_ok": bool(c2 > 0 and c1 ** 2 <= 4.0 * c0 * c2 * 1.0001)}
    if kind == "null_irr_tones":
        if v.ndim != 2:
            raise ValueError("null_irr_tones needs a (n_temps, n_tones) array")
        cols = [fit("null_irr", t, v[:, j]) for j in range(v.shape[1])]
        return {"tones": cols, "n_tones": len(cols),
                "shape_ok": all(c["shape_ok"] for c in cols)}
    raise ValueError(f"unknown interp kind {kind!r}; one of {INTERP_KINDS}")


def predict(kind: str, coeffs: dict, temps_c) -> np.ndarray:
    """``kind`` evaluated at ``temps_c`` from its coefficients."""
    t = np.asarray(temps_c, dtype=float)
    x = t - CAL_TEMP_C
    if kind == "hold":
        return np.full(t.shape, float(coeffs["value"]))
    if kind == "linear":
        return coeffs["a"] + coeffs["b_per_c"] * x
    if kind == "vee_dbc":
        amp = np.maximum(np.abs(coeffs["slope_amp_per_c"] * x),
                         coeffs["floor_amp"])
        return 20.0 * np.log10(amp)
    if kind in _POWER_SIGN:
        p = coeffs["c0"] + coeffs["c1"] * x + coeffs["c2"] * x ** 2
        return _from_power(p, kind)
    if kind == "null_irr_tones":
        # the shipped minimum of the predicted tones
        per_tone = np.stack([predict("null_irr", c, t) for c in coeffs["tones"]],
                            axis=1)
        return per_tone.min(axis=1)
    raise ValueError(f"unknown interp kind {kind!r}; one of {INTERP_KINDS}")


def scale_drift(kind: str, coeffs: dict, scale: float) -> dict:
    """The same coefficients with the drift term multiplied by ``scale``
    — a hardware tempco off its nominal by that factor.  The null
    forms scale their cross term once and their |b|^2 twice."""
    c = dict(coeffs)
    if kind == "linear":
        c["b_per_c"] = coeffs["b_per_c"] * scale
    elif kind == "vee_dbc":
        c["slope_amp_per_c"] = coeffs["slope_amp_per_c"] * scale
    elif kind in _POWER_SIGN:
        c["c1"] = coeffs["c1"] * scale
        c["c2"] = coeffs["c2"] * scale ** 2
    elif kind == "null_irr_tones":
        c["tones"] = [scale_drift("null_irr", cj, scale) for cj in coeffs["tones"]]
    return c


# ------------------------------------------------------------ records
def fit_record(record: dict) -> dict:
    """Coefficients from a key's file record (``interp`` + ``points``)."""
    kind = record.get("interp", "hold")
    pts = sorted(record.get("points") or [], key=lambda p: p["t_c"])
    if not pts:
        raise ValueError("temperature record carries no points")
    t = [float(p["t_c"]) for p in pts]
    if kind == "null_irr_tones":
        v = np.array([p["tones"] for p in pts], dtype=float)
    else:
        v = np.array([p["value"] for p in pts], dtype=float)
    return fit(kind, t, v)


def value_at(record: dict, temp_c: float, recalibrated: bool = False) -> dict:
    """What the key is worth at ``temp_c`` under the file's own rule.

    Returns ``{"value", "rule", "detail"}``.  ``recalibrated=False`` is
    the frozen rule: the corrections stay at their calibrated values and
    the residual drifts along ``interp`` through ``points``.
    ``recalibrated=True`` is the ``after_recal`` rule: the part has been
    recalibrated at the target temperature, and the residual is the
    bound its step guarantees — ``after_recal.value`` in the key's own
    unit, read directly.  Both are worst-case readings for a consumer:
    a bound is injected as the bound.
    """
    if recalibrated:
        ar = record.get("after_recal")
        if not ar or "value" not in ar:
            raise ValueError("record carries no after_recal bound")
        value = float(ar["value"])
        if ar.get("unit") == "% of nominal":
            # a trim bound is stated as a fraction of the nominal; the
            # injectable worst case is the low corner (more droop)
            value = float(ar["nominal_hz"]) * (1.0 - value / 100.0)
        return {"value": value,
                "rule": f"after_recal {ar.get('kind', 'bound')} "
                        f"({ar.get('sense', '?')} {ar['value']:g}"
                        f"{' ' + ar['unit'] if ar.get('unit') else ''})",
                "detail": ar.get("reason", "")}
    kind = record.get("interp", "hold")
    coeffs = fit_record(record)
    v = float(predict(kind, coeffs, [temp_c])[0])
    pts = record.get("points") or []
    return {"value": v,
            "rule": f"interp {kind} through {len(pts)} points at "
                    + "/".join(f"{p['t_c']:g}" for p in pts) + " degC",
            "detail": ""}
