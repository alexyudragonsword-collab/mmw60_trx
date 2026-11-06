# Vendored from wifi_trx_cal@cc06b9ac8dafb5cbb261a59280e81ae0cfbf787c: src/wifitrx/link/temp_study.py
# Adapted-copy policy: see src/mmw60/vendor/__init__.py
"""Temperature hold study: how far does a 25 degC calibration survive?

Calibration corrections are programmed once (factory or power-on) but the
die does not stay at the calibration temperature.  This study moves the
modeled die across temperature with the corrections FROZEN and re-measures
each calibrated spec, answering the production question the saturation
flag only hints at: which corrections hold over the range, which need a
recalibration trigger, and at what temperature the first spec breaks.

Verdicts are judged against the specs EMBEDDED in the CalResult list (the
spec each step was actually calibrated to), the same rule the handoff
inspector follows.  The derived hold range ships as ``expiry`` metadata in
the cal-state JSON so a consumer knows the corrections' validity window.

Observation honesty: lo_leak/IRR/EVM are *measured* through the modeled
observation paths; the LPF corner residual is read from model truth
(a real bench would re-run the tone-ratio measurement) — cheap and exact,
and this study is about drift, not estimator quality.
"""
from __future__ import annotations

import copy
from dataclasses import replace

import numpy as np

from ..cal.base import CalResult, _jsonable
from ..cal.deps import recal_steps
from ..cal.dpd_tracking import tracked_update, tracking_adapter
from ..cal.group_delay import estimate_gd_mismatch_ps
from ..cal.residuals import RESIDUAL_SPEC, extract_residuals
from ..cal.rx_figures import (measure_rx_im3_dbc, measure_rx_nf_db,
                              measure_rx_phase_err_dbc)
from ..cal.rx_iq import measure_rx_irr
from ..cal.sequence import (agc_for_loopback, run_cal_steps, rx_snapshot,
                            tx_snapshot)
from ..cal.tx_iq import measure_tx_irr, measure_tx_rho
from ..chain.loopback import LoopbackPath
from ..chain.rx import RxChain
from ..chain.tx import TxChain
from ..metrics import evm
from ..metrics.irr import dc_dbfs, lo_leak_dbc
from ..waveform.ofdm import OFDMConfig, demodulate_ofdm, generate_ofdm
from ..waveform.stimuli import scaled_probe, single_tone

CAL_TEMP_C = 25.0

#: Capture length for the PER-TONE image curves (``row["tones"]``).  The
#: steps read their ``irr_min_db`` on 2^14 samples and that reading is
#: kept verbatim as the shipped key; but a 2^14 capture leaves each
#: tone's image bin quantisation-limited (per-tone residual from a
#: smooth null of 0.4-2.6 dB on the RX side, 0.25-0.95 dB at 2^16), and
#: a per-tone temperature rule needs the smoother instrument.
IRR_TONE_CAPTURE: int = 1 << 16


def _limit(results: list[CalResult], name: str, default: float) -> float:
    for r in results:
        if r.name == name and r.spec:
            return float(r.spec["limit"])
    return default


def _fc_err_pct(lpf) -> float:
    return 100.0 * (lpf.fc_actual_hz / lpf.fc_nominal_hz - 1.0)


def _result(results: list[CalResult], name: str) -> CalResult | None:
    for r in results:
        if r.name == name:
            return r
    return None


def _rx_dc_worst_dbfs(rx: RxChain, n: int, rng: np.random.Generator) -> float:
    """The ``rx_dc_offset`` step's after-metric, read back without
    re-trimming: zero input at every LNA state under the step's own
    measurement condition (VGA at 20 dB)."""
    saved_idx, saved_vga = rx.lna_idx, rx.vga_db
    rx.vga_db = 20.0
    worst = -np.inf
    for idx in range(len(rx.params.lna_states)):
        rx.lna_idx = idx
        worst = max(worst, dc_dbfs(rx(np.zeros(n, dtype=complex), rng=rng)))
    rx.lna_idx, rx.vga_db = saved_idx, saved_vga
    return float(worst)


