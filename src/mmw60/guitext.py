"""The other language of every fixed sentence a report carries.

The library's own words were written in one language each, wherever they first got printed: an
example's accepted output holds the row verdicts and the calibration mechanisms in Chinese, the
footing and the job notes were written in English.  Those texts stay where they are (the accepted
outputs print them); this module pairs each with its other half, and ``guiutil`` puts both in the
reports (``reason`` + ``reason_en``, ``mechanism_zh`` + ``mechanism_en`` ...), so a page shows one
language without mixing.

Two kinds of text are **not** paired and say so (``AS_WRITTEN``): sentences the engine composes with
numbers inside (a power block's note, wifitrx's detail of a calibration step).  A page shows those
as they were written, marked as the engine's own words.

``tests/test_guitext.py`` holds every table here to the texts it pairs: a new reason, mechanism,
footing or job note without its other half fails there.
"""
from __future__ import annotations

from . import compare
from .frontend.grid import REASON_ZH

VERDICT_EN = {"能": "works", "不能": "does not"}

#: ``frontend.grid.REASON_ZH`` by the same keys
REASON_EN = {"cfo": "CFO capture", "phase_noise": "phase noise", "iq_image": "IQ imbalance",
             "converters": "converters", "pa": "PA", "isi": "ISI beyond the GI", "plan": "frequency plan",
             "chip": "chip residual", "chip_lo": "chip LO phase noise"}
_LIMITS_ZH, _LIMITS_EN = " 限 MCS", " limits the MCS"


def reason_en(reason_zh: str) -> str:
    """A row's reason as ``compare`` composes it (reasons joined by ", ", or one term + " 限 MCS"),
    in English; raises KeyError on a piece it does not know."""
    by_zh = {v: REASON_EN[k] for k, v in REASON_ZH.items()}
    out = []
    for piece in reason_zh.split(", "):
        limits = piece.endswith(_LIMITS_ZH)
        out.append(by_zh[piece.removesuffix(_LIMITS_ZH)] + (_LIMITS_EN if limits else ""))
    return ", ".join(out)


#: why a cell of the matrix has no row (``compare.NOT_A_SCHEME`` / ``NOT_A_CHIP_CHANNEL``)
PENDING_ZH = {
    compare.NOT_A_SCHEME: "不适用：ay 波形是拓扑 B 的硬件；拓扑 A 的芯片只出 WiFi 7 的数字学，最宽到它最宽的信道",
    compare.NOT_A_CHIP_CHANNEL: "不适用：拓扑 A 只升频数字基带，所以 K × 基准带宽必须是芯片的一个信道"
                                "（≤ 320 MHz；assumed.ifext_upclock）",
}

#: ``calcheck.MECHANISM`` by the same keys
MECHANISM_EN = {
    "tx_lpf_corner": "the corner search is relative to the bandwidth (recommended_lpf_corner_hz × BW) and scales "
                     "with K; the sweep resolution of n = 2^14 samples coarsens with fs",
    "rx_lpf_corner": "as above",
    "rx_dc_offset": "reads the DC bin, independent of fs; the RX self-mixing DC is itself given in dBc",
    "tx_lo_leak_envdet": "the envelope detector's LPF is fixed at 60 MHz: at a large K the in-band signal power "
                         "falls outside the detector's band and the leak-to-signal reading is distorted",
    "tx_lo_leak_loopback": "the RX LO offset of 4.8 MHz is put on this capture's FFT grid since wifitrx 0.7.41 "
                           "(B42, wifi_trx_cal#6; off the grid before, the probe tone's spectrum leaked into the "
                           "leak bin and 2.56 GHz stopped at −40 dBc); the wide columns still read about 9 dB "
                           "worse than 20 MHz, which was not looked into separately",
    "rx_iip2": "the two tones are fixed at 17 / 23 MHz (no longer scaled with the bandwidth from 80 MHz up): at a "
               "large K they sit at the very bottom of the band and the 6 MHz IM2 beat overlaps the DC loop",
    "loopback_delay": "a 6 ns loopback delay is 6e-9 × fs samples; capture_aligned searches max_lag = 32 samples, "
                      "which it exceeds from fs = 5.3 GS/s",
    "tx_iq": "the RX LO offset is fixed at 5.1 MHz and the correction FIR has 7.5·fs/BW taps (the same at every K); "
             "an IQ mismatch given in ps is a phase error ∝ K over a wider band, and what can be corrected is set "
             "by the FIR's frequency resolution",
    "group_delay": "the tolerance is fixed at 80 ps; the frequency leverage of the ρ(f) slope estimate grows with "
                   "the bandwidth, so it is more accurate at a large K",
    "rx_iq": "as tx_iq",
    "tx_power": "independent of fs",
    "dpd": "the GMP ILA is identified at fs_eff; with a memoryless PA its order and memory depth are redundant but "
           "it converges; the observation path's ADC ENOB falling with fs is identification noise",
    "agc_sweep": "the probe tone is fixed at 23 MHz (from 80 MHz up); the AGC thresholds are tuned for 320 MHz",
    "final_loopback_evm": "standard bandwidths (≤ 320 MHz) use that bandwidth's standard waveform; wider ones the "
                          "base waveform × K (the same tones and pilots, TonePlan.pilots since wifitrx 96078aa)",
}

