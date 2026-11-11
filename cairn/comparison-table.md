---
type: project_topic
status: active
summary: "同台表（ROADMAP A3）：每种方案（拓扑 × 波形）在同一个前端实例上的 MCS 上限、吞吐、谱效率、EIRP 余量、pJ/bit；解析 / 时域 / wifitrx EvmBudget 三方对账；LO 三种剖面并排；哪些假设决定结论。"
tags: [mmw60, comparison-table, budget, power, evm-budget, law-2]
contains: [comparison-table, finding, decision, pitfall]
created: "2026-11-07"
updated: "2026-11-11"
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
| **拓扑 A**：be IF 延伸 @60.48 | 20 M | 4.0 µs | 7.74 | MLO 预补偿后接住 | −17.3 / −18.2 / −17.3 | MCS2（2） | 20 | 29291 | PA 限 |
| be K=1 @6 GHz（WiFi 7 链） | 20 M | 4.0 µs | 0.77 | 接住 | −17.2 / −17.5 / −17.2 | MCS2（2） | 20 | 8720 | PA 限 |
| be_upclocked K=1 @60.48 | 20 M | 4.0 µs | 7.74 | **失锁** | −17.2 / +13.1 / −17.2 | MCS2 | 20 | 10771 | 不能：CFO |
| K=4 | 80 M | 1.0 µs | 1.94 | 接住 | −17.3 / −17.4 / −17.3 | MCS2 | 78 | 3803 | PA 限 |
| K=8 | 160 M | 500 ns | 0.97 | 接住 | −17.4 / −17.4 / −17.4 | MCS2 | 156 | 2456 | PA 限 |
| K=16 | 320 M | 250 ns | 0.48 | 接住 | −17.1 / −17.2 / −17.1 | MCS2 | 312 | 1694 | PA 限 |
| K=32 | 640 M | 125 ns | 0.24 | 接住 | −15.2 / −15.4 / −15.2 | MCS1（2） | 416 | 1869 | PA 限（IQ 压到 MCS1） |

基准 11be 80 MHz（最后一行是拓扑 A 在芯片最宽的 320 MHz 信道上）：

| 行 | BW_eff | 底板 / 时域 / EvmBudget | MCS 上限（IQcal） | Mb/s | pJ/bit | 结论 |
|---|---|---|---|---|---|---|
| **拓扑 A**：be IF 延伸 @60.48 | 80 M | −17.2 / −18.2 / −17.3 | MCS2（2） | 108 | 6289 | PA 限 |
| be K=1 @6 GHz | 80 M | −17.1 / −18.0 / −17.1 | MCS2（2） | 108 | 2393 | PA 限 |
| K=4 | 320 M | −16.6 / −17.3 / −16.6 | MCS2（2） | 432 | 1241 | PA 限 |
| K=8 | 640 M | −14.9 / −15.2 / −15.0 | MCS1（2） | 576 | 1381 | PA 限 |
| K=16 | 1.28 G | −11.2 / −10.9 / −11.2 | MCS0（2） | 576 | 2162 | IQ 限 |
| K=32 | 2.56 G | −5.5 / −4.7 / −5.5 | —（2，38 dB） | — | — | 不能：IQ |
| **拓扑 A**：11be 320 MHz，IF 延伸 | 320 M | −17.2 / −17.9 / −17.2 | MCS2（2） | 432 | 2240 | PA 限 |

- **拓扑 A 对拓扑 B，同样 320 MHz**：合规口径都是 MCS2、432 Mb/s，A 2240 对 B 1241 pJ/bit；解码器口径都是 MCS4、865 Mb/s，A 1127 对 B 628 pJ/bit。A 每比特贵 1.8 倍：
  芯片的 PA 当驱动级（682 pJ/bit，294 mW）、每端两个频综（278 对 185）、4 倍过采样的转换器（750 对 531）。A 的底板与 B 相同（都是 60 GHz PA 的 −18.1 dB），
  带宽止于芯片的 320 MHz。细节见 `topology-a.md`。拓扑 A 行的“芯片残差 −42.0 dB、芯片 LO −41.1 dB”是它独有的两项，B 独有的是未校准 IQ 镜像与 ENOB(fs_eff) 的转换器（示例 04 §3 逐行标出）。
