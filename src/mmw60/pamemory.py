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

    The anchors are taken on the sample-spaced PA and kept for the spread
    one: the two have the same static curve (the same taps, only further
    apart), but wifitrx's ``ScaledPA`` finds the small-signal gain on an
    amplitude ramp, and with the taps two or more samples apart it reads the
    main tap alone — 1.80 dB more gain for the same part.  Anchoring each
    law separately would put the two ends of the comparison at different
    drive levels."""
    pa = ScaledPA(ReferencePA(), gain_db=fe.pa_gain_db, psat_dbm=fe.psat_dbm, pae_max=fe.pa_pae_max)
    if fir_fs_hz is not None:
        pa.pa_model = ReferencePA(fs=float(fs_eff_hz), fir_fs=float(fir_fs_hz))
    return pa


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


def study(fe: Frontend60, k: int, base_bw_hz: float, standard: str, fir_fs_hz: float | None = None,
          oversampling: int = 2, with_rapp: bool = True, obo_db: float | None = None) -> list[MemoryRow]:
    """The rows of one K: the preset Rapp (DPD off / on), the reference PA
    at the scales-with-the-signal end (DPD off / on), and at ``fir_fs_hz``
    (default assumed.pa_memory_fir_fs_hz) with the DPD off and at every
    candidate tap spacing.  ``obo_db`` puts every row's final check at the
    same output back-off (default: wherever wifitrx's drive lands, which
    differs by about 1 dB between the two memory laws)."""
    fir = default_fir_fs_hz() if fir_fs_hz is None else float(fir_fs_hz)
    kw = dict(oversampling=oversampling, obo_db=obo_db)
    rows = [run_row(fe, k, base_bw_hz, standard, "rapp", tap_spacing=ts, **kw) for ts in (None, 1)] if with_rapp else []
    rows += [run_row(fe, k, base_bw_hz, standard, tap_spacing=ts, **kw) for ts in (None, 1)]
    stride = memory_stride(base_bw_hz * k * oversampling, fir)
    rows += [run_row(fe, k, base_bw_hz, standard, fir_fs_hz=fir, tap_spacing=ts, **kw)
             for ts in (None, *candidate_spacings(stride))]
    return rows


def cost_rows(fe: Frontend60, k: int, base_bw_hz: float, standard: str, obo_db: float,
              fir_fs_hz: float | None = None, oversampling: int = 2) -> tuple[MemoryRow, MemoryRow, MemoryRow]:
    """(scales, fixed with the sample-spaced basis, fixed with the matched
    spacing), all with DPD at the same back-off: the three readings the
    cost of the memory law is read from."""
    fir = default_fir_fs_hz() if fir_fs_hz is None else float(fir_fs_hz)
    kw = dict(oversampling=oversampling, obo_db=obo_db)
    stride = memory_stride(base_bw_hz * k * oversampling, fir)
    return (run_row(fe, k, base_bw_hz, standard, tap_spacing=1, **kw),
            run_row(fe, k, base_bw_hz, standard, fir_fs_hz=fir, tap_spacing=1, **kw),
            run_row(fe, k, base_bw_hz, standard, fir_fs_hz=fir, tap_spacing=stride, **kw))


def best_spacing(rows: list[MemoryRow]) -> MemoryRow:
    """The fixed-memory row with the best final TX EVM among those with DPD."""
    cand = [r for r in rows if r.law == FIXED and r.tap_spacing is not None]
    return min(cand, key=lambda r: r.tx_evm_db)
