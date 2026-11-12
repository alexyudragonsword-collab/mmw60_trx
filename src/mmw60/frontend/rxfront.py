"""The 60 GHz receive front end as one object: its gain ladder for the
wifitrx AGC, and the numbers a link budget or a radar reads off it (gain,
noise figure and input compression at the maximum-gain state).

Input compression is two numbers.  ``p1db_inband_dbm`` is the in-band one,
from the state's IIP3: what a wanted signal meets, and a full-duplex link's
own leakage.  ``p1db_oob_dbm`` is the stages before the baseband high-pass,
measured with a tone below its corner: what an FMCW radar's transmit leakage
meets.  A radar chip's datasheet gives both and they are tens of dB apart;
the communication receivers read so far give only the first.

``wifi7_ladder`` is wifitrx's own table, a sub-7 GHz WiFi 7 chip's: every
result before ROADMAP D4 was produced with it and the presets still are, so
their numbers do not move.  It is not a 60 GHz front end; ``sourced`` says
so.  ``anchored`` moves that ladder so its top state reads a 60 GHz noise
figure / IIP3 / gain (data/spec: assumed.rx60_ladder_shape).
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from .. import spec
from ..vendor.wifitrx.chain.agc import DEFAULT_LNA_STATES, LNAState, select_lna_state

MODELS = ("wifi7_ladder", "anchored")


@dataclass(frozen=True)
class RxFront60:
    model: str = "wifi7_ladder"
    states: tuple[LNAState, ...] = DEFAULT_LNA_STATES
    #: which of the top state's figures were given (the rest are still wifitrx's)
    anchored_fields: tuple[str, ...] = ()
    #: input 1 dB compression before the baseband high-pass, maximum gain; None = not specified
    p1db_oob_dbm: float | None = None

    @classmethod
    def from_config(cls, cfg) -> "RxFront60":
        """``cfg`` is a ``config.RxFrontConfig``."""
        if cfg.model not in MODELS:
            raise ValueError(f"frontend.rx_front.model must be one of {MODELS}")
        if cfg.model == "wifi7_ladder":
            if (cfg.nf_db, cfg.iip3_dbm, cfg.gain_db, cfg.p1db_oob_dbm) != (None,) * 4:
                raise ValueError("frontend.rx_front: nf_db / iip3_dbm / gain_db / p1db_oob_dbm only apply to "
                                 "model 'anchored'")
            return cls()
        return cls.anchored(cfg.nf_db, cfg.iip3_dbm, cfg.gain_db, cfg.p1db_oob_dbm)

    @classmethod
    def anchored(cls, nf_db: float | None = None, iip3_dbm: float | None = None,
                 gain_db: float | None = None, p1db_oob_dbm: float | None = None) -> "RxFront60":
        """wifitrx's ladder moved so its top state reads the given figures;
        None keeps wifitrx's.  The hand-over levels follow wifitrx's own rule
        for them (``chain/agc``: the noise-against-IM3 balance point
        t_i = (2·IIP3_i + NF_{i+1} + const) / 3): a uniform shift of the
        ladder moves every one by (2·ΔIIP3 + ΔNF) / 3, and the gain does not
        enter.  The official table's levels are kept as the base, so nothing
        given is wifitrx's ladder exactly."""
        top = DEFAULT_LNA_STATES[0]
        d_nf = 0.0 if nf_db is None else float(nf_db) - top.nf_db
        d_ip3 = 0.0 if iip3_dbm is None else float(iip3_dbm) - top.iip3_dbm
        d_g = 0.0 if gain_db is None else float(gain_db) - top.gain_db
        if top.nf_db + d_nf < 0.0:
            raise ValueError("frontend.rx_front.nf_db must be >= 0 dB")
        d_t = (2.0 * d_ip3 + d_nf) / 3.0
        last = len(DEFAULT_LNA_STATES) - 1
        states = tuple(replace(st, gain_db=st.gain_db + d_g, nf_db=st.nf_db + d_nf, iip3_dbm=st.iip3_dbm + d_ip3,
                               # the last state's ceiling is kept, as wifitrx's rebalance_thresholds keeps it
                               max_input_dbm=st.max_input_dbm + (0.0 if i == last else d_t))
                       for i, st in enumerate(DEFAULT_LNA_STATES))
        given = tuple(name for name, v in (("nf_db", nf_db), ("iip3_dbm", iip3_dbm), ("gain_db", gain_db))
                      if v is not None)
        if p1db_oob_dbm is not None:
            given += ("p1db_oob_dbm",)
        return cls(model="anchored", states=states, anchored_fields=given,
                   p1db_oob_dbm=None if p1db_oob_dbm is None else float(p1db_oob_dbm))

    # ------------------------------------------------------------ the face
    @property
    def sourced(self) -> bool:
        """False for the WiFi 7 chip's ladder: usable as a model, not as a
        statement about a 60 GHz front end.  True means at least one figure
        was given; ``anchored_fields`` says which."""
        return bool(self.anchored_fields)

    @property
    def top(self) -> LNAState:
        return self.states[0]

    @property
    def gain_db(self) -> float:
        return float(self.top.gain_db)

    @property
    def nf_db(self) -> float:
        return float(self.top.nf_db)

    @property
    def iip3_dbm(self) -> float:
        return float(self.top.iip3_dbm)

    @property
    def p1db_inband_dbm(self) -> float:
        """In-band input 1 dB compression at the maximum-gain state, from the
        IIP3 (data/spec: assumed.rx60_p1db_from_iip3_db — the chain's own cubic
        compresses 1 dB at IIP3 − 9.64 dB; tests/test_frontend_faces.py)."""
        return self._p1db_inband(self.top)

    @staticmethod
    def _p1db_inband(state: LNAState) -> float:
        return float(state.iip3_dbm) - float(spec.value("assumed.rx60_p1db_from_iip3_db"))

    def p1db_inband_by_gain(self) -> tuple[tuple[float, float], ...]:
        """(gain dB, in-band input P1dB dBm) for every state of the ladder,
        maximum gain first: the in-band compression moves with the gain."""
        return tuple((float(st.gain_db), self._p1db_inband(st)) for st in self.states)

    def state_for(self, p_in_dbm: float) -> tuple[int, LNAState]:
        """The gain state wifitrx's AGC picks for this input level (its own
        ``select_lna_state`` on this ladder)."""
        i = int(select_lna_state(self.states, float(p_in_dbm)))
        return i, self.states[i]

    def describe(self) -> dict:
        return {"rx_front": self.model, "rx_front_sourced": self.sourced,
                "rx_front_given": list(self.anchored_fields), "rx_gain_db": self.gain_db,
                "rx_nf_db": self.nf_db, "rx_iip3_dbm": self.iip3_dbm, "rx_p1db_inband_dbm": self.p1db_inband_dbm,
                "rx_p1db_oob_dbm": self.p1db_oob_dbm,
                "rx_gain_states": len(self.states), "rx_gain_min_db": float(self.states[-1].gain_db)}
