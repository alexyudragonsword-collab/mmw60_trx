# Vendored from wifi_trx_cal@cc06b9ac8dafb5cbb261a59280e81ae0cfbf787c: src/wifitrx/link/temp_residual_study.py
# Adapted-copy policy: see src/mmw60/vendor/__init__.py
"""Can a residual carry a temperature coefficient?  (Phase 1: data only.)

The cal-state file ships its residual surface at 25 degC and an
``expiry`` block that says how far the corrections hold.  A consumer
simulating the link at 85 degC has no number: inside the hold window
there is no drift figure, outside it only "recalibrate", not what a
recalibration leaves.  Before the file format grows a temperature axis
(phase 2), three things have to be measured rather than assumed:

* **H1** — frozen at the 25 degC corrections, do the *continuous*
  residuals (LO-leak null, image rejection, receive figures) follow a
  low-order model in temperature well enough that three points predict
  the rest?
* **H2** — after recalibrating at each temperature, are the *quantised*
  residuals (the RC tuning code's corner error) bounded by half a code
  and uncorrelated with temperature — a sawtooth, not a slope — while
  the continuous ones return to their estimator floor?
* **H3** (phase 2) — does a replay at a second temperature close.

The split is by the *kind of correction*, not by the key's physics: a
continuous digital quantity (``dc_pre``, ``w2``, ``gain_code_db``)
re-estimates to the floor, a trim code lands wherever the drift's
remainder against the code pitch puts it.  ``classify_residuals`` is
that table.

The models are deliberately few.  The LO leak after its
amplitude-matched null is a "V": the residual amplitude grows as
``|a (T - 25)|`` either side of the null, floored by whatever the null
left at 25 degC.  An image after its w2 is the other nulled complex
quantity, but its 25 degC remainder is frequency-dependent and of the
same order as the drift over a few tens of degrees, so it is not a
small floor and the V misfits it (3.5 dB measured); its residual power
``|r0 + b (T - 25)|^2`` is a parabola in the power domain instead.
Everything else is linear in its own unit.  Fit temperatures and
validation temperatures never overlap: scoring on the training points
is the silent optimism of backlog B18.

Every function here consumes the rows ``temp_study.temperature_hold_study``
emits with ``residual_keys=True`` (and ``recalibrate=True`` for H2) and
returns plain dicts — no plotting, no file format.
"""
from __future__ import annotations

import inspect

import numpy as np

from ..cal.residuals import RESIDUAL_SPEC
from ..cal.tx_lo_leak import calibrate_tx_lo_leak_loopback
from ..temprule import fit as _rule_fit
from ..temprule import predict as _rule_predict
from ..temprule import scale_drift

#: What the loopback leak step leaves alone: a frozen leak already at or
#: below this is not refined ("near the measurement floor the iteration
#: just walks on noise"), so after a recalibration the leak is bounded by
#: this, not returned to the 25 degC null.  Read from the step's own
#: signature so the bound cannot drift from the behaviour.
LEAK_SKIP_DBC: float = float(inspect.signature(calibrate_tx_lo_leak_loopback)
                             .parameters["skip_below_dbc"].default)

#: 13 points over the industrial range.  A 10 degC grid from -40 cannot
#: contain 25, 55 or 85, so the upper half is placed on the fit and
#: sensitivity temperatures instead; -40 and 85 are the range ends.
TEMPS: tuple[float, ...] = (-40.0, -30.0, -20.0, -10.0, 0.0, 10.0, 25.0,
                            30.0, 40.0, 55.0, 60.0, 70.0, 85.0)
#: the three points a coefficient would be fitted from
FIT_TEMPS: tuple[float, ...] = (-10.0, 25.0, 55.0)
#: where the coefficient's robustness is judged
SENSITIVITY_TEMP_C = 85.0
#: what a delivered file is swept over: the fit points, which become the
#: shipped samples, and the two range ends, which become closure targets
#: nobody fitted on (the E4 temperatures)
DELIVERY_TEMPS: tuple[float, ...] = (-40.0, -10.0, 25.0, 55.0, 85.0)

#: Placeholder temperature coefficients for a delivered file.  The model
#: carries a tempco on every drifting carrier but defaults them all to
#: zero — no part data says otherwise — and a file whose rules came out
#: of a zero-tempco part would ship flat lines that look like stability.
#: These are the values the study ran on (sized so a 25 degC calibration
#: holds the industrial range against the -40 dBc / 50 dB / 2 % specs,
#: see ``reference_pair``) plus a driver-gain tempco, without which the
#: DPD has no temperature path and its tracked and frozen rules could not
#: be told apart.  -0.02 dB/degC moves the PA drive by 2.5 dB over the
#: range.  They are placeholders in the same sense as the baseband noise
#: table of backlog A4: every file built on them says so
#: (``residuals.temperature.tempco_source``), and circuit or bench values
#: replace them without changing any code.  At 25 degC every one of them
#: multiplies (T - 25) = 0, so applying them changes no calibrated number.
PLACEHOLDER_TEMPCOS: dict[str, float] = {
    "rc_tempco_per_c": 2e-4,
    "phase_tempco_deg_per_c": 0.004,
    "lo_leak_tempco_db_per_c": 0.02,
    "pa_gain_tempco_db_per_c": -0.02,
}

