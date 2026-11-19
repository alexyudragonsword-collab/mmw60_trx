"""The two 802.11ay waveforms on the shared 60 GHz front end, as data.

Example 15's computation (``examples/15_ay_on_the_shared_front_end.py``):
single carrier against OFDM on one front end, at the EVM limits the standard
sets for each — PAPR, each impairment alone, floors and conformance caps,
EVM against back-off, wifitrx's calibration sequence on the ay chain, the
calibrated chains, the residuals item by item, rate against range, and EVM
under multipath.  ``build`` runs all of it and returns one plain dict; the
example only formats that dict, and a graphical interface reads the same
numbers.

The report
----------
``build(...)`` returns ``{section: value}``, the sections in the order they
are computed (``SECTIONS``).  A value is a list of rows (dicts with string
keys) or, for the five sections of ``RECORDS``, one dict.  Everything in it
is a plain Python ``float`` / ``int`` / ``str`` / ``bool`` / ``None``, or a
list or dict of those: ``json.dumps(report, allow_nan=False)`` succeeds.

* a quantity that does not exist is ``None`` (a limit no back-off on the
  grid meets, a distance where the floor alone exceeds the threshold, an MCS
  without a DMG twin);
* a number that is not finite is the string Python prints for it
  (``"nan"``, ``"inf"``, ``"-inf"``; JSON has none of them);
* a code rate is the string the tables write (``"13/16"``);
* units are in the field names: ``_db``, ``_dbm``, ``_dbc``, ``_dbi``,
  ``_hz``, ``_bps``, ``_m``, ``_ns``.

``header`` carries the settings the headings and footnotes quote (the front
end, the grids, the spec values and the ``source`` tag of every spec key the
text names), so a consumer needs no spec lookup of its own.

Progress
--------
``progress(section, None)`` is called when a section starts, then
``progress(section, row)`` after each of its rows is in the report (a record
section calls it once, with the record).  Sections do not interleave.  The
rows are the report's own objects: a consumer must not change them.

Order
-----
The packets come from seeded generators and the chains carry state (the AGC
ladder, the VGA trim, one calibration run per back-off, shared by every
payload at that back-off).  The sections run in the example's order, and
nothing inside one may be reordered without proving the numbers stay put
(``examples/expected/15_ay_on_the_shared_front_end.txt``).

Every link is built from the two configs ``build`` is given (``cfgs``, one
per waveform; ``default_cfgs()`` are the presets): another MCS or GI of a
waveform is that config with ``ay.mcs`` / ``ay.gi`` changed (``at_mcs``),
never a preset called anew, so a caller's modified front end, LO or crystals
reach every row.
"""
from __future__ import annotations

import copy
import dataclasses as dc
import math
from fractions import Fraction

import numpy as np

from .. import ENGINE_BANNER, __version__, spec
from .. import arraylink as al
from ..calcheck import run_cal_ay
from ..config import ChannelConfig, ay_60ghz, unspecified_antenna, wifi7_rx_ladder
from ..frontend import Frontend60
from ..sim.link import DIGITAL_DRIVE_RMS, LinkSim
from . import edmg, papr

#: the sections of the report, in the order they are computed
SECTIONS = ("header", "numbers", "papr", "impairments_alone", "floors", "caps", "evm_vs_backoff", "backoff_per_mcs",
            "same_modulation", "best_rate_at_pout", "calibration", "calibrated_floors", "calibrated_caps",
            "calibrated_evm_vs_backoff", "one_calibration_reused", "same_modulation_calibrated", "residuals",
            "range_evm_vs_backoff", "rate_vs_range", "link_budget", "fastest_rate_at_distance",
            "multipath_same_modulation", "sensitivity_rows", "threshold_comparison", "multipath_evm")
#: the sections that are one dict; every other one is a list of rows
RECORDS = ("header", "numbers", "calibration", "one_calibration_reused", "link_budget")

#: the order the comparison runs the waveforms in (the MCS tables run in ``edmg.WAVEFORMS`` order)
WAVEFORMS = ("ay_sc", "ay_ofdm")
#: the MCS the two preset configs carry (``default_cfgs``)
PRESET_MCS = {"ay_sc": 16, "ay_ofdm": 15}
FLAT = ChannelConfig(model="flat")
#: one MCS per payload constellation (the EVM payload carries its points; assumed.ay_evm_payload)
SC_REP = {"π/2-BPSK": 6, "π/2-QPSK": 11, "π/2-16-QAM": 16, "π/2-64-QAM": 21}
OFDM_REP = {"QPSK points (DCM BPSK)": 5, "16-QAM points (DCM QPSK)": 10, "16-QAM": 15, "64-QAM": 20}
REPS = {"ay_sc": SC_REP, "ay_ofdm": OFDM_REP}
#: the 16-QAM payload of each waveform (sections 8, 8b and 10)
QAM16 = {"ay_sc": SC_REP["π/2-16-QAM"], "ay_ofdm": OFDM_REP["16-QAM"]}
#: the back-off grid of section 6 (the output-power table), dB from Psat
POUT_BACKOFFS_DB = tuple(float(v) for v in np.arange(1.0, 15.01, 1.0))
#: the back-off section 8 runs the preset's calibration at, and section 8b's second operating point
REUSE_BACKOFF_DB = 15.0
#: the calibration residuals of section 8b, each kept alone on the stripped chain
RESIDUAL_ITEMS = {"tx_iq": "TX IQ", "tx_leak": "TX LO leak", "rx_iq": "RX IQ", "rx_dc": "RX DC"}
#: where section 8b reads the TX image rejection
IMAGE_FREQS_HZ = (0.5e9, 0.86e9, 1.0e9, 1.1e9)
#: the distances of section 9's second table
DISTANCES_M = (1.0, 1.5, 2.0, 3.0, 5.0, 8.0)
#: SC / OFDM MCS pairs of the same modulation and code rate where OFDM's is a DCM one (section 9's third table
#: puts them ahead of ``matched_pairs()``)
DCM_PAIRS = ((7, 6), (9, 8), (11, 10))
#: the comparison table's calibrated caps: section 9's sensitivity rows are read for these
SENSITIVITY_MCS = {"ay_sc": 14, "ay_ofdm": 13}
#: section 9's last table: label, waveform, EDMG MCS, the 11be MCS of the same modulation and code rate
THRESHOLD_ROWS = (("BPSK 1/2", "ay_sc", 2, None), ("QPSK 1/2", "ay_sc", 7, 1), ("QPSK 1/2", "ay_ofdm", 6, 1),
                  ("16-QAM 1/2", "ay_sc", 12, 3), ("16-QAM 1/2", "ay_ofdm", 11, 3), ("16-QAM 3/4", "ay_sc", 14, 4),
                  ("16-QAM 3/4", "ay_ofdm", 13, 4), ("16-QAM 13/16", "ay_sc", 15, None),
                  ("64-QAM 3/4", "ay_sc", 19, 6), ("64-QAM 7/8", "ay_sc", 21, None))
