---
type: project_topic
status: active
summary: "规范 / 文献数字的来源制度：四种标签、Liu 2025 两个 arXiv 版本的差异、11ad EM 参数的出处与未核实之处、本库自己定的假设清单。"
tags: [mmw60, spec, provenance, liu2025]
contains: [reference, decision, open_question]
created: "2026-11-06"
updated: "2026-11-13"
related: [external-validation.md, upclocking.md]
authoring_mode: ai_generated
---

# 数字从哪里来

## 制度（铁律 5）

一条一个数，`source` 四选一：`spec`（原文，必须带 quote + section）、`survey`（文献 / 搜索命中，一律"未核实"）、`assumed`（原文没说，本库定）、`derived`（公式推出）。
代码只经 `mmw60.spec.value(key)` 取，`liu2025_table2()` 预设就是这样建的。

**两张表（2026-11-13 起，mmw60_trx#21）**：关于外部世界的数——规范条文、论文与数据手册的数字、只由它们推出的 derived——在共享库 spec_sources 里，按完整 SHA（`d7b4d1e`）vendor 在 `src/mmw60/vendor/spec_sources/`（读取器加 6 张表：`liu2025`、`ieee80211`、`regulatory`、`frontend60`、`pa60`、`energy`）。本库自己的取舍与产出留在 `src/mmw60/data/spec/survey.yaml`：assumed 56、derived 3、survey 3。
`mmw60.spec` 是一层薄垫片：`all_entries()` 把两张表合起来，同一个键出现两次直接报错；公开名字一个没少，另加 `ref()`。迁移前后 125 个旧键逐条相同（8 个字段的 `repr`），只多了共享库新增的 `isolation.tx_rx_tue2018_no_ebg_min_db`；数值指纹逐位不变。
外部的数要改，回 spec_sources 提，不改副本（`tools/vendor_check.py --strict` 连 YAML 一起逐字核对）。每张表、四个标签都按 `grep -c "source: <标签>"` 核对（`tests/test_spec_sources.py`），所以表头与注释里不写“标签词 + 冒号”。迁移前本地表的 spec 计数是 11 而条目只有 10：D4 一段注释里的那句话被多数了一次，当时的守卫只数 survey 与 assumed，没发现。

下面各节按主题列条目；读过原文、文献、规管、11ad 的那些现在都在共享表里，键名没变。

## Liu 2025 的版本

| 版本 | 日期 | 有什么 |
|---|---|---|
| arXiv 2309.16813 **v1** | 2023-09-28 | Table I / II、**Fig. 4 PER 曲线**（只有"有损伤"一组）、§V-A 设定 |
| arXiv **v2** | 2024-07-08 | 同样的正文，加了"without considering these non-idealities"的描述，但**图被删了**，正文 "Fig." 引用悬空 |
| IEEE Commun. Mag. 2025-03 | — | 刊出版，**未取得** |

本库的读图值（`liu2025_fig4.yaml`）来自 v1 第 5 页 300 dpi 渲染，精度约 ±0.3 dB。v2 正文说的"无损伤"曲线在任何可得版本里都没有，所以示例 00 的 ideal 组没有外部参照。

## 原文给了的（survey）

MCS 0/1/4、VHT、11ad CR 信道、1T1R、73.44 GHz（11ay channel 8）、4096 B、20 + 20 ppm → ±2.94 MHz、相噪 1 极 1 零（1 MHz / 100 MHz / −93 dBc/Hz）、modified Rapp OBO 8 dB、STF/LTF 捕获 ±625 / ±156.25 kHz、门槛 5.88 MHz 与 4.7、PER 目标 1e-2、"refrained from using estimation and compensation algorithms for CFO and PN"。

## 读过原文的（spec，带 quote 与 section；2026-11-12 起）

本库第一批 `source: spec` 条目，都在 ROADMAP D4 这一轮（原文经放行站点后直接下载，没有绕任何访问校验）：