#: where each tempco lives: (side, attribute path)
_TEMPCO_FIELDS: dict[str, tuple[tuple[str, str], ...]] = {
    "rc_tempco_per_c": (("tx", "lpf"), ("rx", "lpf")),
    "phase_tempco_deg_per_c": (("tx", "iq"), ("rx", "iq")),
    "lo_leak_tempco_db_per_c": (("tx", ""),),
    "pa_gain_tempco_db_per_c": (("tx", ""),),
}


def apply_tempcos(tx_params, rx_params, tempcos: dict) -> None:
    """Set ``tempcos`` on the parameter objects of both chains."""
    sides = {"tx": tx_params, "rx": rx_params}
    for name, value in tempcos.items():
        if name not in _TEMPCO_FIELDS:
            raise KeyError(f"unknown tempco {name!r}; one of "
                           f"{sorted(_TEMPCO_FIELDS)}")
        for side, attr in _TEMPCO_FIELDS[name]:
            obj = getattr(sides[side], attr) if attr else sides[side]
            setattr(obj, name, float(value))


def part_tempcos(tx, rx) -> dict:
    """The tempcos the chains actually carry, per side — what a file's
    rules were computed from, read back rather than remembered."""
    sides = {"tx": tx.params, "rx": rx.params}
    out: dict[str, dict] = {"tx": {}, "rx": {}}
    for name, places in _TEMPCO_FIELDS.items():
        for side, attr in places:
            obj = getattr(sides[side], attr) if attr else sides[side]
            out[side][name] = float(getattr(obj, name))
    return out

#: Steps whose correction is a trim code rather than a continuous
#: estimate — the residual after recalibration is a remainder against
#: the code pitch, not an estimator floor.  Everything else that ships
#: as ``role="impairment"`` is continuous.
QUANTIZED_STEPS: dict[str, str] = {
    "tx_lpf_corner": "RC tuning code: 1 LSB moves the corner by rc_step",
    "rx_lpf_corner": "RC tuning code: 1 LSB moves the corner by rc_step",
    "rx_iip2": "mixer IM2 trim code (parabolic null, no temperature "
               "path in the model)",
}

#: How a quantised key's post-recalibration residual is read from a row,
#: as (value, one LSB in the same unit, unit).  The corner keys read the
#: model-truth corner error the row already carries; the IM2 trim reads
#: the code's distance from the model's best code.
QUANTIZED_RESIDUAL = {
    "tx_lpf_corner.fc_hz": lambda row: (
        float(row["tx_fc_err_pct"]), float(row["codes"]["rc_lsb_pct"]), "%"),
    "rx_lpf_corner.fc_hz": lambda row: (
        float(row["rx_fc_err_pct"]), float(row["codes"]["rx_rc_lsb_pct"]),
        "%"),
    "rx_iip2.iip2_dbm": lambda row: (
        float(row["codes"]["im2_trim_code"] - row["codes"]["im2_trim_best"]),
        1.0, "code"),
}

#: Which fitted model each key gets.  ``vee_dbc``: amplitude V
#: ``max(|a (T-25)|, floor)`` converted to dBc; ``null_irr_tones``: one
#: power-domain parabola of a drifting complex null PER TONE (the
#: ``tones`` array the row carries), the shipped minimum then taken over
#: the predicted tones — because the minimum itself switches tone with
#: temperature and no single null follows it (1.0 / 2.0 dB measured
#: with ``null_irr``, the scalar form, kept for reference).  Keys not
#: listed are linear.
MODELS: dict[str, str] = {
    "tx_lo_leak_envdet.lo_leak_dbc": "vee_dbc",
    "tx_lo_leak_loopback.lo_leak_dbc": "vee_dbc",
    "tx_iq.irr_min_db": "null_irr_tones",
    "rx_iq.irr_min_db": "null_irr_tones",
    # the predistorter is the inverse at the calibration drive; a driver
    # gain drift mismatches it either way, so its error power is a
    # parabola in temperature.  Phase 2 shipped "linear" here, which
    # held only because that part had no driver-gain tempco: with -0.02
    # dB/degC linear misses the range ends by 1.4 dB, the parabola by
    # 0.17 (frozen) / 0.19 (tracked).
    "dpd.evm_db": "null_evm",
}

#: Prediction-error criterion per key: (width, unit of the error, why).
#: The widths for EVM, leak/IRR and corner are the study's brief; the
#: rest are placed in the same families.
CRITERIA: dict[str, tuple[float, str, str]] = {
    "tx_lpf_corner.fc_hz": (0.3, "%", "corner family"),
    "rx_lpf_corner.fc_hz": (0.3, "%", "corner family"),
    "tx_lo_leak_envdet.lo_leak_dbc": (1.0, "dB", "leak/IRR family"),
    "tx_lo_leak_loopback.lo_leak_dbc": (1.0, "dB", "leak/IRR family"),
    "tx_iq.irr_min_db": (1.0, "dB", "leak/IRR family"),
    "rx_iq.irr_min_db": (1.0, "dB", "leak/IRR family"),
    "rx_dc_offset.worst_dc_dbfs": (1.0, "dB", "a level figure, as leak"),
    "rx_iip2.iip2_dbm": (1.0, "dB", "a level figure, as leak"),
    "dpd.evm_db": (0.5, "dB", "EVM family"),
    "final_loopback_evm.rx_nf_db": (0.5, "dB", "enters the EVM budget "
                                                "directly, EVM family"),
    "final_loopback_evm.rx_im3_dbc": (0.5, "dB", "EVM family"),
    "final_loopback_evm.rx_phase_err_dbc": (0.5, "dB", "EVM family"),
    "group_delay.error_ps": (8.0, "ps", "a tenth of the step's own 80 ps "
                                        "tolerance"),
}