#: the in-band SNRs of section 10 (None = no noise) and the one its last column compares with the flat channel at
MULTIPATH_SNRS_DB = (None, 20.0, 12.0)
MULTIPATH_COMPARE_SNR_DB = 12.0
#: the spec keys the example's text names: ``header["sources"]`` holds the ``source`` tag of each
SOURCE_KEYS = ("edmg.ofdm_params", "edmg.ofdm_pilot_tones_ncb1", "edmg.sc_params", "edmg.sc_rate_mbps",
               "edmg.ofdm_rate_mbps", "edmg.sc_mcs", "edmg.ofdm_mcs", "assumed.ay_sc_pulse", "assumed.lo_leak_dbc",
               "assumed.iq_mismatch", "assumed.ay_receiver", "assumed.ay_cal_probe", "assumed.ay_ofdm_tone_order",
               "assumed.ay_sensitivity", "assumed.ay_ofdm_multipath_margin_db", "assumed.cr_rms_delay_ns")


# ---------------------------------------------------------------- the defaults
def default_cfgs() -> dict:
    """The two preset configs, one per waveform: what example 15 runs."""
    return {wf: ay_60ghz(wf, m) for wf, m in PRESET_MCS.items()}


def default_frontend(cfgs: dict | None = None) -> Frontend60:
    """The one front end both waveforms run on (iron rule 2), built from the single-carrier config."""
    return Frontend60.from_config((default_cfgs() if cfgs is None else cfgs)["ay_sc"])


def multipath_rows(cr: ChannelConfig | None = None) -> tuple:
    """Section 10's rows: label, channel, options (``gi``, ``sc_equalizer``).  ``cr`` is the CR stand-in
    (default: ``ChannelConfig()``, data/spec: assumed.cr_rms_delay_ns / cr_los_k_db)."""
    cr = ChannelConfig() if cr is None else cr
    return (("flat", FLAT, {}), ("CR 7 ns", cr, {}), ("CR 15 ns", dc.replace(cr, rms_delay_ns=15.0), {}),
            ("CR 15 ns, long GI", dc.replace(cr, rms_delay_ns=15.0), {"gi": "long"}),
            ("CR 7 ns, zero forcing", cr, {"sc_equalizer": "zf"}))


# ---------------------------------------------------------------- pure helpers
def plain(x):
    """``x`` as JSON-safe plain Python: numpy scalars and arrays become ``int`` / ``float`` / ``bool`` /
    lists, tuples lists, a ``Fraction`` its string, dict keys strings, and a float that is not finite the
    string Python prints for it (``"nan"``, ``"inf"``, ``"-inf"``)."""
    if x is None or isinstance(x, (str, bool)):
        return x
    if isinstance(x, np.bool_):
        return bool(x)
    if isinstance(x, (int, np.integer)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        v = float(x)
        return v if math.isfinite(v) else str(v)
    if isinstance(x, Fraction):
        return str(x)
    if isinstance(x, dict):
        return {str(k): plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, np.ndarray)):
        return [plain(v) for v in x]
    raise TypeError(f"no plain form for {type(x).__name__}: {x!r}")


def at_mcs(cfg, mcs: int, gi: str | None = None):
    """``cfg`` carrying another EDMG MCS (and GI) of its waveform; everything else as it is.  On a preset
    this is the preset of that MCS, label included: ``at_mcs(ay_60ghz(wf, a), b) == ay_60ghz(wf, b)``."""
    a = cfg.ay
    gi = a.gi if gi is None else gi
    label = cfg.label.replace(f"MCS{a.mcs} {a.gi} GI", f"MCS{int(mcs)} {gi} GI")
    return dc.replace(cfg, ay=dc.replace(a, mcs=int(mcs), gi=gi), label=label)


def at_backoff(cfg, obo_db: float):
    """``cfg`` with the PA at another back-off."""
    return dc.replace(cfg, frontend=dc.replace(cfg.frontend, pa=dc.replace(cfg.frontend.pa, obo_db=float(obo_db))))


def calibrated_away(cfg):
    """``cfg`` with the IQ mismatch and the TX LO leakage off: what a calibration is taken to remove
    (section 4's shortcut; section 8 runs the sequence instead)."""
    fe = cfg.frontend
    return dc.replace(cfg, frontend=dc.replace(fe, iq=dc.replace(fe.iq, enabled=False), lo_leak_dbc=None))


def crossing_backoff_db(backoffs_db, evms_db, limit_db: float) -> float | None:
    """Smallest back-off on the grid where the EVM curve reaches ``limit_db`` (linear in dB between
    points); None when it never does."""
    o, e = np.asarray(backoffs_db, float), np.asarray(evms_db, float)
    if e[0] <= limit_db:
        return float(o[0])
    for i in range(1, o.size):
        if e[i - 1] > limit_db >= e[i]:
            return float(o[i - 1] + (e[i - 1] - limit_db) / (e[i - 1] - e[i]) * (o[i] - o[i - 1]))
    return None


def matched_pairs() -> list:
    """(SC MCS, OFDM MCS) of the same modulation and code rate, 16-QAM and up, OFDM's DCM ones left out."""
    return [(sm, om) for sm in range(12, 22) for om in range(11, 21)
            if edmg.mcs_entry("ay_sc", sm).order == edmg.mcs_entry("ay_ofdm", om).order
            and edmg.mcs_entry("ay_sc", sm).code_rate == edmg.mcs_entry("ay_ofdm", om).code_rate
            and edmg.mcs_entry("ay_ofdm", om).modulation[:3] != "DCM"]


def best_passing_mcs(waveform: str, floor_of_order, gi: str = "normal"):
    """The conformance cap: of the MCS whose TX EVM limit the floor of their payload's constellation
    meets (``floor_of_order(tone_order)`` at or under the limit), the one with the highest rate; None
    when none passes."""
    ok = [e for e in edmg.mcs_table(waveform) if floor_of_order(e.tone_order) <= e.evm_limit_db]
    if not ok:
        return None
    return max(ok, key=lambda e: (e.rate_bps(gi), e.mcs))


def mean_evm_db(sim, n: int, snr_db: float | None = None, seed: int = 0) -> float:
    """EVM over ``n`` packets of ``sim`` from one generator, averaged as powers."""
    rng = np.random.default_rng(seed)
    e = [sim.packet(snr_db, rng).rx.evm_db for _ in range(n)]
    return float(10 * np.log10(np.mean(10 ** (np.asarray(e) / 10))))


