"""Run wifitrx's calibration sequence on the upclocked zero-IF chain, step by step,
and say for each step whether it works at that clock (iron rule 4: calibrated
is something you ran, not something you wrote down).

The chains come from the shared ``Frontend60`` at ``fs_eff``; the sequence is
wifitrx's own (``cal/sequence._step_runners`` — the same runner table
``run_full_cal`` and ``run_cal_steps`` use, so every step runs with the
arguments the delivered sequence uses).  Each runner is wrapped so a step
that raises is recorded as *failed* with its exception instead of aborting
the table, and the metric that step's own ``spec`` names is read out.

What the scoring waveform can be at a given effective bandwidth is itself a
finding: wifitrx's pilot tables exist for the standard bandwidths (11ac
20–160 MHz, 11be 20–320 MHz), so the EVM snapshots — and with them
``final_loopback_evm`` — have no waveform beyond 320 MHz; the other steps
use plain OFDM or tones and run at any rate.
"""
from __future__ import annotations

import traceback
from dataclasses import dataclass, field

import numpy as np

from .frontend import Frontend60
from .vendor.wifitrx.cal.deps import planned_steps
from .vendor.wifitrx.cal.sequence import PROFILES, _step_runners, loopback_snapshot
from .vendor.wifitrx.chain.loopback import LoopbackPath, recommended_loopback_atten_db
from .vendor.wifitrx.waveform.ofdm import OFDMConfig

STANDARD_SCS = {312.5e3: (20e6, 40e6, 80e6, 160e6), 78.125e3: (20e6, 40e6, 80e6, 160e6, 320e6)}

#: why a step behaves as it does when the clock is K times faster — written
#: from the step implementations (absolute Hz / ns / sample constants) and
#: checked against the table the examples print
MECHANISM = {
    "tx_lpf_corner": "角频搜索相对 BW（recommended_lpf_corner_hz × BW），随 K 缩放；n = 2^14 样本的扫频分辨率随 fs 变粗",
    "rx_lpf_corner": "同上",
    "rx_dc_offset": "读 DC 箱，与 fs 无关；RX 自混频 DC 本身按 dBc 给定",
    "tx_lo_leak_envdet": "包络检波器 LPF 固定 60 MHz：K 大时带内信号功率落在检波带外，泄漏/信号比的读数失真",
    "tx_lo_leak_loopback": "RX LO 偏置固定 4.8 MHz：泄漏箱偏到 4.8 MHz / SCS_eff 个子载波，K ≥ 8 时落进信号带内（2.5 MHz 音距）",
    "rx_iip2": "双音固定 17 / 23 MHz（bw ≥ 80 MHz 不再按 BW 缩放）：K 大时音在带内极低频处，IM2 拍频 6 MHz 与 DC 环路重叠",
    "loopback_delay": "6 ns 回环延迟 = 6e-9 × fs 个样本；capture_aligned 的 max_lag = 32 样本，fs ≥ 5.3 GS/s 时越界",
    "tx_iq": "RX LO 偏置固定 5.1 MHz、校正 FIR 7.5·fs/BW 抽头（随 K 不变）；IQ 失配 ps 绝对值在宽带上相位误差 ∝ K，可校正范围由 FIR 频率分辨率决定",
    "group_delay": "容差固定 80 ps；ρ(f) 斜率估计的频率杠杆随 BW 增大，K 大时更准",
    "rx_iq": "同 tx_iq",
    "tx_power": "与 fs 无关",
    "dpd": "GMP ILA 在 fs_eff 上辨识；PA 无记忆时阶数/记忆深度冗余但收敛；观测通路 ADC ENOB 随 fs 下降是辨识噪声",
    "agc_sweep": "探针音 23 MHz 固定（bw ≥ 80 MHz）；AGC 门限按 320 MHz 调",
    "final_loopback_evm": "需要 wifitrx 标准带宽的导频波形（≤ 320 MHz）；更宽带宽没有评分波形",
}


@dataclass
class StepRow:
    k: int
    bw_eff_hz: float
    fs_eff_hz: float
    step: str
    status: str                      # ok | degraded | failed | skipped
    metric: str = ""
    value: float | None = None
    passed: bool | None = None
    detail: str = ""
    mechanism: str = ""


@dataclass
class CalRun:
    k: int
    bw_eff_hz: float
    fs_eff_hz: float
    waveform: str
    rows: list = field(default_factory=list)
    evm_before_db: float | None = None
    evm_after_db: float | None = None

    @property
    def label(self) -> str:
        return f"K={self.k} {self.bw_eff_hz / 1e6:g}M"


def scoring_config(bw_eff_hz: float, oversampling: int = 2, n_symbols: int = 8) -> tuple[OFDMConfig | None, str]:
    """A wifitrx OFDM config with a real pilot set at this bandwidth, if one exists."""
    for scs, bws in STANDARD_SCS.items():
        if any(abs(bw_eff_hz - b) < 1 for b in bws):
            cp = 1 / 4 if scs == 312.5e3 else 1 / 16
            return (OFDMConfig(bandwidth_hz=bw_eff_hz, subcarrier_spacing_hz=scs, cp_fraction=cp,
                               qam_order=64, n_symbols=n_symbols, oversampling=oversampling,
                               window_fraction=1 / 32 if scs == 78.125e3 else 1 / 16),
                    f"{'11ac' if scs == 312.5e3 else '11be'} {bw_eff_hz / 1e6:g} MHz (standard pilots)")
    return None, "no standard pilot set at this bandwidth"


