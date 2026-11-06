---
type: project_topic
status: active
summary: "里程碑 0 的对外校验：选了什么参照、拿不到什么、什么是本库自己定的、逐条差值、发现与坑。"
tags: [mmw60, external-validation, liu2025, per]
contains: [comparison-table, finding, scope, pitfall]
created: "2026-11-06"
updated: "2026-11-06"
related: [upclocking.md, spec-sources.md, engineering-pitfalls.md]
authoring_mode: ai_generated
---

# 对外校验：Liu 2025 Table II / Fig. 4

## 1. 参照是什么、为什么、拿不到什么

- **参照**：Liu et al., "Wi-Fi 8: Embracing the Millimeter-Wave Era"，arXiv 2309.16813 **v1** 的 Fig. 4（PER–SNR，K = 4/8/16 × MCS 0/1/4，有损伤一组），读图值在 `src/mmw60/data/spec/liu2025_fig4.yaml`（±0.3 dB）。选它因为这是 IMMW upclocking 唯一带数字的公开仿真，而且它的设定（VHT、CFO、1 极 1 零相噪、Rapp）每一项本库都能逐一关掉，是 Halo 对 serdespy 那种"两边各自独立算"的校验。
- **拿不到**：刊出版（IEEE Comm. Mag. 2025-03）；v2 删掉了图；Rapp 参数、OBO 定义、CR 信道实现、SNR 口径、相噪加在哪一侧、基准带宽、接收机细节（定时、信道估计、跟踪）——这些全是 `source: assumed`（`spec-sources.md`）。
- **两边共享因而不算校验的东西**：没有。原文的仿真器未知，本库没有任何代码或数字来自它，除了 Table II 的设定与 Fig. 4 的读图值。

## 2. 配置

`configs/liu2025_table2.yaml`（`liu2025_table2(k, mcs)`）：VHT 20 MHz × K，4096 B，73.44 GHz，20 + 20 ppm → 2.9376 MHz，相噪 −93 dBc/Hz（1 MHz / 100 MHz）TX+RX 各一份，Rapp（11ad EM）OBO 8 dB，信道指数 PDP 7 ns + LOS/散射 10 dB，接收机 L-STF 粗 + L-LTF 细 CFO 估计、L-LTF 信道估计 3 音平滑、逐符号 4 导频 CPE、ZF、max-log LLR、软 Viterbi。三组曲线：

| 组 | 含义 |
|---|---|
| impaired | Table II 按字面：LOS/散射信道，OBO 相对 Psat |
| ideal | 关掉 CFO / 相噪 / PA，信道与接收机不变 |
| flat | 同样的损伤，信道换成 flat（原文曲线自己给出的可观测事实：近 AWGN）|

## 3. 对表（PER = 1e-2 处的 SNR，dB；`python tools/external_check.py`，每点 ≤ 600 包或 30 个错包，读图精度 ±0.3 dB）

| K | MCS | 原文 Fig. 4 | impaired（字面） | 差 | flat | 差 | ideal |
|---|---|---|---|---|---|---|---|
| 4 | 0 / 1 / 4 | PER = 1 | PER = 1（0–8 / 3–11 / 12–26 dB 全部） | ✓ | PER = 1 | ✓ | 5.50 / 8.64 / 16.04 |
| 8 | 0 | 4.2 | 6.59 | +2.39 | 5.35 | +1.15 | 6.10 |
| 16 | 0 | 4.2 | 6.68 | +2.48 | 5.18 | +0.98 | 6.40 |
| 8 | 1 | 7.5 | 9.83 | +2.33 | 8.59 | +1.09 | 9.00 |
| 16 | 1 | 7.5 | 9.80 | +2.30 | 8.82 | +1.32 | 9.50 |
| 8 | 4 | 19.7 | 21.00 | +1.30 | 20.42 | +0.72 | 17.00 |
| 16 | 4 | 19.0 | 21.83 | +2.83 | 19.84 | +0.84 | 17.00 |