def _dpd_evm_db(tx: TxChain, cfg: OFDMConfig, drive_scale: float) -> float:
    """The ``dpd`` step's after-metric: PA-output per-tone-equalised EVM
    of the training waveform at the training drive."""
    wf = generate_ofdm(cfg)
    x = wf.x * drive_scale
    y = tx(x)
    g = np.vdot(x, y) / np.vdot(x, x)
    return float(evm(demodulate_ofdm(y / g, wf), wf.tx_symbols,
                     equalize="per_tone").db)


def measure_residual_surface(tx: TxChain, rx: RxChain, path: LoopbackPath,
                             cfg: OFDMConfig, results: list[CalResult],
                             n_iq: int = 1 << 14, seed: int = 0
                             ) -> list[CalResult]:
    """Re-read every ``role="impairment"`` residual key at the chains'
    *current* state — temperature and corrections as they are now —
    without touching any correction.

    Returns a ``CalResult`` per step present in ``results`` whose
    ``metrics_after`` carries that step's specced keys, so
    ``extract_residuals`` yields the same key set the delivered file
    ships, measured again.  ``seed`` moves only the reads that pass
    through a noise source (the receive-side figures, the DC and
    group-delay captures); the transmit-side probes are noise-free in
    the model and read the same every time.  Each key is read the way its own step reads
    its after-metric (the PA-output IRR comb, the loopback probe tone,
    the receive figures at the delivered input level); the LPF corners
    and IIP2 are model truth, exactly as their steps report them.  The
    one correction touched is the TX w2 FIR, lifted for a single
    capture so the group-delay key keeps the file's definition (see
    the comment there) and restored immediately.
    """
    present = {r.name for r in results}
    bw = tx.params.bandwidth_hz
    rng = np.random.default_rng(1000 + seed)
    out: list[CalResult] = []

    def emit(name: str, metrics: dict) -> None:
        if name in present:
            out.append(CalResult(name=name, metrics_after=metrics))

    emit("tx_lpf_corner", {"fc_hz": float(tx.params.lpf.fc_actual_hz),
                           "fc_err_pct": _fc_err_pct(tx.params.lpf)})
    emit("rx_lpf_corner", {"fc_hz": float(rx.params.lpf.fc_actual_hz),
                           "fc_err_pct": _fc_err_pct(rx.params.lpf)})
    if "rx_dc_offset" in present:
        emit("rx_dc_offset",
             {"worst_dc_dbfs": _rx_dc_worst_dbfs(rx, 1 << 13, rng)})
    if present & {"tx_lo_leak_envdet", "tx_lo_leak_loopback"}:
        x = single_tone(scaled_probe(23e6, bw), tx.fs, 1 << 13, amp=0.25)
        leak = float(lo_leak_dbc(tx(x), tx.fs))
        emit("tx_lo_leak_envdet", {"lo_leak_dbc": leak})
        emit("tx_lo_leak_loopback", {"lo_leak_dbc": leak})
    if "rx_iip2" in present:
        emit("rx_iip2", {"iip2_dbm": float(
            rx.params.im2.iip2_eff_dbm(rx.im2_trim_code))})
    if "tx_iq" in present:
        # the step's own comb (its default seed): the key is the worst
        # tone of THAT comb, and a different comb puts the PA's comb IM3
        # products on different image bins — comb choice, not noise
        _, irr = measure_tx_irr(tx)
        # the per-tone curve travels too: the shipped key is its minimum,
        # and a minimum over tones is not a quantity a null model can
        # follow in temperature, whereas each tone is — read on the
        # longer capture (see IRR_TONE_CAPTURE), the scalar as the step
        # reads it
        _, tones = measure_tx_irr(tx, n=IRR_TONE_CAPTURE)
        emit("tx_iq", {"irr_min_db": float(np.min(irr)),
                       "irr_db": np.asarray(tones, dtype=float)})
    if "group_delay" in present:
        # The file's number is the estimator's error on the RAW rho(f)
        # (measured before the w2 correction existed), not what the
        # correction leaves behind — so re-reading it means lifting w2
        # for one capture and putting it back.  With w2 in place the
        # residual rho is nearly zero and the "error" would read as
        # minus the injected mismatch at every temperature.
        wf = generate_ofdm(cfg)
        agc_for_loopback(tx, rx, path, wf.x * 0.25)
        w2 = tx.w2
        tx.w2 = None
        try:
            f_raw, rho_raw = measure_tx_rho(tx, rx, LoopbackPath(
                atten_db=path.atten_db, delay_ns=path.delay_ns,
                rx_lo_offset_hz=5.1e6), n=n_iq, n_tones=8, seed=3 + seed)
        finally:
            tx.w2 = w2
        inj = tx.params.iq.gd_mismatch_ps if tx.params.iq.enabled else 0.0
        est = estimate_gd_mismatch_ps(f_raw, rho_raw)
        emit("group_delay", {"error_ps": float(est - inj)})
    if "rx_iq" in present:
        _, irr = measure_rx_irr(rx)          # same reason as tx_iq
        _, tones = measure_rx_irr(rx, n=IRR_TONE_CAPTURE)
        emit("rx_iq", {"irr_min_db": float(np.min(irr)),
                       "irr_db": np.asarray(tones, dtype=float)})
    if "dpd" in present:
        r = _result(results, "dpd")
        emit("dpd", {"evm_db": _dpd_evm_db(
            tx, cfg, float(r.estimated.get("drive_scale", 0.12)))})
    final = _result(results, "final_loopback_evm")
    if final is not None and "rx_input_dbm" in final.metrics_after:
        # last: these set the AGC for the delivered input level
        p_in = float(final.metrics_after["rx_input_dbm"])
        nf = measure_rx_nf_db(rx, cfg, p_in, seed=seed)
        emit("final_loopback_evm", {
            "rx_nf_db": nf,
            "rx_phase_err_dbc": measure_rx_phase_err_dbc(rx, cfg, p_in, nf,
                                                         seed=seed),
            "rx_im3_dbc": measure_rx_im3_dbc(rx, cfg, p_in, seed=seed)})
    return out


