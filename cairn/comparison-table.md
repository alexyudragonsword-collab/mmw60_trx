---
type: project_topic
status: active
summary: "同台表（ROADMAP A3）：每种方案（拓扑 × 波形）在同一个前端实例上的 MCS 上限、吞吐、谱效率、EIRP 余量、pJ/bit；解析 / 时域 / wifitrx EvmBudget 三方对账；LO 三种剖面并排；哪些假设决定结论。"
tags: [mmw60, comparison-table, budget, power, evm-budget, law-2]
contains: [comparison-table, finding, decision, pitfall]
created: "2026-11-07"
updated: "2026-11-07"
related: [topology-b.md, architecture-invariants.md, spec-sources.md, upclocking.md]
authoring_mode: ai_generated
---

# 同台表（示例 04，`tools/budget_report.py`）

## 1. 表是什么

`mmw60.compare.scheme_matrix` 把 `TOPOLOGIES × WAVEFORMS` 的 8 个格子全部点名：建好的格子有配置和数字
（拓扑 B × `be`：K = 1 的 WiFi 7 链；拓扑 B × `be_upclocked`：K = 1 / 4 / 8 / 16 / 32），没建的写明哪个里程碑带来它
（拓扑 A × `be`：里程碑 1 / A1，另一会话；拓扑 B × `ay_ofdm` / `ay_sc`：里程碑 3），不成立的组合写 n/a
（A 不改波形；ay 是 B 的硬件）。`tests/test_compare.py::test_law2_matrix_names_every_topology_x_waveform_pair` 守着矩阵完整。

**一个 `Frontend60` 实例给每一行**（铁律 2 的完整测试 `test_law2_every_scheme_on_the_shared_frontend_reads_the_k1_evm_when_ideal`：
理想前端实例共用，ppm = 0 / 理想 LO / 理想 PA 下每种已建方案的 EVM 与 K = 1 差 < 0.1 dB；A 与 ay 的行以它们的里程碑为由 skip）。
LO 链是该实例的一部分：6 GHz 的 K = 1 行也跑在共用的 60 GHz 剖面上（它自己的 `wifitrx_wifi7` 设置只在"单独仿真"时生效——§4）。
这是有意的：表比较的是"同一套硬件、时钟 ×K"，不是"两颗不同的芯片"。

每行的列（`compare.Row`）：数字学（BW_eff、SCS、T_sym）、CFO（Hz、子载波数、L-STF 是否接住）、解析底板及其分项、
同格的时域 EVM（flat、无噪声）、wifitrx `EvmBudget` 喂同样分项的预测、MCS 上限（未校准 / 校准后——用示例 03 **实测**的 IRR，
`derived.irr_after_cal_measured_db`，按不大于该行带宽的最近一档）、上限处的速率与 b/s/Hz、PA 工作点对共用 EIRP 上限的余量、
功率分块 pJ/bit（§5）。

## 2. 数字（`examples/expected/04_comparison_table.txt`）

基准 11ac 20 MHz；60.48 GHz；40 ppm = 2.42 MHz；PA Psat 15 dBm、OBO 8 dB → Pout 7 dBm（EIRP 余量 +33 dB，天线 0 dBi）：

| 行 | BW_eff | T_sym | CFO [sc] | STF | 底板 / 时域 / EvmBudget [dB] | MCS 上限（IQcal） | Mb/s | pJ/bit | 结论 |
|---|---|---|---|---|---|---|---|---|---|
| be K=1 @6 GHz（WiFi 7 链） | 20 M | 4.0 µs | 0.77 | 接住 | −17.2 / −17.0 / −17.5 | MCS2（2） | 20 | 8720 | PA 限 |
| be_upclocked K=1 @60.48 | 20 M | 4.0 µs | 7.74 | **失锁** | −17.2 / +15.6 / −17.5 | MCS2 | 20 | 10771 | 不能：CFO |
| K=4 | 80 M | 1.0 µs | 1.94 | 接住 | −17.3 / −17.2 / −17.6 | MCS2 | 78 | 3803 | PA 限 |
| K=8 | 160 M | 500 ns | 0.97 | 接住 | −17.4 / −17.3 / −17.6 | MCS2 | 156 | 2456 | PA 限 |
| K=16 | 320 M | 250 ns | 0.48 | 接住 | −17.1 / −16.9 / −17.2 | MCS2 | 312 | 1694 | PA 限 |
| K=32 | 640 M | 125 ns | 0.24 | 接住 | −15.2 / −15.3 / −15.2 | MCS1（2） | 416 | 1869 | PA 限（IQ 压到 MCS1） |

基准 11be 80 MHz：