- **验收**：K = 4 三个 MCS 全部 PER = 1 ✓；K = 8 / 16 能工作 ✓；曲线形状一致（从 PER 1 到 1e-2 跨 2.5–4 dB，16× 在 MCS4 不比 8× 好——这一点与原文相反，见 §4.2）；
  PER = 1e-2 处的 SNR 差：字面读法 +1.3 … +2.8 dB（**超过 1 dB**），flat 信道 +0.7 … +1.3 dB（MCS4 两条与 16× MCS0 在 1 dB 内；8× MCS0、两条 MCS1 为 1.1–1.3 dB，与 ±0.3 dB 读图精度加上约 ±0.5 dB 的仿真统计散布同量级——同一 flat MCS4 配置上一轮 300 包灵敏度行读 19.67、这轮 600 包读 20.42）。超过的原因在 §4，不调参数。
- 推导数（`examples/derived.yaml` 守着）：K = 8 MCS0 字面 6.59 dB、flat 5.35 dB，信道假设值 1.24 dB；K = 8 MCS1 字面 9.83 dB、flat 8.59 dB。
- 灵敏度（K = 8 MCS4，300 包 / 20 错，1 dB 步）：OBO 自 P1dB 17.27；理想 PA 17.27；PN 只加 RX 22.04；纯 Rayleigh（无 LOS）到 26 dB 仍 PER 0.21；不平滑信道估计 26.0；
  上一轮的 flat 行 19.67（与原文 19.7 差 0.03 dB）。
- 字面读法诊断行：CFO 估计全关、只做导频相位跟踪，SNR 20 dB，K = 4 / 8 / 16 全部 PER = 1（20/20）。
- 示例 01（整数子载波模糊解算，其余同字面组）：K = 4 MCS0 6.00、MCS1 9.21、MCS4 22.00 dB；K = 8 / 16 与字面组逐点相同（估计器在范围内时整数项为 0）。

## 4. 发现

1. **原文的 CFO 句子与它自己的论证矛盾**：§V-A 说没做 CFO 估计补偿，§V-B 的"K > 4.7"却是 L-STF 自相关捕获范围的结论；全关时 K = 8 / 16 也整包 ICI（示例 00 诊断行 PER = 1）。只用 L-LTF 要 K ≥ 18.8（`upclocking.md` §2）。
2. **信道**：原文曲线 3 dB 内从 1 到 1e-3，且 16× 处处不比 8× 差 → 信道近 AWGN、50 ns 外无能量。任何"像样的"CR 散射模型都会把 K = 8 的曲线右移 ~2 dB（LOS/散射 10 dB + 7 ns）或更多（纯 Rayleigh：曲线拉平）。
3. **PA**：11ad EM 的 CMOS Rapp 在 OBO 8 dB（相对 Psat）下孤立 EVM −17 dB，16-QAM 3/4 到不了 1e-2；原文 MCS4 在 19–19.7 dB 工作，说明其 PA 在"OBO 8 dB"下温和得多——要么参数不同，要么 OBO 相对 P1dB。
4. **接收机**：解码器压在并集界上；逐符号导频 CPE 的尾部贵 2.5 dB（MCS0）；这解释了为什么本库 flat 信道下 MCS0 在 5.35 dB 而不是理论的 2 dB，与原文的 4.2 dB 差 +1.15 dB——剩下的差是接收机实现（原文的信道估计 / 跟踪细节未知）。
5. **示例 01**：整数子载波模糊解开后 K = 4 工作（MCS0 6.0 / MCS1 9.2 / MCS4 22.0 dB，比 K = 8 差 0.6 / 0.6 / 1.0 dB）——原文的门槛是估计器的性质，不是波形的。
6. **16× 在 MCS4 比 8× 差 0.8 dB（字面组）而原文好 0.7 dB**：K = 16 的 GI 只有 50 ns，7 ns rms 的散射尾（−31 dB）加上 5 MHz 音距上 3 音平滑的偏差，刚好吃掉相噪 ICI 减小带来的好处；flat 组里两者 20.42 / 19.84。

## 5. 坑

见 `engineering-pitfalls.md`（YAML 浮点、OBO 参考点、平滑跨度与相干带宽、CFO 估计必须配 CPE）。