def impairment_residuals(measured: list[CalResult]) -> dict[str, float]:
    """``extract_residuals`` narrowed to the injectable keys: the ones a
    temperature rule could ever attach to (totals, figures and
    conditions are never re-injected, so they get no temperature axis)."""
    res = extract_residuals(measured)
    return {k: float(v) for k, v in res["values"].items()
            if RESIDUAL_SPEC[k]["role"] == "impairment"}


def _rc_lsb_pct(lpf) -> float:
    """What one code step moves the corner by, in percent, AT the landed
    code.  The nominal ``rc_step`` is the pitch at mid-code only: the
    corner goes as 1 / (1 + rc_step (code - mid)), so a part tuned seven
    codes below mid sees 2.33 % per LSB, not 2 %.  A half-LSB bound has
    to use the pitch the part actually has."""
    mid = 1 << (lpf.rc_code_bits - 1)
    return 100.0 * lpf.rc_step / (1.0 + lpf.rc_step * (lpf.rc_code - mid))


def _codes(tx: TxChain, rx: RxChain) -> dict:
    """The quantised trim codes and their step sizes, so an analysis can
    express a post-recalibration residual in LSBs without reaching back
    into the model."""
    return {
        "tx_rc_code": int(tx.params.lpf.rc_code),
        "rx_rc_code": int(rx.params.lpf.rc_code),
        "rc_lsb_pct": _rc_lsb_pct(tx.params.lpf),
        "rx_rc_lsb_pct": _rc_lsb_pct(rx.params.lpf),
        "rc_lsb_nominal_pct": 100.0 * float(tx.params.lpf.rc_step),
        "im2_trim_code": int(rx.im2_trim_code),
        "im2_trim_best": int(rx.params.im2.trim_best),
        "im2_trim_bits": int(rx.params.im2.trim_bits),
    }