# ------------------------------------------------------------ classification
def classify_residuals(spec: dict | None = None) -> dict[str, str]:
    """``{key: "continuous" | "quantized"}`` for every injectable key.

    Read from each entry's ``temp_class`` in ``RESIDUAL_SPEC`` — the
    shipped contract — and refused when an injectable key lacks one;
    ``QUANTIZED_STEPS`` is the reasoning behind those entries.  Totals,
    figures and conditions are left out because a temperature rule
    never attaches to them.
    """
    spec = RESIDUAL_SPEC if spec is None else spec
    out = {}
    for k, v in spec.items():
        if v.get("role") != "impairment":
            continue
        cls = v.get("temp_class")
        if cls not in ("continuous", "quantized"):
            raise ValueError(f"{k}: impairment entry without a temp_class")
        out[k] = cls
    return out


# ------------------------------------------------------------ seed pooling
_SCALARS = ("lo_leak_dbc", "irr_min_db", "tx_evm_db", "tx_evm_modem_db",
            "tx_fc_err_pct", "rx_fc_err_pct")


def median_rows(runs: list[list[dict]]) -> list[dict]:
    """Pool the per-seed row lists of one sweep: medians per temperature,
    with the across-seed 1-sigma of every residual key kept beside it.

    Non-numeric content (codes, the recalibration record) is taken from
    the first run; ``codes_agree`` records whether every seed landed on
    the same trim codes, which for the recalibration path is also the
    statement that the steps' own seeds are fixed.
    """
    if not runs:
        raise ValueError("no runs to pool")
    n_t = len(runs[0])
    if any(len(r) != n_t for r in runs):
        raise ValueError("every run must cover the same temperatures")
    rows = []
    for i in range(n_t):
        pts = [run[i] for run in runs]
        temps = {float(p["temp_c"]) for p in pts}
        if len(temps) != 1:
            raise ValueError(f"temperature mismatch across runs at {i}")
        row = {"temp_c": temps.pop(), "n_seeds": len(pts)}
        for k in _SCALARS:
            if k in pts[0]:
                row[k] = float(np.median([p[k] for p in pts]))
        if "residuals" in pts[0]:
            keys = list(pts[0]["residuals"])
            row["residuals"] = {}
            row["residual_sigma"] = {}
            for k in keys:
                v = np.array([p["residuals"][k] for p in pts], dtype=float)
                row["residuals"][k] = float(np.median(v))
                row["residual_sigma"][k] = _sigma(v)
        if "tones" in pts[0]:
            row["tones"] = {
                step: np.median(np.array([p["tones"][step] for p in pts],
                                         dtype=float), axis=0).tolist()
                for step in pts[0]["tones"]}
        if "codes" in pts[0]:
            row["codes"] = dict(pts[0]["codes"])
            row["codes_agree"] = all(p["codes"] == pts[0]["codes"]
                                     for p in pts)
        if "recal" in pts[0]:
            row["recal"] = pts[0]["recal"]
        if "holds" in pts[0]:
            row["holds"] = {k: all(p["holds"][k] for p in pts)
                            for k in pts[0]["holds"]}
            row["all_hold"] = all(row["holds"].values())
        rows.append(row)
    return rows


def _sigma(v: np.ndarray) -> float:
    """Sample standard deviation (n - 1), spelled out: the Android numpy
    allow-list holds names verified against 1.19.5 and ``std`` is not
    among them."""
    if v.size < 2:
        return 0.0
    return float(np.sqrt(np.sum((v - np.mean(v)) ** 2) / (v.size - 1)))


def _pearson(x: np.ndarray, y: np.ndarray) -> float:
    """Correlation coefficient, spelled out for the same reason."""
    dx, dy = x - np.mean(x), y - np.mean(y)
    return float(np.sum(dx * dy) / np.sqrt(np.sum(dx ** 2) * np.sum(dy ** 2)))


def _mask_in(t: np.ndarray, temps: tuple) -> np.ndarray:
    """Which entries of ``t`` are one of ``temps`` (``isin``, spelled out)."""
    wanted = {float(x) for x in temps}
    return np.array([float(x) in wanted for x in t], dtype=bool)


def _series(rows: list[dict], key: str) -> tuple[np.ndarray, np.ndarray]:
    order = sorted(rows, key=lambda r: r["temp_c"])
    t = np.array([r["temp_c"] for r in order], dtype=float)
    v = np.array([r["residuals"][key] for r in order], dtype=float)
    return t, v


def _tone_series(rows: list[dict], key: str) -> np.ndarray:
    """(n_temps, n_tones) per-tone IRR for an ``irr_min_db`` key, in the
    same temperature order as ``_series``."""
    step = key.split(".")[0]
    order = sorted(rows, key=lambda r: r["temp_c"])
    return np.array([r["tones"][step] for r in order], dtype=float)


# ------------------------------------------------------------ models
def _fit(t_fit: np.ndarray, v_fit: np.ndarray, model: str) -> dict:
    """``temprule.fit`` — one implementation shared with the replay."""
    return _rule_fit(model, t_fit, v_fit)