| 行 | BW_eff | 底板 / 时域 / EvmBudget | MCS 上限（IQcal） | Mb/s | pJ/bit | 结论 |
|---|---|---|---|---|---|---|
| be K=1 @6 GHz | 80 M | −17.1 / −17.3 / −17.5 | MCS2（2） | 108 | 2401 | PA 限 |
| K=4 | 320 M | −16.6 / −16.6 / −16.9 | MCS2（2） | 432 | 1248 | PA 限 |
| K=8 | 640 M | −14.9 / −14.5 / −15.1 | MCS1（2） | 576 | 1381 | PA 限 |
| K=16 | 1.28 G | −11.2 / −10.2 / −11.3 | MCS0（2） | 576 | 2162 | IQ 限 |
| K=32 | 2.56 G | −5.5 / −3.8 / −5.5 | —（2，38 dB） | — | — | 不能：IQ |

- 两个基准合在一张表上，11be 80 MHz × 4（320 MHz）以 432 Mb/s、1248 pJ/bit 居首；20 MHz 基准里 K = 16 的 1694 pJ/bit 到 K = 32 升到 1869。
- 11be 行的 pJ/bit 自 A2 起含 LDPC 解码块（1944 码、30 次迭代、每边每迭代 2 次加等效：21–22 pJ/bit，占 1–2 %）；11be 格的时域 EVM 自 A2 起来自编码的 MCS0 数据域而不是随机 16-QAM 载荷，表里的时域列随之动了 ≤ 0.3 dB（示例 02 同）。
- K = 1 的 WiFi 7 链在同一套硬件上是 8720 pJ/bit，是 K = 16 的 5.1 倍——不是硬件差，是 20 Mb/s 分母小（§6 ①）。
- MCS 上限在 ≤ 320 MHz 全部是 PA 的 MCS2（OBO 8 dB 自 Psat 的 Rapp 隔离 EVM −18.1 dB）；IQ 从 640 MHz 开始压上限，1.28 GHz 压到 MCS0，2.56 GHz 不能。校准后（实测 IRR）全部回到 PA 限的 MCS2——与 `topology-b.md` §2 的网格一致。

## 3. 三方对账

- **解析底板 vs 时域 EVM**：底板 ≤ −8 dB 且 CFO 接住的行，差 −0.1 … +1.1 dB（11be 80 × 16 的 +1.1 最大）；2.56 GHz 行 +1.7 dB 不判（IQ 镜像 −5.8 dB 已不是小扰动，线性叠加不成立）；60.48 GHz 上 K = 1 的 +32.8 dB 不判（CFO 7.7 个子载波失锁，接收机输出无意义）。
- **wifitrx `EvmBudget` vs 解析底板**：每行差 −0.0 … −0.4 dB。两者只在相噪一项口径不同：EvmBudget 积分 10 kHz–100 MHz 的 IPN 再乘 (1 − CPE 跟踪份额)，
  本库按 ICI 权重积到 fs_eff/2——K = 8 处 −31.1 对 −28.0 dB、K = 32 处 −35.5 对 −31.6 dB（EvmBudget 乐观 3–4 dB：它不含 100 MHz 以上的 −133 dBc/Hz 底板，也不含 1–10 kHz）。
  跟踪份额随 K 升：T_FFT 变短，8.9 %（K = 1）→ 50 %（K = 8）→ 82 %（K = 32）。总量仍对得上，因为 PA 项 −18.1 dB 盖住一切（§6 ③）。

## 4. LO 三种剖面并排（各自的 `Frontend60`；`PhaseNoiseConfig.model`）

| 模型 | IPN 10 kHz–100 MHz | K = 8：相噪 ICI / 底板 / 时域 | K = 32：底板 / 时域 |
|---|---|---|---|
| `pole_zero`（11ad EM 形状、Liu 的数） | −31.1 dBc | −28.0 / −17.4 / −17.3 | −15.2 / −15.3 |
| `wifitrx_wifi7`（WiFi 7 频综，vendored 剖面） | −46.9 dBc | −49.6 / −17.8 / −18.1 | −15.3 / −15.5 |
| `profile`：pllsim wu19 剖面 × N（+19.7 dB，`assumed.lo_multiplier_law`） | −33.2 dBc | −32.3 / −17.7 / −17.8 | −15.2 / −15.5 |

WiFi 7 频综好 16 dB IPN，底板只好 0.4 dB：在 OBO 8 dB 处 LO 不是瓶颈。pllsim 剖面经理想 ×N 与 Liu 的 pole-zero 同量级（差 2 dB）——
这条是"WiFi 7 全链路四条整合"里的"pll 剖面替换解析相噪"：接口已通，倍频器自身的底噪与杂散等 pll_simulator 的 D2。

## 5. pJ/bit（`mmw60.power`，Halo 示例 41 的口径：公开数系数，读比值不读总量）

