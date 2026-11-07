"""The data-field coding wifitrx does not have (it is an EVM-level model).

VHT 20 MHz: scrambler, BCC encoder / soft Viterbi decoder, puncturing, the
20 MHz interleaver.  11be (every bandwidth): the 802.11 LDPC codes, the
LDPC PPDU encoding process, tone mapper and segment parser.  Gray mappers
with max-log LLRs up to 4096-QAM and the PPDU bit assembly, so a packet
error rate can be measured.  All of it is this library's own code
(outside ``vendor/``); the OFDM modulation itself stays wifitrx's.
"""
from .eht import EhtDataField, EhtMcs, build_eht_data_field, decode_eht_data_field, eht_mcs
from .mcs import VhtMcs, vht_mcs
from .ppdu import DataField, build_data_field, decode_data_field

__all__ = ["VhtMcs", "vht_mcs", "DataField", "build_data_field", "decode_data_field",
           "EhtMcs", "eht_mcs", "EhtDataField", "build_eht_data_field", "decode_eht_data_field"]
