"""Milestone 2 / 3: the array layer's tables as data (what example 10 prints).

``build`` runs every computation of ``examples/10_array_link_and_training.py``
in the example's own order and returns one plain dict (float / int / str /
bool / None, lists, dicts with string keys: ``json.dumps(report,
allow_nan=False)`` works), so a printer or a graphical page only formats.
Numbers are at full precision, in the unit the example prints them in (the
field name says which: ``_db``, ``_dbm``, ``_m``, ``_us``, ``_mw``,
``_mbps``, ``_pct``); a value the example prints as a dash or ``nan`` is
None.

One key per section of the example (``SECTIONS``; ``HEADER_FIELDS`` and
``ROW_FIELDS`` name every field):

``header``
    a dict: the settings the headings and footnotes print (spec values, the
    front end's operating point, SCAN angle, oxygen absorptions, phase-shifter
    powers, the sweep's threshold ...).
``faces`` (1)
    per N: transmit / receive gain, the gain at the scanned beam relative to
    broadside, 3 dB beamwidth (None at N = 1), sectors, the phase shifters'
    loss without and with the element errors.
``link`` (2-3)
    per scheme and N: per-element output and back-off, PA EVM, EIRP, receive
    gain, floor, decoder cap, the path loss and the distance at MCS0 and at
    the cap.
``oxygen`` (3b)
    per scheme and N: the MCS0 path loss and its distance at each of
    ``header["oxygen_alphas_db_per_km"]``.
``power`` (3c)
    per scheme and N: PAE, PA / phase-shifter / rest / total power, rate and
    pJ/bit at the cap, pJ/bit at each of ``header["phase_shifter_alt_mw"]``
    (``cap_mcs`` None and the rest None without a decoder cap).
``ay_operating_points`` (3d)
    per 802.11ay waveform: its own operating back-off, the PA alone at the
    preset back-off, the 16-QAM 3/4 MCS the distance columns use.
``ay`` (3d)
    per waveform, operating point (``preset`` / ``own``) and N: the ``link``
    columns plus rate, the distances at MCS1 / 16-QAM 3/4 / the cap, pJ/bit
    and the 16-QAM 3/4 distance on the multipath thresholds.
``ay_smallest`` (3d)
    per waveform and operating point: the smallest array that reaches the
    EIRP limit and its cost.
``training`` (4)
    per scheme and N: tones, the per-tone SNR each sweep needs, the path loss
    each takes, the transmit sweep against the MCS0 edge and the cap, sweep
    time (``sweep`` False and the rest None at one sector).
``training_repetitions`` (4b)
    per scheme and N > 1: ``cells``, one per combining (the preset's, then
    coherent): repetitions, required SNR, margin to the MCS0 edge, sweep time.
``two_stage`` (4c)
    per scheme, target and sub-array size m: the target path loss and the
    ``flat`` / ``wide`` / ``narrow`` stages (sectors, repetitions, EIRP,
    required SNR, path loss reached, time), the two-stage time.
``ay_sweep`` (4d)
    per N: the 802.11ay sector sweep's EIRP and path losses, per waveform
    (``waveforms``) the MCS1 and cap edges against it, the be row of section
    4 and both sweep times (``sweep`` False at one sector).
``squint`` (5)
    per occupied band and N: the gain lost to squint, mean and worst tone,
    phase shifters and true time delay (unrounded; the example rounds to two
    decimals).
``sensitivity`` (6)
    per assumed input: transmit gain, phase loss, sectors, required SNR, the
    transmit sweep against the MCS0 edge.

``progress(section, row)`` is called with ``row=None`` when a section starts
and with each row as it is computed (the same dict that ends up in the
report).  The header arrives in pieces: ``progress("header", piece)`` is
called whenever more of it is known, always before the section that prints
it starts and, for a footnote's values, before the next section starts; the
pieces together are ``report["header"]``.
"""
from __future__ import annotations

import dataclasses as dc
import math

import numpy as np

from . import ENGINE_BANNER, __version__, spec
from . import arraylink as al
from .ay import edmg
from .config import ChannelConfig, array_frontend, ay_60ghz, if_extender_60ghz, zero_if_60ghz
from .frontend import Frontend60
from .frontend.array60 import Array60
from .power import PowerCoefficients
from .sim.link import LinkSim
from .vendor.arraytx.beam import beam_response, beamwidth_3db_deg

FLAT = ChannelConfig(model="flat")
SIZES = (1, 4, 16, 64)
SCAN_DEG = 45.0
#: 16-QAM 3/4: the fastest MCS both 802.11ay waveforms have a threshold for
AY_COMMON_MCS = {"ay_sc": 14, "ay_ofdm": 13}
#: the phase-shifter powers of the sensitivity columns of section 3c [W]
PHASE_SHIFTER_ALT_W = (0.0, 30e-3)
#: the top-level keys of a report, in the order the sections run
SECTIONS = ("header", "faces", "link", "oxygen", "power", "ay_operating_points", "ay", "ay_smallest", "training",
            "training_repetitions", "two_stage", "ay_sweep", "squint", "sensitivity")