- 两个基准合在一张表上，11be 80 MHz × 4（320 MHz）以 432 Mb/s、1241 pJ/bit 居首；20 MHz 基准里 K = 16 的 1694 pJ/bit 到 K = 32 升到 1869。
- 11be 行的 pJ/bit 自 A2 起含 LDPC 解码块（1944 码、30 次迭代、每边每迭代 2 次加等效，按该行上限 MCS 的码率计：14–22 pJ/bit，占 1–2 %）；11be 格的时域 EVM 自 A2 起来自编码的 MCS0 数据域而不是随机 16-QAM 载荷，表里的时域列随之动了 ≤ 0.3 dB（示例 02 同）。
- K = 1 的 WiFi 7 链在同一套硬件上是 8720 pJ/bit，是 K = 16 的 5.1 倍——不是硬件差，是 20 Mb/s 分母小（§6 ①）。
- MCS 上限在 ≤ 320 MHz 全部是 PA 的 MCS2（OBO 8 dB 自 Psat 的 Rapp 隔离 EVM −18.1 dB）；IQ 从 640 MHz 开始压上限，1.28 GHz 压到 MCS0，2.56 GHz 不能。校准后（实测 IRR）全部回到 PA 限的 MCS2——与 `topology-b.md` §2 的网格一致。

## 2b. 解码器上限（示例 04 §4b；`frontend/grid.py::decoder_cap`）

§2 的“MCS 上限”是**发射机合规口径**（底板比规范的 TX EVM 要求低 3 dB）。接收机实际能带的是另一回事：EVM 底板就是一层噪声，
MCS 的 ideal 门限 T（`data/spec/per_thresholds.yaml`，本库接收机在理想链上实测的 PER 1e-2 点，79 条曲线）加上底板后需要
SNR_req = −10·log10(10^(−T/10) − 10^(floor/10))；判可达的口径是 −floor ≥ T + 3 dB（`assumed.decoder_cap_margin_db`，此时底板最多吃 3.0 dB 灵敏度）。
底板取**解析底板与该格时域 EVM 中较差的一个**（`decoder_floor_db`；C1–C3 起）：解析的功率相加在 IQ 镜像不再是小扰动时偏乐观（80 MHz 基准：1.28 GHz 差 0.3 dB、2.56 GHz 差 0.8 dB；示例 02 全部 2.56 GHz 格差 0.3–1.2 dB）。
门限是 C1 / C2 改进后的接收机重量的（`RxConfig.cpe_window_symbols = 17`、`ce_smooth_auto`，`zero_if_60ghz` 预设默认开）。

| 行 | 底板 | 合规上限 | **解码器上限** | T / 所需 SNR / 代价 [dB] | 校准后 | 速率 | pJ/bit |
|---|---|---|---|---|---|---|---|
| 11ac 20M K=1 @6 GHz | −17.2 | MCS2 | MCS3 | 11.00 / 12.20 / 1.20 | MCS3 | 26 | 6543 |
| 11ac 20M K=4 / 8 / 16 | −17.3 / −17.4 / −17.1 | MCS2 | MCS3 | 11.00 / 12.1–12.2 / 1.1–1.2 | MCS4 | 104 / 208 / 416 | 2855 / 1845 / 1273 |
| 11ac 20M K=32 | −15.2 | MCS1 | MCS3 | 11.00 / 13.09 / 2.09 | MCS3 | 832 | 939 |
| 11be 80M K=1 @6 GHz | −17.1 | MCS2 | MCS4 | 11.40 / 12.76 / 1.36 | MCS4 | 216 | 1204 |
| 11be 80M K=4 | −16.6 | MCS2 | MCS4 | 11.40 / 12.97 / 1.57 | MCS4 | 865 | 628 |
| 11be 80M K=8 | −14.9 | MCS1 | **MCS4** | 11.40 / 13.93 / 2.53 | MCS4 | 1729 | **467** |
| 11be 80M K=16 | −10.9（解析 −11.2） | MCS0 | MCS3 | 7.51 / 10.13 / 2.62 | MCS4 | 2306 | 557 |
| 11be 80M K=32（2.56 GHz） | −4.7（解析 −5.5） | — | MCS0 | −0.96 / 0.43 / 1.39 | MCS4 | 1153 | 1805 |

