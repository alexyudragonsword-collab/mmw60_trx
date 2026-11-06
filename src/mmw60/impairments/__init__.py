"""Impairments this library adds on top of wifitrx's: the 1-pole/1-zero LO
profile, the end-to-end CFO (ppm × carrier) and the in-band SNR definition."""
from .cfo import CfoModel
from .noise import add_awgn_per_tone, per_sample_snr_offset_db
from .phase_noise import PoleZeroPhase, lo_phase

__all__ = ["CfoModel", "PoleZeroPhase", "lo_phase", "add_awgn_per_tone",
           "per_sample_snr_offset_db"]