#: the keys of ``report["header"]``
HEADER_FIELDS = (
    "version", "engine", "sizes", "trials", "users", "scan_deg", "pa_pout_dbm", "obo_db", "rx_nf_db",
    "element_gain_dbi", "eirp_limit_dbm", "spacing_lambda", "element_pattern", "phase_bits", "element_errors",
    "oxygen_db_per_km", "carrier_ghz", "oxygen_alphas_db_per_km", "phase_shifter_mw", "phase_shifter_alt_mw",
    "cr_rms_delay_ns", "ay_ofdm_multipath_margin_db", "training_field", "training_estimator",
    "training_success_within_db", "training_p_target_pct", "max_repetitions", "repetition_combining", "two_stage_n",
    "two_stage_m", "ay_sweep_threshold_db", "ay_sweep_occupied_bw_ghz", "ay_waveforms", "implementation_loss_db",
    "be_scheme", "ssw_frame_us", "ssw_frame_octets", "ssw_frame_codewords", "sbifs_us", "squint_sizes",
    "sensitivity_scheme", "sensitivity_n", "sensitivity_preset_req_tx_db")
#: the keys of every row of each section
ROW_FIELDS = {
    "faces": ("n", "tx_gain_db", "rx_gain_db", "scan_rel_db", "beamwidth_3db_deg", "sectors", "phase_loss_db",
              "phase_and_error_loss_db"),
    "link": ("scheme", "n", "element_pout_dbm", "obo_db", "pa_evm_db", "eirp_dbm", "rx_gain_db", "floor_db",
             "cap_mcs", "path_loss_mcs0_db", "path_loss_cap_db", "range_mcs0_m", "range_cap_m"),
    "oxygen": ("scheme", "n", "path_loss_mcs0_db", "range_mcs0_by_alpha_m"),
    "power": ("scheme", "n", "element_pout_dbm", "pae_pct", "pa_mw", "phase_shifters_mw", "rest_mw", "total_mw",
              "cap_mcs", "rate_mbps", "pj_per_bit", "pj_per_bit_alt"),
    "ay_operating_points": ("waveform", "own_obo_db", "pa_alone_evm_at_preset_db", "common_mcs"),
    "ay": ("waveform", "point", "n", "element_pout_dbm", "obo_db", "pa_evm_db", "eirp_dbm", "rx_gain_db", "floor_db",
           "cap_mcs", "rate_mbps", "range_mcs1_m", "range_common_m", "range_cap_m", "pj_per_bit",
           "range_common_multipath_m"),
    "ay_smallest": ("waveform", "point", "operating_obo_db", "n", "element_pout_dbm", "pae_pct", "pa_mw",
                    "phase_shifters_mw", "rx_gain_db", "range_mcs1_m", "range_common_m", "pj_per_bit",
                    "range_common_multipath_m"),
    "training": ("scheme", "n", "tones", "sweep", "req_tx_db", "req_rx_db", "path_loss_txss_db",
                 "path_loss_rxss_db", "txss_minus_mcs0_db", "txss_minus_cap_db", "sweep_us"),
    #: cells: one per combining, each {combining, repetitions, req_tx_db, txss_minus_mcs0_db, tx_sweep_us}
    "training_repetitions": ("scheme", "n", "cells"),
    #: flat / wide / narrow: each {elements, sectors, eirp_dbm, repetitions, req_db, path_loss_db, time_us}
    "two_stage": ("scheme", "target", "target_path_loss_db", "m", "flat", "wide", "narrow", "two_stage_us"),
    #: waveforms: one per waveform, each {waveform, path_loss_mcs1_db, txss_minus_mcs1_db, cap_mcs,
    #: txss_minus_cap_db}
    "ay_sweep": ("n", "sweep", "eirp_dbm", "path_loss_txss_db", "path_loss_rxss_db", "waveforms",
                 "be_path_loss_txss_db", "be_txss_minus_mcs0_db", "ay_sweep_us", "be_sweep_us"),
    "squint": ("band", "n", "phase_mean_db", "phase_edge_db", "ttd_mean_db", "ttd_edge_db"),
    "sensitivity": ("input", "tx_gain_db", "phase_loss_db", "sectors", "req_tx_db", "txss_minus_mcs0_db"),
}


# ---------------------------------------------------------------- the example's inputs
def default_frontend() -> Frontend60:
    """The one front end at every element of every scheme (iron rule 2)."""
    return Frontend60.from_config(zero_if_60ghz(k=8))