- 解码器上限比合规上限高 1–2 档（11ac BCC）到 2–3 档（11be LDPC）；吞吐翻倍、pJ/bit 减半：11be 80 MHz × 4 从 432 Mb/s / 1241 到 865 Mb/s / 628。
- **接收机改进把最好的一行从 K = 4 挪到 K = 8**：门限降 0.6–1.0 dB 后 640 MHz 的格从 MCS3 升到 MCS4（1729 Mb/s、467 pJ/bit），1.28 GHz 从 MCS2 升到 MCS3（2306 Mb/s、557）。
  A3 那一轮的数（K = 8 MCS3 1153 Mb/s / 701、K = 16 MCS2 1729 / 728）是旧接收机的。
- 20 MHz 基准的 K = 32 现在是该基准里最省的（MCS3、832 Mb/s、939 pJ/bit，K = 16 是 1273）：§6 ② 的结论只在合规口径下成立。
- **2.56 GHz 未校准能带 MCS0**（合规口径“不能”），示例 05 实测 PER 1e-2 在 0.60 dB（MCS1 在 6.39 dB）。旧接收机是 5.16 / 10.58 dB：
  这一格拆开量过（同一组 150 包 / 10 错的扫描，dB）：旧接收机 5.42、只开跨符号 CPE 3.42、只开自动平滑跨度 2.06、两者都开 1.06。
  在这么高的底板上信道估计里的镜像比 CPE 更贵（动手前猜的是反过来）；同一拆分在理想链上是 0.89 / −0.83 / 0.04 / −0.91，CPE 占大头。
- **预测对不对，示例 05 逐格量过**（impaired PER，上限 MCS 与高一档）：

| K（80 MHz 基准） | 上限 MCS：预测 / 实测 [dB] | 高一档：预测 / 实测 |
|---|---|---|
| 4 | MCS4：12.97 / 12.12 | MCS5：20.21 / 19.24 |
| 8 | MCS4：13.93 / 13.83 | MCS5：never / never |
| 16 | MCS3：10.13 / 10.19 | MCS4：never / never |
| 32 | MCS0：0.43 / 0.60 | MCS1：5.49 / 6.39 |

  四个 K 的上限 MCS 预测与实测差 −0.85 … +0.17 dB，高一档差 ≤ 1.0 dB，可达 / never 全部对上。用解析底板时 K = 32 的 MCS1 被判可达、预测 4.62 dB 而实测 6.50 dB；
  换成时域底板后这一格落在裕量之外（上限 MCS0），预测与实测差 0.17 dB。K = 4 的预测偏保守 0.85 dB：一半是门限表（11.40）与示例 05 自己量的 ideal（11.09）之间 0.3 dB 的测量散布，
  另一半是 PA 压缩在 16-QAM 上不是高斯噪声。
- 门限本身的发现：改进后 11be 的 MCS 1–10 各带宽门限彼此差 ≤ 0.6 dB；20 MHz 的 MCS0 仍比其余差 1.3 dB（0.3 对 −0.9 … −1.0）。旧接收机下 20 MHz 比 320 MHz 在 MCS0 差 1.8 dB、MCS4 差 1.3 dB，那大部分是逐符号 CPE 的代价随导频数（8 → 64）缩小，不是码的性质。
  11ac 的 BCC 比 11be 的 LDPC 在 MCS4 贵 3.5 dB（14.5 对 11.0）；4096-QAM（MCS 12 / 13）在理想链上要 32–37 dB，20 MHz 的 MCS12 到不了（链路自身 −40 dB 的底板：LPF 群时延 + 平滑偏差）。
- 11ac 40 / 80 / 160 MHz 基准没有编码数据域，这一列是 n/a（没有门限可比）。

## 3. 三方对账

- **解析底板 vs 时域 EVM**：底板 ≤ −8 dB 且 CFO 接住的行，差 −0.1 … +1.1 dB（11be 80 × 16 的 +1.1 最大）；2.56 GHz 行 +1.7 dB 不判（IQ 镜像 −5.8 dB 已不是小扰动，线性叠加不成立）；60.48 GHz 上 K = 1 的 +32.8 dB 不判（CFO 7.7 个子载波失锁，接收机输出无意义）。
- **wifitrx `EvmBudget` vs 解析底板**：每行差 0.0 dB（A1 更正后）。两者只在相噪一项口径不同：EvmBudget 积分 10 kHz–100 MHz 的 IPN 再乘 (1 − CPE 跟踪份额)，
  本库按 ICI 权重积到 fs_eff/2——K = 8 处 −28.1 对 −28.0 dB、K = 32 处 −32.5 对 −31.6 dB（20 MHz 基准），11be 80 MHz × 32 处 −28.1 对 −26.8 dB：
  fs_eff/2 超过 100 MHz 以后 EvmBudget 少算了 100 MHz 以上的底板，差 0.1–1.3 dB。
  跟踪份额随 K 升：T_FFT 变短，8.9 %（K = 1）→ 50 %（K = 8）→ 82 %（K = 32）。
