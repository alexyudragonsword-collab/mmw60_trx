---
type: project_topic
status: active
summary: "规范 / 文献数字的来源制度：四种标签、Liu 2025 两个 arXiv 版本的差异、11ad EM 参数的出处与未核实之处、本库自己定的假设清单。"
tags: [mmw60, spec, provenance, liu2025]
contains: [reference, decision, open_question]
created: "2026-11-06"
updated: "2026-11-12"
related: [external-validation.md, upclocking.md]
authoring_mode: ai_generated
---

# 数字从哪里来

## 制度（铁律 5）

`src/mmw60/data/spec/survey.yaml` 一条一个数，`source` 四选一：`spec`（原文，必须带 quote + section）、`survey`（文献 / 搜索命中，一律"未核实"）、`assumed`（原文没说，本库定）、`derived`（公式推出）。
代码只经 `mmw60.spec.value(key)` 取，`liu2025_table2()` 预设就是这样建的。`grep -c "source: survey"` 等于未核实条目数（`tests/test_spec_sources.py`）。

## Liu 2025 的版本

| 版本 | 日期 | 有什么 |
|---|---|---|
| arXiv 2309.16813 **v1** | 2023-09-28 | Table I / II、**Fig. 4 PER 曲线**（只有"有损伤"一组）、§V-A 设定 |
| arXiv **v2** | 2024-07-08 | 同样的正文，加了"without considering these non-idealities"的描述，但**图被删了**，正文 "Fig." 引用悬空 |
| IEEE Commun. Mag. 2025-03 | — | 刊出版，**未取得** |

本库的读图值（`liu2025_fig4.yaml`）来自 v1 第 5 页 300 dpi 渲染，精度约 ±0.3 dB。v2 正文说的"无损伤"曲线在任何可得版本里都没有，所以示例 00 的 ideal 组没有外部参照。

## 原文给了的（survey）

MCS 0/1/4、VHT、11ad CR 信道、1T1R、73.44 GHz（11ay channel 8）、4096 B、20 + 20 ppm → ±2.94 MHz、相噪 1 极 1 零（1 MHz / 100 MHz / −93 dBc/Hz）、modified Rapp OBO 8 dB、STF/LTF 捕获 ±625 / ±156.25 kHz、门槛 5.88 MHz 与 4.7、PER 目标 1e-2、"refrained from using estimation and compensation algorithms for CFO and PN"。

## 原文没给、从别处拿的（survey，未核实）

- Rapp 参数：IEEE 802.11-09/0296r16（TGad EM）CMOS PA，g = 4.65、Asat = 0.58、p = 0.81、α = 2560、β = 0.114、q1 = 2.4、q2 = 2.3——来自搜索命中的文档摘录，.doc 原文未读（r09 版是 5 / 0.6 / 0.71）。公式形状按记忆。
- 相噪 PSD 形状 PSD0·(1+(f/f_z)²)/(1+(f/f_p)²)：TGad EM 的写法（它的 PSD0 是 −90，Liu 用 −93）。
- VHT MCS 表（N_SD = 52、N_DBPS 26/52/156）、交织 N_COL = 13、BCC 133/171、扰码 x⁷+x⁴+1：802.11 的通用知识，原文未贴入。
- FCC 15.255 的 40 / 43 dBm：里程碑 1 用。
- 802.11 LDPC 的 12 张原型矩阵（`data/spec/ldpc_80211.yaml`，A2）：规范 Annex F 原文未贴入，取两份独立公开转录（simgunz/802.11n-ldpc、tavildar/LDPC，MIT）逐项比对相同，再按双对角结构逐张校验；EHT 的 N_SD、D_TM、LDPC PPDU 流程阈值（912 / 1464 / 2916、10 % / 1.2 / 30 %）同样 survey。
- 同台表 pJ/bit 列（A3）：Walden FoM 70 fJ（38.4–120.2）与 45 → 7 nm 能量比 0.175 经 Halo 的 `PowerCoefficients` 转引 Murmann / DeepScaleTool；pllsim wu19 时钟剖面是 Halo 随库数据（模型输出，不是实测）。
- PA 记忆研究（示例 07，2026-11-11）：`assumed.pa_memory_model`（wifitrx / PA_DPD 的参考 PA，sub-7 GHz WiFi PA 的模型，不是 60 GHz 器件）、`assumed.pa_memory_fir_fs_hz`（80 MS/s，即 12.5 ns 一个抽头）及其灵敏度档、回退扫描的格点（细 / 粗）、目标 EVM（−25 / −27 dB）、DPD 抽头间隔候选，全部是本库的 assumed；60 GHz PA 的记忆时间常数没有查到出处。
- pllsim ×10 剖面（`survey.clock_profile_wu19_x10`，2026-11-11）：pll_simulator@d67043e 的 CLI 在本地生成（命令在条目的 cite 里），wu19 预设重调到 6.048 GHz 再过对方的 ×10 倍频器模型；同样是模型输出，不是实测。倍频器底噪 −150 dBc/Hz 与谐波抑制 40 dB 是本库的 assumed，没有出处。
- 前端的三个面（示例 08，2026-11-12，ROADMAP D4）：八条 survey，**全部只读到搜索摘要，原文一份都没打开**（本会话的网络策略不放行这些站点）。接收前端按“通信文献为主”：`survey.rx60_comm_asada2011`（A-SSCC 2011，NF < 6.1 dB、IIP3 −20 dBm，基准档）、`survey.rx60_comm_iscas2015`（NF 7.1 dB；64 dB 是含基带的整机增益，不用）、`survey.dmg_sensitivity_assumptions`（802.11ad 灵敏度表的前提 NF 10 dB / 实现损耗 5 dB，二手转引）、`survey.dmg_rx_max_input_dbm`（−33 dBm，出自 ITU-R M.2003 的复述）；雷达芯片 `survey.rx60_radar_iwr6843`（NF 12 dB、带外 P1dB −12 dBm）只作对照。隔离 `survey.tx_rx_isolation_tue2018`（一篇摘要：加隔离结构 40 dB、好 15–20 dB；20 / 25 dB 是减出来的）。天线 `survey.antenna60_okada2013_dbi`（6 dBi）与 `survey.antenna60_bgt60_an600_dbi`（2 / 3.5 / 5 dBi，fmcw_radar 在 mmw60_trx#14 上贴的，本库没有搜到摘要）。没有查到任何数据手册直接给收发隔离度。