def default_schemes():
    """(label, config): topology B on the 11be 80 MHz base x 4 and the 11ac 20 MHz base x 8,
    topology A on 11be 80 MHz."""
    b_be = zero_if_60ghz(k=4, standard="11be", bandwidth_hz=80e6)
    a_be = if_extender_60ghz(standard="11be", bandwidth_hz=80e6)
    return (("B 11be 80M x4 (320 MHz)", dc.replace(b_be, channel=FLAT)),
            ("B 11ac 20M x8 (160 MHz)", dc.replace(zero_if_60ghz(k=8), channel=FLAT)),
            ("A 11be 80M (IF extender)", dc.replace(a_be, channel=FLAT)))


def default_ay_cfgs() -> dict:
    """{waveform: config}: the two 802.11ay waveforms on topology B's hardware, flat channel."""
    return {wf: dc.replace(ay_60ghz(wf, 1), channel=FLAT) for wf in ("ay_sc", "ay_ofdm")}


def default_squint_schemes():
    """(label, config) of section 5: the 11be 80 MHz base at three clock ratios."""
    return (("B 11be 80M x4 (320 MHz)", zero_if_60ghz(k=4, standard="11be", bandwidth_hz=80e6)),
            ("B 11be 80M x8 (640 MHz)", zero_if_60ghz(k=8, standard="11be", bandwidth_hz=80e6)),
            ("B 11be 80M x32 (2.56 GHz)", zero_if_60ghz(k=32, standard="11be", bandwidth_hz=80e6)))


def quick_kwargs() -> dict:
    """``build``'s arguments for the example's ``--quick`` path (the numbers are meaningless)."""
    return dict(sizes=(1, 16), trials=200, users=5, two_stage_m=(8,), squint_sizes=(16,), sensitivity_n=None)


# ---------------------------------------------------------------- plain data
def plain(v):
    """``v`` as JSON data: numpy scalars to Python's, tuples and arrays to lists, dict keys to str, a
    non-finite float to None."""
    if v is None or isinstance(v, (bool, str)):
        return v
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        f = float(v)
        return f if math.isfinite(f) else None
    if isinstance(v, dict):
        return {str(k): plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, np.ndarray)):
        return [plain(x) for x in v]
    raise TypeError(f"not report data: {type(v).__name__}")


class _Report:
    """The dict being built, and the caller's ``progress``."""

    def __init__(self, progress=None):
        self.data = {k: ({} if k == "header" else []) for k in SECTIONS}
        self._progress = progress

    def start(self, section: str) -> None:
        if self._progress is not None:
            self._progress(section, None)

    def header(self, **kw) -> None:
        piece = plain(kw)
        self.data["header"].update(piece)
        if self._progress is not None:
            self._progress("header", piece)

    def row(self, section: str, **kw) -> None:
        r = plain(kw)
        self.data[section].append(r)
        if self._progress is not None:
            self._progress(section, r)


# ---------------------------------------------------------------- rows that stand alone
def faces_row(base, fe, n: int) -> dict:
    """Section 1's row: the faces of an ``n``-element array of ``base``'s front end."""
    ar = Array60.from_config(array_frontend(base, n), fe)
    ideal = Array60.from_config(dc.replace(array_frontend(base, n), frontend=dc.replace(
        array_frontend(base, n).frontend, array=dc.replace(array_frontend(base, n).frontend.array,
                                                           gain_err_db_rms=0.0, phase_err_deg_rms=0.0))), fe)
    th = np.linspace(-ar.scan_max_deg, ar.scan_max_deg, 61)
    q = float(np.mean([ideal.quantisation_loss_db("tx", t) for t in th]))
    qe = float(np.mean([ar.quantisation_loss_db("tx", t) for t in th]))
    scan = ar.tx_gain_db(SCAN_DEG, SCAN_DEG)[0] - ar.tx_gain_db(0.0, 0.0)[0]
    bw = beamwidth_3db_deg(ar.tx, 0.0) if n > 1 else float("nan")
    return dict(n=n, tx_gain_db=ar.tx_gain_db(0.0, 0.0)[0], rx_gain_db=ar.rx_gain_db(0.0, 0.0)[0],
                scan_rel_db=scan, beamwidth_3db_deg=bw, sectors=ar.codebook_deg().size, phase_loss_db=q,
                phase_and_error_loss_db=qe)


def squint_row(label: str, cfg, fe, n: int, f_hz) -> dict:
    """Section 5's row: the array gain lost across the tones ``f_hz`` at a SCAN_DEG beam."""
    ar = Array60.from_config(array_frontend(cfg, n), fe)
    row = []
    for mode in ("phase", "ttd"):
        h = np.abs(beam_response(ar.tx, SCAN_DEG, f_hz, mode)) ** 2
        row += [-10 * np.log10(np.mean(h)), -10 * np.log10(np.min(h))]
    return dict(band=label, n=n, phase_mean_db=row[0], phase_edge_db=row[1], ttd_mean_db=row[2], ttd_edge_db=row[3])