def numbers(cfgs: dict | None = None) -> dict:
    """Section 1: the EDMG single-channel numerology of the configs' channel and GI and the two MCS
    tables with their rates and TX EVM limits, as read from spec_sources (no simulation)."""
    cfg = (default_cfgs() if cfgs is None else cfgs)["ay_sc"]
    ch, gi = edmg.channel_of(cfg.carrier_hz), cfg.ay.gi
    o, s = edmg.ofdm_numerology(ch, gi), edmg.sc_numerology(gi)
    return plain({
        "channel": ch, "gi": gi,
        "ofdm": {"fs_hz": o.fs_hz, "n_fft": o.n_fft, "scs_hz": o.scs_hz, "data_tones": len(o.data_tones),
                 "pilot_tones": len(o.pilot_tones), "max_tone": max(o.used_tones), "gi_samples": o.cp,
                 "pilots": list(o.pilot_tones)},
        "sc": {"fs_hz": s.fs_hz, "block_chips": s.block, "gi_chips": s.guard,
               "data_chips_per_block": s.data_per_block},
        "mcs": [{"waveform": wf, "mcs": e.mcs, "modulation": e.modulation, "code_rate": e.code_rate,
                 "rate_bps": e.rate_bps(gi), "evm_limit_db": e.evm_limit_db, "order": e.order,
                 "tone_order": e.tone_order, "repetition": e.repetition}
                for wf in edmg.WAVEFORMS for e in edmg.mcs_table(wf)]})


def _cap_row(chain: str, waveform: str, best, gi: str) -> dict:
    if best is None:
        return {"chain": chain, "waveform": waveform, "mcs": None, "modulation": None, "code_rate": None,
                "evm_limit_db": None, "rate_bps": None}
    return {"chain": chain, "waveform": waveform, "mcs": best.mcs, "modulation": best.modulation,
            "code_rate": best.code_rate, "evm_limit_db": best.evm_limit_db, "rate_bps": best.rate_bps(gi)}


# ---------------------------------------------------------------- section 8b's chain surgery
def _stripped_evm_db(cfg, fe, run, keep, n: int) -> float:
    """EVM on the calibrated chains with converters, phase noise, receiver noise and the PA off (the PA
    after the VGA was trimmed with it in) and of the four calibration residuals only those in ``keep``."""
    tx, rx = copy.deepcopy(run.chains[:2])
    tx.params.dac.enabled = False
    tx.params.lo.enabled = False
    rx.params.adc.enabled = False
    rx.params.lo.enabled = False
    rx.noise_enabled = False
    rx.params.nonlin_enabled = False
    if "tx_iq" not in keep:
        tx.params.iq.enabled, tx.w1, tx.w2 = False, None, None
    if "tx_leak" not in keep:
        tx.params.lo_leak_dbm, tx.dc_pre = None, 0j
    if "rx_iq" not in keep:
        rx.params.iq.enabled, rx.w1, rx.w2, rx.w2_by_state, rx.frac_delay_iq = False, None, None, {}, 0.0
    if "rx_dc" not in keep:
        rx.params.dc_offset, rx.dc_ana, rx.dc_post = tuple(0j for _ in rx.params.dc_offset), {}, {}
    sim = LinkSim(cfg, frontend=fe, chains=[tx, rx])
    sim.tx.params.pa_enabled = False          # after the VGA trim: dc_pre holds at that gain state only
    return mean_evm_db(sim, n)


def _exact_dc_pre(tx) -> complex:
    """The dc_pre that cancels the TX LO leak exactly at this gain state (the chain is linear in it
    from the digital input to the modulator output; solved with the PA, LO and DAC out of the way)."""
    def dc_out(d):
        t = copy.deepcopy(tx)
        t.dc_pre, t.params.pa_enabled, t.params.lo.enabled, t.params.dac.enabled = d, False, False, False
        return complex(np.mean(t(np.zeros(4000, complex))[-1000:]))
    b0 = dc_out(0j)
    a1, aj = dc_out(1e-2) - b0, dc_out(1e-2j) - b0
    sol = np.linalg.solve(np.array([[a1.real, aj.real], [a1.imag, aj.imag]]) / 1e-2, [-b0.real, -b0.imag])
    return complex(sol[0], sol[1])


def _evm_with_dc_pre_db(cfg, fe, run, exact: bool, n: int) -> float:
    """EVM on the whole calibrated chain, with the sequence's dc_pre or with the one solved to cancel
    the leak exactly."""
    tx, rx = copy.deepcopy(run.chains[:2])
    sim = LinkSim(cfg, frontend=fe, chains=[tx, rx])
    if exact:
        sim.tx.dc_pre = _exact_dc_pre(sim.tx)
    return mean_evm_db(sim, n)


def _image_rejection_db(tx, fs: float, f_hz: float, n: int = 8192) -> float:
    t = copy.deepcopy(tx)
    t.params.lo_leak_dbm, t.dc_pre, t.params.pa_enabled, t.params.lo.enabled = None, 0j, False, False
    k = int(round(f_hz / fs * n))
    y = np.fft.fft(t(0.05 * np.exp(2j * np.pi * k * np.arange(n) / n)))
    return float(10 * np.log10(abs(y[k]) ** 2 / max(abs(y[-k]) ** 2, 1e-30)))


