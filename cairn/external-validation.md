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
| interp | 两个原文没定义的输入按另一种读法：flat 信道 + OBO 相对 P1dB |

## 3. 对表（PER = 1e-2 处的 SNR，dB；`python tools/external_check.py`）

（全量运行后由 `examples/expected/00_liu2025_per_vs_snr.txt` 与 external_check 的输出填入。）

## 4. 发现

1. **原文的 CFO 句子与它自己的论证矛盾**：§V-A 说没做 CFO 估计补偿，§V-B 的"K > 4.7"却是 L-STF 自相关捕获范围的结论；全关时 K = 8 / 16 也整包 ICI（示例 00 诊断行 PER = 1）。只用 L-LTF 要 K ≥ 18.8（`upclocking.md` §2）。
2. **信道**：原文曲线 3 dB 内从 1 到 1e-3，且 16× 处处不比 8× 差 → 信道近 AWGN、50 ns 外无能量。任何"像样的"CR 散射模型都会把 K = 8 的曲线右移 ~2 dB（LOS/散射 10 dB + 7 ns）或更多（纯 Rayleigh：曲线拉平）。
3. **PA**：11ad EM 的 CMOS Rapp 在 OBO 8 dB（相对 Psat）下孤立 EVM −17 dB，16-QAM 3/4 到不了 1e-2；原文 MCS4 在 19–19.7 dB 工作，说明其 PA 在"OBO 8 dB"下温和得多——要么参数不同，要么 OBO 相对 P1dB。
4. **接收机**：解码器压在并集界上；逐符号导频 CPE 的尾部贵 2.5 dB（MCS0）；这解释了为什么本库 flat 信道下 MCS0 在 4.4–4.9 dB 而不是理论的 2 dB，也与原文的 4.2 dB 同量级。
5. **示例 01**：整数子载波模糊解开后 K = 4 工作——原文的门槛是估计器的性质。

## 5. 坑

见 `engineering-pitfalls.md`（YAML 浮点、OBO 参考点、平滑跨度与相干带宽、CFO 估计必须配 CPE）。