分块（每链路方向）：PA 直流（Pout / PAE(Pout)，B 类规律自 `assumed.pa60_pae_max` 20 %）、两只频综（定值，`assumed.pll60_power_mw` 40 / `pll_sub7` 20）、
I/Q DAC + I/Q ADC（Walden 70 fJ × 2^ENOB(fs_eff) × fs_eff）、DPD（dsp_ip 140 项 × Horowitz 运算能耗 × 4·BW）、基准尺寸的 IFFT + FFT（时钟 ×K）、
11ac 的软判决 Viterbi 或 11be 的 min-sum LDPC（每边每迭代 2 次加等效、按最大迭代数计）。不计流水线寄存器、时钟树、存储、LNA / 混频 / 滤波。

K = 8（20 MHz 基准，156 Mb/s）：pa 404、lo 513、conv 1040、dpd 474、fft 17、dec 10 → 2456 pJ/bit。随 K 升，PA 与 LO 按速率摊薄，
转换器因 ENOB 随速率下降摊得慢（K = 16 → 32 从 735 到 780），DPD 随带宽涨（K = 32 处 711，超过 PA 的 151）。

**哪些假设决定结论**（示例 04 §6，解析侧在每个系数的区间端点重跑）：

| 旋钮 | 端点 | MCS 上限 | pJ/bit 倍率（各行 min … max） | pJ/bit 排名 |
|---|---|---|---|---|
| Walden FoM 38.4 / 120.2 fJ | 两端 | 不动 | ×0.80–0.88 / ×1.20–1.32 | 不变 |
| 数字工艺 45 → 7 nm（×0.175） | | 不动 | ×0.57–0.96 | **变** |
| 频综功耗 ×0.5 / ×2 | | 不动 | ×0.81–0.97 / ×1.06–1.38 | ×0.5 时变（相邻两行只差 1 %） |
| PA 峰值 PAE 10 % / 30 % | | 不动 | ×1.05–1.37 / ×0.88–0.98 | 10 % 时变 |
| **PA 回退 −2 / +2 dB** | | **7 行降一档 / 8 行升一档** | ×1.01–1.64 / ×0.66–0.99 | 变 |
| 转换器 ENOB 法则 1 bit/octave | | 不动 | ×0.86–2.35 | **变** |
| 校准后 IRR：假设 45 dB 对实测 | | 不动 | ×1.00 | 不变 |

结论：MCS 上限只被 PA 回退决定；pJ/bit 的排名被数字工艺节点、ENOB 法则和低 PAE 改写，被 Walden FoM 的区间不改写；频综功耗减半只换了相邻两行的次序（它们本来只差 1 %）。

## 6. 被推翻的判断

1. 以为"WiFi 7 芯片 K = 1"行是 60 GHz 行要追的效率参照——同一套硬件在 20 Mb/s 上是最差的 pJ/bit（8720），因为 LO、PA、转换器的功耗几乎不随速率降；
   同速率量级的比较才公平：11be 80 MHz K = 1（108 Mb/s，2379）与 11ac 20 MHz K = 8（156 Mb/s，2456）相当。
2. 以为 K 越大 pJ/bit 一定越低——20 MHz 基准上 K = 32 比 K = 16 差（1869 对 1694）：IQ 把上限压到 MCS1，DPD 项随带宽涨过了 PA 项。
3. 以为 EvmBudget 会和本库底板对不上（相噪口径差 3–4 dB）——总量差 ≤ 0.4 dB，因为每一行都是 PA 项主导；只有把 PA 回退拉大或 DPD 之后，口径差才会露出来。
4. 以为 A2 第一条（实测 IRR 替换假设 45 dB）会改网格结论——≤ 640 MHz 实测 ≥ 46.8 dB 比假设好，2.56 GHz 的 38.4 dB 仍回到 PA 限的 MCS2：一格都不动。
5. 以为铁律 2 的完整测试可以沿用"每个配置自己 `.ideal()`"——`ideal()` 改的是配置，硬件在实例里；共用一个按损伤配置建的 `Frontend60`，`ideal()` 的行照样带着它的 PA 和 IQ（第一版测试读出 −17.3 dB）。改为共用一个**理想**实例。

## 7. 留下的（ROADMAP A3 剩余）

拓扑 A 的行（等 A1 落地，`PENDING` 里的那格）；Halo ADC 校准接入（要 vendor halo 的 adc 模块，现在转换器列是 ENOB 法则）；
PA_DPD 的 PA / DPD 进 wifitrx 链（K = 1 可行，K > 1 等 D3 的"记忆按秒参数化"）；11be 的 LDPC 解码功耗；校准列（`calcheck.run_cal_at` 实跑进表，现用示例 03 实测 IRR 的表）。