- `rx60.comm_asada2011`：Asada et al., A-SSCC 2011，作者实验室站点上的论文 PDF。§V 与 Table III：接收变频增益 27 dB（高增益）/ 17 dB（低增益），“The entire noise figure is less than 6.1 dB, and the measured IIP3 is −20 dBm”，封装内天线 2 dBi。同一张表还有发射 P1dB 5.4 dBm、Psat 6.5 dBm、相噪 −94.2 dBc/Hz @ 1 MHz（60.48 GHz）。没说 IIP3 是哪一档增益下量的。
- `rx60.radar_iwr6843`：TI SWRS219F（2025-04 修订）§7.9 RF Specification：NF 12 dB、带外 P1dB −12 dBm（脚注：10 kHz 连续波）、最大增益 48 dB、范围 18 dB、发射 12 dBm，全部是典型值。带内 P1dB 在 Figure 7-2 里，是图。
- `rx60.radar_iwr6843_fig7_2`：同一份手册第 32 页的图 7-2（把页面渲染出来读图）：增益 30 / 36 / 40 / 44 / 48 dB 上 NF 15.6 / 12.2 / 11.0 / 10.5 / 10.3 dB，带内 P1dB −24 / −30 / −34 / −38 / −42 dBm。fmcw_radar 先读出，本库对着图核过。带内与带外（−12 dBm）是两个量。
- `isolation.tx_rx_tue2018`：Adela et al., IEEE TAP vol. 66, 2018，TU/e 研究门户上的**摘要**（正文没有读）：57–64 GHz 收发隔离 40 dB，比不加 EBG 好 15–20 dB。正文由 fmcw_radar 读过，本库转述在条目备注里：不加 EBG 的整机 21–27 dB 是仿真，天线级 21–28 dB 是实测。
- `dmg.rx_max_input_dbm`：ITU-R M.2003 (03/2012) Annex 1 §2.4.6：“at least −33 dBm”。**现行版 M.2003-2 (01/2018) 同一节改成了接收天线处 10 µW/cm²**；60.48 GHz 下折合 −37.1 dBm（0 dBi）/ −31.1 dBm（6 dBi）。

60 GHz PA（示例 09，2026-11-12）：三篇东工大 65 nm 60 GHz CMOS PA 的论文 PDF，作者实验室站点直接下载：
- `pa60.asada_eumc2011`（基准档）：增益 23.2 dB、P1dB 10.0 dBm、Psat 14.6 dBm、峰值 PAE 16.3 %、P1dB 处 7.9 %、135 mW @ 1.2 V。会议名按文件路径是 EuMC 2011，PDF 本身没印。
- `pa60.wu_asscc2012`：末级 1.0 V 时 Psat 13.2 / P1dB 10.2 dBm / PAE 15.0 %，0.7 V 时 10.1 / 5.8 / 8.1 %。
- `pa60.ning_elex2011`：IEICE ELEX 2011，增益 9.8 dB、P1dB 9.4、Psat 11.7 dBm、PAE 14.3 % / P1dB 处 12.0 %。
- `pa60.eumc2011_table1`：Asada 那篇的 Table I，14 颗 60 GHz CMOS PA 的汇编。是那篇转引的，各行原文本库没读，只用来看分布。
- `rx60.comm_asada2011` 补了发射侧（变频增益 16 dB、P1dB 5.4、Psat 6.5 dBm）：那是收发机的发射输出，没有单独 PA 级。
- `derived.pa60_rapp_p_asada_eumc2011` = 1.286：使 Rapp 的 Psat − P1dB 等于 4.6 dB 的平滑度，`tests/test_pa60.py` 复算。`assumed.pa60_surveyed_pick` 说基准档取哪一篇。
- 没出处的：AM/PM（三篇都不给，仍用 11ad 的）。`assumed.pa60_psat_dbm` / `assumed.pa60_pae_max` 的备注里加了与测量值的对照。
- 2026-11-12 起拓扑 A / B 的预设（`zero_if_60ghz`，以及建在它上面的 `if_extender_60ghz` / `wifi7_chain_k1`）取 `assumed.pa60_surveyed_pick`：Psat 14.6 dBm、增益 23.2 dB、峰值 PAE 16.3 %、p = 1.286。回退那时仍从 Psat 8 dB（Pout 6.6 dBm），2026-11-13 起按下一段的规则取 7.5 dB（Pout 7.1 dBm）。
  `assumed.pa60_psat_dbm` / `assumed.pa60_gain_db` / `assumed.pa60_pae_max` 现在只由 `config.tgad_em_pa` 读（旧的 11ad EM PA，连同 Liu 的 8 dB 回退，作灵敏度行）。Liu 的预设 `liu2025_table2` 不变，仍是 11ad EM 的 Rapp、8 dB。
  （之前预设用的就是这三条 assumed 加 `tgad_em.pa_rapp_p` 的 0.81。）