# ---------------------------------------------------------------- the run
class _Build:
    """One run of the report: the state the sections share, and one method per group of sections, called
    in order by ``build``."""

    def __init__(self, fe, cfgs, quick, progress, packets, backoffs_db, low_backoffs_db, rolloffs,
                 multipath_packets):
        self.fe, self.cfgs, self.quick, self.progress = fe, cfgs, bool(quick), progress
        self.gi = cfgs["ay_sc"].ay.gi
        self.psat = fe.psat_dbm
        self.n_pk = (1 if quick else 2) if packets is None else int(packets)
        self.obos = (np.arange(1.0, 15.01, 2.0 if quick else 0.5) if backoffs_db is None
                     else np.asarray(backoffs_db, float))
        # the range table's own grid: sections 5 and 8 start at 1 dB; four points under it show where the
        # low-order MCS really peak (asked back-offs; the PA lands where it can, and the table uses that)
        self.low = ((np.array([0.0, 0.25, 0.5, 0.75]) if not quick else np.array([0.0]))
                    if low_backoffs_db is None else np.asarray(low_backoffs_db, float))
        self.rolloffs = (((0.25,) if quick else (0.15, 0.25, 0.35)) if rolloffs is None
                         else tuple(float(r) for r in rolloffs))
        self.n_mp = (4 if quick else 40) if multipath_packets is None else int(multipath_packets)
        self.rep = {}
        self.floors = {"raw": {}, "cal": {}}      # section 4, by (waveform, tone order)
        self.need = {}                            # section 5: the back-off each (waveform, MCS) limit needs
        self.pairs = []
        self.run = None                           # section 7's calibration, at the preset back-off
        self.runs = {}                            # back-off -> (front end, calibration run)
        self.landed = {}                          # (waveform, tone order, asked back-off) -> PA output, dBm
        self.cal_curves = {}                      # (waveform, tone order) -> EVM on the calibrated chains

    # ------------------------------------------------------------ the report and its progress
    def _start(self, section: str) -> None:
        self.rep[section] = None if section in RECORDS else []
        if self.progress is not None:
            self.progress(section, None)

    def _row(self, section: str, row: dict) -> dict:
        row = plain(row)
        if section in RECORDS:
            self.rep[section] = row
        else:
            self.rep[section].append(row)
        if self.progress is not None:
            self.progress(section, row)
        return row

    # ------------------------------------------------------------ links
    def cfg(self, wf: str, mcs: int, gi: str | None = None):
        return at_mcs(self.cfgs[wf], mcs, gi)

    def flat(self, wf: str, mcs: int):
        return dc.replace(self.cfg(wf, mcs), channel=FLAT)

    def evm(self, cfg, fe=None, n: int = 2, seed: int = 0) -> float:
        return mean_evm_db(LinkSim(cfg, frontend=fe), n, seed=seed)

    def cal_at(self, obo):
        """The sequence run on fresh chains with the PA at this back-off (one run per back-off, shared by
        both waveforms: the same chain, the same PA target)."""
        if obo not in self.runs:
            c = at_backoff(self.cfgs["ay_sc"], obo)
            f2 = Frontend60.from_config(c)
            self.runs[obo] = (f2, run_cal_ay(f2, c))
        return self.runs[obo]

    def cal_evm(self, cfg, obo=None, n=None, single=False) -> float:
        n = self.n_pk if n is None else n
        if obo is None:
            c, f2, r = cfg, self.fe, self.run
        elif single:                                     # calibrated at the preset back-off only, drive re-trimmed
            c = at_backoff(cfg, obo)
            f2, r = Frontend60.from_config(c), self.run
        else:
            c = at_backoff(cfg, obo)
            f2, r = self.cal_at(obo)
        sim = LinkSim(c, frontend=f2, chains=copy.deepcopy(r.chains[:2]))
        if obo is not None and not single:
            # where the PA landed: the VGA cannot put the average output closer to Psat than about 0.25 dB
            self.landed[(c.waveform, sim.mcs.tone_order, round(float(obo), 3))] = float(sim.pout_dbm)
        return mean_evm_db(sim, n)

    # ------------------------------------------------------------ header
    def header(self) -> None:
        self._start("header")
        b, fe = self.cfgs["ay_sc"], self.fe
        cr = edmg.chain_rate()
        mp = ChannelConfig()
        sc_fs = edmg.sc_numerology().fs_hz
        self._row("header", {
            "engine": ENGINE_BANNER, "version": __version__, "quick": self.quick,
            "channel": edmg.channel_of(b.carrier_hz), "carrier_hz": b.carrier_hz, "gi": self.gi,
            "presets": {wf: {"mcs": self.cfgs[wf].ay.mcs,
                             "modulation": edmg.mcs_entry(wf, self.cfgs[wf].ay.mcs).modulation,
                             "label": self.cfgs[wf].label} for wf in WAVEFORMS},
            "psat_dbm": fe.psat_dbm, "preset_backoff_db": fe.obo_db, "backoff_reference": fe.obo_reference,
            "pout_dbm": fe.target_pout_dbm(), "chain_fs_hz": cr["fs_hz"],
            "channel_spacing_hz": edmg.channel_spacing_hz(), "cfo_hz": b.cfo_hz,
            "tx_antenna_gain_dbi": fe.antenna_gain_tx_dbi, "rx_antenna_gain_dbi": fe.antenna_gain_rx_resolved_dbi,
            "tx_lo_leak_dbc": fe.lo.tx_leak_dbc,
            # the sizes of the run
            "packets_per_point": self.n_pk, "multipath_packets": self.n_mp,
            "backoff_grid_db": self.obos, "low_backoffs_db": self.low, "rolloffs": self.rolloffs,
            "pout_backoffs_db": POUT_BACKOFFS_DB, "reuse_backoff_db": REUSE_BACKOFF_DB,
            "image_freqs_hz": IMAGE_FREQS_HZ, "distances_m": DISTANCES_M, "sensitivity_mcs": SENSITIVITY_MCS,
            # spec values the text quotes
            "sc_rolloff_assumed": spec.value("assumed.ay_sc_pulse")["rolloff"],
            "ofdm_multipath_margin_db": float(spec.value("assumed.ay_ofdm_multipath_margin_db")),
            "gi_ns": {gi: edmg.sc_numerology(gi).guard / sc_fs * 1e9 for gi in ("normal", "long")},
            "multipath_channel": {"rms_delay_ns": mp.rms_delay_ns, "los_k_db": mp.los_k_db},
            "multipath_snrs_db": MULTIPATH_SNRS_DB, "multipath_compare_snr_db": MULTIPATH_COMPARE_SNR_DB,
            "sources": {k: spec.survey(k).source for k in SOURCE_KEYS}})

    # ------------------------------------------------------------ 1. the numbers
    def numbers(self) -> None:
        self._start("numbers")
        self._row("numbers", numbers(self.cfgs))

    # ------------------------------------------------------------ 2. PAPR
    def papr(self) -> None:
        self._start("papr")
        for label, m in OFDM_REP.items():
            sim = LinkSim(dc.replace(self.cfg("ay_ofdm", m).ideal(), channel=FLAT))
            ref, frame = sim.transmit(np.random.default_rng(1))
            x = frame.x[(ref.stf_len + ref.cef_len) * sim.phy.up:]
            self._row("papr", {"waveform": "ay_ofdm", "payload": label, "mcs": m, "rolloff": None,
                               "papr_1e3_db": papr.papr_db(x, 1e-3), "papr_1e4_db": papr.papr_db(x, 1e-4)})
        for ro in self.rolloffs:
            for label, m in SC_REP.items():
                c = dc.replace(self.cfg("ay_sc", m).ideal(), channel=FLAT)
                c = dc.replace(c, ay=dc.replace(c.ay, sc_rolloff=ro))
                sim = LinkSim(c)
                ref, frame = sim.transmit(np.random.default_rng(1))
                x = frame.x[(ref.stf_len + ref.cef_len) * sim.phy.up:-len(sim.taps)]
                self._row("papr", {"waveform": "ay_sc", "payload": label, "mcs": m, "rolloff": ro,
                                   "papr_1e3_db": papr.papr_db(x, 1e-3), "papr_1e4_db": papr.papr_db(x, 1e-4)})

    # ------------------------------------------------------------ 3. isolation
    def impairments_alone(self) -> None:
        self._start("impairments_alone")
        iso = {}
        for wf in WAVEFORMS:
            flat = dc.replace(self.cfgs[wf], channel=FLAT)
            ideal = flat.ideal()
            f = flat.frontend
            variants = {
                "ideal chain": ideal,
                "PA": dc.replace(ideal, frontend=dc.replace(ideal.frontend, pa=f.pa)),
                "phase noise": dc.replace(ideal, lo=flat.lo),
                "CFO (estimated)": dc.replace(ideal, xo_ppm_tx=flat.xo_ppm_tx, xo_ppm_rx=flat.xo_ppm_rx),
                "converters": dc.replace(ideal, frontend=dc.replace(ideal.frontend, converters=f.converters)),
                "IQ mismatch (raw)": dc.replace(ideal, frontend=dc.replace(ideal.frontend, iq=f.iq)),
                "TX LO leakage (raw), no CFO": dc.replace(ideal, frontend=dc.replace(ideal.frontend,
                                                                                    lo_leak_dbc=f.lo_leak_dbc)),
                "TX LO leakage (raw) + CFO": dc.replace(ideal, xo_ppm_tx=flat.xo_ppm_tx, xo_ppm_rx=flat.xo_ppm_rx,
                                                         frontend=dc.replace(ideal.frontend,
                                                                             lo_leak_dbc=f.lo_leak_dbc)),
                "RX DC + CFO": dc.replace(ideal, xo_ppm_tx=flat.xo_ppm_tx, xo_ppm_rx=flat.xo_ppm_rx,
                                          frontend=dc.replace(ideal.frontend, rx_dc_dbc=f.rx_dc_dbc)),
            }
            if wf == "ay_sc":
                variants["phase noise, one phase per block"] = dc.replace(ideal, lo=flat.lo,
                                                                          ay=dc.replace(ideal.ay, sc_phase="block"))
            iso[wf] = {k: self.evm(v, n=self.n_pk) for k, v in variants.items()}
        for k in iso["ay_sc"]:
            self._row("impairments_alone", {"impairment": k, "ay_sc_evm_db": iso["ay_sc"][k],
                                            "ay_ofdm_evm_db": iso["ay_ofdm"].get(k)})

    # ------------------------------------------------------------ 4. floors and caps at the preset back-off
    def floors_and_caps(self) -> None:
        self._start("floors")
        floors = self.floors
        for wf, rep in REPS.items():
            for label, m in rep.items():
                cfg = self.flat(wf, m)
                e = edmg.mcs_entry(wf, m)
                floors["raw"][(wf, e.tone_order)] = self.evm(cfg, self.fe, n=self.n_pk)
                floors["cal"][(wf, e.tone_order)] = self.evm(calibrated_away(cfg), n=self.n_pk)
                self._row("floors", {"waveform": wf, "payload": label, "mcs": m, "tone_order": e.tone_order,
                                     "raw_evm_db": floors["raw"][(wf, e.tone_order)],
                                     "calibrated_away_evm_db": floors["cal"][(wf, e.tone_order)]})
        self._start("caps")
        for which in ("raw", "cal"):
            for wf in edmg.WAVEFORMS:
                best = best_passing_mcs(wf, lambda order: floors[which][(wf, order)], self.gi)
                self._row("caps", _cap_row("raw" if which == "raw" else "calibrated_away", wf, best, self.gi))

    # ------------------------------------------------------------ 5. back-off per MCS limit
    def backoff(self) -> None:
        obos = self.obos
        self._start("evm_vs_backoff")
        curves = {}
        for wf, rep in REPS.items():
            for label, m in rep.items():
                cfg = calibrated_away(self.flat(wf, m))
                curves[(wf, edmg.mcs_entry(wf, m).tone_order)] = [self.evm(at_backoff(cfg, ob), n=1) for ob in obos]
        # a row reads its constellation's curve as the table of the limits below does: two payloads of one
        # waveform with the same points per tone (OFDM's DCM QPSK and 16-QAM) share the one run last
        for wf, rep in REPS.items():
            for label, m in rep.items():
                order = edmg.mcs_entry(wf, m).tone_order
                self._row("evm_vs_backoff", {"waveform": wf, "payload": label, "mcs": m, "tone_order": order,
                                             "backoff_db": obos, "evm_db": curves[(wf, order)]})
        self._start("backoff_per_mcs")
        need = self.need
        for wf in edmg.WAVEFORMS:
            for e in edmg.mcs_table(wf):
                need[(wf, e.mcs)] = crossing_backoff_db(obos, curves[(wf, e.tone_order)], e.evm_limit_db)
        for wf in edmg.WAVEFORMS:
            for e in edmg.mcs_table(wf):
                ob = need[(wf, e.mcs)]
                self._row("backoff_per_mcs", {
                    "waveform": wf, "mcs": e.mcs, "modulation": e.modulation, "code_rate": e.code_rate,
                    "rate_bps": e.rate_bps(self.gi), "evm_limit_db": e.evm_limit_db, "backoff_db": ob,
                    "pout_dbm": None if ob is None else self.psat - ob})
        self._start("same_modulation")
        self.pairs = matched_pairs()
        for sm, om in self.pairs:
            es, eo = edmg.mcs_entry("ay_sc", sm), edmg.mcs_entry("ay_ofdm", om)
            bs, bo = need[("ay_sc", sm)], need[("ay_ofdm", om)]
            dp = None if bs is None or bo is None else bo - bs
            self._row("same_modulation", {
                "modulation": eo.modulation, "code_rate": es.code_rate, "sc_mcs": sm,
                "sc_evm_limit_db": es.evm_limit_db, "sc_backoff_db": bs, "ofdm_mcs": om,
                "ofdm_evm_limit_db": eo.evm_limit_db, "ofdm_backoff_db": bo, "delta_pout_db": dp,
                "rate_ratio": es.rate_bps(self.gi) / eo.rate_bps(self.gi)})

    # ------------------------------------------------------------ 6. rate at each output power
    def best_rate_at_pout(self) -> None:
        self._start("best_rate_at_pout")
        need = self.need
        for ob in np.arange(1.0, 15.01, 1.0):
            row = {"pout_dbm": self.psat - ob, "backoff_db": ob}
            for wf in WAVEFORMS:
                ok = [e for e in edmg.mcs_table(wf)
                      if need[(wf, e.mcs)] is not None and need[(wf, e.mcs)] <= ob + 1e-9]
                best = max(ok, key=lambda e: e.rate_bps(self.gi)) if ok else None
                row[f"{wf[3:]}_rate_bps"] = None if best is None else best.rate_bps(self.gi)
                row[f"{wf[3:]}_mcs"] = None if best is None else best.mcs
            self._row("best_rate_at_pout", row)

    # ------------------------------------------------------------ 7. calibration on the ay chain
    def calibration(self) -> None:
        self._start("calibration")
        self.run = run = run_cal_ay(self.fe, self.cfgs["ay_sc"])
        v = run.final_views
        self._row("calibration", {
            "probe": run.waveform, "backoff_db": self.fe.obo_db,
            "steps": [{"step": r.step, "status": r.status, "metric": r.metric, "value": r.value,
                       "passed": None if r.passed is None else bool(r.passed), "detail": str(r.detail)}
                      for r in run.rows],
            "final": {"isolation_evm_db": run.evm_after_db, "modem_evm_db": v.get("evm_modem_db", np.nan),
                      "tx_modem_evm_db": v.get("tx_evm_modem_db", np.nan),
                      "rx_modem_evm_db": v.get("rx_evm_modem_db", np.nan), "pout_dbm": run.pout_dbm}})

    # ------------------------------------------------------------ 8. on the calibrated chains
    def calibrated(self) -> None:
        fe, floors = self.fe, self.floors
        self._start("calibrated_floors")
        cal_floor = {}
        for wf, rep in REPS.items():
            for label, m in rep.items():
                e = edmg.mcs_entry(wf, m)
                cal_floor[(wf, e.tone_order)] = self.cal_evm(self.flat(wf, m))
                self._row("calibrated_floors", {
                    "waveform": wf, "payload": label, "mcs": m, "tone_order": e.tone_order,
                    "calibrated_evm_db": cal_floor[(wf, e.tone_order)],
                    "raw_evm_db": floors["raw"][(wf, e.tone_order)],
                    "calibrated_away_evm_db": floors["cal"][(wf, e.tone_order)]})
        self._start("calibrated_caps")
        for wf in edmg.WAVEFORMS:
            best = best_passing_mcs(wf, lambda order: cal_floor[(wf, order)], self.gi)
            self._row("calibrated_caps", _cap_row("calibrated", wf, best, self.gi))
        self._start("calibrated_evm_vs_backoff")
        obos8 = self.obos
        sub = {("ay_sc", 16): SC_REP["π/2-16-QAM"], ("ay_sc", 64): SC_REP["π/2-64-QAM"],
               ("ay_ofdm", 16): OFDM_REP["16-QAM"], ("ay_ofdm", 64): OFDM_REP["64-QAM"]}
        cal_curves = self.cal_curves
        for key, m in sub.items():
            cal_curves[key] = [self.cal_evm(self.flat(key[0], m), ob, n=1) for ob in obos8]
            self._row("calibrated_evm_vs_backoff", {
                "waveform": key[0], "mcs": m, "tone_order": key[1], "backoff_db": obos8,
                "pout_dbm": [self.landed[(key[0], key[1], round(float(ob), 3))] for ob in obos8],
                "evm_db": cal_curves[key]})
        self._start("one_calibration_reused")
        m16 = SC_REP["π/2-16-QAM"]
        one = self.flat("ay_sc", m16)
        leak_on = self.cal_evm(one, REUSE_BACKOFF_DB, single=True)
        leak_off = self.cal_evm(dc.replace(one, xo_ppm_tx=0.0, xo_ppm_rx=0.0), REUSE_BACKOFF_DB, single=True)
        there = self.cal_evm(one, REUSE_BACKOFF_DB)
        self._row("one_calibration_reused", {
            "calibrated_at_backoff_db": fe.obo_db, "run_at_backoff_db": REUSE_BACKOFF_DB, "waveform": "ay_sc",
            "mcs": m16, "payload": "π/2-16-QAM", "evm_db": leak_on, "evm_without_cfo_db": leak_off,
            "evm_calibrated_there_db": there})
        self._start("same_modulation_calibrated")
        need = self.need
        for sm, om in self.pairs:
            es, eo = edmg.mcs_entry("ay_sc", sm), edmg.mcs_entry("ay_ofdm", om)
            bs = crossing_backoff_db(obos8, cal_curves[("ay_sc", es.tone_order)], es.evm_limit_db)
            bo = crossing_backoff_db(obos8, cal_curves[("ay_ofdm", eo.tone_order)], eo.evm_limit_db)
            dp = None if bs is None or bo is None else bo - bs
            b5s, b5o = need[("ay_sc", sm)], need[("ay_ofdm", om)]
            d5 = None if b5s is None or b5o is None else b5o - b5s
            self._row("same_modulation_calibrated", {
                "modulation": eo.modulation, "code_rate": es.code_rate, "sc_mcs": sm, "ofdm_mcs": om,
                "sc_backoff_db": bs, "ofdm_backoff_db": bo, "delta_pout_db": dp, "delta_pout_section5_db": d5})

    # ------------------------------------------------------------ 8b. the residual, item by item
    def residuals(self) -> None:
        self._start("residuals")
        fe, n_pk = self.fe, self.n_pk
        for ob in (fe.obo_db, REUSE_BACKOFF_DB):
            f2, r = self.cal_at(ob)
            per_wf = []
            for wf, m in QAM16.items():
                c = at_backoff(self.flat(wf, m), ob)
                alone = {k: _stripped_evm_db(c, f2, r, (k,), n_pk) for k in RESIDUAL_ITEMS}
                base_e = _stripped_evm_db(c, f2, r, (), n_pk)
                no_cfo = _stripped_evm_db(dc.replace(c, xo_ppm_tx=0.0, xo_ppm_rx=0.0), f2, r, ("tx_leak",), n_pk)
                no_rm = _stripped_evm_db(dc.replace(c, rx=dc.replace(c.rx, dc_removal=False)), f2, r, ("tx_leak",),
                                         n_pk)
                away_e = self.evm(calibrated_away(c), n=n_pk)
                full = self.cal_evm(self.flat(wf, m), ob)
                psum = 10 * np.log10(10 ** (away_e / 10) + sum(10 ** (v / 10) for v in alone.values()))
                ex = {lab: (_evm_with_dc_pre_db(cc, f2, r, False, n_pk), _evm_with_dc_pre_db(cc, f2, r, True, n_pk))
                      for lab, cc in (("CFO on", c), ("CFO off", dc.replace(c, xo_ppm_tx=0.0, xo_ppm_rx=0.0)))}
                per_wf.append({
                    "waveform": wf, "mcs": m, "none_evm_db": base_e,
                    "alone": [{"item": k, "label": RESIDUAL_ITEMS[k], "evm_db": v} for k, v in alone.items()],
                    "tx_leak_without_cfo_evm_db": no_cfo, "tx_leak_without_dc_removal_evm_db": no_rm,
                    "calibrated_away_evm_db": away_e, "power_sum_evm_db": psum, "calibrated_chain_evm_db": full,
                    "dc_pre": [{"label": lab, "sequence_evm_db": a, "exact_evm_db": b}
                               for lab, (a, b) in ex.items()]})
            sim = LinkSim(at_backoff(dc.replace(self.cfgs["ay_sc"], channel=FLAT), ob), frontend=f2,
                          chains=copy.deepcopy(r.chains[:2]))
            _, fr = sim.transmit(np.random.default_rng(0))
            tx = copy.deepcopy(sim.tx)
            tx.params.lo.enabled = False
            sig = tx(fr.x * DIGITAL_DRIVE_RMS)
            # the leak read with the DAC off: a zero input through the 9-bit DAC rounds dc_pre (a few LSB)
            # away, and the reading floors near -40 dBc whatever the step did (wifi_trx_cal#6)
            quiet = copy.deepcopy(tx)
            quiet.params.dac.enabled = False
            leak = copy.deepcopy(quiet)(np.zeros_like(fr.x))[-1000:]
            raw = copy.deepcopy(quiet)
            raw.dc_pre = 0j
            raw_leak = raw(np.zeros_like(fr.x))[-1000:]
            p_sig = float(np.mean(abs(sig) ** 2))
            uncorr = copy.deepcopy(sim.tx)
            uncorr.w1 = uncorr.w2 = None
            lk = 10 * np.log10(np.mean(abs(leak) ** 2) / p_sig)
            lk_raw = 10 * np.log10(np.mean(abs(raw_leak) ** 2) / p_sig)
            irr = [_image_rejection_db(sim.tx, sim.phy.fs_eff, f) for f in IMAGE_FREQS_HZ]
            irr_raw = [_image_rejection_db(uncorr, sim.phy.fs_eff, f) for f in IMAGE_FREQS_HZ]
            self._row("residuals", {
                "backoff_db": ob, "waveforms": per_wf,
                "direct": {"tx_leak_after_dc_pre_dbc": lk, "tx_leak_without_dc_pre_dbc": lk_raw,
                           "image_rejection": [{"freq_hz": f, "irr_db": a, "irr_uncorrected_db": b}
                                               for f, a, b in zip(IMAGE_FREQS_HZ, irr, irr_raw)]}})

    # ------------------------------------------------------------ 9. rate against range
    def ranges_at(self, wf, i, sim=None, keep_il=False, gains=None, rule="measured", channel="flat") -> dict:
        """Every MCS of ``wf`` at grid point i, each at the output power its own constellation landed on."""
        gains = (self.g_tx, self.g_rx) if gains is None else gains
        floors_i = {o: self.curves9[(wf, o)][i] for o in self.orders[wf]}
        out = {}
        for o in self.orders[wf]:
            pout = self.landed[(wf, o, round(float(self.obos9[i]), 3))]
            r = al.ay_mcs_ranges(sim or self.rx_sim[wf], floors_i, pout + gains[0], gains[1],
                                 keep_implementation_loss=keep_il, rule=rule, channel=channel)
            out.update({m: dict(row, pout_dbm=pout) for m, row in r.items()
                        if edmg.mcs_entry(wf, m).tone_order == o})
        return dict(sorted(out.items()))

    def ranges(self) -> None:
        fe, psat, obos8, low, cal_curves, landed = self.fe, self.psat, self.obos, self.low, self.cal_curves, self.landed
        self._start("range_evm_vs_backoff")
        self.obos9 = obos9 = np.concatenate([low, obos8])
        n_low = len(low)
        self.orders = orders = {"ay_sc": {e.tone_order: e.mcs for e in edmg.mcs_table("ay_sc")},
                                "ay_ofdm": {e.tone_order: e.mcs for e in edmg.mcs_table("ay_ofdm")}}
        for wf, by_order in orders.items():
            for o, m in by_order.items():
                if (wf, o) not in cal_curves:
                    cal_curves[(wf, o)] = [self.cal_evm(self.flat(wf, m), ob, n=1) for ob in obos8]
        self.curves9 = curves9 = {}
        for wf, by_order in orders.items():
            for o, m in by_order.items():
                curves9[(wf, o)] = ([self.cal_evm(self.flat(wf, m), ob, n=1) for ob in low]
                                    + list(cal_curves[(wf, o)]))
                self._row("range_evm_vs_backoff", {
                    "waveform": wf, "mcs": m, "tone_order": o, "backoff_db": obos9,
                    "pout_dbm": [landed[(wf, o, round(float(ob), 3))] for ob in obos9], "evm_db": curves9[(wf, o)]})

        self._start("rate_vs_range")
        self.g_tx, self.g_rx = g_tx, g_rx = fe.antenna_gain_tx_dbi, fe.antenna_gain_rx_resolved_dbi
        self.rx_sim = rx_sim = {wf: LinkSim(self.flat(wf, 1), frontend=fe, chains=copy.deepcopy(self.run.chains[:2]))
                                for wf in orders}
        i0 = n_low + int(np.argmin(np.abs(obos8 - fe.obo_db)))
        ranges_at = self.ranges_at
        table = {wf: [ranges_at(wf, i) for i in range(len(obos9))] for wf in orders}
        table_mp = {wf: [ranges_at(wf, i, channel="multipath") for i in range(len(obos9))] for wf in orders}
        best, best_mp = {}, {}
        for wf in orders:
            for m in table[wf][0]:
                e = edmg.mcs_entry(wf, m)
                cands = [(r[m]["range_m"], i) for i, r in enumerate(table[wf])
                         if r[m]["conforms"] and r[m]["range_m"]]
                b = max(cands) if cands else None
                best[(wf, m)] = None if b is None else b[0]
                cm = [(r[m]["range_m"], i) for i, r in enumerate(table_mp[wf])
                      if m in r and r[m]["conforms"] and r[m]["range_m"]]
                bm = max(cm) if cm else None
                best_mp[(wf, m)] = None if bm is None else bm[0]
                r0 = table[wf][i0][m]
                at_preset = r0["range_m"] if r0["conforms"] else None
                # the back-off the PA landed on (the grid asks; under about 0.25 dB the PA cannot follow)
                bo = None if b is None else float(psat - table[wf][b[1]][m]["pout_dbm"])
                self._row("rate_vs_range", {
                    "waveform": wf, "mcs": m, "modulation": e.modulation, "code_rate": e.code_rate,
                    "rate_bps": e.rate_bps(self.gi), "dmg_twin": table[wf][0][m]["twin"],
                    "threshold_db": table[wf][0][m]["threshold_db"], "threshold_source": table[wf][0][m]["source"],
                    "range_at_preset_m": at_preset, "best_range_m": None if b is None else b[0],
                    "best_backoff_db": bo, "best_is_smallest_backoff": b is not None and b[1] == 0,
                    "best_pout_dbm": None if b is None else psat - bo,
                    "floor_at_best_db": None if b is None else table[wf][b[1]][m]["floor_db"],
                    "multipath_threshold_db": table_mp[wf][0].get(m, {}).get("threshold_db"),
                    "multipath_best_range_m": best_mp[(wf, m)]})
        self._start("link_budget")
        lands = {wf: psat - landed[(wf, min(orders[wf]), round(float(obos9[0]), 3))] for wf in orders}
        margin = float(spec.value("assumed.ay_ofdm_multipath_margin_db"))
        self._row("link_budget", {
            "tx_antenna_gain_dbi": g_tx, "rx_antenna_gain_dbi": g_rx, "rx_nf_db": rx_sim["ay_sc"]._rx_nf_db(),
            "oxygen_db_per_km": al.oxygen_db_per_km(), "low_backoffs_db": low, "grid_first_db": obos8[0],
            "grid_last_db": obos8[-1], "grid_step_db": obos8[1] - obos8[0],
            "smallest_asked_backoff_db": obos9[0], "smallest_landed_backoff_db": lands,
            "ofdm_multipath_margin_db": margin})

        self._start("fastest_rate_at_distance")
        for d in DISTANCES_M:
            row = {"distance_m": d}
            for tab, suffix in ((best, ""), (best_mp, "_multipath")):
                for wf in orders:
                    ok = [m for m in table[wf][0] if tab.get((wf, m)) is not None and tab[(wf, m)] >= d]
                    top = max(ok, key=lambda m: edmg.mcs_entry(wf, m).rate_bps(self.gi)) if ok else None
                    row[f"{wf[3:]}{suffix}_rate_bps"] = (None if top is None
                                                         else edmg.mcs_entry(wf, top).rate_bps(self.gi))
                    row[f"{wf[3:]}{suffix}_mcs"] = top
            self._row("fastest_rate_at_distance", row)

        # the two multipath columns are not on the same footing: say so, and show what the other footing gives
        self._start("multipath_same_modulation")
        sim_o = rx_sim["ay_ofdm"]
        for sm, om in list(DCM_PAIRS) + self.pairs:
            es = edmg.mcs_entry("ay_sc", sm)
            ts, tm = table["ay_sc"][0][sm]["threshold_db"], table_mp["ay_sc"][0].get(sm, {}).get("threshold_db")
            cost = None if tm is None else tm - ts
            alt = None
            if cost is not None:
                ds = []
                for r in table["ay_ofdm"]:
                    req = (al.required_snr_db(r[om]["threshold_db"] + cost, r[om]["floor_db"])
                           if r[om]["conforms"] else None)
                    if req is not None:
                        pl = r[om]["pout_dbm"] + g_tx + g_rx - float(sim_o.rx_input_dbm_for_snr(req))
                        ds.append(al.range_m(pl, sim_o.cfg.carrier_hz))
                alt = max(ds) if ds else None
            self._row("multipath_same_modulation", {
                "modulation": edmg.mcs_entry("ay_ofdm", om).modulation.replace("DCM ", ""),
                "code_rate": es.code_rate, "sc_mcs": sm, "ofdm_mcs": om, "sc_cost_db": cost,
                "sc_multipath_range_m": best_mp.get(("ay_sc", sm)), "ofdm_cost_db": margin,
                "ofdm_multipath_range_m": best_mp.get(("ay_ofdm", om)), "ofdm_range_at_sc_cost_m": alt})

        self._start("sensitivity_rows")
        # the presets until 2026-11-18: a 0 dBi "not specified" antenna, and (separately) the WiFi 7 receive ladder
        sv_cfg = {wf: unspecified_antenna(self.flat(wf, 1)) for wf in orders}
        sv_fe = {wf: Frontend60.from_config(c) for wf, c in sv_cfg.items()}
        sv_sim = {wf: LinkSim(sv_cfg[wf], frontend=sv_fe[wf]) for wf in orders}
        w7_sim = {wf: LinkSim(wifi7_rx_ladder(self.flat(wf, 1))) for wf in orders}
        for wf, m in SENSITIVITY_MCS.items():
            base_r = table[wf][i0][m]["range_m"]
            il = ranges_at(wf, i0, keep_il=True, rule="twin")[m]["range_m"]
            tw = ranges_at(wf, i0, rule="twin")[m]["range_m"]
            sv = ranges_at(wf, i0, sim=sv_sim[wf], gains=(sv_fe[wf].antenna_gain_tx_dbi,
                                                          sv_fe[wf].antenna_gain_rx_resolved_dbi))[m]["range_m"]
            w7 = ranges_at(wf, i0, sim=w7_sim[wf])[m]["range_m"]
            self._row("sensitivity_rows", {
                "waveform": wf, "mcs": m, "preset_range_m": base_r, "twin_threshold_range_m": tw,
                "twin_with_implementation_loss_range_m": il, "unspecified_antenna_range_m": sv,
                "unspecified_antenna_tx_gain_dbi": sv_fe[wf].antenna_gain_tx_dbi,
                "unspecified_antenna_rx_gain_dbi": sv_fe[wf].antenna_gain_rx_resolved_dbi,
                "wifi7_rx_ladder_range_m": w7, "wifi7_rx_ladder_nf_db": w7_sim[wf]._rx_nf_db()})

        self._start("threshold_comparison")
        for lab, wf, m, be_mcs in THRESHOLD_ROWS:
            t, _ = edmg.threshold_db(wf, m, rx_sim[wf].occupied_bw_hz, rule="twin")
            tm = spec.ay_per_threshold_db(wf, m)
            tb = None if be_mcs is None else spec.per_threshold_db("11be", 80e6, be_mcs)
            self._row("threshold_comparison", {
                "label": lab, "waveform": wf, "mcs": m, "be_mcs": be_mcs, "twin_threshold_db": t,
                "measured_threshold_db": tm, "be_threshold_db": tb,
                "twin_minus_measured_db": None if tm is None else t - tm,
                "twin_minus_be_db": None if tb is None else t - tb})

    # ------------------------------------------------------------ 10. multipath
    def multipath(self) -> None:
        self._start("multipath_evm")
        for wf, m in QAM16.items():
            flat12 = None
            for lab, ch, opt in multipath_rows():
                if opt.get("sc_equalizer") and wf != "ay_sc":
                    continue
                c = self.cfg(wf, m, gi=opt.get("gi"))
                if "sc_equalizer" in opt:
                    c = dc.replace(c, ay=dc.replace(c.ay, sc_equalizer=opt["sc_equalizer"]))
                sim = LinkSim(dc.replace(c, channel=ch), frontend=self.fe, chains=copy.deepcopy(self.run.chains[:2]))
                cells, mean12 = [], None
                for snr in MULTIPATH_SNRS_DB:
                    rng = np.random.default_rng(1)              # the same realisations in every row
                    e = np.asarray([sim.packet(snr, rng).rx.evm_db for _ in range(self.n_mp)])
                    mean = float(10 * np.log10(np.mean(10 ** (e / 10))))
                    cells.append({"snr_db": snr, "mean_evm_db": mean, "p90_evm_db": np.percentile(e, 90)})
                    if snr == MULTIPATH_COMPARE_SNR_DB:
                        mean12 = mean
                if lab == "flat":
                    flat12 = mean12
                self._row("multipath_evm", {
                    "waveform": wf, "mcs": m, "channel": lab, "gi": c.ay.gi, "sc_equalizer": c.ay.sc_equalizer,
                    "evm": cells, "delta_vs_flat_db": mean12 - flat12})


