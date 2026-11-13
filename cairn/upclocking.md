---
type: project_topic
status: active
summary: "IMMW upclocking 在本库里怎么建（基准数字学 + 时钟 ×K），以及 Liu 2025 的 SCS ≥ 5.88 MHz / K > 4.7 门槛从 L-STF 自相关范围自己推一遍。"
tags: [mmw60, upclocking, cfo, liu2025]
contains: [derivation, decision, pitfall]
created: "2026-11-06"
updated: "2026-11-06"
related: [external-validation.md, architecture-invariants.md, engineering-pitfalls.md]
authoring_mode: ai_generated
---

# Upclocking（拓扑 B）

## 1. 建模方式：PHY 不动，时钟 ×K

Liu 2025 §III-B 的定义是"把 802.11ac 的子载波间距和信道带宽乘一个倍数，OFDM 符号时间相应缩短，基带处理不变"。本库按字面实现：
wifitrx 在**基准数字学**（312.5 kHz / 20 MHz / 64 点 / GI 1/4）生成与解调，样本时钟被重新解释为 `fs_eff = fs_base × K`
（`src/mmw60/upclock.py::UpclockedPhy`）。所有**物理量**——CFO（Hz）、相噪 PSD（Hz）、信道时延（s）、噪声密度——在 `fs_eff` 域施加；估计器也用 `fs_eff`。

- K = 1 就是未改动的 wifitrx 链（铁律 2 的回归锚，`tests/test_laws.py::test_law2_*`）。
- 不这样做的代价见 engineering-pitfalls：把 wifitrx 的 `subcarrier_spacing_hz` 配成 312.5 kHz × K 会在 `pilots._tables` 的精确匹配上抛 ValueError。

| K | SCS | T_FFT | GI | L-STF 周期 | STF 捕获 | LTF 捕获 | 2.94 MHz 占子载波 |
|---|---|---|---|---|---|---|---|
| 1 | 312.5 kHz | 3.2 µs | 800 ns | 0.8 µs | ±625 kHz | ±156 kHz | 9.40 |
| 4 | 1.25 MHz | 800 ns | 200 ns | 200 ns | ±2.5 MHz | ±625 kHz | 2.35 |
| 8 | 2.5 MHz | 400 ns | 100 ns | 100 ns | ±5 MHz | ±1.25 MHz | 1.18 |
| 16 | 5 MHz | 200 ns | 50 ns | 50 ns | ±10 MHz | ±2.5 MHz | 0.59 |
| 32 | 10 MHz | 100 ns | 25 ns | 25 ns | ±20 MHz | ±5 MHz | 0.29 |

（`UpclockedPhy.summary()`；原文 Table I 的 16× 一列是 802.11be 基准 78.125 kHz × 16 = 1.25 MHz，与 4×/8× 不是同一尺度，本库复现按 11ac 基准。）

## 2. 门槛推导：SCS ≥ 5.88 MHz ⇔ K > 4.7 是 L-STF 自相关的捕获范围

一个周期为 T 的重复训练序列，自相关 Σ conj(r[n])·r[n+T] 的相位是 2π·Δf·T，只能在 (−π, π] 内读出，所以无歧义范围是 **|Δf| < 1/(2T)**。

- L-STF：T_stf = 0.8 µs / K → 范围 ±625 kHz × K。原文说的"STF 有效子载波间距 4 × 312.5 kHz = 1.25 MHz"就是 1/T_stf。
- L-LTF：T_ltf = 3.2 µs / K → 范围 ±156.25 kHz × K = ±SCS/2。

要接住 Δf_max = 40 ppm × 73.44 GHz = 2.9376 MHz：

- 用 STF：625 kHz × K ≥ 2.9376 MHz ⇔ **K ≥ 4.70**；写成"训练场有效间距 1/T_stf ≥ 2·Δf_max = 5.875 MHz"就是原文的 5.88 MHz 门槛（`liu2025.k_threshold_stf`）。
- 只用 LTF：156.25 kHz × K ≥ 2.9376 MHz ⇔ K ≥ 18.8（`liu2025.k_threshold_ltf_only`）——**K = 16 也接不住**，所以原文的 8×/16× 能工作这一事实本身说明其接收机在跑 STF 粗估计（见 external-validation.md 的矛盾记录）。

仿真里的表现（`tests/test_models.py::test_stf_estimator_*`、示例 00 首行表）：K = 4 时 STF 估计读出 2.9376 − 2 × 2.5 = −2.06 MHz（混叠到范围内），再经 LTF 细估计也无法回到真值，整包 ICI → PER = 1；K = 8 / 16 估计误差 < 0.02 SCS。

## 3. 门槛不是波形的性质——示例 01

把 L-LTF 的整数子载波模糊用频域互相关解开（`rx/cfo.py::ltf_integer_cfo`，差分相关，±8 音），K = 4 的 2.35 个子载波偏移被分成 0.35（LTF 细估计）+ 2（整数搜索）。
这之后 K = 4 能不能活取决于 0.8 µs 符号、200 ns GI 下的相噪与 PA，数字见 external-validation.md §4 与 LOG。

## 4. 随 K 变的东西 / 不变的东西

- 变：CFO 占子载波的份额（∝ 1/K）、相噪在 T_FFT 内的 CPE/ICI 划分（T_FFT ∝ 1/K，CPE 份额随 K 增大）、信道时延展宽相对 GI（GI ∝ 1/K，见 `derived.isi_beyond_gi_k16_db`）、转换器速率（里程碑 1）。
- 不变：无记忆 PA 的失真（Rapp 不含时间常数）、每包符号数、交织 / 编码、导频布局、PER–SNR 的 AWGN 极限。