def _correction_summary(r: CalResult) -> dict:
    """A step's programmed corrections with FIR taps reduced to a count
    and an energy, so the row stays small enough to store per temperature."""
    out = {}
    for k, v in (r.corrections or {}).items():
        arr = np.asarray(v) if not isinstance(v, dict) else None
        if arr is not None and arr.ndim >= 1 and arr.size > 4:
            out[k] = {"n": int(arr.size),
                      "energy": float(np.sum(np.abs(arr) ** 2))}
        else:
            out[k] = _jsonable(v)
    return out


def temperature_hold_study(tx: TxChain, rx: RxChain, path: LoopbackPath,
                           cfg: OFDMConfig, results: list[CalResult],
                           temps: tuple = (-40.0, -10.0, 25.0, 55.0, 85.0),
                           drive_scale: float = 0.12,
                           n_iq: int = 1 << 14, seed: int = 0,
                           residual_keys: bool = False,
                           recalibrate: bool = False,
                           recal_profile: str = "poweron",
                           dpd_tracking: bool = False,
                           tracking_updates: int = 3) -> dict:
    """Re-measure calibrated specs across ``temps`` with corrections frozen.

    Returns {"rows": [...], "expiry": {...}}; expiry carries the contiguous
    hold range around the calibration temperature for the cal-state JSON.

    ``residual_keys``: additionally re-read every ``role="impairment"``
    residual key at each temperature (``measure_residual_surface``) into
    ``row["residuals"]``, with the trim codes in ``row["codes"]`` — the
    full residual surface the delivered file ships, as a function of
    temperature rather than at 25 degC only.

    ``recalibrate``: at each temperature, after moving the die, first
    run the ``deps.recal_steps`` subset of the original sequence through
    ``sequence.run_cal_steps`` (the same step implementations as the
    delivered run, under ``recal_profile``), then measure.  Each
    temperature starts from the delivered 25 degC correction state, so
    the points are independent — a part that jumps straight to T and
    recalibrates there.  ``row["recal"]`` records the steps, their
    programmed corrections (``rc_code`` included) and after-metrics.
    The chains' corrections are restored on exit, like the temperature.

    ``dpd_tracking``: the part runs the RLS DPD tracking loop instead of
    holding the one-shot ILA coefficients.  A tracker is converged on the
    chain at the calibration temperature (``cal.dpd_tracking.
    tracking_adapter``); at every point a copy of it follows the chain
    for ``tracking_updates`` blocks and is programmed before anything is
    measured, the other corrections staying frozen — so the DPD residual
    and the EVM targets of the row are the tracking loop's, which is a
    different rule from the frozen ILA's and the file has to say which
    it carries.  The tracker re-converges at every temperature but from
    its own floor, and holds the output power (so it drives the PA harder
    as the PA gain drops); which rule reads better is a property of the
    part.  Measured with -0.02 dB/degC of driver-gain drift: on a 40 MHz
    part it reads -40.6 / -40.9 dB at -40 / 85 degC against the frozen
    ILA's -40.0 / -40.5, from a floor 0.5 dB above the ILA's; on the
    tutorial's 80 MHz part it reads worse at both ends, its floor 1.4 dB
    above.
    Needs a DPD in ``results``; refused with ``recalibrate``, which
    retrains the DPD anyway.

    All default off; without them the study is the 0.6-era hold study
    unchanged.
    """
    executed_names = {r.name for r in results}
    if dpd_tracking and "dpd" not in executed_names:
        raise ValueError("dpd_tracking needs a DPD in the calibration results")
    if dpd_tracking and recalibrate:
        raise ValueError("dpd_tracking applies to the frozen sweep: a "
                         "recalibration retrains the DPD at each point")
    lim_leak = _limit(results, "tx_lo_leak_loopback", -40.0)
    lim_irr = _limit(results, "tx_iq", 50.0)
    lim_fc_tx = _limit(results, "tx_lpf_corner", 2.0)
    lim_fc_rx = _limit(results, "rx_lpf_corner", 2.0)
    lim_txevm = None
    for r in results:
        if r.name == "final_loopback_evm" and r.spec:
            lim_txevm = float(r.spec["limit"])

    t_tx0, t_rx0 = tx.temperature_c, rx.temperature_c
    executed = [r.name for r in results]
    plan = recal_steps(executed) if recalibrate else []
    tx_state, rx_state = tx.correction_state(), rx.correction_state()
    dpd0 = tx.dpd
    agc0 = (rx.lna_idx, rx.vga_db)
    r_pwr = _result(results, "tx_power")
    target_pout = (None if r_pwr is None
                   else r_pwr.estimated.get("target_dbm"))
    try:
        tx.set_temperature(CAL_TEMP_C)
        rx.set_temperature(CAL_TEMP_C)
        ref_txevm = tx_snapshot(tx, cfg, drive_scale=drive_scale)["evm_modem_db"]
        # no embedded EVM spec (e.g. no-DPD flow): hold = within 2 dB of
        # the calibrated-temperature value
        evm_lim = lim_txevm if lim_txevm is not None else ref_txevm + 2.0

        tracker = x_track = track_path = None
        if dpd_tracking:
            # the observation coupler the DPD step itself uses (>= 40 dB:
            # the receiver's own IM3 must not be learned into the inverse)
            track_path = replace(path, atten_db=max(path.atten_db, 40.0))
            x_track = generate_ofdm(cfg).x * drive_scale
            tracker = tracking_adapter(tx, rx, x_track, track_path)

        rows = []
        for t in temps:
            tx.set_temperature(t)
            rx.set_temperature(t)
            recal = None
            tracked = None
            if tracker is not None:
                # each point from the converged 25 degC tracker, so the
                # points stay independent like the recalibrated ones
                adpd = copy.deepcopy(tracker)
                info = tracked_update(adpd, tx, rx, x_track, track_path,
                                      updates=tracking_updates)
                tracked = {"updates": int(tracking_updates),
                           "resid_db": float(info.get("resid_db", np.nan))}
            if recalibrate:
                tx.load_correction_state(tx_state)
                rx.load_correction_state(rx_state)
                tx.dpd = dpd0
                redone = run_cal_steps(tx, rx, cfg, path, plan,
                                       profile=recal_profile,
                                       target_pout_dbm=target_pout,
                                       final_drive_scale=drive_scale,
                                       seed=seed)
                recal = {
                    "steps": [r.name for r in redone],
                    "corrections": {r.name: _correction_summary(r)
                                    for r in redone},
                    "metrics_after": {r.name: _jsonable(r.metrics_after)
                                      for r in redone},
                    "saturated": {r.name: r.saturated for r in redone
                                  if r.saturated is not None},
                    # the step's own verdict and the spec it was judged
                    # against: what "recalibrated and in spec" means for
                    # a consumer is exactly this pair
                    "passed": {r.name: r.passed for r in redone},
                    "spec": {r.name: _jsonable(r.spec) for r in redone
                             if r.spec},
                }

            tone = single_tone(11e6, tx.fs, 1 << 13, amp=0.25)
            leak = lo_leak_dbc(tx(tone), tx.fs)

            wf = generate_ofdm(cfg)
            agc_for_loopback(tx, rx, path, wf.x * 0.25)
            iq_path = LoopbackPath(atten_db=path.atten_db,
                                   delay_ns=path.delay_ns,
                                   rx_lo_offset_hz=5.1e6)
            _, rho = measure_tx_rho(tx, rx, iq_path, n=n_iq, n_tones=8,
                                    seed=seed)
            irr_min = float(np.min(-20.0 * np.log10(
                np.maximum(np.abs(rho), 1e-12))))

            snap = tx_snapshot(tx, cfg, drive_scale=drive_scale)
            te, te_modem = snap["evm_db"], snap["evm_modem_db"]
            fc_tx = _fc_err_pct(tx.params.lpf)
            fc_rx = _fc_err_pct(rx.params.lpf)

            holds = {
                "lo_leak_dbc": leak <= lim_leak,
                "irr_min_db": irr_min >= lim_irr,
                "tx_fc_err_pct": abs(fc_tx) <= lim_fc_tx,
                "rx_fc_err_pct": abs(fc_rx) <= lim_fc_rx,
                # the EVM hold is judged in the modem form, like the
                # spec verdict (0.7.18); the isolation view travels
                # alongside in the row
                "tx_evm_modem_db": te_modem <= evm_lim,
            }
            row = {
                "temp_c": float(t), "lo_leak_dbc": leak,
                "irr_min_db": irr_min, "tx_evm_db": te,
                "tx_evm_modem_db": te_modem,
                "tx_fc_err_pct": fc_tx, "rx_fc_err_pct": fc_rx,
                "holds": holds, "all_hold": all(holds.values()),
            }
            if residual_keys:
                measured = measure_residual_surface(
                    tx, rx, path, cfg, results, n_iq=n_iq, seed=seed)
                row["residuals"] = impairment_residuals(measured)
                row["codes"] = _codes(tx, rx)
                row["tones"] = {r.name: [float(v) for v in r.metrics_after["irr_db"]]
                                for r in measured if "irr_db" in r.metrics_after}
                # the receive-view closure target at this temperature, at
                # the delivered input level, so a replay at T has both
                # planes to close against
                final = _result(results, "final_loopback_evm")
                if final is not None and "rx_input_dbm" in final.metrics_after:
                    rs = rx_snapshot(rx, cfg,
                                     float(final.metrics_after["rx_input_dbm"]),
                                     seed=seed)
                    row["rx_evm_db"] = rs["evm_db"]
                    row["rx_evm_modem_db"] = rs["evm_modem_db"]
            if recal is not None:
                row["recal"] = recal
            if tracked is not None:
                row["dpd_tracking"] = tracked
            rows.append(row)
    finally:
        tx.set_temperature(t_tx0)
        rx.set_temperature(t_rx0)
        if dpd_tracking:
            tx.dpd = dpd0
        if recalibrate:
            tx.load_correction_state(tx_state)
            rx.load_correction_state(rx_state)
            tx.dpd = dpd0
            rx.lna_idx, rx.vga_db = agc0

    # contiguous hold range around the calibration temperature: walking
    # outward stops at the first failing point on each side — a pass
    # beyond a failure does not extend validity
    order = sorted(rows, key=lambda r: r["temp_c"])
    hold_min = hold_max = CAL_TEMP_C
    for r in [r for r in order if r["temp_c"] <= CAL_TEMP_C][::-1]:
        if not r["all_hold"]:
            break
        hold_min = r["temp_c"]
    for r in [r for r in order if r["temp_c"] >= CAL_TEMP_C]:
        if not r["all_hold"]:
            break
        hold_max = r["temp_c"]

    expiry = {
        "calibrated_at_c": CAL_TEMP_C,
        "hold_min_c": hold_min,
        "hold_max_c": hold_max,
        "criteria": {"lo_leak_dbc_max": lim_leak, "irr_min_db_min": lim_irr,
                     "tx_fc_err_pct_abs_max": lim_fc_tx,
                     "rx_fc_err_pct_abs_max": lim_fc_rx,
                     "tx_evm_modem_db_max": evm_lim},
        "note": "corrections frozen at the calibration values; outside the "
                "hold range a recalibration (or tracking loop) is required",
    }
    if dpd_tracking:
        expiry["dpd_tracking"] = True
        expiry["note"] = ("corrections frozen at the calibration values "
                          "except the DPD, which the RLS tracking loop "
                          "follows at every point; outside the hold range "
                          "a recalibration is required")
    if recalibrate:
        expiry["recalibrated_per_point"] = True
        expiry["note"] = ("each point recalibrated at its own temperature "
                          f"(profile {recal_profile}) before measurement; "
                          "the hold range is the post-recalibration one")

    # the answer to "then what": the minimal re-run when the range is left,
    # priced with the capture costs the original run actually recorded
    plan = recal_steps(executed)
    cost = {r.name: r.cost for r in results}
    samples = sum(int(cost.get(s, {}).get("samples", 0)) for s in plan)
    expiry["recal_plan"] = {
        "steps": plan,
        "capture_samples": samples,
        "capture_ms": samples / tx.fs * 1e3,
    }
    return {"rows": rows, "expiry": expiry}