def _stage(x: dict) -> dict:
    """One stage of ``arraylink.hierarchical_training`` with its time in microseconds."""
    return dict(elements=x["elements"], sectors=x["sectors"], eirp_dbm=x["eirp_dbm"], repetitions=x["repetitions"],
                req_db=x["req_db"], path_loss_db=x["pl_db"], time_us=None if x["time_s"] is None else 1e6 * x["time_s"])


def _ay_sweep(out: _Report, fe, sizes, ay_cfgs: dict, ay_budgets: dict, budgets: dict, train: dict,
              be_lab: str) -> None:
    """Section 4d: the 802.11ay sector sweep on the arrays of 3d (the first waveform's budget carries it),
    next to section 4's row of the be scheme ``be_lab``."""
    wf0 = next(iter(ay_cfgs))
    occ = ay_budgets[(wf0, "preset", sizes[0])][2].occupied_bw_hz
    t_ctl = edmg.control_threshold_db(occ)
    loss = float(spec.value("dmg.sensitivity_assumptions")["implementation_loss_db"])
    out.header(ay_sweep_threshold_db=t_ctl, ay_sweep_occupied_bw_ghz=occ / 1e9, ay_waveforms=list(ay_cfgs),
               implementation_loss_db=loss, be_scheme=be_lab)
    out.start("ay_sweep")
    for n in sizes:
        if n == 1:
            out.row("ay_sweep", n=n, sweep=False, eirp_dbm=None, path_loss_txss_db=None, path_loss_rxss_db=None,
                    waveforms=None, be_path_loss_txss_db=None, be_txss_minus_mcs0_db=None, ay_sweep_us=None,
                    be_sweep_us=None)
            continue
        _, ar, b = ay_budgets[(wf0, "preset", n)]
        t_ay = al.ay_sweep_time_s(ar, "tx") + al.ay_sweep_time_s(ar, "rx")
        pl_tx = al.transmit_sweep_reach_db(b, ar, t_ctl)
        pl_rx = b.eirp_dbm + b.g_rx_db - (b.noise_dbm + t_ctl)
        cells = []
        for wf in ay_cfgs:
            bw = ay_budgets[(wf, "preset", n)][2]
            pl1 = bw.eirp_dbm + bw.g_rx_db - bw.sens_by_mcs[1] if 1 in bw.sens_by_mcs else None
            plc = (bw.eirp_dbm + bw.g_rx_db - bw.sens_by_mcs[bw.dec_mcs]
                   if bw.dec_mcs is not None and bw.dec_mcs in bw.sens_by_mcs else None)
            cells.append(dict(waveform=wf, path_loss_mcs1_db=pl1,
                              txss_minus_mcs1_db=None if pl1 is None else pl_tx - pl1, cap_mcs=bw.dec_mcs,
                              txss_minus_cap_db=None if plc is None else pl_tx - plc))
        c_be, ar_be, b_be = budgets[(be_lab, n)]
        t_be = al.sweep_time_s(ar_be, c_be.upclocked(), "tx") + al.sweep_time_s(ar_be, c_be.upclocked(), "rx")
        rt = train.get((be_lab, n))
        be_tx = (None if rt is None or rt[0]["snr_db"] is None
                 else al.transmit_sweep_reach_db(b_be, ar_be, rt[0]["snr_db"]))
        out.row("ay_sweep", n=n, sweep=True, eirp_dbm=b.eirp_dbm, path_loss_txss_db=pl_tx, path_loss_rxss_db=pl_rx,
                waveforms=cells, be_path_loss_txss_db=be_tx, be_txss_minus_mcs0_db=None if rt is None else rt[2],
                ay_sweep_us=1e6 * t_ay, be_sweep_us=1e6 * t_be)
    octets = spec.value("dmg.ssw_frame")["ssw_frame_octets"]
    out.header(ssw_frame_us=1e6 * al.ssw_frame_s(), ssw_frame_octets=octets,
               ssw_frame_codewords=len(al.control_phy_codewords(octets)),
               sbifs_us=1e6 * spec.value("dmg.phy_timing")["sbifs_s"])