def _predict(t: np.ndarray, coeffs: dict, model: str) -> np.ndarray:
    return _rule_predict(model, coeffs, t)


def _error(pred: np.ndarray, meas: np.ndarray, key: str) -> np.ndarray:
    """Prediction error in the key's criterion unit."""
    unit = CRITERIA[key][1]
    if unit == "%":
        return 100.0 * (pred - meas) / meas
    return pred - meas


def fit_and_predict(rows: list[dict], key: str,
                    fit_temps: tuple = FIT_TEMPS) -> dict:
    """Fit ``key``'s model on ``fit_temps`` and predict every other
    temperature in ``rows``; the validation set is the complement, never
    the training points.

    Returns the coefficients, the per-point predictions and errors, the
    maximum absolute error, the criterion it is judged against and the
    verdict.
    """
    if key not in CRITERIA:
        raise KeyError(f"no criterion for {key}")
    t, v = _series(rows, key)
    fit_mask = _mask_in(t, fit_temps)
    if fit_mask.sum() != len(fit_temps):
        raise ValueError(f"fit temperatures {fit_temps} not all in the rows")
    if (~fit_mask).sum() == 0:
        raise ValueError("nothing left to validate on")
    model = MODELS.get(key, "linear")
    extra = {}
    if model == "null_irr_tones":
        # like for like: the per-tone curves are read on the longer
        # capture (temp_study.IRR_TONE_CAPTURE), so the quantity the
        # prediction is scored against is the minimum of THOSE tones,
        # not the shipped scalar read on the step's shorter capture —
        # the two instruments differ by their floors (0.4-1.3 dB
        # measured), and the deliverable this model argues for is the
        # per-tone array itself
        tones = _tone_series(rows, key)
        fit_on, v = tones, tones.min(axis=1)
        coeffs = _fit(t[fit_mask], fit_on[fit_mask], model)
        per_tone = np.stack([_predict(t[~fit_mask], c, "null_irr")
                             for c in coeffs["tones"]], axis=1)
        tone_err = per_tone - tones[~fit_mask]
        extra = {"max_abs_tone_error": float(np.max(np.abs(tone_err))),
                 "scored_against": "min over the per-tone array"}
    else:
        fit_on = v
        coeffs = _fit(t[fit_mask], fit_on[fit_mask], model)
    pred = _predict(t[~fit_mask], coeffs, model)
    err = _error(pred, v[~fit_mask], key)
    width, unit, why = CRITERIA[key]
    points = [{"temp_c": float(tt), "measured": float(mm),
               "predicted": float(pp), "error": float(ee)}
              for tt, mm, pp, ee in zip(t[~fit_mask], v[~fit_mask], pred, err)]
    worst = max(points, key=lambda q: abs(q["error"]))
    return {"key": key, "model": model, "fit_temps": [float(x) for x in fit_temps],
            "coeffs": coeffs, "points": points,
            "max_abs_error": float(abs(worst["error"])),
            "worst_temp_c": worst["temp_c"],
            "criterion": width, "unit": unit, "criterion_reason": why,
            "passes": bool(abs(worst["error"]) <= width), **extra}


# ------------------------------------------------------------ sawtooth
def sawtooth_stats(rows: list[dict], key: str) -> dict:
    """Post-recalibration residual of a quantised key against temperature:
    its largest magnitude (in LSBs too), its correlation with T, and how
    many times it changes sign along the temperature axis.

    A trim that re-centres at every temperature leaves a remainder that
    wanders inside +-1/2 LSB and flips sign where the code steps; a
    residual that grows with T instead says the code pitch itself has a
    temperature coefficient.  A series that never changes at all has no
    correlation to report (``constant``), which in this model means the
    key has no temperature path.
    """
    if key not in QUANTIZED_RESIDUAL:
        raise KeyError(f"{key} is not a quantised key")
    order = sorted(rows, key=lambda r: r["temp_c"])
    t = np.array([r["temp_c"] for r in order], dtype=float)
    reads = [QUANTIZED_RESIDUAL[key](r) for r in order]
    v = np.array([x[0] for x in reads], dtype=float)
    # the pitch is read per row: the corner's LSB depends on the landed
    # code, and the code steps along the sweep
    lsb = np.array([x[1] for x in reads], dtype=float)
    unit = reads[0][2]
    constant = bool(np.allclose(v, v[0]))
    if constant:
        r = 0.0
    else:
        r = _pearson(t, v)
    nz = v[v != 0.0]
    flips = int(np.sum(nz[1:] * nz[:-1] < 0)) if nz.size > 1 else 0
    in_lsb = np.abs(v) / lsb
    return {"key": key, "temps_c": t.tolist(), "values": v.tolist(),
            "unit": unit, "lsb": lsb.tolist(),
            "max_abs": float(np.max(np.abs(v))),
            "max_abs_lsb": float(np.max(in_lsb)),
            "within_half_lsb": bool(np.max(in_lsb) <= 0.5),
            "corr_with_temp": r, "constant": constant,
            "sign_flips": flips}