#: ``guiutil.FOOTING``'s two sentences per footing, in Chinese
FOOTING_ZH = {
    "be_zero_if": {
        "raw_floor": "各分项的解析和；同一格再跑一遍时域 EVM 核对",
        "cal_floor": "这条链上没有量：解析和里的 IQ 镜像换成校准序列在该带宽上量到的 IRR（查表得来的值）"},
    "be_if_extender": {
        "raw_floor": "各分项的解析和；其中芯片残差是芯片自己校准之后量的（建链时就跑）",
        "cal_floor": "与未校准的底板相同（芯片已经校准过）"},
    "ay": {
        "raw_floor": "未校准链上的时域 EVM，取最差的星座（没有解析和）",
        "cal_floor": "实测：wifitrx 校准序列校准过的链上的时域 EVM"},
}

#: ``guiutil.JOBS[job]["seconds_note"]`` in Chinese
SECONDS_NOTE_ZH = {
    "calibration_be": "42 s 是在 4 核容器上与另外三个任务并排跑的；每列 12 步，共六列",
    "table": "55 s 是在 4 核容器上单独跑的，含敏感度与本振模型两节；106 s 是有那两节之前与另外三个任务并排跑的",
    "array": "560 s 是在 4 核容器上单独跑的（示例 10，同一份计算）；893 s 是与另外三个任务并排；"
             "1650 s 是与三个示例并排",
    "ay": "224 s 是在 4 核容器上单独跑的（示例 15，同一份计算）；428 s 是与另外三个任务并排；563 s 是与三个示例并排",
    "table_analytic": "24 s 是在 4 核容器上、旁边同时在测页面时跑的（拓扑 A 的行要建芯片并跑它的校准）",
}

#: ``guiutil.calibration_from_runs``'s ``status_rule``, in Chinese
STATUS_RULE_ZH = {
    "status_wifitrx": "wifitrx 自己对这一步在这次运行上的判定",
    "status_summary": "wifitrx 的判定；另外，一个 ok 的步若 dB 读数比第一列差 3 dB 以上，记为 degraded"
                      "（本库的规则，calcheck.compare_runs）",
}

EIRP_LAW = {"en": "EIRP = element EIRP + 20 log10 N (TX gain = 20 log10 N + element gain)",
            "zh": "EIRP = 单元 EIRP + 20 log10 N（发射增益 = 20 log10 N + 单元增益）"}

#: ``compare.sensitivity_knobs()``'s ``source_note`` by knob name
SOURCE_NOTE_ZH = {"calibrated IRR": "代替实测的那张表"}

#: sentences the engine composes with numbers inside: shown as written, in this language
AS_WRITTEN = {"power_block_note": "en", "calibration_step_detail": "en"}

_OUT_OF_STEP_ZH = (
    ("schema ", lambda s: "结果的格式版本与这份代码不同（" + s.removeprefix("schema ") + "）"),
    ("the spec tables changed", lambda s: "算它之后规范表变了"),
    ("a vendored library's pin changed", lambda s: "算它之后某个 vendored 库的 pin 变了"),
    ("a smoke-size run", lambda s: "试算规模的结果"),
    ("not the presets: ", lambda s: "不是预设：" + s.removeprefix("not the presets: ")),
)


def out_of_step_zh(reasons: list[str]) -> list[str]:
    """``guistore.stale_reasons`` in Chinese, sentence by sentence; raises KeyError on one it does
    not know."""
    out = []
    for r in reasons:
        for prefix, fn in _OUT_OF_STEP_ZH:
            if r.startswith(prefix):
                out.append(fn(r))
                break
        else:
            raise KeyError(f"no Chinese for the out-of-step reason {r!r}")
    return out