def plain_config(bw_eff_hz: float, k: int, oversampling: int = 2, n_symbols: int = 8) -> OFDMConfig:
    """Plain OFDM (no pilots) at the upclocked numerology: what the tone / OFDM
    stimuli steps can run on when no scoring waveform exists."""
    return OFDMConfig(bandwidth_hz=bw_eff_hz, subcarrier_spacing_hz=312.5e3 * k, cp_fraction=1 / 4,
                      qam_order=64, n_symbols=n_symbols, oversampling=oversampling, window_fraction=1 / 16)


def _metric(res) -> tuple[str, float | None]:
    if res.spec and res.spec.get("metric") in res.metrics_after:
        m = res.spec["metric"]
        return m, float(res.metrics_after[m])
    for k, v in res.metrics_after.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return k, float(v)
    return "", None


def run_cal_at(fe: Frontend60, k: int, base_bw_hz: float = 20e6, oversampling: int = 2,
               profile: str = "poweron", with_dpd: bool = True, seed: int = 0,
               log=None) -> CalRun:
    bw_eff = base_bw_hz * k
    fs_eff = bw_eff * oversampling
    cfg, waveform = scoring_config(bw_eff, oversampling)
    full = cfg is not None
    if cfg is None:
        cfg = plain_config(bw_eff, k, oversampling)
    tx, rx = fe.build_chains(bw_eff, fs_eff)
    path = LoopbackPath(atten_db=recommended_loopback_atten_db(bw_eff), delay_ns=6.0)
    prof = PROFILES[profile]
    plan = planned_steps(prof, with_iip2=rx.params.im2.enabled, with_dpd=with_dpd)
    run = CalRun(k=k, bw_eff_hz=bw_eff, fs_eff_hz=fs_eff, waveform=waveform)
    ctx: dict = {"results": []}
    if full:
        try:
            snap = loopback_snapshot(tx, rx, path, cfg, drive_scale=0.12, seed=seed)
            ctx.update({"snap_before": snap, "evm_before": snap["evm_db"]})
            run.evm_before_db = float(snap["evm_db"])
        except Exception as e:      # noqa: BLE001
            run.rows.append(StepRow(k, bw_eff, fs_eff, "loopback_snapshot", "failed",
                                    detail=f"{type(e).__name__}: {e}"[:160]))
            full = False
    runners = _step_runners(tx, rx, cfg, path, prof, profile, with_dpd, None, 0.12, seed, ctx)
    for name in plan:
        if name == "final_loopback_evm" and not full:
            run.rows.append(StepRow(k, bw_eff, fs_eff, name, "skipped", detail=waveform,
                                    mechanism=MECHANISM.get(name, "")))
            continue
        try:
            res = runners[name]()
            ctx["results"].append(res)
            m, v = _metric(res)
            status = "ok" if res.passed in (True, None) else "degraded"
            if res.saturated:
                status = "degraded"
            run.rows.append(StepRow(k, bw_eff, fs_eff, name, status, m, v, res.passed,
                                    (res.notes or "")[:80], MECHANISM.get(name, "")))
            if name == "final_loopback_evm":
                run.evm_after_db = float(res.metrics_after.get("evm_db", np.nan))
        except Exception:      # noqa: BLE001
            tb = traceback.format_exc().splitlines()[-1]
            run.rows.append(StepRow(k, bw_eff, fs_eff, name, "failed", detail=tb[:160],
                                    mechanism=MECHANISM.get(name, "")))
        if log:
            r = run.rows[-1]
            log(f"  K={k:<3} {name:<22} {r.status:<9} {r.metric} {'' if r.value is None else f'{r.value:.2f}'} {r.detail}")
    return run


def compare_runs(runs: list[CalRun], degrade_db: float = 3.0) -> list[dict]:
    """Per step, the metric of each run (keyed by its label: K and effective
    bandwidth) next to the first run's reading; a passed step whose dB metric
    is worse than the reference by more than ``degrade_db`` is marked degraded."""
    ref = {r.step: r for r in runs[0].rows} if runs else {}
    out = []
    steps = [r.step for r in runs[0].rows] if runs else []
    for step in steps:
        row = {"step": step, "mechanism": MECHANISM.get(step, ""), "by_k": {}}
        for run in runs:
            r = next((x for x in run.rows if x.step == step), None)
            if r is None:
                continue
            status = r.status
            if (status == "ok" and ref.get(step) and r.value is not None and ref[step].value is not None
                    and r.metric and ("db" in r.metric.lower())):
                sense = -1 if any(t in r.metric for t in ("irr", "snr", "rejection")) else 1
                if sense * (r.value - ref[step].value) > degrade_db:
                    status = "degraded"
            row["by_k"][run.label] = (status, r.metric, r.value, r.detail)
        out.append(row)
    return out