PA 的工作点（2026-11-13，ROADMAP C10）：
- `pa60.wu_isscc2015`（spec）：Wu 等 ISSCC 2015 paper 19.5 的报告幻灯片（作者实验室站点的 PDF，两页渲染出来读图）。65 nm 60 GHz 收发机，单载波 16-QAM 7 Gb/s；发射机平均输出 9.3 dBm 时 TX EVM 碰到幻灯片上标的 “IEEE802.11ad MCS12(16QAM) specification” −21 dB 线；对比表的 Pout 一栏就写 “@TX EVM = −21dB”。单独 PA 的 P1dB 约 7.0 dBm 是读图。−21 dB 是幻灯片上的规范线，802.11ad 条文本身没读。
- `assumed.pa60_operating_rule`：预设的回退 = PA 单独在 OFDM 样的高斯包络上 EVM 刚好 −21 dB 的回退（`frontend.grid.obo_for_isolated_evm`）。只看 PA 单独，是为了同台表各行共用一个前端实例（铁律 2）；读法取自上一条，数不是。
- `derived.pa60_obo_at_evm_limit_db` = 7.5 dB（算出 7.457，种子 1–5 为 7.46–7.59）：`tests/test_pa60.py` 复算。灵敏度在示例 09 §2：去掉 AM/PM 7.06，汇编表中位形状 6.74，11ad 形状 9.97 dB。
- 想读而没去绕的：MDPI 上一篇 22 nm 60 GHz PA（可能给 OFDM 工作点）对脚本访问返回 403，没有去绕。

## 被下游消费的条目（改之前先看这里）

（2026-11-13：下面这三条已随迁移进了 spec_sources 的 `data/frontend60.yaml`，键名与值不变；共享库在它的 `consumers.yaml` 登记谁读哪条。fmcw_radar 迁到直接 vendor spec_sources 之前，它仍按本库旧的 pin 读，本库的守卫测试先留着。）

fmcw_radar 从 0.2.8 起（它的 main@`7685bb3`，fmcw_radar#11）vendor 本库的两个文件：`src/mmw60/spec.py` 与 `src/mmw60/data/spec/survey.yaml`，pin 在本库 `ef0f00c`，逐字节校验。它没有 vendor `Frontend60`（依赖整条 wifitrx 收发链，对只读几个数的雷达太重），所以读的是来源表，不是对象。以上是对方在 mmw60_trx#14 上的说明（评论 6823377875），本库没有读对方的仓库。

| 它读的量 | 本库的条目与字段 | 值 |
|---|---|---|
| 发射功率 | `rx60.radar_iwr6843` 的 `tx_power_dbm` | 12 dBm |
| NF | `rx60.radar_iwr6843` 的 `nf_db` | 12 dB |
| 带外压缩点 | `rx60.radar_iwr6843` 的 `p1db_in_oob_dbm` | −12 dBm |
| 带内压缩点 | `rx60.radar_iwr6843_fig7_2` 里增益 40 dB 那一点 | −34 dBm |
| 收发隔离 | `isolation.tx_rx_tue2018` 的 `with_ebg_db − improvement_max_db` | 20 dB |

对方加载时核对这五个数与它自己的表相等：本库改数、改键名或改字段结构，它下次重新 pin 时直接加载失败。所以动这三条或 `spec.py` 的公开名字之前，要在 CHANGELOG 里写明，并同步改 `tests/test_spec_sources.py::test_entries_a_downstream_library_reads_keep_their_keys_fields_and_values`（这条测试就是为了让改动不被悄悄带过去）。