# ------------------------------------------------------------ sensitivity
def sensitivity(rows: list[dict], key: str, coeff_error: float = 0.3,
                fit_temps: tuple = FIT_TEMPS,
                at_c: float = SENSITIVITY_TEMP_C) -> dict:
    """How much a wrong temperature coefficient costs at ``at_c``.

    The drift term of the fitted model (``b`` of the linear model, the
    complex drift rate ``b`` of the null model) is scaled by
    ``1 +- coeff_error`` — a hardware tempco off its nominal by that
    much — and the prediction error at ``at_c`` is re-read.  Returns the
    nominal and perturbed errors, the growth, and whether the worst case
    stays inside twice the key's criterion (the plan's threshold for
    shipping a coefficient without an uncertainty field).
    """
    t, v = _series(rows, key)
    if at_c not in t:
        raise ValueError(f"{at_c} degC is not one of the measured points")
    if at_c in fit_temps:
        raise ValueError("the sensitivity point must not be a fit point")
    model = MODELS.get(key, "linear")
    fit_mask = _mask_in(t, fit_temps)
    if model == "null_irr_tones":
        tones = _tone_series(rows, key)
        fit_on, v = tones, tones.min(axis=1)     # same scoring as fit_and_predict
    else:
        fit_on = v
    coeffs = _fit(t[fit_mask], fit_on[fit_mask], model)
    meas = v[t == at_c][0]
    width = CRITERIA[key][0]

    def err_with(scale: float) -> float:
        c = scale_drift(model, coeffs, scale)
        return float(_error(_predict(np.array([at_c]), c, model),
                            np.array([meas]), key)[0])

    nominal = err_with(1.0)
    plus = err_with(1.0 + coeff_error)
    minus = err_with(1.0 - coeff_error)
    worst = max(abs(nominal), abs(plus), abs(minus))
    return {"key": key, "model": model, "at_c": float(at_c),
            "coeff_error": coeff_error,
            "error_nominal": nominal, "error_plus": plus,
            "error_minus": minus, "worst_abs_error": worst,
            "growth": float(worst - abs(nominal)),
            "unit": CRITERIA[key][1], "criterion": width,
            "within_2x_criterion": bool(worst <= 2.0 * width)}


# ------------------------------------------------------------ recal vs floor
def recal_departure(rows_recal: list[dict], ref_row: dict, key: str,
                    floor: float | None = None) -> dict:
    """A continuous key after recalibration at each temperature against
    its delivered 25 degC value, in units of the measurement noise.

    The noise is the across-seed sigma pooled over every temperature of
    the recalibrated sweep (more degrees of freedom than any single
    point's three seeds), and the departure is judged against three of
    them.  A residual that re-estimates to its floor sits inside that
    band; one that does not has a temperature path the recalibration
    does not remove.

    ``floor`` is the least width the band can have.  The transmit-side
    reads are noise-free in this model, so their sigma is exactly zero
    and a literal "within noise" would fail on any change at all —
    including the 0.1 dB a re-estimated null legitimately moves by.  The
    default floor is the key's E1 criterion: the width a consumer
    resolves the number at.  The raw sigma travels in the result so the
    reader can see which bound was in force.
    """
    t, v = _series(rows_recal, key)
    ref = float(ref_row["residuals"][key])
    # a single-seed sweep carries no sigma: then the floor is the band
    sig = np.array([(r.get("residual_sigma") or {}).get(key, 0.0)
                    for r in rows_recal], dtype=float)
    pooled = float(np.sqrt(np.mean(sig ** 2)))
    if floor is None:
        floor = CRITERIA[key][0]
    band = max(3.0 * pooled, float(floor))
    dep = v - ref
    worst_i = int(np.argmax(np.abs(dep)))
    return {"key": key, "reference_25c": ref, "temps_c": t.tolist(),
            "departure": dep.tolist(), "pooled_sigma": pooled,
            "max_abs_departure": float(abs(dep[worst_i])),
            "worst_temp_c": float(t[worst_i]),
            "band": band, "band_is_floor": bool(band > 3.0 * pooled),
            "unit": CRITERIA[key][1],
            "within_noise": bool(abs(dep[worst_i]) <= band)}


