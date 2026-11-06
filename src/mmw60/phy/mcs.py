"""VHT MCS table for one spatial stream at 20 MHz (N_SD = 52, N_SP = 4).

Values as the 802.11 VHT MCS tables give them (IEEE 802.11-2020 Table
21-30, VHT-MCSs for mandatory 20 MHz, N_SS = 1).  The text is not in this
repository, so the table is ``source: survey`` like the rest of
``data/spec/survey.yaml``; the numbers are consistent with each other by
construction (``N_CBPS = N_SD · N_BPSCS``, ``N_DBPS = N_CBPS · R``) and
``tests/test_phy.py`` checks that.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

N_SD_20 = 52          # data subcarriers, VHT 20 MHz
N_SP_20 = 4           # pilot subcarriers
N_SERVICE = 16
N_TAIL = 6

SOURCE = "survey"     # IEEE 802.11-2020 Table 21-30 (text not held; 未核实)


@dataclass(frozen=True)
class VhtMcs:
    index: int
    modulation: str      # BPSK | QPSK | 16-QAM | 64-QAM | 256-QAM
    qam_order: int       # 2, 4, 16, 64, 256
    rate: Fraction
    n_sd: int = N_SD_20

    @property
    def n_bpscs(self) -> int:
        return {2: 1, 4: 2, 16: 4, 64: 6, 256: 8}[self.qam_order]

    @property
    def n_cbps(self) -> int:
        return self.n_sd * self.n_bpscs

    @property
    def n_dbps(self) -> int:
        d = Fraction(self.n_cbps) * self.rate
        assert d.denominator == 1, (self.index, d)
        return int(d)

    def n_symbols(self, psdu_bytes: int) -> int:
        """Data OFDM symbols for a PSDU (non-LDPC, single user, no STBC)."""
        n_bits = N_SERVICE + 8 * int(psdu_bytes) + N_TAIL
        return -(-n_bits // self.n_dbps)

    def n_pad(self, psdu_bytes: int) -> int:
        return self.n_symbols(psdu_bytes) * self.n_dbps - (N_SERVICE + 8 * psdu_bytes + N_TAIL)

    def data_rate_bps(self, t_symbol_s: float) -> float:
        return self.n_dbps / t_symbol_s


_TABLE = {
    0: VhtMcs(0, "BPSK", 2, Fraction(1, 2)),
    1: VhtMcs(1, "QPSK", 4, Fraction(1, 2)),
    2: VhtMcs(2, "QPSK", 4, Fraction(3, 4)),
    3: VhtMcs(3, "16-QAM", 16, Fraction(1, 2)),
    4: VhtMcs(4, "16-QAM", 16, Fraction(3, 4)),
    5: VhtMcs(5, "64-QAM", 64, Fraction(2, 3)),
    6: VhtMcs(6, "64-QAM", 64, Fraction(3, 4)),
    7: VhtMcs(7, "64-QAM", 64, Fraction(5, 6)),
    8: VhtMcs(8, "256-QAM", 256, Fraction(3, 4)),
}


def vht_mcs(index: int) -> VhtMcs:
    if index not in _TABLE:
        raise ValueError(f"VHT 20 MHz MCS must be one of {sorted(_TABLE)}, got {index}")
    return _TABLE[index]