`Frontend60` 上的三个面（`rx_front`、`tx_rx_isolation_db`、两个天线增益）目前没有下游在读，消费者是本库自己的示例 08 与链路预算。对方没有读天线增益与接收增益档，理由是天线增益是设计选择：本库读到的封装内 2 dBi 与它读到的板上 8 元阵约 12 dBi 都不是 MIMO 的单个阵元。

## 原文没给、从别处拿的（survey，未核实）

- Rapp 参数：IEEE 802.11-09/0296r16（TGad EM）CMOS PA，g = 4.65、Asat = 0.58、p = 0.81、α = 2560、β = 0.114、q1 = 2.4、q2 = 2.3——来自搜索命中的文档摘录，.doc 原文未读（r09 版是 5 / 0.6 / 0.71）。公式形状按记忆。
- 相噪 PSD 形状 PSD0·(1+(f/f_z)²)/(1+(f/f_p)²)：TGad EM 的写法（它的 PSD0 是 −90，Liu 用 −93）。
- VHT MCS 表（N_SD = 52、N_DBPS 26/52/156）、交织 N_COL = 13、BCC 133/171、扰码 x⁷+x⁴+1：802.11 的通用知识，原文未贴入。
- FCC 15.255 的 40 / 43 dBm：里程碑 1 用。
- 802.11 LDPC 的 12 张原型矩阵（`data/spec/ldpc_80211.yaml`，A2）：规范 Annex F 原文未贴入，取两份独立公开转录（simgunz/802.11n-ldpc、tavildar/LDPC，MIT）逐项比对相同，再按双对角结构逐张校验；EHT 的 N_SD、D_TM、LDPC PPDU 流程阈值（912 / 1464 / 2916、10 % / 1.2 / 30 %）同样 survey。
- 同台表 pJ/bit 列（A3）：Walden FoM 70 fJ（38.4–120.2）与 45 → 7 nm 能量比 0.175 经 Halo 的 `PowerCoefficients` 转引 Murmann / DeepScaleTool；pllsim wu19 时钟剖面是 Halo 随库数据（模型输出，不是实测）。
- PA 记忆研究（示例 07，2026-11-11）：`assumed.pa_memory_model`（wifitrx / PA_DPD 的参考 PA，sub-7 GHz WiFi PA 的模型，不是 60 GHz 器件）、`assumed.pa_memory_fir_fs_hz`（80 MS/s，即 12.5 ns 一个抽头）及其灵敏度档、回退扫描的格点（细 / 粗）、目标 EVM（−25 / −27 dB）、DPD 抽头间隔候选，全部是本库的 assumed；60 GHz PA 的记忆时间常数没有查到出处。
- pllsim ×10 剖面（`survey.clock_profile_wu19_x10`，2026-11-11）：pll_simulator@d67043e 的 CLI 在本地生成（命令在条目的 cite 里），wu19 预设重调到 6.048 GHz 再过对方的 ×10 倍频器模型；同样是模型输出，不是实测。倍频器底噪 −150 dBc/Hz 与谐波抑制 40 dB 是本库的 assumed，没有出处。
- 前端的三个面（示例 08，2026-11-12，ROADMAP D4）里还没读到原文的三条：`survey.rx60_comm_iscas2015`（ISCAS 2015，NF 7.1 dB；64 dB 是含基带的整机增益，不用）、`survey.antenna60_okada2013_dbi`（JSSC 2013，6 dBi）——这两条在 IEEE Xplore，对脚本访问返回空页，没有去绕；`survey.dmg_sensitivity_assumptions`（802.11ad 灵敏度表的前提 NF 10 dB / 实现损耗 5 dB，二手转引；ITU-R M.2003 里没有这两个数）。三条都只作灵敏度档。没有查到任何数据手册直接给收发隔离度。**已删的一条**：`survey.antenna60_bgt60_an600_dbi`（2 / 3.5 / 5 dBi）。这组数是 fmcw_radar 在 mmw60_trx#14 上贴的搜索摘要，对方读了 AN600 原文（Rev. 2.40）后撤回：文件里没有天线增益，只有归一化方向图。教训：转引别人的搜索摘要，等于未核实再套一层。

## 本库自己定的（assumed；每条在示例 00 有灵敏度行或在 LOG 有数字）