## 本库自己定的（assumed；每条在示例 00 有灵敏度行或在 LOG 有数字）

基准带宽 20 MHz；SNR = 每有效子载波 Es/N0；相噪 TX/RX 各一份；CR 信道 = 指数 PDP 7 ns rms + LOS/散射 10 dB；OBO 参考 Psat（另给 P1dB）；信道估计平滑 3 音（里程碑 0 的接收机；`zero_if_60ghz` 预设逐包自动选，上限 9 音 `assumed.ce_smooth_max_tones`）；跨符号 CPE 合并窗 17 个符号（`assumed.cpe_window_symbols`，示例 00 有 5 / 33 的灵敏度行）；genie 定时；只建 L-STF / L-LTF / Data；扰码种子 93。

拓扑 A（A1）的一组：IF 6.48 GHz、固定 LO ×3、IF 带通（Chebyshev-I 5 阶 0.5 dB、通带 1.2 GHz）、镜像抑制 30 dB、芯片 seed 5 与 4 倍过采样、MLO 的 sub-7 链路 5.5 GHz / 20 dB、同源晶振；每条在示例 06 §7 有灵敏度行（`cairn/topology-a.md` §9）。

A3 的 pJ/bit 列另有一组只进功率列、不碰 EVM 的 assumed：PA 峰值 PAE 20 %（B 类回退规律）、60 GHz / sub-7 频综 40 / 20 mW、数字字宽 16 bit、理想 ×N 的 20·log10 搬移；每条在示例 04 §6 的灵敏度表里有两端的数（`cairn/comparison-table.md` §5）。

前端三个面的一组（示例 08）：`assumed.rx60_ladder_shape`（查到的只有最高增益档一个点，八档梯子是 wifitrx 的整体平移）、`assumed.rx60_p1db_from_iip3_db`（9.6 dB）、`assumed.frontend_faces_pick`（基准档各取哪个数：NF / IIP3 取通信收发机，隔离取减出来的下端 20 dB，发 / 收天线各 6 dBi）。预设不用这一档；示例 08 每张表都是灵敏度行。

## 本库自己量的（derived）

- `data/spec/per_thresholds.yaml`：各 MCS 的 ideal PER 门限（`tools/measure_thresholds.py`）。不是规范数，是这份代码的接收机的性质（C1–C3 后是改进的那一档，比里程碑 0 的接收机低 0.1–2.8 dB）；`tests/test_thresholds.py` 复量一个点守着它不与代码漂开。
- `derived.irr_after_cal_measured_db`：示例 03 实测的校准后 IRR。

## 要原文才能关掉的问题

1. Liu 2025 的 Rapp 参数与 OBO 定义（刊出版或作者）。
2. 11ad CR 信道的 tap 表（Maltsev 11-09/0334；拿到后 `TapTableChannel` 直接接，`cairn/Reference/` 放原文）。
3. IEEE 802.11-09/0296r16 原文：把 `tgad_em.*` 从 survey 改成 spec。
4. 前端三个面的八条 survey（上面“前端的三个面”一条）：每条都要对着原文核数、核条件。核的时候要看的：Asada 2011 的 6.1 dB 对应哪一档增益、是否含混频器；IWR6843 手册里带内 P1dB 随增益的那张图；TU/e 2018 不加隔离结构时的隔离度原文到底给没给；802.11ad 条文里灵敏度表的前提与最大输入电平。