- **更正（2026-11-11，A1）**：本节原先写“EvmBudget 乐观 3–4 dB（−31.1 对 −28.0、−35.5 对 −31.6）”。其中 3.0 dB 是本库的换算错：wifitrx 的 `ipn_dbc` 是单边带口径（相位功率 / 2），
  `compare._pn_terms` 把 10^(dBc/10) 直接当相位方差喂给 EvmBudget，少了 2 倍。拓扑 A 的 LO 扫描里时域读数与本库解析项一致、与 EvmBudget 恒差 3.16 dB，才查出来。
  改正后 EvmBudget 与时域的相噪 EVM 差 −0.09 … −0.23 dB（示例 06 §4）。原先“总量仍对得上，因为 PA 盖住一切”是对的现象、错的解释。

## 4. LO 三种剖面并排（各自的 `Frontend60`；`PhaseNoiseConfig.model`）

| 模型 | IPN 10 kHz–100 MHz | K = 8：相噪 ICI / 底板 / 时域 | K = 32：相噪 ICI / 底板 / 时域 |
|---|---|---|---|
| `pole_zero`（11ad EM 形状、Liu 的数） | −31.1 dBc | −28.0 / −17.4 / −17.4 | −31.6 / −15.2 / −15.4 |
| `wifitrx_wifi7`（WiFi 7 频综，vendored 剖面） | −46.9 dBc | −49.6 / −17.8 / −18.5 | −54.7 / −15.3 / −16.0 |
| `profile`：pllsim wu19 6.048 GHz × 10，倍频器底噪 −150 dBc/Hz（`survey.clock_profile_wu19_x10`） | −33.0 dBc | −32.0 / −17.7 / −17.8 | −36.1 / −15.2 / −15.7 |
| 同上，底噪 −160 / −140 / −130 dBc/Hz | −33.0 dBc（三档相同） | −32.0 / −31.9 / −31.6，底板 −17.7 / −17.7 / −17.6 | −36.1 / −35.7 / −33.0，底板都是 −15.2 |

WiFi 7 频综好 16 dB IPN，底板只好 0.4 dB：在 OBO 8 dB 处 LO 不是瓶颈。pllsim 剖面与 Liu 的 pole-zero 同量级（IPN 差 2 dB）。
倍频器底噪四档的 MCS 上限一格不动：PLL 远端 ×10² 在 100 MHz 处 L(f) 约 −133.6 dBc/Hz，−150 与 −160 埋在它下面，−130 才在 K = 32 的相噪 ICI 上露出 3 dB，而那一行是 PA 限。

- 剖面怎么来的：pll_simulator@`d67043e` 的 `pllsim export bench_wu19_spll_frac_52m_6p253g --set fout=6.048G --set osc.f0=6.048G --clock-profile <file> --multiply-by 10 --floor-dbchz=<F> --spur-rejection-db 40`，
  本库在本地检出的该 commit 上生成四个文件入库（`src/mmw60/data/clock_profiles/pllsim_wu19_x10_60p48g_floor*.yaml`）。f_in/2 以内是 N²·S 加底噪，以上只有底噪；杂散表不消费（铁律 6）。
- `profile_at_carrier` 只接受整数的 f_c / f0（`assumed.lo_multiplier_law`）：带倍频器的文件只在自己的 f0 上用，不带的按理想 20·log10(N) 平移；非整数比与分频报错。
- **更正（2026-11-11，pin pll_simulator@d67043e）**：本节原先的 `profile` 行是 wu19 的 6.253 GHz 剖面按 20·log10 平移 +19.7 dB，那是 ×9.672，不对应可实现的倍频器（pll_simulator#71 指出）。换成 ×10 剖面后 IPN −33.2 → −33.0 dBc，
  相噪 ICI K = 1 / 8 / 32 从 −28.1 / −32.3 / −36.4 到 −27.9 / −32.0 / −36.1 dB，底板 K = 1 从 −17.5 到 −17.4 dB，其余底板与 MCS 上限不动。原表 `pole_zero` 与 `wifitrx_wifi7` 两行的时域读数是 C1–C3 之前的（−17.3 / −18.1、−15.3 / −15.5），这次按现在的示例输出改正。
