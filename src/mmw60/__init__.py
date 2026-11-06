"""mmw60 — 60 GHz (57–71 GHz unlicensed) WiFi transceiver behavioural simulation.

Two topologies on one engine, fairly comparable:

* **A, IF extender** — a WiFi 7 chip as-is, its 5–7 GHz RF output used as a
  real IF, one fixed-LO (×3 / ×4) 60 GHz up/down-converter, image filter,
  PA / LNA; the waveform is unchanged (milestone 1).
* **B, IMMW upclocking** (Liu et al., "Wi-Fi 8: Embracing the Millimeter-Wave
  Era", IEEE Comm. Mag. 2025-03) — PHY / MAC untouched, the clock ×K
  (4 / 8 / 16 / 32), bandwidth and subcarrier spacing scale with it, a new
  wide-band zero-IF 60 GHz transceiver.

The engine is the vendored ``wifi_trx_cal`` package (``mmw60.vendor.wifitrx``,
pinned by full SHA); everything 60 GHz-specific wraps it from here.
"""

__version__ = "0.0.1"

#: What every example prints on its first line (iron rule 6).  The engine is
#: a time-domain complex-baseband model with linearised (behavioural) PA and
#: phase-noise blocks and no cycle-accurate PLL: spur / intermodulation
#: conclusions drawn from it are not endorsed.
ENGINE_BANNER = ("engine: upclocked wifitrx time-domain baseband "
                 "(linearised PA / PN models, no cycle-accurate PLL) "
                 "-- spur / IM conclusions not endorsed")