# ------------------------------------------------------------ after_recal
def after_recal_bound(rows_recal: list[dict], rows_frozen: list[dict],
                      ref_row: dict, key: str) -> dict:
    """What a recalibration guarantees for ``key`` — a bound, not the
    25 degC number — judged against what the steps actually do.

    Phase 1 measured that "recalibrated continuous residuals return to
    their floor" is false for two keys for reasons that are properties
    of the steps, not of temperature, and the deliverable's
    ``after_recal`` has to say what the step guarantees instead:

    * the loopback leak step refines only a leak above ``LEAK_SKIP_DBC``;
      a frozen leak already below it is left where it is.  So after a
      recalibration the leak is **at or below the skip threshold** at
      every temperature, and at the temperatures where the step did
      refine it is back within the 25 degC band;
    * the IQ steps re-estimate to a floor that depends on the profile
      (one iteration on power-on moves +-3 dB, two on factory +-1 dB),
      and what they guarantee is their own verdict: the recalibrated
      part **meets the step's spec** (``irr_min_db >= limit``), read
      both from the step's ``passed`` and from the independent re-read.

    Every other continuous key keeps the floor reading of
    ``recal_departure``.
    """
    step = key.split(".")[0]
    t, v = _series(rows_recal, key)
    out = {"key": key, "temps_c": t.tolist(), "values": v.tolist()}
    if step in ("tx_lo_leak_loopback", "tx_lo_leak_envdet"):
        # matched by temperature, not by position: the frozen sweep may
        # cover more temperatures than the recalibrated one
        frozen_at = {float(r["temp_c"]): float(r["residuals"][key])
                     for r in rows_frozen}
        missing = [float(x) for x in t if float(x) not in frozen_at]
        if missing:
            raise ValueError(f"no frozen reading at {missing} degC to decide "
                             "whether the leak step refined there")
        frozen = np.array([frozen_at[float(x)] for x in t])
        refined = frozen > LEAK_SKIP_DBC
        dep = recal_departure(rows_recal, ref_row, key)
        dep_refined = np.abs(np.array(dep["departure"]))[refined]
        worst_refined = float(dep_refined.max()) if dep_refined.size else 0.0
        out.update({"kind": "bound", "bound_dbc": LEAK_SKIP_DBC,
                    "all_within_bound": bool(np.all(v <= LEAK_SKIP_DBC)),
                    "worst_dbc": float(v.max()),
                    "refined_temps_c": t[refined].tolist(),
                    "skipped_temps_c": t[~refined].tolist(),
                    "refined_max_departure": worst_refined,
                    "band": dep["band"],
                    "refined_within_band": bool(worst_refined <= dep["band"]),
                    "passes": bool(np.all(v <= LEAK_SKIP_DBC)
                                   and worst_refined <= dep["band"])})
        return out
    if step in ("tx_iq", "rx_iq"):
        order = sorted(rows_recal, key=lambda r: r["temp_c"])
        limits = {float(r["recal"]["spec"][step]["limit"]) for r in order}
        if len(limits) != 1:
            raise ValueError(f"{step}: spec limit changed across the sweep")
        limit = limits.pop()
        passed = [bool(r["recal"]["passed"][step]) for r in order]
        out.update({"kind": "bound", "bound_db": limit, "sense": "min",
                    "step_passed_everywhere": all(passed),
                    "reread_min_db": float(v.min()),
                    "reread_worst_temp_c": float(t[int(np.argmin(v))]),
                    "spread_db": float(v.max() - v.min()),
                    "passes": bool(all(passed) and np.all(v >= limit))})
        return out
    raise KeyError(f"{key} has no after_recal bound rule; use recal_departure")


# ------------------------------------------------------------ the file block
def _targets(rows: list[dict]) -> list[dict]:
    keys = ("tx_evm_db", "tx_evm_modem_db", "rx_evm_db", "rx_evm_modem_db")
    return [{"t_c": float(r["temp_c"]),
             **{k: float(r[k]) for k in keys if k in r}}
            for r in sorted(rows, key=lambda r: r["temp_c"])]


def temperature_block(rows_frozen: list[dict], rows_recal: list[dict] | None,
                      fit_temps: tuple = FIT_TEMPS,
                      recal_profile: str = "poweron",
                      calibrated_at_c: float = 25.0,
                      dpd_tracking: bool = False,
                      tempcos: dict | None = None,
                      tempco_source: str | None = None) -> dict:
    """The schema-1.2 ``residuals.temperature`` record from the two sweeps.

    ``rows_frozen`` is a ``temperature_hold_study(residual_keys=True)``
    sweep (pooled or single seed) and ``rows_recal`` the same with
    ``recalibrate=True``; the points shipped per key are the rows at
    ``fit_temps`` and nothing else — the other temperatures become
    closure ``targets`` for the replay, so a consumer's check never
    scores on the points the rule was fitted from.

    Per key: ``class`` and ``interp`` from the tables above; ``points``
    (``tones`` too for the per-tone rule); ``sensitivity`` — the
    prediction error at ``SENSITIVITY_TEMP_C`` when the drift term is
    off by +-30 %, which is the uncertainty a consumer should carry
    (E3: the keys with a real temperature path exceed twice their
    criterion, so the file says so instead of shipping a bare slope);
    and ``after_recal`` — always a bound: the loopback leak step's skip
    threshold, the IQ steps' spec, half an LSB at the landed code for a
    trim, and for every other key the worst value a recalibration left
    anywhere in the sweep.

    ``dpd_tracking``: the frozen sweep was taken with the DPD tracking
    loop running (``temperature_hold_study(dpd_tracking=True)``), so the
    DPD key's rule is the tracker's, class ``tracked``, and the targets
    are the tracked part's.  Refused when the rows say otherwise.
    ``tempcos`` / ``tempco_source`` record what the rules were computed
    from (``part_tempcos``; "placeholder" for ``PLACEHOLDER_TEMPCOS``).
    """
    classes = classify_residuals()
    order = sorted(rows_frozen, key=lambda r: r["temp_c"])
    tracked_rows = [("dpd_tracking" in r) for r in order]
    if dpd_tracking and not all(tracked_rows):
        raise ValueError("dpd_tracking=True but the frozen sweep was not "
                         "taken with the tracking loop running")
    if not dpd_tracking and any(tracked_rows):
        raise ValueError("the frozen sweep ran the DPD tracking loop; pass "
                         "dpd_tracking=True so the file says so")
    temps = [float(r["temp_c"]) for r in order]
    for ft in fit_temps:
        if float(ft) not in temps:
            raise ValueError(f"fit temperature {ft} not in the frozen sweep")
    if calibrated_at_c not in temps:
        raise ValueError("the frozen sweep must include the calibration "
                         "temperature")
    ref = next(r for r in order if r["temp_c"] == calibrated_at_c)
    fit_rows = [r for r in order if float(r["temp_c"]) in
                {float(x) for x in fit_temps}]
    keys: dict[str, dict] = {}
    for key, cls in classes.items():
        if key not in ref["residuals"]:
            continue
        step = key.split(".")[0]
        kind = MODELS.get(key, "linear")
        points = []
        for r in fit_rows:
            pt = {"t_c": float(r["temp_c"]), "value": float(r["residuals"][key])}
            if kind == "null_irr_tones":
                pt["tones"] = [float(v) for v in r["tones"][step]]
            points.append(pt)
        if dpd_tracking and RESIDUAL_SPEC[key].get("tracking"):
            cls = "tracked"
        entry = {"class": cls, "interp": kind, "points": points}
        if len(order) > len(fit_rows):
            try:
                sens = sensitivity(order, key, fit_temps=fit_temps)
                entry["sensitivity"] = {
                    k: sens[k] for k in ("at_c", "coeff_error", "error_nominal",
                                         "worst_abs_error", "unit",
                                         "within_2x_criterion")}
            except ValueError:
                pass            # the sensitivity point is not in this sweep
        if rows_recal is not None:
            entry["after_recal"] = _after_recal_entry(
                rows_recal, order, ref, key, cls, recal_profile)
        keys[key] = entry
    out = {
        "calibrated_at_c": float(calibrated_at_c),
        "basis": "model-tempco",
        "fit_temps_c": [float(x) for x in fit_temps],
        "recal_profile": recal_profile,
        "dpd_tracking": bool(dpd_tracking),
        "keys": keys,
        "targets": _targets(order),
    }
    if tempcos is not None:
        out["tempcos"] = tempcos
        out["tempco_source"] = tempco_source or "part"
    if rows_recal is not None:
        out["targets_recalibrated"] = _targets(rows_recal)
    return out


