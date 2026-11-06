---
type: project_topic
status: active
summary: "开工前先读：vendored wifitrx 在 K ≠ 1 下会断在哪里、接收机里哪一步吃掉了多少 dB、YAML 浮点、numba 逐位相同的写法。"
tags: [mmw60, pitfalls, wifitrx, receiver]
contains: [pitfall, lesson, finding]
created: "2026-11-06"
updated: "2026-11-06"
related: [architecture-invariants.md, upclocking.md, external-validation.md]
authoring_mode: ai_generated
---

# 工程坑

## wifitrx 在 K ≠ 1 下的断点（都不改上游，在本库包一层）

- **`pilots._tables` 对 SCS 做精确相等匹配**（78.125e3 / 312.5e3），`tone_plan.standard`、`_ACTIVE_TONES*` 按 20/40/80/160/320e6 查表：
  把 `subcarrier_spacing_hz` 配成 312.5 kHz × K 直接 ValueError。→ 基准数字学 + `fs_eff`（upclocking.md §1）。
- **VHT 20 MHz 有 56 个有效音**（52 数据 + 4 导频），wifitrx 的 legacy 表给的是 11a 的 52：用 `tone_plan=contiguous(56)`，`pilot_positions` 在显式 plan 上按标准索引 ±7/±21 直接查，得到列 [21, 35, 7+28-1 …]；别用 `pilot_set="model"`。
- **`stf_waveform` 硬编码 0.8e-6 s 与 1.25e6 Hz**：在基准数字学上用没问题（K 只改 fs 的解释）。
- **wifitrx 的 `estimate_cfo` 只用 LTF 两段**（±SCS/2），STF 只是 AGC 激励："the estimators never look at it"。STF 粗估计是本库 `rx/cfo.py` 写的。
- **`run_full_cal` 在 K ≠ 1 直接失败**（第一步 `generate_ofdm_with_pilots`），另有绝对频偏探针（4.8 / 5.1 MHz、11 / 17 / 23 MHz）、固定样本窗（`max_lag = 32`）、320 MHz 调的阈值。里程碑 1 的校准表要逐项记这些。
- **`TDLChannel.k_db` 只让第一个 tap 变 Rician**，尾部功率不变；要 LOS 占优（抑制 GI 之外的 ISI）用本库 `channel.ExponentialTdl(los_k_db=…)`。
- `EvmBudget` 默认 `t_fft_s = 12.8e-6`：用时必须传 `1/SCS_eff`。

## 接收机里每一步的代价（K = 8、flat、MCS0、PER = 1e-2 处的 SNR；`tests/test_link.py`）

| 配置 | SNR@1e-2 |
|---|---|
| BCC 并集界（d_free = 10，32768 bit） | ≈ 2.0 dB |
| genie CSI、不做 CPE、不估 CFO（解码器本身） | 1.5–2 dB（压在并集界上） |
| genie CSI + 逐符号 4 导频 CPE | ≈ 4.4 dB |
| L-LTF 信道估计（平滑 3 音）+ CPE + STF/LTF CFO 估计（默认接收机） | ≈ 4.9 dB |
| 同上，不平滑 | ≈ 6.0 dB |
| 同上，平滑 9 音 | ≈ 4.1 dB |

- **逐符号导频 CPE 的代价来自尾部，不是方差**：4 个导频在 SNR 3 dB 下相位估计 σ ≈ 14°，平均损失只有 0.3 dB，但一个符号的 4 导频和碰巧抵消时整符号 52 bit 被转掉，交织只在符号内，Viterbi（d_free 10）救不回 → 这包就错。1262 符号 × 每符号 ~1e-4 的尾概率就是 PER 量级。跨符号平滑 CPE 是接收机改进项（ROADMAP）。
- **CFO 估计开着就必须开 CPE**：估计残差（~0.02 SCS）的相位斜坡跨 1262 符号累积到多个弧度，没有 CPE 整包必错（`genie CSI, CPE off, CFO est on` → PER = 1）。
- **信道估计平滑要和相干带宽比**：K = 16 时音距 5 MHz，15 ns rms 的信道相干带宽 ~10 MHz，3 音平滑把估计拉偏到 EVM −7 dB；LOS 占优的默认信道纹波小才无妨。

## 文献对不上时的几个"口径"而非"参数"

- **OBO 参考点**：11ad EM 的 CMOS Rapp（p = 0.81）P1dB 在 Psat 以下 9.5 dB；"OBO 8 dB" 相对 Psat 是平均功率在 P1dB 之上 1.5 dB（孤立 EVM −17 dB），相对 P1dB 则是 −26 dB 量级。两种都跑，哪种是原文的意思写进 external-validation。
- **SNR 口径**：每有效子载波 Es/N0 与每样本 SNR 差 10·log10(os·N_FFT/N_active) = 3.59 dB（os = 2，64 点，56 音）。
- **信道**："802.11ad CR 信道"在没有 tap 表时只能用 PDP 代替；选 rms / LOS 比的依据是原文曲线自己给出的可观测事实（16× 不比 8× 差 ⇒ 50 ns 之外能量可忽略；曲线 3 dB 内从 1 到 1e-3 ⇒ 近 AWGN）。

## 工具层

- **PyYAML 把 `73.44e9` 读成字符串**（YAML 1.1 要求有小数点且指数带符号）：spec 表里的浮点一律写成 `73.44e+9`；`spec.py` 的测试会在算术时暴露。
- **numba 与 numpy 内核逐位相同的写法**：两边都是"每个候选 = 一次加法 (metric[prev] + (a·la + b·lb))、严格 `c1 < c0` 选路"，不用 `np.minimum` 以外的归约、不改运算顺序；`MMW60_NO_JIT=1` 走 numpy 内核，`tests/test_phy.py` 比对解码比特。
- **polar_tx 的 vendor_check 会剥掉所有前导 `# ` 行**，而 wifitrx 自己的文件就以 `# Vendored from PA_DPD…` 开头：本库的检查器只剥自己加的两行头（`_strip_header`），并检查 `__init__.py`。
- `tools/example_drift.py` 与 `fingerprint_walk.py` 是 d2d_link 的文件原样（ruff 对它们放开 E501）。