# ---------------------------------------------------------------- the report
def build(fe=None, schemes=None, ay_cfgs=None, sizes=SIZES, trials=2000, users=25, progress=None, *,
          squint_schemes=None, squint_sizes=(16, 64), two_stage_n=None, two_stage_m=(8, 16),
          sensitivity_n=16) -> dict:
    """Every number of example 10 as one plain dict (the module docstring lists the keys).

    ``fe`` the shared ``Frontend60``, ``schemes`` the ``(label, Mmw60Config)`` be schemes (the first one
    is the base of sections 1, 4d and 6), ``ay_cfgs`` ``{waveform: Mmw60Config}`` for the 802.11ay
    waveforms (the first one carries section 4d's sweep), ``squint_schemes`` section 5's ``(label,
    config)``: each defaults to what the example builds (``default_*``).  ``sizes`` the array sizes,
    ``trials`` / ``users`` the sweeps' Monte-Carlo size.  ``squint_sizes`` section 5's array sizes;
    ``two_stage_n`` section 4c's array (default the largest of ``sizes``) and ``two_stage_m`` its
    sub-arrays (those smaller than the array); ``sensitivity_n`` section 6's array.  Sections 4c and 6
    read the budgets of their N: they are left empty when it is not in ``sizes`` (or is None, or 1).
    An empty ``ay_cfgs`` leaves the 802.11ay sections (3d, 4d) empty.  A section left empty does not
    start (no ``progress`` call), and the header entries only it fills are None.

    ``progress(section, row)``: see the module docstring.
    """
    out = _Report(progress)
    sizes = tuple(int(n) for n in sizes)
    out.start("header")
    fe = default_frontend() if fe is None else fe
    geo, tr = spec.value("assumed.array_geometry"), spec.value("assumed.array_training")
    out.header(version=__version__, engine=ENGINE_BANNER, sizes=sizes, trials=int(trials), users=int(users),
               scan_deg=SCAN_DEG, pa_pout_dbm=float(fe.target_pout_dbm()), obo_db=fe.obo_db,
               rx_nf_db=fe.rx_front.nf_db, element_gain_dbi=fe.antenna_gain_tx_dbi, eirp_limit_dbm=fe.eirp.avg_dbm,
               spacing_lambda=geo["spacing_lambda"], element_pattern=geo["element_pattern"],
               phase_bits=spec.value("assumed.array_phase_bits"),
               element_errors=spec.value("assumed.array_element_errors"), oxygen_db_per_km=al.oxygen_db_per_km())

    # ---------------------------------------------------------------- 1. faces
    schemes = tuple(default_schemes() if schemes is None else schemes)
    base = schemes[0][1]
    out.start("faces")
    for n in sizes:
        out.row("faces", **faces_row(base, fe, n))

    # ---------------------------------------------------------------- 2-3. budgets
    out.start("link")
    budgets = {}
    for lab, cfg in schemes:
        for n in sizes:
            c = array_frontend(cfg, n)
            ar = Array60.from_config(c, fe)
            b = al.array_budget(c, fe, ar, lab)
            budgets[(lab, n)] = (c, ar, b)
            pl0 = None if 0 not in b.sens_by_mcs else b.eirp_dbm + b.g_rx_db - b.sens_by_mcs[0]
            plc = None if b.dec_mcs is None else b.eirp_dbm + b.g_rx_db - b.sens_by_mcs[b.dec_mcs]
            out.row("link", scheme=lab, n=n, element_pout_dbm=b.p_elem_dbm, obo_db=b.obo_db, pa_evm_db=b.pa_evm_db,
                    eirp_dbm=b.eirp_dbm, rx_gain_db=b.g_rx_db, floor_db=b.floor_db, cap_mcs=b.dec_mcs,
                    path_loss_mcs0_db=pl0, path_loss_cap_db=plc, range_mcs0_m=b.range_by_mcs.get(0),
                    range_cap_m=b.range_by_mcs.get(b.dec_mcs))
    out.header(carrier_ghz=base.carrier_hz / 1e9)

    # ---------------------------------------------------------------- 3b. the oxygen estimate
    alphas = (0.0, 10.0, al.oxygen_db_per_km(), 20.0)
    out.header(oxygen_alphas_db_per_km=alphas)
    out.start("oxygen")
    for lab, _ in schemes:
        for n in sizes:
            c, ar, b = budgets[(lab, n)]
            if 0 not in b.sens_by_mcs:
                continue
            pl0 = b.eirp_dbm + b.g_rx_db - b.sens_by_mcs[0]
            out.row("oxygen", scheme=lab, n=n, path_loss_mcs0_db=pl0,
                    range_mcs0_by_alpha_m=[al.range_m(pl0, c.carrier_hz, a) for a in alphas])

    # ---------------------------------------------------------------- 3c. power per bit
    coeffs = PowerCoefficients.from_spec()
    ps_alt = PHASE_SHIFTER_ALT_W
    out.header(phase_shifter_mw=1e3 * coeffs.phase_shifter_w, phase_shifter_alt_mw=[1e3 * w for w in ps_alt])
    out.start("power")
    for lab, _ in schemes:
        for n in sizes:
            c, ar, b = budgets[(lab, n)]
            rp = al.array_power_report(c, fe, ar, b, coeffs)
            if rp is None:
                out.row("power", scheme=lab, n=n, element_pout_dbm=b.p_elem_dbm, pae_pct=None, pa_mw=None,
                        phase_shifters_mw=None, rest_mw=None, total_mw=None, cap_mcs=None, rate_mbps=None,
                        pj_per_bit=None, pj_per_bit_alt=None)
                continue
            pae = 100 * float(fe.scaled_pa().pae(b.p_elem_dbm))
            alt = [al.array_power_report(c, fe, ar, b, coeffs.with_(phase_shifter_w=w)).pj_per_bit for w in ps_alt]
            pa_w, ps_w = rp.watts("pa"), rp.watts("phase_shifters")
            out.row("power", scheme=lab, n=n, element_pout_dbm=b.p_elem_dbm, pae_pct=pae, pa_mw=1e3 * pa_w,
                    phase_shifters_mw=1e3 * ps_w, rest_mw=1e3 * (rp.total_w - pa_w - ps_w), total_mw=1e3 * rp.total_w,
                    cap_mcs=b.dec_mcs, rate_mbps=rp.bit_rate / 1e6, pj_per_bit=rp.pj_per_bit, pj_per_bit_alt=alt)

    # ---------------------------------------------------------------- 3d. 802.11ay
    ay_cfgs = dict(default_ay_cfgs() if ay_cfgs is None else ay_cfgs)
    if ay_cfgs:
        out.start("ay_operating_points")
    own = {wf: al.ay_operating_obo_db(c) for wf, c in ay_cfgs.items()}
    common = AY_COMMON_MCS
    alone = [(wf, own[wf], al.ay_pa_alone_evm_db(c, fe.obo_db)) for wf, c in ay_cfgs.items()]
    for wf, ob, ev in alone:
        out.row("ay_operating_points", waveform=wf, own_obo_db=ob, pa_alone_evm_at_preset_db=ev,
                common_mcs=common[wf])
    if ay_cfgs:
        out.start("ay")
    cal_cache = {}
    ay_budgets = {}
    for wf, c in ay_cfgs.items():
        for view, ob in (("preset", None), ("own", own[wf])):
            for n in sizes:
                cn = array_frontend(c, n)
                ar = Array60.from_config(cn, fe)
                b = al.ay_array_budget(cn, fe, ar, wf, obo_db=ob, cal_cache=cal_cache)
                ay_budgets[(wf, view, n)] = (cn, ar, b)
                rp = al.array_power_report(cn, fe, ar, b, coeffs)
                rate = None if b.dec_mcs is None else b.rate_by_mcs[b.dec_mcs] / 1e6
                out.row("ay", waveform=wf, point=view, n=n, element_pout_dbm=b.p_elem_dbm, obo_db=b.obo_db,
                        pa_evm_db=b.pa_evm_db, eirp_dbm=b.eirp_dbm, rx_gain_db=b.g_rx_db, floor_db=b.floor_db,
                        cap_mcs=b.dec_mcs, rate_mbps=rate, range_mcs1_m=b.range_by_mcs.get(1),
                        range_common_m=b.range_by_mcs.get(common[wf]), range_cap_m=b.range_by_mcs.get(b.dec_mcs),
                        pj_per_bit=None if rp is None else rp.pj_per_bit,
                        range_common_multipath_m=b.range_multipath_by_mcs.get(common[wf]))
    out.header(cr_rms_delay_ns=spec.value("assumed.cr_rms_delay_ns"),
               ay_ofdm_multipath_margin_db=spec.value("assumed.ay_ofdm_multipath_margin_db"))
    if ay_cfgs:
        out.start("ay_smallest")
    for wf, c in ay_cfgs.items():
        for view, ob in (("preset", fe.obo_db), ("own", own[wf])):
            p_op = float(dc.replace(fe, obo_db=ob).target_pout_dbm())
            n_min = next(n for n in range(1, 257)
                         if p_op + Array60.from_config(array_frontend(c, n), fe).tx_gain_db(0.0, 0.0)[0]
                         >= fe.eirp.avg_dbm)
            cn = array_frontend(c, n_min)
            ar = Array60.from_config(cn, fe)
            b = al.ay_array_budget(cn, fe, ar, wf, obo_db=ob, cal_cache=cal_cache)
            m16 = common[wf]
            rp = (al.array_power_report(cn, fe, ar, dc.replace(b, dec_mcs=m16), coeffs)
                  if m16 in b.range_by_mcs else None)
            pae = float(fe.scaled_pa().pae(b.p_elem_dbm))
            out.row("ay_smallest", waveform=wf, point=view, operating_obo_db=ob, n=n_min,
                    element_pout_dbm=b.p_elem_dbm, pae_pct=100 * pae,
                    pa_mw=1e3 * n_min * 10 ** (b.p_elem_dbm / 10) * 1e-3 / pae,
                    phase_shifters_mw=1e3 * 2 * n_min * coeffs.phase_shifter_w, rx_gain_db=b.g_rx_db,
                    range_mcs1_m=b.range_by_mcs.get(1), range_common_m=b.range_by_mcs.get(m16),
                    pj_per_bit=None if rp is None else rp.pj_per_bit,
                    range_common_multipath_m=b.range_multipath_by_mcs.get(m16))

    # ---------------------------------------------------------------- 4. training
    out.header(training_field=tr["field"], training_estimator=tr["estimator"],
               training_success_within_db=tr["success_within_db"], training_p_target_pct=100 * tr["p_target"])
    out.start("training")
    train = {}
    for lab, cfg in schemes:
        for n in sizes:
            c, ar, b = budgets[(lab, n)]
            n_tones = LinkSim(c, frontend=fe).n_active
            if n == 1:
                out.row("training", scheme=lab, n=n, tones=n_tones, sweep=False, req_tx_db=None, req_rx_db=None,
                        path_loss_txss_db=None, path_loss_rxss_db=None, txss_minus_mcs0_db=None,
                        txss_minus_cap_db=None, sweep_us=None)
                continue
            rt = al.required_training_snr_db(ar, "tx", n_tones, trials=trials, n_users=users)
            rr = al.required_training_snr_db(ar, "rx", n_tones, trials=trials, n_users=users)
            one = float(ar.element_factor_db("rx", 0.0)[0] + ar.element_gain_rx_dbi)
            pl_tx = None if rt["snr_db"] is None else b.eirp_dbm + one - (b.noise_dbm + rt["snr_db"])
            pl_rx = None if rr["snr_db"] is None else b.eirp_dbm + b.g_rx_db - (b.noise_dbm + rr["snr_db"])
            pl0 = None if 0 not in b.sens_by_mcs else b.eirp_dbm + b.g_rx_db - b.sens_by_mcs[0]
            plc = None if b.dec_mcs is None else b.eirp_dbm + b.g_rx_db - b.sens_by_mcs[b.dec_mcs]
            d0 = None if pl_tx is None or pl0 is None else pl_tx - pl0
            dc_ = None if pl_tx is None or plc is None else pl_tx - plc
            t_sw = al.sweep_time_s(ar, c.upclocked(), "tx") + al.sweep_time_s(ar, c.upclocked(), "rx")
            train[(lab, n)] = (rt, rr, d0)
            out.row("training", scheme=lab, n=n, tones=n_tones, sweep=True, req_tx_db=rt["snr_db"],
                    req_rx_db=rr["snr_db"], path_loss_txss_db=pl_tx, path_loss_rxss_db=pl_rx, txss_minus_mcs0_db=d0,
                    txss_minus_cap_db=dc_, sweep_us=1e6 * t_sw)

    # ---------------------------------------------------------------- 4b. repetitions to the MCS0 edge
    rep_cfg = spec.value("assumed.array_training_repetition")
    out.header(max_repetitions=rep_cfg["max_repetitions"], repetition_combining=rep_cfg["combining"])
    out.start("training_repetitions")
    for lab, _ in schemes:
        for n in sizes:
            if n == 1:
                continue
            c, ar, b = budgets[(lab, n)]
            if 0 not in b.sens_by_mcs:
                continue
            n_tones = LinkSim(c, frontend=fe).n_active
            pl0 = b.eirp_dbm + b.g_rx_db - b.sens_by_mcs[0]
            cells = []
            for comb in (rep_cfg["combining"], "coherent"):
                r = al.repetitions_to_reach(b, ar, n_tones, pl0, combining=comb, trials=trials, n_users=users)
                t_tx = None if r["repetitions"] is None else al.sweep_time_s(ar, c.upclocked(), "tx", r["repetitions"])
                cells.append(dict(combining=comb, repetitions=r["repetitions"], req_tx_db=r["req_db"],
                                  txss_minus_mcs0_db=r["margin_db"], tx_sweep_us=None if t_tx is None else 1e6 * t_tx))
            out.row("training_repetitions", scheme=lab, n=n, cells=cells)

    # ---------------------------------------------------------------- 4c. two-stage sweep
    n_h = max(sizes) if two_stage_n is None else int(two_stage_n)
    ms = tuple(int(m) for m in two_stage_m if int(m) < n_h)
    if n_h in sizes and ms:
        out.header(two_stage_n=n_h, two_stage_m=ms)
        out.start("two_stage")
        for lab, cfg in schemes:
            c, _, b = budgets[(lab, n_h)]
            n_tones = LinkSim(c, frontend=fe).n_active
            targets = (("MCS0 edge", b.eirp_dbm + b.g_rx_db - b.sens_by_mcs[0]),
                       ("cap", b.eirp_dbm + b.g_rx_db - b.sens_by_mcs[b.dec_mcs]))
            for tname, tgt in targets:
                for m in ms:
                    h = al.hierarchical_training(cfg, fe, n_h, m, n_tones, tgt, trials=trials, n_users=users)
                    tot = h["hierarchical_time_s"]
                    out.row("two_stage", scheme=lab, target=tname, target_path_loss_db=tgt, m=m,
                            flat=_stage(h["flat"]), wide=_stage(h["wide"]), narrow=_stage(h["narrow"]),
                            two_stage_us=None if tot is None else 1e6 * tot)
    else:
        out.header(two_stage_n=None, two_stage_m=())

    # ---------------------------------------------------------------- 4d. the 802.11ay sector sweep
    if ay_cfgs:
        _ay_sweep(out, fe, sizes, ay_cfgs, ay_budgets, budgets, train, schemes[0][0])
    else:
        out.header(ay_sweep_threshold_db=None, ay_sweep_occupied_bw_ghz=None, ay_waveforms=(),
                   implementation_loss_db=None, be_scheme=schemes[0][0], ssw_frame_us=None, ssw_frame_octets=None,
                   ssw_frame_codewords=None, sbifs_us=None)

    # ---------------------------------------------------------------- 5. squint
    squint_sizes = tuple(int(n) for n in squint_sizes)
    out.header(squint_sizes=squint_sizes)
    out.start("squint")
    for lab, cfg in (default_squint_schemes() if squint_schemes is None else squint_schemes):
        phy = cfg.upclocked()
        f = phy.base.active_tone_indices() * phy.scs_eff
        for n in squint_sizes:
            out.row("squint", **squint_row(lab, cfg, fe, n, f))

    # ---------------------------------------------------------------- 6. sensitivity
    n = None if sensitivity_n is None else int(sensitivity_n)
    if n is None or n == 1 or n not in sizes:
        out.header(sensitivity_scheme=None, sensitivity_n=None, sensitivity_preset_req_tx_db=None)
        return out.data
    lab, cfg = schemes[0]
    c0, ar0, b0 = budgets[(lab, n)]
    n_tones = LinkSim(c0, frontend=fe).n_active
    rt0 = train[(lab, n)][0]
    out.header(sensitivity_scheme=lab, sensitivity_n=n, sensitivity_preset_req_tx_db=rt0["snr_db"])
    out.start("sensitivity")

    def row(name, c, est=None, within=None):
        ar = Array60.from_config(c, fe)
        b = al.array_budget(c, fe, ar)
        th = np.linspace(-ar.scan_max_deg, ar.scan_max_deg, 61)
        q = float(np.mean([ar.quantisation_loss_db("tx", t) for t in th]))
        rt = al.required_training_snr_db(ar, "tx", n_tones, trials=trials, n_users=users, estimator=est,
                                         within_db=within)
        one = float(ar.element_factor_db("rx", 0.0)[0] + ar.element_gain_rx_dbi)
        pl_tx = None if rt["snr_db"] is None else b.eirp_dbm + one - (b.noise_dbm + rt["snr_db"])
        pl0 = b.eirp_dbm + b.g_rx_db - b.sens_by_mcs[0]
        out.row("sensitivity", input=name, tx_gain_db=ar.tx_gain_db(0.0, 0.0)[0], phase_loss_db=q,
                sectors=ar.codebook_deg().size, req_tx_db=rt["snr_db"],
                txss_minus_mcs0_db=None if pl_tx is None else pl_tx - pl0)

    def arr(**kw):
        return dc.replace(c0, frontend=dc.replace(c0.frontend, array=dc.replace(c0.frontend.array, **kw)))

    row("preset", c0)
    row("element factor isotropic", arr(element_pattern="isotropic"))
    for bits in (None, 4, 2, 1):
        row(f"phase shifters {'continuous' if bits is None else f'{bits} bit'}", arr(phase_bits=bits))
    row("no element errors", arr(gain_err_db_rms=0.0, phase_err_deg_rms=0.0))
    row("codebook oversampled x2", arr(sector_oversampling=2.0))
    row("estimator: tones coherently", c0, est="coherent")
    row("success: the best sector only", c0, within=0.0)
    return out.data


__all__ = ["build", "default_frontend", "default_schemes", "default_ay_cfgs", "default_squint_schemes",
           "quick_kwargs", "faces_row", "squint_row", "plain", "SECTIONS", "HEADER_FIELDS", "ROW_FIELDS", "SIZES",
           "SCAN_DEG", "AY_COMMON_MCS", "PHASE_SHIFTER_ALT_W", "FLAT"]