def _covers(entry: dict) -> dict:
    """A bound must cover the sweep it was measured on.  A step-defined
    bound (skip threshold, spec, half an LSB) that the recalibrated
    sweep itself exceeded is widened to the measured worst and says so:
    the file may be conservative, never contradicted by its own data."""
    v, w, sense = entry["value"], entry["measured_worst"], entry["sense"]
    exceeded = ((sense == "max" and w > v) or (sense == "min" and w < v)
                or (sense == "abs_max" and abs(w) > v))
    if exceeded:
        entry["stated"] = v
        entry["value"] = abs(w) if sense == "abs_max" else w
        entry["reason"] += (f"; the recalibrated sweep itself reached "
                            f"{w:.4g}, beyond the stated {v:.4g}, so the "
                            "bound is the measured worst")
    return entry


def _after_recal_entry(rows_recal, rows_frozen, ref, key, cls, profile) -> dict:
    return _covers(_after_recal_raw(rows_recal, rows_frozen, ref, key, cls,
                                    profile))


def _after_recal_raw(rows_recal, rows_frozen, ref, key, cls, profile) -> dict:
    step = key.split(".")[0]
    unit = RESIDUAL_SPEC[key]["unit"]
    if step in ("tx_lo_leak_loopback", "tx_lo_leak_envdet", "tx_iq", "rx_iq"):
        b = after_recal_bound(rows_recal, rows_frozen, ref, key)
        if "bound_dbc" in b:
            return {"kind": "bound", "sense": "max", "value": b["bound_dbc"],
                    "unit": unit, "profile": profile,
                    "reason": "the loopback leak step refines only a leak "
                              "above its skip threshold; below it the "
                              "frozen value is left where it is",
                    "measured_worst": b["worst_dbc"]}
        return {"kind": "bound", "sense": "min", "value": b["bound_db"],
                "unit": unit, "profile": profile,
                "reason": "the IQ step re-estimates to a profile-dependent "
                          "floor; what it guarantees is its own spec",
                "measured_worst": b["reread_min_db"]}
    if cls == "quantized" and key in QUANTIZED_RESIDUAL:
        s = sawtooth_stats(rows_recal, key)
        if s["unit"] == "%":
            nominal = float(ref["residuals"][key]) / (
                1.0 + float(QUANTIZED_RESIDUAL[key](ref)[0]) / 100.0)
            half = 0.5 * float(max(s["lsb"]))
            return {"kind": "bound", "sense": "abs_max", "value": half,
                    "unit": "% of nominal", "nominal_hz": nominal,
                    "profile": profile,
                    "reason": "half an RC code at the landed code's pitch "
                              "(the pitch is rc_step only at mid-code)",
                    "measured_worst": s["max_abs"]}
        # the IM2 trim: no temperature path, the code stays put
        return {"kind": "bound", "sense": "min",
                "value": float(min(r["residuals"][key] for r in rows_recal)),
                "unit": unit, "profile": profile,
                "reason": "no temperature path in the model; the code "
                          "stays where the calibration left it",
                "measured_worst": float(min(r["residuals"][key]
                                            for r in rows_recal))}
    # every other continuous key: the worst value a recalibration left
    better = RESIDUAL_SPEC[key]["better"]
    vals = [float(r["residuals"][key]) for r in rows_recal]
    if better.startswith("larger"):
        sense, worst = "min", min(vals)
    elif better.startswith("smaller magnitude"):
        sense, worst = "abs_max", max(abs(v) for v in vals)
    else:
        sense, worst = "max", max(vals)
    return {"kind": "bound", "sense": sense, "value": worst, "unit": unit,
            "profile": profile,
            "reason": "the worst value a recalibration left anywhere in the "
                      "sweep (the key re-estimates to its floor)",
            "measured_worst": worst}