- 这条是"WiFi 7 全链路四条整合"里的"pll 剖面替换解析相噪"：接口与倍频器模型都已接通。拓扑 A 没有对应的行（ROADMAP A1）。

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
   （A1 更正：那 3–4 dB 里 3.0 dB 是本库把单边带 IPN 当相位方差的换算错，见 §3；改正后相噪项本身也只差 0.1–1.3 dB，没有什么会“露出来”。）
4. 以为 A2 第一条（实测 IRR 替换假设 45 dB）会改网格结论——≤ 640 MHz 实测 ≥ 46.8 dB 比假设好，2.56 GHz 的 38.4 dB 仍回到 PA 限的 MCS2：一格都不动。（2026-11-11 重新 pin wifitrx@96078aa 后这两档是 46.5 / 37.9 dB，同台表仍然一格不动。）
6. （A2，示例 05）以为“MCS 上限 = 底板比该 MCS 的 TX EVM 要求低 3 dB”是解码器能不能活的判据——11be 80 MHz × 4 / 8 的 MCS4（16-QAM 3/4）按它“超出上限”（MCS2 / MCS1），PER 却在 12.14 / 13.91 dB 到了 1e-2，只比 ideal 的 11.09 贵 1.05 / 2.82 dB。
   EVM 底板就是一层噪声：有效 SNR = 1/(1/SNR + 10^(floor/10)) 达到 ideal 门限即可，预测 12.54 / 13.40 dB；MCS7 在底板高于其门限（18.10）的格 never、K = 4 no-PA（底板 −22.0）预测 20.38、实测 21.08。
   （这里的数是 C1–C3 改进接收机后重跑的；A2 当时逐符号 CPE 的接收机读 13.88 / 15.05 对 ideal 12.04，结论相同。）
   TX EVM 要求是发射机合规数，比接收机容忍度保守约 2 档。表里的“max MCS / IQcal”列保留这个合规口径（它仍是“发射机过不过认证”的问题），但读吞吐和 pJ/bit 时要知道它偏保守——解码器口径已作为并排的一列落地（§2b）。
7. 以为铁律 2 的完整测试可以沿用"每个配置自己 `.ideal()`"——`ideal()` 改的是配置，硬件在实例里；共用一个按损伤配置建的 `Frontend60`，`ideal()` 的行照样带着它的 PA 和 IQ（第一版测试读出 −17.3 dB）。改为共用一个**理想**实例。
8. （C1–C3）以为解码器上限的预测在高底板上差 3 dB（2.56 GHz MCS0 预测 2.15、实测 5.16）是“IQ 镜像不是高斯噪声”——主要是两件别的事：解析底板比时域 EVM 乐观 0.8 dB（改取较差者）；
   旧接收机在这种底板上比在理想链上多贵 2.6 dB（同一格新旧接收机差 5.42 − 1.06 = 4.4 dB，理想链上只差 1.8 dB），门限表量不到这一份。换成改进的接收机和时域底板后预测 0.43、实测 0.60 dB。

## 7. 留下的（ROADMAP A3 剩余）

- 解码器上限列的剩余：11ac 40–160 MHz 没有门限（要先建 BCC 宽带交织器）；示例 04 §6 的灵敏度仍从解析底板起算（每个旋钮不跑时域），2.56 GHz 那行在那一节比 §4b 高一档；门限随接收机改动要重量（`tools/measure_thresholds.py --check`）。
Halo ADC 校准接入（要 vendor halo 的 adc 模块，现在转换器列是 ENOB 法则）；
带记忆的 PA 进表（PA_DPD 的参考 PA 与 wifitrx 的 DPD 在 K > 1 上已作为灵敏度研究接通，示例 07、`topology-b.md` §3b；表里的 PA 仍是无记忆的 Rapp，且表里计了 DPD 的功耗、底板用的是未预失真的 Rapp）；11be 的 LDPC 解码功耗；校准列（`calcheck.run_cal_at` 实跑进表，现用示例 03 实测 IRR 的表）。
