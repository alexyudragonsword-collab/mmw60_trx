"""What electrical memory in the 60 GHz PA costs the predistorter at K > 1.

The preset PA is the memoryless modified Rapp of the 11ad evaluation
methodology.  A real PA has electrical memory, and upclocking raises a
question the standard-rate chain never meets: when the clock goes ×K, does
the PA's memory go with it?

- **scales with the signal** — the taps sit one sample apart at whatever
  ``fs_eff`` is, i.e. the PA was designed for the bandwidth it carries.  The
  predistorter sees the same problem at every K.
- **fixed in seconds** — the taps sit ``1 / fir_fs`` apart whatever the
  clock does, so at ``fs_eff`` they are ``fs_eff / fir_fs`` samples apart
  and a sample-spaced GMP basis no longer reaches them.

The model is wifitrx's ``ReferencePA`` (PA_DPD's reference PA: 3-tap input
FIR → Saleh → 2-tap output FIR) at the front end's own small-signal gain,
saturated power and peak PAE, with ``fs`` / ``fir_fs`` from PA_DPD@02ca433
(PA_DPD#4); the predistorter is wifitrx's own DPD step, whose GMP tap
spacing is an argument since wifi_trx_cal@da37888 (wifi_trx_cal#5).  Both
the PA model and ``fir_fs`` are assumptions (data/spec:
assumed.pa_memory_model, assumed.pa_memory_fir_fs_hz): this is a sensitivity
study on one scheme, the comparison table keeps the memoryless Rapp.

The tap spacing is measured on the chain, not set to ``fs_eff / fir_fs``:
the transmit baseband filter sits between the predistorter and the PA and
adds sample-level memory a sparse basis cannot represent (wifi_trx_cal#5).
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass

from . import spec
from .calcheck import run_cal_at
from .frontend import Frontend60
from .vendor.wifitrx.pa import ReferencePA, ScaledPA
from .vendor.wifitrx.pa.reference_pa import tap_stride

SCALES = "scales"          # memory law: taps one sample apart at any fs_eff
FIXED = "fixed"            # memory law: taps 1 / fir_fs apart in seconds


def default_fir_fs_hz() -> float:
    return float(spec.value("assumed.pa_memory_fir_fs_hz"))


def memory_stride(fs_eff_hz: float, fir_fs_hz: float | None) -> int:
    """Samples between the PA's memory taps at ``fs_eff_hz``: 1 when the
    memory scales with the signal (``fir_fs_hz`` None), else
    ``fs_eff / fir_fs``, which must be a positive integer (wifitrx refuses a
    fractional ratio: it would need a fractional-delay filter)."""
    return 1 if fir_fs_hz is None else tap_stride(float(fs_eff_hz), float(fir_fs_hz))


def memory_pa(fe: Frontend60, fs_eff_hz: float, fir_fs_hz: float | None = None) -> ScaledPA:
    """The reference PA with memory, anchored like the front end's own PA
    (small-signal gain, Psat, peak PAE).  ``fir_fs_hz`` None: the taps are
    one sample apart at ``fs_eff_hz`` (memory scales with the signal).

    Both memory laws get the same static curve: wifitrx's ``ScaledPA`` reads
    a PA with memory level by level in steady state since 0.7.40
    (wifi_trx_cal B41).  Before that it read the small-signal gain on an
    amplitude ramp and, with the taps two or more samples apart, saw the
    main tap alone — 1.80 dB more gain for the same part, which this
    function used to work around by anchoring on the sample-spaced PA."""
    inner = ReferencePA() if fir_fs_hz is None else ReferencePA(fs=float(fs_eff_hz), fir_fs=float(fir_fs_hz))
    return ScaledPA(inner, gain_db=fe.pa_gain_db, psat_dbm=fe.psat_dbm, pae_max=fe.pa_pae_max)


@dataclass
class MemoryRow:
    k: int
    bw_eff_hz: float
    fs_eff_hz: float
    pa: str                           # "rapp" (the preset) | "reference"
    law: str | None                   # SCALES | FIXED | None for the memoryless Rapp
    fir_fs_hz: float | None
    stride: int                       # samples between the PA's memory taps
    tap_spacing: int | None           # the DPD basis's tap spacing; None = DPD off
    dpd_evm_db: float | None          # the DPD step's own PA-output EVM
    tx_evm_db: float                  # final TX EVM as a standard receiver reads it
    loop_evm_db: float                # the same through the loopback (TX + RX)
    obo_db: float | None = None       # back-off from Psat at the final check
    failed: tuple = ()

    @property
    def label(self) -> str:
        if self.pa == "rapp":
            return "Rapp, memoryless (the preset)"
        if self.law == SCALES:
            return "reference PA, memory scales with the signal"
        return f"reference PA, taps {1e9 / self.fir_fs_hz:g} ns apart (x{self.stride} samples)"


def run_row(fe: Frontend60, k: int, base_bw_hz: float, standard: str, pa: str = "reference",
            fir_fs_hz: float | None = None, tap_spacing: int | None = 1, oversampling: int = 2,
            obo_db: float | None = None) -> MemoryRow:
    """One run of wifitrx's sequence at K with the given PA and DPD tap
    spacing (None: the sequence without its DPD step)."""
    bw_eff = base_bw_hz * k
    fs_eff = bw_eff * oversampling
    if pa == "rapp":
        model, law, stride = None, None, 1
    else:
        model = memory_pa(fe, fs_eff, fir_fs_hz)
        law = SCALES if fir_fs_hz is None else FIXED
        stride = memory_stride(fs_eff, fir_fs_hz)
    run = run_cal_at(fe, k, base_bw_hz, oversampling=oversampling, standard=standard, pa=model,
                     with_dpd=tap_spacing is not None, dpd_tap_spacing=tap_spacing or 1, obo_db=obo_db)
    dpd = next((r.value for r in run.rows if r.step == "dpd"), None)
    if tap_spacing is not None and run.dpd_tap_spacing != tap_spacing:
        raise RuntimeError(f"the DPD step ran with tap spacing {run.dpd_tap_spacing}, not {tap_spacing}")
    return MemoryRow(k=k, bw_eff_hz=bw_eff, fs_eff_hz=fs_eff, pa=pa, law=law, fir_fs_hz=fir_fs_hz, stride=stride,
                     tap_spacing=tap_spacing, dpd_evm_db=dpd, tx_evm_db=run.final_views["tx_evm_modem_db"],
                     loop_evm_db=run.final_views["evm_modem_db"],
                     obo_db=None if run.pout_dbm is None else fe.psat_dbm - run.pout_dbm,
                     failed=tuple(r.step for r in run.rows if r.status == "failed"))


def candidate_spacings(stride: int) -> tuple[int, ...]:
    """The tap spacings worth measuring for a PA whose taps are ``stride``
    samples apart: sample-spaced, the matched spacing, and the powers of two
    up to it that data/spec lists (assumed.pa_memory_dpd_candidates)."""
    listed = tuple(int(v) for v in spec.value("assumed.pa_memory_dpd_candidates"))
    return tuple(sorted({1, int(stride), *(v for v in listed if v < stride)}))


# ---------------------------------------------------------------- many rows
def row_key(k: int, base_bw_hz: float, standard: str, pa: str = "reference", fir_fs_hz: float | None = None,
            tap_spacing: int | None = 1, oversampling: int = 2, obo_db: float | None = None) -> tuple:
    """The arguments of ``run_row`` after the front end, as a hashable key
    (two requests for the same row are run once)."""
    return (int(k), float(base_bw_hz), str(standard), str(pa), None if fir_fs_hz is None else float(fir_fs_hz),
            None if tap_spacing is None else int(tap_spacing), int(oversampling),
            None if obo_db is None else float(obo_db))


def _run_key(args: tuple) -> MemoryRow:
    fe, key = args
    return run_row(fe, *key)


def run_many(fe: Frontend60, keys: list[tuple], jobs: int = 1) -> dict[tuple, MemoryRow]:
    """``run_row`` for every distinct key, in worker processes when
    ``jobs`` > 1.  Each row builds its own chains from the front end and
    draws nothing from a shared generator, so the numbers do not depend on
    ``jobs`` or on the order."""
    todo = list(dict.fromkeys(keys))
    if jobs > 1 and len(todo) > 1:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            rows = list(pool.map(_run_key, [(fe, key) for key in todo]))
    else:
        rows = [_run_key((fe, key)) for key in todo]
    return dict(zip(todo, rows))


def study_keys(k: int, base_bw_hz: float, standard: str, fir_fs_hz: float | None = None, oversampling: int = 2,
               with_rapp: bool = True, obo_db: float | None = None) -> list[tuple]:
    """The rows of one K, in table order: the preset Rapp (DPD off / on),
    the reference PA at the scales-with-the-signal end (DPD off / on), and
    at ``fir_fs_hz`` (default assumed.pa_memory_fir_fs_hz) with the DPD off
    and at every candidate tap spacing."""
    fir = default_fir_fs_hz() if fir_fs_hz is None else float(fir_fs_hz)
    kw = dict(oversampling=oversampling, obo_db=obo_db)
    keys = [row_key(k, base_bw_hz, standard, "rapp", tap_spacing=ts, **kw) for ts in (None, 1)] if with_rapp else []
    keys += [row_key(k, base_bw_hz, standard, tap_spacing=ts, **kw) for ts in (None, 1)]
    stride = memory_stride(base_bw_hz * k * oversampling, fir)
    keys += [row_key(k, base_bw_hz, standard, fir_fs_hz=fir, tap_spacing=ts, **kw)
             for ts in (None, *candidate_spacings(stride))]
    return keys


def study(fe: Frontend60, k: int, base_bw_hz: float, standard: str, fir_fs_hz: float | None = None,
          oversampling: int = 2, with_rapp: bool = True, obo_db: float | None = None, jobs: int = 1) -> list[MemoryRow]:
    """``study_keys`` run: ``obo_db`` puts every row's final check at the
    same output back-off (default: wherever wifitrx's drive lands, which
    differs by about 1 dB between the two memory laws)."""
    keys = study_keys(k, base_bw_hz, standard, fir_fs_hz, oversampling, with_rapp, obo_db)
    done = run_many(fe, keys, jobs)
    return [done[key] for key in keys]


def cost_keys(k: int, base_bw_hz: float, standard: str, obo_db: float, fir_fs_hz: float | None = None,
              oversampling: int = 2) -> tuple[tuple, tuple, tuple]:
    """(scales, fixed with the sample-spaced basis, fixed with the matched
    spacing), all with DPD at the same back-off: the three readings the
    cost of the memory law is read from."""
    fir = default_fir_fs_hz() if fir_fs_hz is None else float(fir_fs_hz)
    kw = dict(oversampling=oversampling, obo_db=obo_db)
    stride = memory_stride(base_bw_hz * k * oversampling, fir)
    return (row_key(k, base_bw_hz, standard, tap_spacing=1, **kw),
            row_key(k, base_bw_hz, standard, fir_fs_hz=fir, tap_spacing=1, **kw),
            row_key(k, base_bw_hz, standard, fir_fs_hz=fir, tap_spacing=stride, **kw))


def cost_rows(fe: Frontend60, k: int, base_bw_hz: float, standard: str, obo_db: float,
              fir_fs_hz: float | None = None, oversampling: int = 2, jobs: int = 1
              ) -> tuple[MemoryRow, MemoryRow, MemoryRow]:
    keys = cost_keys(k, base_bw_hz, standard, obo_db, fir_fs_hz, oversampling)
    done = run_many(fe, list(keys), jobs)
    return tuple(done[key] for key in keys)


def best_spacing(rows: list[MemoryRow]) -> MemoryRow:
    """The fixed-memory row with the best final TX EVM among those with DPD."""
    cand = [r for r in rows if r.law == FIXED and r.tap_spacing is not None]
    return min(cand, key=lambda r: r.tx_evm_db)


# ---------------------------------------------------------------- the cost in back-off
def backoff_for_evm(obo_db: list[float], evm_db: list[float], target_db: float) -> tuple[float | None, bool]:
    """(the smallest back-off at which the EVM reaches ``target_db``, whether
    that is a crossing inside the sweep).  The crossing is the first one
    going from little back-off to much, linear between the two grid points
    around it.  (None, False) when the sweep never reaches the target;
    (the first grid point, False) when it is already there at the first
    point, so the true value is at most that."""
    pts = sorted(zip(obo_db, evm_db))
    if pts[0][1] <= target_db:
        return float(pts[0][0]), False
    for (o0, e0), (o1, e1) in zip(pts, pts[1:]):
        if e1 <= target_db < e0:
            return float(o0 + (o1 - o0) * (e0 - target_db) / (e0 - e1)), True
    return None, False


@dataclass
class SweepPoint:
    obo_db: float
    scales: MemoryRow
    fixed_x1: MemoryRow
    fixed_matched: MemoryRow

    @property
    def fixed_best_evm_db(self) -> float:
        """The fixed-memory PA with whichever of the two spacings reads better here."""
        return min(self.fixed_x1.tx_evm_db, self.fixed_matched.tx_evm_db)


def sweep_keys(k: int, base_bw_hz: float, standard: str, obos, fir_fs_hz: float | None = None,
               oversampling: int = 2) -> list[tuple]:
    return [key for o in obos for key in cost_keys(k, base_bw_hz, standard, float(o), fir_fs_hz, oversampling)]


def sweep_points(done: dict, k: int, base_bw_hz: float, standard: str, obos, fir_fs_hz: float | None = None,
                 oversampling: int = 2) -> list[SweepPoint]:
    return [SweepPoint(float(o), *(done[key] for key in cost_keys(k, base_bw_hz, standard, float(o), fir_fs_hz,
                                                                  oversampling))) for o in obos]


def backoff_penalty(points: list[SweepPoint], target_db: float) -> dict:
    """What memory fixed in seconds costs in output power at equal EVM: the
    back-off the scales-with-the-signal PA needs for ``target_db``
    (``scales``), the back-off the fixed-memory PA needs with its better
    spacing (``fixed``), and the difference (``cost``; None unless both are
    crossings inside the sweep; ``*_exact`` say which are).

    A single back-off cannot show this: the predistorter's gain falls off a
    cliff as the PA nears saturation, the two PAs' cliffs sit 1–2 dB apart,
    and an EVM difference read on the cliff is mostly the cliff."""
    obos = [p.obo_db for p in points]
    a, a_exact = backoff_for_evm(obos, [p.scales.tx_evm_db for p in points], target_db)
    b, b_exact = backoff_for_evm(obos, [p.fixed_best_evm_db for p in points], target_db)
    return {"target_db": float(target_db), "scales": a, "scales_exact": a_exact, "fixed": b, "fixed_exact": b_exact,
            "cost": b - a if a_exact and b_exact else None}