# ------------------------------------------------------------ the part
def reference_pair(seed: int = 11):
    """The study's part: the configuration of
    ``tests/test_temperature.py::calibrated_pair`` — 80 MHz / 256-QAM /
    4 symbols / 2x oversampling, tempcos 2e-4 (RC), 0.004 deg/degC (IQ
    phase), 0.02 dB/degC (LO leak) — so the study and the existing hold
    tests read the same die.  Returns ``(tx, rx, path, cfg)`` before
    calibration.
    """
    from ..chain import LoopbackPath, RxChain, RxParams, TxChain, TxParams
    from ..waveform import OFDMConfig
    bw = 80e6
    cfg = OFDMConfig(bandwidth_hz=bw, qam_order=256, n_symbols=4,
                     oversampling=2)
    rng = np.random.default_rng(seed)
    txp = TxParams(bandwidth_hz=bw).randomize(rng)
    rxp = RxParams(bandwidth_hz=bw).randomize(rng)
    txp.lpf.fc_nominal_hz = bw / 2 * 1.12
    rxp.lpf.fc_nominal_hz = bw / 2 * 1.12
    # tempcos sized so a 25 degC cal holds the industrial range against
    # the -40 dBc / 50 dB / 2 % specs: the leak null is amplitude-matched
    # at 25 degC, so residual ~ leak * (10^(tempco*dT/20) - 1) — 20
    # mdB/degC over 30 degC leaves ~ -46 dBc on a -25 dBc injected leak;
    # the LPF corner cal may leave up to 1 LSB (2 %) residual, so its
    # drift budget over 35 degC is what's left of the 2 % spec (200
    # ppm/degC * 35 = 0.7 %).  The driver-gain tempco is left out: the
    # phase-1 study has no DPD, its numbers were recorded on this die
    # without it, and it would move only that study's EVM targets.
    apply_tempcos(txp, rxp, {k: v for k, v in PLACEHOLDER_TEMPCOS.items()
                             if k != "pa_gain_tempco_db_per_c"})
    tx, rx = TxChain(txp, cfg.sample_rate_hz), RxChain(rxp, cfg.sample_rate_hz)
    return tx, rx, LoopbackPath(atten_db=40.0, delay_ns=6.0), cfg


def run_sweeps(tx, rx, path, cfg, results, temps: tuple = TEMPS,
               seeds: tuple = (0, 1, 2), recalibrate: bool = False) -> list[dict]:
    """``temperature_hold_study`` with the residual surface, once per
    seed, pooled to medians.  Shared by the example and the tests."""
    from .temp_study import temperature_hold_study
    runs = [temperature_hold_study(tx, rx, path, cfg, results, temps=temps,
                                   seed=s, residual_keys=True,
                                   recalibrate=recalibrate)["rows"]
            for s in seeds]
    return median_rows(runs)


def delivery_temperature(tx, rx, path, cfg, results,
                         temps: tuple = DELIVERY_TEMPS,
                         dpd_tracking: bool = False,
                         tempcos: dict | None = PLACEHOLDER_TEMPCOS,
                         tempco_source: str = "placeholder",
                         recal_profile: str = "poweron",
                         drive_scale: float = 0.12,
                         seed: int = 0) -> dict:
    """Everything a delivered file needs to carry about temperature, from
    the calibrated chains: ``{"temperature", "expiry", "rows_frozen",
    "rows_recalibrated"}`` — the first two go straight into
    ``save_cal_state(temperature=, expiry=)``.

    The one entry point every writer uses (the full-calibration example,
    both workbench front ends through ``app/specs.py``), so a file from
    the GUI and a file from the script are built the same way.  Two
    sweeps over ``temps`` — corrections frozen (with the DPD tracking
    loop running when ``dpd_tracking``) and recalibrated at each point —
    then ``temperature_block``.  ``tempcos`` are applied to the part
    first (placeholders by default; ``None`` keeps whatever the part
    carries and records it as such); they leave every 25 degC number
    unchanged.  Single seed: this is a production artefact, not the
    three-seed study.  The chains come back at 25 degC with their
    delivered corrections.
    """
    from .temp_study import temperature_hold_study
    source = "part"
    if tempcos is not None:
        apply_tempcos(tx.params, rx.params, tempcos)
        source = tempco_source
    frozen = temperature_hold_study(tx, rx, path, cfg, results, temps=temps,
                                    drive_scale=drive_scale, seed=seed,
                                    residual_keys=True,
                                    dpd_tracking=dpd_tracking)
    recal = temperature_hold_study(tx, rx, path, cfg, results, temps=temps,
                                   drive_scale=drive_scale, seed=seed,
                                   residual_keys=True, recalibrate=True,
                                   recal_profile=recal_profile)
    block = temperature_block(frozen["rows"], recal["rows"],
                              recal_profile=recal_profile,
                              dpd_tracking=dpd_tracking,
                              tempcos=part_tempcos(tx, rx),
                              tempco_source=source)
    return {"temperature": block, "expiry": frozen["expiry"],
            "rows_frozen": frozen["rows"],
            "rows_recalibrated": recal["rows"]}