基准带宽 20 MHz；SNR = 每有效子载波 Es/N0；相噪 TX/RX 各一份；CR 信道 = 指数 PDP 7 ns rms + LOS/散射 10 dB；OBO 参考 Psat（另给 P1dB）；信道估计平滑 3 音（里程碑 0 的接收机；`zero_if_60ghz` 预设逐包自动选，上限 9 音 `assumed.ce_smooth_max_tones`）；跨符号 CPE 合并窗 17 个符号（`assumed.cpe_window_symbols`，示例 00 有 5 / 33 的灵敏度行）；genie 定时；只建 L-STF / L-LTF / Data；扰码种子 93。

拓扑 A（A1）的一组：IF 6.48 GHz、固定 LO ×3、IF 带通（Chebyshev-I 5 阶 0.5 dB、通带 1.2 GHz）、镜像抑制 30 dB、芯片 seed 5 与 4 倍过采样、MLO 的 sub-7 链路 5.5 GHz / 20 dB、同源晶振；每条在示例 06 §7 有灵敏度行（`cairn/topology-a.md` §9）。

A3 的 pJ/bit 列另有一组只进功率列、不碰 EVM 的 assumed：PA 的 B 类回退规律（峰值 PAE 2026-11-12 起取测量的 16.3 %，经 `assumed.pa60_surveyed_pick`；之前是 `assumed.pa60_pae_max` 的 20 %，现在只由 `config.tgad_em_pa` 读）、60 GHz / sub-7 频综 40 / 20 mW、数字字宽 16 bit、理想 ×N 的 20·log10 搬移；每条在示例 04 §6 的灵敏度表里有两端的数（`cairn/comparison-table.md` §5）。

前端三个面的一组（示例 08）：`assumed.rx60_ladder_shape`（原文只给高 / 低两档增益与一个 NF、一个 IIP3，八档梯子是 wifitrx 的整体平移，换档电平按 wifitrx 的平衡点规则）、`assumed.rx60_p1db_from_iip3_db`（9.6 dB）、`assumed.frontend_faces_pick`（基准档各取哪个数：接收机与天线取同一颗通信收发机，隔离取减出来的下端 20 dB）。预设不用这一档；示例 08 每张表都是灵敏度行。

## 本库自己量的（derived）

- `data/spec/per_thresholds.yaml`：各 MCS 的 ideal PER 门限（`tools/measure_thresholds.py`）。不是规范数，是这份代码的接收机的性质（C1–C3 后是改进的那一档，比里程碑 0 的接收机低 0.1–2.8 dB）；`tests/test_thresholds.py` 复量一个点守着它不与代码漂开。
- `derived.irr_after_cal_measured_db`：示例 03 实测的校准后 IRR，同台表的 IQcal 列读它。2026-11-13 按校准跑在预设 PA 工作点（从 Psat 7.5 dB）上的示例 03 重导：20 / 80 / 160 / 320 / 640 / 2560 MHz 为 57.3 / 55.9 / 53.4 / 51.9 / 48.1 / 40.2 dB（2026-11-12 默认驱动、测量的 PA：56.3 / 56.8 / 52.9 / 50.9 / 47.6 / 38.5；换 PA 之前 55.3 / 55.2 / 50.4 / 51.1 / 46.5 / 37.9）。

## 要原文才能关掉的问题

1. Liu 2025 的 Rapp 参数与 OBO 定义（刊出版或作者）。
2. 11ad CR 信道的 tap 表（Maltsev 11-09/0334；拿到后 `TapTableChannel` 直接接，`cairn/Reference/` 放原文）。
3. IEEE 802.11-09/0296r16 原文：把 `tgad_em.*` 从 survey 改成 spec。
4. 前端三个面还剩三条 survey（上面“前端的三个面”一条）：ISCAS 2015 与 Okada 2013 要 IEEE Xplore 的访问权或 PDF；802.11ad 灵敏度表的前提与最大输入电平要标准条文。另外两处读了原文仍没有答案：Asada 2011 的 IIP3 对应哪一档增益；TU/e 2018 正文里不加隔离结构时的隔离度到底给没给（只读了摘要）；通信接收前端的带外压缩点（基带高通之前）没有任何出处。