def build(fe: Frontend60 | None = None, cfgs: dict | None = None, quick: bool = False, progress=None, *,
          packets: int | None = None, backoffs_db=None, low_backoffs_db=None, rolloffs=None,
          multipath_packets: int | None = None) -> dict:
    """Example 15's numbers as one JSON-safe dict (the module docstring describes it).

    ``cfgs`` is ``{"ay_sc": config, "ay_ofdm": config}`` (default: the presets, ``default_cfgs()``) and
    ``fe`` the front end both waveforms share (default: ``default_frontend(cfgs)``).  ``quick`` shrinks the
    run to a smoke test whose numbers mean nothing (one packet per point, a 2 dB back-off grid, one
    roll-off, four multipath packets); the keyword-only arguments set each size on its own and win over
    ``quick``: ``packets`` per EVM point, the back-off grid from Psat ``backoffs_db`` (sections 5, 8 and
    9; ascending, at least two points), the back-offs under it that only the range table asks
    ``low_backoffs_db``, the SC pulse ``rolloffs`` of the PAPR rows, and the ``multipath_packets`` of
    section 10.  ``progress(section, row)`` is called as the module docstring says."""
    cfgs = default_cfgs() if cfgs is None else dict(cfgs)
    fe = default_frontend(cfgs) if fe is None else fe
    b = _Build(fe, cfgs, quick, progress, packets, backoffs_db, low_backoffs_db, rolloffs, multipath_packets)
    b.header()
    b.numbers()
    b.papr()
    b.impairments_alone()
    b.floors_and_caps()
    b.backoff()
    b.best_rate_at_pout()
    b.calibration()
    b.calibrated()
    b.residuals()
    b.ranges()
    b.multipath()
    return b.rep
