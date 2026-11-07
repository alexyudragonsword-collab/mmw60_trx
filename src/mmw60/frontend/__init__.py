"""The 60 GHz front end shared by both topologies (iron rule 2).

One ``Frontend60`` instance — PA, LO (phase-noise profile + leakage), converter
law (ENOB vs sample rate), IQ imbalance, EIRP limit — is built from the config
and handed to whichever topology runs.  Topology B (``zero_if_chain``) turns
it into wifitrx ``TxChain`` / ``RxChain`` parameters at ``fs_eff``: the WiFi 7
chip's own zero-IF architecture clocked K times faster, so wifitrx's
calibration sequence runs on it unchanged.  Topology A (milestone 1, the
other session) takes the same instance for its 60 GHz stage after the
chip's RF.
"""
from .converters import ConverterLaw
from .eirp import EirpLimit
from .freqplan import zero_if_plan
from .frontend import Frontend60
from .lo import Lo60
from .pa import ScaledRappPA

__all__ = ["ConverterLaw", "EirpLimit", "zero_if_plan", "Frontend60", "Lo60", "ScaledRappPA"]
