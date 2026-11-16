# 变更记录 / Changelog

按里程碑记录。每条写**做了什么**和**为什么**；数字原值在 `cairn/LOG.md`。

## 未发布

### 里程碑 3 第二段 2b（下）：按功率换距离（2026-11-16）—— 预设、同台表与指纹不变；示例 15 多 §9
- 新 assumed `ay_sensitivity`：EDMG 门限借 DMG 同档灵敏度，参考接收机的 NF 与实现损耗拿掉；没有对应档的 EDMG MCS 不给门限。
- `ay.edmg.dmg_twin`、`ay.edmg.ideal_threshold_db`、`arraylink.ay_mcs_ranges`（新）。
- 示例 15 §9：每档射程最远的回退、每个距离上最快的速率、三行灵敏度（实现损耗留着、查到的 60 GHz 前端、对本库实测 11be 门限）。
- 结论：单天线时近处两种波形相当，5 m 起 SC 领先（低阶星座能把回退压到 1 dB）；SC 的高阶档缺 DMG 对应档，记 ROADMAP。

### 里程碑 3 第二段 2b（中）：同台表的两行 802.11ay（2026-11-16）—— 指纹与 be 各行的数不变；示例 04 多 §1b
- `compare.evaluate_ay`（新）：底板读时域，原始链与 `calcheck.run_cal_ay` 校准过的链各一列；合规上限照 be 行的余量规则（`assumed.mcs_evm_margin_db`），另给不留余量的读法；pJ/bit 不计解码器。`compare.build` 的报告多 `ay_rows`（**报告 JSON 加键**），`compare.PENDING` 清空，`scheme_matrix` 给出 ay 两行。
- `compare.Row` 加 `power_cal`：be 行在校准后上限处的功耗（**报告 JSON 加键**），用来和 ay 行同口径比。
- `power_report` 认得 ay 波形（变换按 512 点、按 OFDM 符号 / SC 块计；解码器记为未计）。
- `compare.sensitivity` 不再重跑 ay 行（它们没有解析侧）；示例 04 与 `tools/budget_report.py` 多基准时 ay 两行只出现一次。
- 结论：同在校准后上限，ay SC 4620 Mb/s、188 pJ/bit，be 最好的一行（11be 80 MHz × 32）3459 Mb/s、270 pJ/bit。两边校准读法不对称，见 `cairn/comparison-table.md` §2c 与 ROADMAP A3。

### 里程碑 3 第二段 2b（上）：§8 每个回退点各校一次（2026-11-16）—— 源码、预设与指纹不变；示例 15 §8 的数更正
- 示例 15 §8：每个回退点各跑一次 `run_cal_ay`，不再只在预设回退校准一次；另加一行，给出单次校准跑到 15 dB 时读成什么。
- 更正：同调制同码率时 SC 少退 0.14–0.32 dB（16-QAM），不是 #51 的 0.01–0.15 dB。原因是 wifitrx 的 TX LO 泄漏抵消只对它校准时的增益状态成立。
- 新测试 `test_the_tx_lo_leak_calibration_holds_only_at_its_gain_state`。

### 里程碑 3 第二段 2a：在 ay 的链上真跑 wifitrx 的校准（2026-11-16）—— be 方案与指纹不变；示例 15 多 §7–§8
- `calcheck.ay_probe_config`、`calcheck.run_cal_ay`（新）；新 assumed `ay_cal_probe`。
- `LinkSim(cfg, frontend=, chains=)`：ay 配置可以传进一对建好的（校准过的）链（**公开签名加参数**，be 不接受）；`describe()` 多 `calibrated`。
- 示例 15 §7：校准步骤表；§8：校准过的链上的底板、合规上限，以及同调制同码率的回退。结论更正：SC 的回退优势只剩 0.01–0.15 dB。

### 里程碑 3 第一段：两种 802.11ay 波形接上 EDMG 数字，跑在共享前端上（2026-11-16）—— be 方案、预设与指纹不变；新示例 15
- `config.WAVEFORMS_BUILT` 加 `ay_ofdm`、`ay_sc`。新增 `AY_WAVEFORMS`、`AyConfig`（`Mmw60Config.ay`，**配置 schema 变化**）、预设 `ay_60ghz`。ay 只在拓扑 B、EDMG 信道中心、K = 1 上，配置拒绝其余组合。
- `mmw60.ay.edmg`（新）：EDMG 单信道数字学（导频随信道）、MCS 表、限值、速率、合规上限（限值不单调，取通过的里最快的）、共用的链速率。
- `mmw60.sim.ay_link`（新）：`LinkSim(cfg)` 遇到 ay 时构造 `AyLinkSim`，调用方不用改。帧是 STF + Golay 对 CEF + 载荷；接收机是 STF 估 CFO、截到 GI 的信道估计、SC MMSE 加 GI 间插值的相位跟踪、OFDM ZF 加导频。
- `ay.sc` 加 `pair_estimate`、`window_estimate`，`equalize` 加 `track_phase="interp"`；`ay.ofdm.receive` 加 `h=`，`modulate` 可以不带训练场。
- 新 assumed 五条：`ay_chain_rate`、`ay_sc_pulse`、`ay_preamble`、`ay_evm_payload`、`ay_receiver`。`assumed.pa60_operating_rule` 的值改成指向 `dmg.tx_evm_db#evm_db@mcs=12` 的引用（**值的形状变化**；读它用 `frontend.grid.operating_rule_evm_limit_db()`），回退不变。
- 铁律 3 的 ay 一句更正。`compare.PENDING` 的 ay 两格改成“第二段：同台表行”。

### spec_sources 重新 pin 到 3123b65（2026-11-16，spec_sources#29）—— 代码读的键值、预设、同台表与指纹不变
- vendor 副本跟进 spec_sources#30：`ieee80211.yaml` 新增 DMG / EDMG 单信道 PHY 的 14 个键（2 个 derived），`dmg.sensitivity_assumptions` 与 `ieee80211ay.channel_centres_ghz` 改为 spec；其余 8 个文件只改出处头。
- 示例 08：`dmg.sensitivity_assumptions` 一行的标签变为 `[spec]`。ROADMAP C9 的未核实条数改成 20、没读到原文的剩两条；C10 记下 −21 dB 已有条文出处。

### C12：原文 ideal 16-QAM 门槛的候选逐项量（2026-11-16）—— 预设、引擎默认路径与指纹不变；新示例 14
- `RxConfig` 新字段（默认值即原行为）：`ce_ltf_symbols`（1 = 只用第一个 L-LTF 估信道）、`llr_channel_weighting`（False = LLR 不乘 |H|²）、`hard_decision`（只送 LLR 符号进 Viterbi，仅 BCC）；`phy.ppdu.decode_data_field(hard=)`（**公开签名加参数**，默认不变）。
- 示例 14：原文 ideal 定义下逐项改信道 K 因子 / 信道估计 / LLR 加权 / 硬判决，再看改进接收机 + 硬判决对原文。结论：三类候选单独都不偏罚 16-QAM（最大选择性 1.05 dB，原文要 4.42）；组合对上原文 MCS0 / 1（≤ 0.04 dB），MCS4 仍差 2.3–3.0 dB。
- ROADMAP：C12 从优先级里删掉，正文改成剩下一个候选（解映射幅度基准）。

### 里程碑 3 骨架：802.11ay 与数字无关的部分（2026-11-16）—— 引擎、预设、同台表与指纹不变
- `mmw60.ay`（新包）：`golay`（D / W 递推的 Golay 互补对）、`sc`（带已知 G 的单载波块、互补对信道估计、ZF / 去偏 MMSE 频域均衡、尾 G 相位跟踪）、`ofdm`（任意子载波排布、训练符号估计、导频去公共相位、给定信道的隔离读法）、`papr`（理想插值 / 抽取、RRC 成形与匹配滤波、CCDF、`obo_for_evm`）。数字学全是参数；ay 两种波形仍未接进 `LinkSim`。
- 合成数字学上：SC 对 OFDM 的回退差等于 PAPR 差（同为 16-QAM 2.7 对 2.9 dB）；"低 3–4 dB"只对低阶星座成立，ROADMAP 的验收线随之改写。
- 新专题文档 `cairn/ay.md`；ROADMAP 里程碑 3 记明卡在 spec_sources#29，第一轮只做 EVM 口径与单信道。

### B：两级波束训练（2026-11-16）—— 引擎、预设与指纹不变；示例 10 多 §4c
- `arraylink.hierarchical_training`（新）与 `required_training_snr_db(candidates=)`（新参数，默认不变）。
- 结论：两级扫描在 N = 64 的 MCS0 边上补不了距离（宽扫子阵少 9–15 dB EIRP），只在有余量的距离上快 1.8–3.2 倍；边上缩短训练要的是不靠 60 GHz SNR 的粗方向（第二级只扫 4 个扇区时快 16 倍）。
- ROADMAP：删优先级第 1 条（分层训练），B 的“N = 64 的训练太长”改写成“粗方向来自 sub-7 链路”一档（待测向精度的出处）。

### C7：2.56 GHz 列两种读法差 10 dB 的原因（2026-11-16）—— 引擎、预设与指纹不变；示例 03 多两节
- `calcheck.loopback_views`（新）：最终检查的回环三种读法（wifitrx 的 isolation、先均衡的 isolation、modem）与信道相位斜坡、公共相位的相干度；`CalRun.chains`（新字段）留下校准后的链。
- **被推翻的判断**：2.56 GHz 上 genie（isolation）比 modem 差 10 dB 不是接收机吸收的线性项，是 isolation 读法在回环残余时延（6.06 rad 相位斜坡）下的估计偏差；先均衡读 −24.4 dB（modem −23.4）。
- 示例 03：“read three ways”一节与“calibrated column in a link over multipath”一节（IQ 缩到同台表用的校准后残差；2.56 GHz 多径只多 0.7 dB，即 ISI）。
- 测试守住这个上游现象；ROADMAP 删 C7 第一条、优先级重编号，D 节加候选 D5（是否报 wifi_trx_cal 待定）。

### C6：解码器上限标出踩在门限区间里的格（2026-11-16）—— 上限、速率、pJ/bit 与指纹不变；示例 02 / 04 的列格式变
- `frontend/grid.py::decoder_cap` 的返回多 `mcs_range`、`next_margin_db` 两键（**公开返回值变化**，原有键不变）；新 `format_cap`。`Cell` 与 `compare.Row` 多四个字段（区间两端的上限与离下一档的余量，未校准 / 校准后）。
- 示例 02：dec / dec-cal 两端不同时印 MCS5–6（5 格）。示例 04 §4b 与 markdown：同样标注，另加 next 列。
- ROADMAP：优先级按用户 2026-11-16 定的顺序重排（C7 → B 分层训练 → 里程碑 3 → C12），删 C6 里这一条。

### B：阵列的功率列按 N 计，重复训练场补到 MCS0 的边（2026-11-15）—— 同台表、预设与指纹不变；示例 10 多 §3c 与 §4b
- `arraylink.array_power_report`（新）：N_tx 颗 PA 按 EIRP 上限留下的每单元输出计直流，TX / RX 每单元一个移相器（`assumed.array_phase_shifter_power_mw`，新，15 mW），其余同单元件列；N = 1 逐位等于同台表的列。`PowerCoefficients.phase_shifter_w`（新字段，只有阵列行用）。
- `arraylink.required_training_snr_db(repetitions=, combining=)`、`repetitions_to_reach`、`transmit_sweep_reach_db`（新）；`sweep_time_s(repetitions=)`。`assumed.array_training_repetition`（新）：非相干累加，R 取 2 的幂到 256。R = 1 与原来逐位相同。
- 数：B 11be 80 × 4 的 pJ/bit 在 N = 4 / 16 / 64 是单元件的 ×1.8 / ×4.9 / ×11.9（358 → 4277）；EIRP 上限之后 PA 总直流保持约 3.3 W，N = 64 多出来的主要是移相器。TX 扫够到 MCS0 要 R = 4–16（N = 16）、64–256（N = 64，一个方向 16–111 ms）。
- ROADMAP：删优先级第 1 条与 B 的“功率列不知道阵列”，“训练到不了 MCS0 的边”换成“N = 64 的训练太长”（分层训练待做）。

### A2：拓扑 B 在 K = 4 的 CFO 丢包（2026-11-15）—— 引擎、预设与指纹不变；示例 11 多 B 行
- 示例 11 §2b：每个拓扑 A 的 K = 4 / 8 块后面加拓扑 B 同基准 × K 的行（同一前端实例、同样两种信道、每格 400 包），B 没有 MLO 预补偿。
- 数：B 11ac 20 × 4 在 3 dB 丢 0.5 / 1.0 %（flat / CR 替身），0 dB 丢 11 %；11be 80 × 4 只在 0 dB 丢 0.25–0.5 %；K = 8 不丢——与 A 关 MLO 同量。上限 MCS 在 10 dB 以上不丢，同台表与网格不动；付的是 MCS0 的灵敏度边。
- **被推翻的猜测**：A 在 0 dB 上 CR 替身少丢（27 对 46）不是估计器的性质，B 两种信道同是 45；记进 ROADMAP A1。
- `examples/derived.yaml` 加 A / B 两行丢包数的引用；ROADMAP 删优先级第 1 条与 A2 的对应待办，修 A3 里门限重量的耗时。

### C6：门限表加逼近，每个门限带 95 % 区间（2026-11-15）—— 引擎与指纹不变；门限、解码器上限与示例输出动
- `tools/measure_thresholds.py`：夹住 PER 1e-2 的两点续跑到 60 个错包或 3000 包（`--refine-errors` / `--refine-max-packets`，默认开），每个门限的 95 % 自助区间（`snr_at_per_ci`）写进 `per_thresholds.yaml` 的 `ci_db`；`--cache DIR` 按曲线落盘，被停的一次接着跑。全量 4 核约 2.3 小时（第一次在 2 小时后台上限处停在 70 / 79 条，从缓存跑完剩下 9 条）。
- `spec.per_threshold_ci_db(standard, bandwidth_hz, mcs)`（新）。**schema**：`per_thresholds.yaml` 多一个顶层键 `ci_db`，`cite` 写明逼近与区间。
- 数：78 个门限新减旧平均 +0.09 dB、标准差 0.22，旧表平均偏乐观 0.1 dB；区间中位宽 0.12 dB；11be MCS 1–9 各带宽门限彼此差 ≤ 0.27 dB（之前 ≤ 0.6，那是测量散布）。20 MHz 的 1024-QAM 碰到理想链自身的底板：MCS10 高 0.7–1.1 dB，MCS11 在 31.5–33.5 dB 之间 PER 停在 1–2.6 %，门限 33.50、区间 30.97–33.75（旧表 32.0）。
- 示例 05 / 06 的解码器上限复核也续跑到 60 错包，并打印实测与门限两边的区间（之前 1 dB 网格、不续跑，网格随预测移动时读数自己动 0.05–0.4 dB）。
- **被推翻的判断**：① “320 MHz 上 A 的解码器上限比 B 高一档（MCS6 对 MCS5），A 贵 2.1 倍”：A 的底板对 MCS6 的线只多 0.002 dB，门限移 0.01 dB 就落到 MCS5；现在两边同是 MCS5，A 贵 2.4 倍，而那一档在门限区间之内，两档都可能。② “关掉芯片的 DPD 解码器上限掉一档”：同一个 0.002 dB，现在两边都是 MCS5，DPD 换来的是 0.47 dB 所需 SNR。
- 动的数：拓扑 A 的 80 / 320 MHz 各行（含 × 4 数字升频、PA 旁路）解码器上限 MCS6 → MCS5，pJ/bit 2143 → 2411、765 → 862、764 → 860、旁路 424 → 477；零中频各行上限、速率、pJ/bit 不动；示例 02 一格（11be 320 × 16 校准后 MCS6 → 5）；示例 05 K = 16 的 MCS4 从 never 变成可达（预测 30.61、实测 31.65）；示例 08 灵敏度 0.1–0.2 dB；示例 10 拓扑 A 的上限一列 N ≤ 16 时 MCS6 → 5。合规口径一格不动。
- 测试：有门限就有区间、门限在区间内、宽度上限（中位 < 0.2 dB、最宽 < 1.2 dB，声明在 `ON_OWN_FLOOR` 的底板格另守“仍然宽”）；两种变异（区间不含门限、底板格变窄）都红，还原都绿。
- ROADMAP：优先级第 1 条（C6）与 C6 的第一条待办删掉；C6 加三条发现（20 MHz 1024-QAM 的底板、解码器上限踩在门限区间里的格、逼近只重读两次夹点）。

### C8 + C10：同台表只计底板里有的 DPD（2026-11-15）—— MCS 上限、底板与指纹不变（指纹不含功率列），pJ/bit 动
- 用户定：回退保持 7.5 dB，同台表不再计 60 GHz PA 的 DPD 功耗（底板取的是未预失真的 PA；预设回退上 wifitrx 的 DPD 步在 K ≤ 8 拿回 0–0.7 dB，换训练数据后中位 0）。
- `mmw60.power`：DPD 只在底板里有预失真器时计。零中频各行不计，写进 `omitted`（`power.NO_MMW_DPD`）；拓扑 A 计芯片自己的 DPD（新块 `chip_dpd`），芯片 PA 旁路或 `ifext.with_dpd=False` 时不计。**行为变化**：`PowerReport.blocks` 不再有 `dpd` 块，示例 04 / 同台表 markdown 的那一列改成 `c.dpd` / “chip DPD (A)”。
- 数：零中频各行少 355 pJ/bit（11ac 20 MHz；K = 32 少 474，11be 80 MHz 少 257–1026）；合规口径 11be 80 × 8 592 居首、11ac 20 × 32 794 第二、11be 80 × 4 926 第三，A 旁路 943 第四。**被推翻的判断**：“A 旁路芯片 PA 后比 B 省、全表第二”；320 MHz 上 A 对 B 现在贵 1.85 / 2.1 倍（合规 / 解码器口径，之前 1.35 / 1.6）；20 MHz 基准两个口径都是 K = 32 省。
- ROADMAP：优先级里的 C8 + C10 一条与 C8 / C10 里对应的待办删掉；ROADMAP A1 的芯片 PA 旁路一条改数。
- 测试：零中频不计、A 计芯片 DPD 且关 DPD / 旁路时不计、节点缩放跟着 `chip_dpd` 走；两个变异（去掉 `with_dpd` / 旁路条件、去掉“不计”一栏）都红。
- 顺带修了 main 上的旧问题：示例 09 的期望输出（缺 A × be_upclocked 一行，`liu2025.pa_obo_db` 的标签）、同台表灵敏度表的行数、`derived.yaml` 的取数模式。

### C12 与 A × be_upclocked 的 CFO 余量：示例 13、ideal+CFO 组、关 MLO 的丢包率（2026-11-15）—— 引擎、预设与指纹不变
- 示例 13（新）：用原文自己的 ideal 曲线把它 MCS4 的平台反推成损伤份额（8× −17.93、16× −18.20 dB），对本库字面工作点无噪声时的 −17.74 / −17.94 dB。平台不需要更狠的 PA：原文 ideal 的 16-QAM 要 19.7 / 19.0 dB，本库 flat ideal 16.00 dB，同样的失真压在前者上就封顶。另在本库链路上核对这个噪声样映射（MCS4 回退 8 dB 偏悲观 1.0 dB）。**被推翻的判断**：#36 与示例 12 那一轮的“PA 的有效工作点比字面读法狠”。
- 示例 00 加第六组 ideal+CFO（相噪 / PA 关，CFO 与估计器留着，即原文 ideal 的定义）：K = 4 三个 MCS 都 PER = 1，同原文；K = 8 / 16 对本库 ideal 只差 −0.20 … +0.09 dB，所以原文 ideal 的 16-QAM 门槛高 2.1–2.9 dB 与 CFO 无关（ROADMAP C12 只剩这一项）。`tools/external_check.py` 加一张 ideal+CFO 对原文 ideal 的表，K = 4 也比。期望输出：原有各行逐字不变，加 9 条曲线与一列。
- 示例 11 §2b（新）：A × be_upclocked 关 MLO 时 CFO 的丢包率，每格 400 包，越界与交接错分开计。11ac 20M × 4 在 3 dB 丢 0.5 / 1.0 %、0 dB 丢 11.5 / 6.8 %（flat / CR 替身），K = 8 不越界。**被推翻的判断**：“K ≥ 4 时芯片 L-STF 自己接得住”，AGENTS 铁律 3 与四篇专题文档改成 K ≥ 8。ROADMAP 加 A2“B 的 K = 4 CFO 丢包”。
- `run_curves(cache_dir=…)` 与示例 00 的 `--cache DIR`：每条曲线跑完落盘，键 = 规格 + 包源码摘要，长跑被停后接着跑，输出同一次跑完（曲线只由自己的配置定种子）。默认不开。
- ROADMAP 顶部加“当前优先级”一节（2026-11-15 排）。顺带修 main 上的旧问题：AGENTS 的 vendored 表数、`derived.yaml` 丢的一句引用、示例 00 加列后的取数模式；`derived.yaml` 加 ideal+CFO 一条。

### spec_sources#26：重新 pin 到 7aae876，`liu2025.*` 按刊出版、新表 `tg3c.*`（2026-11-15）—— 引擎、预设、示例输出与指纹不变
- 重新 pin spec_sources @ `7aae87681dcbacb8c0a369d7d2d922d21d56b5da`（它的 PR #27，答复本库发起的 spec_sources#26）。原来 8 个文件里只有 `data/liu2025.yaml` 变了，其余 7 个只换出处头里的 SHA；另 vendor 新表 `data/ieee802153c.yaml`（`tg3c.*`，Liu 的 [15] 与它的 PA 文件，4 条 spec），本库文档里点名的键可以由守卫核对。
- `liu2025.*`：18 条值不变、survey 改 spec；3 条按刊出版改值（Table I 的 16× 列 5 MHz、带宽到 2560 MHz；接收机那句 “…for CFO and used phase tracking only on the receiving end”）；新收 4 条。只有 `liu2025.per_target` 仍是 survey。本库代码读的 12 个键值不变。共享表 75 → 83 条（survey 39 → 18，spec 30 → 59，derived 6）。
- **被推翻的判断**：本节下面一条写的“0396 的 Ghorbani 拟合与 TGad EM 参数量级相近”（以及 `cairn/spec-sources.md` 里“像是同一颗 PA”）。spec_sources 复算：两组数在各自模型里位置不同，两颗 PA 的曲线也不同，0396 对 Liu 的 PA 没有约束。改在 `cairn/spec-sources.md`、`cairn/external-validation.md` §4 第 2 条、ROADMAP C4、示例 12 的说明文字（追加更正，不覆盖）。
- 本地表：`assumed.array_training` 改引 `liu2025.mlo_bf_training_statement`；`assumed.pn_apply_sides`、`assumed.pa_obo_reference` 补 [15] 的出处（`tg3c.pn_model`、`tg3c.pa_modified_rapp_shape`）。测试：vendored 表 6 → 7、“未核实”示例键换成仍是 survey 的 `liu2025.per_target`。

### Liu 2025 的 MCS4 平台：示例 12（信道 K 因子扫描）、读 [15]、spec_sources#26（2026-11-15）—— 引擎、预设与指纹不变
- spec_sources#26：请它按刊出版重读 `liu2025.*`（Table I 的 16× 列、接收机那句、Table II 可升 spec 的各行），并收 IEEE 802.15-06-0477 / 0396 的相噪与 PA 模型条目。本库发起，验收后由本库关。
- 读了 Liu 的 [15] IEEE 802.15-06-0477-01-003c 与它的 PA 文件 15-06-0396-01-003c（公开）：修正 Rapp 没给数；回退是相对 Psat 的输出回退，与本库一致；相噪建议 PSD(0) −87 dBc/Hz，−93 是示例之一；0396 的 Ghorbani 拟合与 TGad EM 参数量级相近。记在 `cairn/spec-sources.md`、ROADMAP C4。
- 示例 12（新）：K = 8、MCS 0 / 1 / 4，Table II 的损伤全开，CR 信道的 LOS K 因子 flat / 10 / 6 / 3 / 0 dB / 纯 Rayleigh，原文列从 `liu2025_fig4.yaml` 算；再在两条衰落信道上逐项关 PA / 相噪。
- 结论：没有哪个 K 因子同时给出“MCS0 / 1 陡、MCS4 停平台”——Rayleigh 的 MCS4 平台 0.106 与原文 0.105 对上，但 MCS0 / 1 从 0.5 到 0.05 要 7 dB 以上（原文约 1 dB）。衰落信道上的平台主要是 PA 的（理想 PA 时能到 1e-2）。**被推翻的判断**：同一天写的“原文 MCS4 的出入更像是信道 / 接收机”，改为 PA 的有效工作点在前（ROADMAP C12）。

### Liu 2025 刊出版：对外校验改对刊出版 Fig. 3（2026-11-15）—— 引擎、示例输出与指纹不变
- 用户提供了刊出版 PDF（IEEE Commun. Mag. 63(3) 69–75，doi 10.1109/MCOM.002.2400059；授权下载件，不进仓库）。**被推翻的判断**：本库按 arXiv v1 读、当作“有损伤”的 9 条曲线，在刊出版 Fig. 3 里是虚线的 ideal 组；实线的有损伤组另画（MCS0 约 4.6 dB、MCS1 约 7.9–8.1 dB，MCS4 到 31 dB 仍停在 PER 0.05–0.1）。
- `liu2025_fig4.yaml` 改成两组（`set: impaired | ideal`，MCS4 有损伤记 `floor_per`）；`tools/external_check.py` 本库四组对原文有损伤组、本库 ideal 对原文 ideal（K = 8 / 16；原文的 ideal 带着 CFO）；原文到不了 1e-2 的曲线只有本库也到不了才算一致。
- 结论：MCS0 / 1 上 flat 组最近（+0.5 … +0.7 dB），字面 +1.7 … +2.1，改进接收机 −1.3 … −2.5；MCS4 本库每组都到 1e-2、原文到不了——新的最大出入（ROADMAP C12）。更正前的“原文 PA 温和得多”“原文 = 近 AWGN + 字面 OBO”两条推翻（`cairn/external-validation.md` §4）。
- 刊出版与 arXiv 的其他差别记在 `cairn/spec-sources.md`（Table I 的 16× 列改 11ac 基准、接收机那句、PN / PA 模型引 802.15-06-0477、MLO 触发扇区扫描的原话）；spec_sources 的 `liu2025.*` 未改（要不要开 issue 等用户定）。
- 测试：读图两组的覆盖与平台、判决三态 + 平台 + ideal 的 K = 4 不比。示例 00 全量重跑，期望输出逐字不变。

### 拓扑 A × be_upclocked：只改数字基带的升频（2026-11-15）—— 已有的行与指纹不变
- 用户定：拓扑 A 只改数字基带也可以升频。芯片的 DAC / ADC、模拟、6 GHz 射频与它的 14 步校准都是原生信道的那一套，数字跑基准 PHY、时钟 ×K；K × 基准带宽必须是芯片的信道（20 … 320 MHz，取 `ieee80211be.n_sd` 的键）。`assumed.ifext_upclock`。
- 配置：`if_extender_60ghz(..., k=K)`；`Mmw60Config` 拒绝拓扑 A 的 `be` 配 K > 1 与越出芯片信道的 `be_upclocked`；`LinkSim` 去掉“拓扑 A 只能 K = 1”那一条。**行为变化**：拓扑 A 配 `be_upclocked` 现在能跑（之前一律拒绝）。
- 同台表：A × be_upclocked 从 n/a 变成已建，11ac 20 MHz × 4 / 8 / 16 与 11be 80 MHz × 4 四行；超出芯片信道的 K 是 n/a 行（`compare.NOT_A_CHIP_CHANNEL`），ay 的 n/a 说明改写。
- 示例 11（新）：同一 320 MHz 模拟信道上换基准 PHY 的表（附同带宽的拓扑 B）、关 MLO 的 CFO 表、同一颗芯片同一份校准的核对。
- 结论：上限不动（PA 限，MCS3），底板最多好 0.9 dB；11be 80 MHz × 4 与原生 11be 320 一样快（576 / 1297 Mb/s）、1708 对 1712 pJ/bit；K ≥ 4 时芯片自己的 L-STF 接住 2.42 MHz，MLO 预补偿变成可选（原生不开 MLO 整包坏）。
- 测试：`test_ifext.py` 三项（铁律 1 的信道约束、铁律 2 / 4 的同一颗芯片与校准、铁律 3 的 L-STF 捕获与 0 ppm 逐位相同），`test_laws.py` / `test_compare.py` 的矩阵与拒绝条件随之改写；示例 04 的已有行逐字不变。

### 里程碑 2：阵列层（2026-11-14）—— 预设一个单元，指纹不变
- vendor array_tx @ `5815c5a7ea43143fd58502d4894ac840b5b5fb86`（包名 `arraytx`）整包 135 个 `.py`，原样（它的 `data/`、`webui/` 资源不搬）；`vendor_check --strict` 249 个全 verbatim；清单、vendor 测试、策略说明与 CI 的 vendor-drift 作业（公开仓库，不用 token）带上新 pin。
- `frontend/array60.py`：`Array60`——arraytx 的几何与阵列因子，加上本库补的移相器量化（以第一个单元为参考、四舍五入）、逐单元静态误差、训练码本、EIRP 与接收阵列 SNR 增益；每个单元是共享前端的，两条拓扑同一个。一个单元（预设）即原单元件链路。
- `arraylink.py`：EIRP 上限下的逐单元工作点（PA 随之回退、更线性）、该点的底板与解码器上限、各 MCS 的最大路径损耗（拓扑自己的灵敏度）、MLO 触发的扇区扫描训练所需 SNR（非中心卡方闭式，测试对照逐音蛮力）、TX / RX 扫的预算与扫描时长。
- 配置：`ArrayConfig` 取代占位（`tx_nx/tx_ny/rx_nx/rx_ny`、间距、单元因子、移相器位数、导向、误差、码本）；`config.array_frontend()` 读新的 `assumed.array_*` 五条。两个 `configs/*.yaml` 的 `array:` 块随之改写。
- 示例 10（新）、`cairn/array-layer.md`（新）；`tests/test_array60.py` 7 项。
- 距离：路径损耗换算成视距距离时计入氧吸收 `assumed.oxygen_absorption`（15 dB/km 的估算，没有原文，ROADMAP B）；示例 10 §3b 有 0 / 10 / 20 dB/km 的灵敏度行。路径损耗本身不含它。
- 结论：N = 64 时 EIRP 上限把每单元压到 3.9 dBm（回退 10.7 dB），PA 单独 EVM −21.1 → −27.8 dB，三个方案的解码器上限各升一到两档；训练的瓶颈是对端单个单元接收的 TX 扫，N ≥ 16 时到不了 MCS0 的边（11be 80 MHz 基准差 2.7 / 8.9 dB，N = 16 / 64），上限 MCS 的范围内都够；2.56 GHz × N = 64 的移相器斜视平均 0.98 dB、最差音 3.36 dB。
- **验收**：指纹逐位不变；已有示例逐字不变。

### C7 推翻：校准里 DPD 成不成看训练数据，不看采集长度（2026-11-14）—— 预设与指纹不变
- `calcheck`：`scoring_config` / `upclocked_scoring_config` / `plain_config` 与 `run_cal_at` / `run_cal_on` 加 `waveform_seed`（训练与评分波形的随机数据，默认 0 = wifitrx 的默认，逐位不变）；`CalRun` 多 `dpd_kept`、`dpd_before_db`、`dpd_after_db`。
- 示例 03 灵敏度节加一张表：K = 1 / 32 × 8 / 32 个符号，各 24 组训练数据，DPD 写入几次、PA 输出的增益（平均 / 中位 / 最大）。写入比例 5/24、6/24、2/24、6/24，平均 0.41 / 0.43 / 0.12 / 0.26 dB，中位 0。
- ROADMAP：C7 “采集 8 个符号不够”删掉（只是 seed 0 的读数），统计并进 C8；C9 “预设还在用 WiFi 7 的梯子”按用户决定移到 E。`engineering-pitfalls.md`、`topology-b.md`、`assumed.cal_capture_symbols` 的说明加更正。
- **验收**：指纹逐位不变；示例 03 只在灵敏度节多出新表。

### 拓扑 A 消费共享接收前端：芯片前的 60 GHz LNA / 混频（2026-11-14，ROADMAP C9）—— 预设不变
- `ifext.MmwRxStage` 多一级 60 GHz LNA（`lna_gain_db` / `lna_nf_db` / `lna_iip3_dbm`）：共享前端的 `rx_front` 是 60 GHz 前端（`sourced`）时，取它的最高增益档当一级固定增益，芯片自己的梯子在后面做 AGC（`assumed.ifext_rx_front60`）。预设的 WiFi 7 梯子就是芯片自己那颗，不重复放，所以预设的数不动。
- `LinkSim`：拓扑 A 的 AGC 看 LNA 之后的电平；灵敏度（`rx_input_dbm_for_snr`）与镜像带噪声用 Friis 级联 NF；时域里 LNA 加输入参考的 kT·(F1 − 1/G1)，与芯片其后的 kT·F2 合起来正好是 Friis。LNA 的 IIP3 用 wifitrx 接收链同一个无记忆三阶项。60 GHz 观测回环从混频器进，不过 LNA。
- 示例 08 §5 改写：拓扑 A 换上查到的前端，灵敏度 −92.52 → −89.92 dBm（差 2.60 dB），与拓扑 B 同一换法相同；此前拓扑 A 差 0.00 dB。
- 铁律 2 的缺口（`architecture-invariants.md`）关掉；新测试 `test_law2_topology_a_consumes_the_shared_receive_front_end`：灵敏度随 NF 同拓扑 B、SNR 轴上 EVM 两种前端一致（去掉 LNA 噪声 → 红）、灵敏度用级联 NF（换回芯片 NF → 红）、观测回环不过 LNA。
- **验收**：指纹逐位不变；示例 04 / 06 逐字不变，示例 08 只有 §5 变。

### 拓扑 A：芯片 PA 旁路一档（2026-11-14，ROADMAP A1）—— 预设不变，同台表多一行
- `ifext.chip_pa_bypass`：IF 从芯片的混频器输出取，芯片 PA 断电（`assumed.ifext_chip_pa_bypass`；预设 False）。wifitrx 的交付序列在这条链上真跑（铁律 4）：校准耦合器跟着移到 PA 前，衰减减去实测的 PA 大信号增益（25.6 dB）；DPD 步不跑；tx_power 步只建表。只对 `chip: wifitrx` 有效，与 `chip_pout_dbm` 互斥。
- 功率列：旁路时去掉芯片 PA 一块，在“没计”里说明。`chip_facts` 多了 `pa_bypass` / `pa_bypass_gain_db`，旁路时 `pa_dc_w` 为 0。
- 示例 04 加一行：11be 320 MHz 的拓扑 A，芯片 PA 旁路。底板 / 上限不动；合规口径 1712 → 1200 pJ/bit（比拓扑 B 80 MHz × 4 的 1268 省，全表第二），解码器口径 765 → 538（B 487）。已有各行的数不变；灵敏度节因多一行，Walden 区间、频综 ×2 的排名、PA 回退与解码器裕量的行数跟着变。
- 示例 06 加 §5b：80 MHz 预设上旁路前后的校准读数、级间（−28.50 → −2.65 dB，仍是衰减）、上限与 pJ/bit（2143 → 1236，芯片 PA 原占 907）。
- **发现**：wifitrx 序列的 IIP2 耦合器衰减有 30 dB 的绝对下限，耦合器在 PA 前时顶住，`rx_iip2` 判失败（74.5 → 42.9 dBm）；测试守着这一条，ROADMAP A1 记着。
- **验收**：指纹逐位不变；新测试变异两处（功率列不去芯片 PA、建链不关 PA）都红，还原都绿。

### 拓扑 A 的固定 LO：pllsim 剖面放在 LO 频率上，加 ×9 一档（2026-11-14，ROADMAP A1）—— 预设的数不变
- **修正**：`model: profile` 的 LO 剖面原来对两条拓扑都放在载频上；拓扑 A 的固定 LO 在 f_c − f_IF = 54.0 GHz，配 pllsim 剖面时用的是 60.48 GHz 的 ×10 文件，IPN 高 0.95 dB。现在按 `Mmw60Config.lo_hz`（零中频是载频，拓扑 A 是 f_c − f_IF）放：`Frontend60.from_config`、`LinkSim`、拓扑 A 的 60 GHz 级、同台表与网格的解析相噪项都读这个频率。
- `Lo60.at(freq)`：同一个 LO 设计在另一频率上。1 极 1 零与 WiFi 7 剖面给在 LO 输出端、不带频率，返回共享实例本身（铁律 2 的同一对象不变）；pllsim 剖面按 `profile_at_carrier` 重放（整数倍；经过 ×N 块的文件只在自己的 f0 上用）。所以拓扑 B 建的共享前端交给拓扑 A 时，剖面落在 54.0 GHz 上。
- `LO_SCHEMES` 加 `fixed_lo_x9`（PLL 6.0 GHz）；pll_simulator@d67043e 的 ×9 剖面 `pllsim_wu19_x9_54p0g_floor150.yaml` 入库，本地表新增 `survey.clock_profile_wu19_x9`（本地 survey 3 → 4，合并表 137 → 138 条）。剖面经过的 ×N 与 `lo.scheme` 的倍频数不同时报错。
- 示例 06 §4 加一行：pllsim wu19 6.0 GHz ×9 到 54.0 GHz 的固定 LO。
- ROADMAP 清理：A1 的 pllsim 条目做完删掉；C4 删去已由 spec_sources 0.3.0 读到的 11-09/0296r16；C5 两条是结论不是待办，删掉（正文在 `cairn/topology-b.md` §被推翻的判断 2 / 3）；C10 末条（示例 09 汇编中位行重算）移到 E（用户定不做）。
- 示例 06 §4 的 pllsim 行：L(1 MHz) −99.4 dBc/Hz、IPN −34.0 dBc、相噪 ICI −28.1 dB（同 L(1 MHz) 的 1 极 1 零 −29.1，形状差 1 dB），上限 MCS6、324 Mb/s，与 −100 一行相同。
- **验收**：指纹逐位不变（预设与 `configs/*.yaml` 都是 1 极 1 零剖面）；新测试的三处调用点（60 GHz 级、同台表解析项、网格解析项）各变异一次都红、还原都绿；示例 06 只多两行，02 / 04 / 08 逐字相同。

### spec_sources 0.4.0：Asada Table I 读了 7 行原文，重新 pin（2026-11-14，mmw60_trx#27）—— 数不变，示例输出不变
- 重新 pin spec_sources @ `8e5f2e26bc2084d324aaaabea49fab18174ecaf8`（0.4.0，它的 PR #21）。8 个文件里只有 `__init__.py`（版本号）和 `data/pa60.yaml`（新增 7 条 spec，`pa60.eumc2011_table1` 只改 note）变了，其余 6 个只换出处头里的 SHA。
- 合并后的表 130 → 137 条，多的就是 7 条 `pa60.*`（Table I 的 [1] [2] [6] [9] [11] [13] [15] 行，读了原文）；其余条目的值与单位不变。
- 文档：`comparison-table.md` §8 补充“14 颗里只有一颗（9.0 dB）接近 11ad Rapp”的那颗是偏置不当（原作者自述），另有一行是 48 / 52 GHz 的数；`spec-sources.md` 改成 7 行已读原文、6 行仍二手；ROADMAP C10 把“汇编表是二手的”改成剩 6 行，并新记一条：示例 09 的“汇编中位形状”灵敏度行把这两行也算进了中位，要不要重算待定。
- **验收**：指纹逐位不变；`vendor_check --strict` 114 个全 verbatim；示例 02 / 04 / 08 / 09 逐字相同。

### spec_sources 0.3.0：TGad 评估方法学读成原文、别名退役，重新 pin（2026-11-13，mmw60_trx#25）—— 数不变，示例 09 一个标签变
- 重新 pin spec_sources @ `9a443ba73655591665df003bd9a863769cf81bdf`（0.3.0，它的 PR #8）。8 个文件里变了 6 个：`__init__.py` 版本号，`ieee80211.yaml`（9 条 `tgad_em.*` 由 survey 改成 spec、新增 4 条），另 4 张表删掉 `aliases:`；`reader.py`、`regulatory.yaml` 没变。
- 合并后的表 126 → 130 条，值与单位一个不变，9 条标签 survey → spec，未核实条目 51 → 42。示例 09 第 15 行打印的 `tgad_em.pa_rapp_p` 标签从 `[survey, unverified]` 变成 `[spec]`。
- 本地表 `assumed.pn_apply_sides`、`assumed.pa_obo_reference` 的说明指向新的原文条目（`tgad_em.pn_sides`、`tgad_em.pa_backoff_definition` / `pa_backoff_recommended_db`）：本库的取法与 TGad 原文一致；仍是 assumed，因为 Liu 本人没说。只改文字。
- 测试：0.2.0 的别名测试改成“17 个旧名现在是 KeyError；垫片的别名路径用一个人造别名守着（警告指向调用方、本套件里是错误）”。新增一条守卫：本地表 cite / note 里点名的键必须是现存的键（往说明里注入一个旧名时红、还原后绿；它读到 25 处引用）。
- ROADMAP C10 加一条：TGad 原文推荐的 OFDM 回退 8 dB 是配它自己那颗 PA 的，同一条工作点规则在那颗 PA 上要 10.0 dB。
- **验收**：指纹逐位不变；`vendor_check --strict` 114 个全 verbatim；示例 02 / 04 / 08 逐字相同，09 只差那一个标签。

### spec_sources 0.2.0：17 个键改名，重新 pin（2026-11-13，mmw60_trx#23）—— 数不变，示例 08 / 09 打印的 4 个键名变
- 重新 pin spec_sources @ `e573d4d99dcf0584b7245c4869aaaa8a84ada24c`（0.2.0，它的 PR #5）。8 个文件里 7 个变了：`__init__.py` 带上版本号，`reader.py` 去掉版本号，5 张表改键名并加 `aliases:`；`regulatory.yaml` 没变。
- 17 个前缀是来源标签的键换成新名（如 `survey.n_sd_11ac` → `ieee80211ac.n_sd`、`derived.pa60_rapp_p_asada_eumc2011` → `pa60.asada_eumc2011_rapp_p`，全表在 spec_sources CHANGELOG 0.2.0）。本库 42 处调用（13 个文件）、本地表 4 处文字（3 条 cite / note 与 `assumed.pa60_surveyed_pick` 值里的键名引用）跟着改；`examples/expected/` 里示例 08 三行、09 一行打印的键名变成新名。
- `mmw60.spec`：旧名经共享表的 `aliases:` 照样读到条目（`.key` 是新名），并发 `DeprecatedKeyWarning`（指向调用方），与 spec_sources 自己的读取器一致。pytest 的 `filterwarnings` 把这个警告变成错误：本库不留旧名，0.3.0 退役别名时无事可做。
- 删掉 `test_entries_a_downstream_library_reads_keep_their_keys_fields_and_values`：fmcw_radar 已迁完、不再 vendor 本库的表（spec_sources 在 #21 确认），这几条的消费者由 spec_sources 登记。换成一条别名测试：17 个旧名都读得到新条目、警告指向调用方、在本套件里是错误。
- **验收**：指纹逐位不变；`all_entries()` 仍 126 条，按改名表对应后 value / unit / source / quote / section 全同，cite / note 只在 spec_sources 登记的 3 条与本地 3 条文字里由旧名换成新名，本地 `assumed.pa60_surveyed_pick` 的值里一个键名引用换成新名；`vendor_check --strict` 114 个全 verbatim。

### 规范 / 文献数字表迁到共享库 spec_sources（2026-11-13，mmw60_trx#21）—— 只搬家，指纹不变
- vendor spec_sources @ `d7b4d1eb510617d69784622c593c8ed31ab32b8b`（它的 PR #1）：`__init__.py`、`reader.py` 与 6 张表（`liu2025`、`ieee80211`、`regulatory`、`frontend60`、`pa60`、`energy`），放在 `src/mmw60/vendor/spec_sources/`，每个文件两行出处头，原样不改。
- 本地 `data/spec/survey.yaml` 删掉迁走的 63 条（spec 10、survey 48、derived 5），剩 62 条（assumed 56、derived 3、survey 3）；表头改写。合并后的表 126 条 = 62 本地 + 64 共享（共享表新增 `isolation.tx_rx_tue2018_no_ebg_min_db`）。
- `mmw60.spec` 改成薄垫片：公开名字一个不少，`SpecNumber` / `SOURCES` 用共享库的（字段、顺序、默认值、校验逐字相同），`all_entries()` 合并两张表、同一个键出现两次报错，新增 `ref()`。Fig. 4、LDPC、PER 门限三组不动。
- 工具：`tools/vendor_check.py` 也核 `*.yaml`，清单的 pins 从文件头读（不再写死）；`tools/example_drift.py::spec_values` 连共享表一起读。`pyproject.toml` 的 package-data 加共享表；CI 的 vendor-drift 加 spec_sources 的 checkout（公开库，不要 token）。
- 测试：`test_spec_sources.py` 的两条 grep 守卫换成“每张表、四个标签都数，`audit_tags` 干净”（往本地表注释里注入一个标签字串时红、还原后绿），加一条“本地表只剩该剩的”；`test_vendor_check.py` 认两个 pin，加一条“共享表被当代码一样逐字核对”（拷贝的表是 verbatim，改一个数是 DRIFT）。
- **验收**：数值指纹逐位不变；迁移前后 `all_entries()` 的 125 个旧键 8 个字段的 `repr` 逐条相同，只多 1 条；`vendor_check --strict` 114 个文件全 verbatim（wifitrx 106 + spec_sources 8）；示例输出不动。
- 发现：迁移前本地表 `grep -c "source: spec"` 得 11、实际 10 条（D4 一段注释被多数一次），旧守卫只数 survey 与 assumed，没发现；现在每个标签都数。

### PA 工作点按 EVM 限值定；示例 03 / 08 在工作点上校准（2026-11-13）—— **numbers-move**（示例 02–09）
- 拓扑 A / B 预设的 PA 回退从 Liu 的 8 dB 改成**从 Psat 7.5 dB**（平均输出 6.6 → 7.1 dBm，P1dB 之下 2.9 dB）。规则是新的 `assumed.pa60_operating_rule`：PA 单独在 OFDM 样的高斯包络上 EVM 刚好到 −21 dB（802.11ad 16-QAM 的发射 EVM 限值）的回退。读法取自新读的 `pa60.wu_isscc2015`（spec）：60 GHz 收发机按“TX EVM 碰到 −21 dB 时的平均输出”给 Pout。数是 `derived.pa60_obo_at_evm_limit_db`（算出 7.457）。ROADMAP C10 的回退口径问题关掉。
- 新增 `frontend.grid.obo_for_isolated_evm(pa, evm_limit_db, …)`：PA 单独到某个 EVM 的最小回退（单调求根）。`config.tgad_em_pa(cfg)` 现在连回退一起放回旧的（11ad 形状 + Liu 的 8 dB）。Liu 的预设不变，**指纹逐位不变**。
- 示例 03 / 08 的校准改在预设工作点上跑（`run_cal_at(obo_db=fe.obo_db)`），不再跑在 wifitrx 的默认驱动上（ROADMAP C8 最后一条关掉）。示例 03 每列打印落点，并留一行默认驱动的对照。`derived.irr_after_cal_measured_db` 重导（57.3 / 55.9 / 53.4 / 51.9 / 48.1 / 40.2 dB）。
- 示例 09：两颗 PA 各自的回退分开打印；§2 加“工作点规则”一节（每种形状的规则回退、去掉 AM/PM、种子散布、Wu 那篇的额定点）；§4 的回退里加上预设的 7.5 dB。
- 测试：`tests/test_pa60.py` +3（规则复算、求根函数的单调与不可达、示例 03 每列落在预设回退上——变异成 6.92 dB 时红、还原后绿），预设与 `tgad_em_pa` 的断言改成新回退。`test_pamemory` 的 K = 32 慢测试改钉在示例 07 扫描的 8 dB 点上（7.5 dB 上匹配间隔比随信号缩放差 1.2 dB，原断言 < 1.0 不成立；那是 DPD 的崖口）；预设回退要在扫描网格上的断言改成成员测试。`test_thresholds` 的 c4 断言改成不等式。
- **动了什么**（详见 `cairn/LOG.md`）：PA 项 −22.1 → −21.1 dB。网格（示例 02）0.32 GHz 的四格 MCS3 → MCS2。同台表合规上限 11be 80 MHz × 4 MCS3 → MCS2，解码器上限 K = 1 @6 GHz 11be 80 MHz MCS6 → MCS5，2.56 GHz 行校准后的两列各降一档，其余行上限不动。7.5 dB 在 wifitrx DPD 的崖口：K = 8 上 DPD 拿回 0.0 dB（8 dB 时 2.0 dB）。示例 03 的 K = 8 回环 / 仅发 −21.0 / −20.4 → −22.1 / −21.4 dB。

### 拓扑 A / B 的预设换成测量的 60 GHz PA（2026-11-12）—— **numbers-move**（示例 02–09）
- `zero_if_60ghz`（以及建在它上面的 `if_extender_60ghz`、`wifi7_chain_k1`）的 PA 换成 `assumed.pa60_surveyed_pick`：Psat 14.6 dBm、增益 23.2 dB、峰值 PAE 16.3 %、Rapp 平滑度 1.286（P1dB 在 Psat 下 4.6 dB）。回退不变（Liu 的从 Psat 8 dB，平均输出 6.6 dBm）；AM/PM 仍是 11ad 的。`liu2025_table2`（示例 00 / 01、数值指纹的两份配置）不换，**指纹逐位不变**。
- 新增 `config.tgad_em_pa(cfg)`：把换之前的 PA（11ad 形状、假设的 15 dBm / 20 dB / 20 %）放回去，作灵敏度行；示例 09 改成“11ad EM 对预设”。
- `derived.irr_after_cal_measured_db` 按新的示例 03 重新导出（56.3 / 56.8 / 52.9 / 50.9 / 47.6 / 38.5 dB）。
- 示例 07 里描述预设 PA 的那句改成按前端实际的 P1dB 打印；`pamemory` 的模块说明同步。
- 测试里写死旧 PA 数字的几处改成读规范条目或新值（`test_compare`、`test_frontend`、`test_thresholds`、`test_pa60`），守的东西不变。`test_pamemory` 里 K = 32 那条慢测试原来在 wifitrx 的默认驱动上比两种记忆规律（落在不同回退上），改成在预设回退上比，与示例 07 一致；读数就是示例 07 回退 8 dB 那一行（−25.3 / −22.8 / −25.2 dB）。
- **动了什么**（详见 `cairn/LOG.md`）：同台表 ≤ 320 MHz 的行从 PA 限 MCS2 变成 PA 限 MCS3，640 MHz 的行改由 IQ 镜像限；解码器上限 K = 4 MCS4 → 5、拓扑 A（320 MHz）MCS4 → 6，K ≥ 8 不动。示例 03 / 08 的校准读数变差，原因是它们跑在 wifitrx 的默认驱动上，换 PA 后那个驱动离压缩近了 3.8 dB（ROADMAP C8）。

### 60 GHz PA 对照原文：`config.surveyed_pa`、示例 09（2026-11-12）
- 读了三篇 60 GHz CMOS PA 的原文（东工大 65 nm，作者实验室站点）。规范条目 +6：`pa60.asada_eumc2011`、`pa60.wu_asscc2012`、`pa60.ning_elex2011`、`pa60.eumc2011_table1`（spec，带引文）、`derived.pa60_rapp_p_asada_eumc2011`、`assumed.pa60_surveyed_pick`；`rx60.comm_asada2011` 补了发射侧三个数。未核实条目数不变（51）。
- **配置 schema 增加字段** `frontend.pa.rapp_p`（Rapp 平滑度，None = 11ad 的 0.81）。`Frontend60` 与 behavioural 路径都读它。`config.surveyed_pa(cfg)`：Psat / 增益 / 峰值 PAE 取一颗测量的 PA，平滑度由它的 Psat − P1dB 算出；回退与参考点不动。
- 示例 09（新）：测量的 PA 与预设并排；两种形状的 PA 单独 EVM 对回退（从 Psat / 从 P1dB 算）；功耗列的效率规律对照；wifitrx 的 DPD 步在两种 PA 上拿回多少；同台表 11be 80 MHz 行换 PA 后的解码器上限、速率、pJ/bit、限制项。
- **发现**：预设的 Psat 在测量范围里，偏的是形状（P1dB 在 Psat 下 9.5 dB，测量中位 3.3 dB）。换成测量的形状，K ≤ 4 与拓扑 A 升一到两档 MCS，K ≥ 8 不动。**推翻**上一条 C9 里“Asada 的发射机比本库假设的 PA 小很多”：那是收发机的发射输出，不是 PA。
- `tests/test_pa60.py`：+9。预设不动，指纹不变，示例 00–08 的输出不变。

### 规范表有了下游：记下被 fmcw_radar 消费的条目，并加一条守卫（2026-11-12）
- fmcw_radar（0.2.8）vendor 了 `spec.py` 与 `data/spec/survey.yaml`，按条目读 `rx60.radar_iwr6843`、`rx60.radar_iwr6843_fig7_2`、`isolation.tx_rx_tue2018`，加载时核对数值相等。`cairn/spec-sources.md` 新增“被下游消费的条目”一节。
- `tests/test_spec_sources.py`：+1，守着这三条的键、字段、数值与 `spec.py` 的公开名字。**以后动它们要在这里写明并同步改这条测试。**
- 只有文档与一条测试；代码、数字、指纹都不动。

### 接收压缩点分成两个面；删掉被撤回的天线条目 —— D4 的更正（2026-11-12）
- 起因：fmcw_radar 在 mmw60_trx#14 上读了原文后更正（AN600 里没有天线增益；TI 手册把接收压缩点分成带内 / 带外两个量），并请本库把压缩点给成两个字段。
- **公开签名变化**（上一条刚加的面，还没有下游消费）：`RxFront60.p1db_in_dbm` 改名 `p1db_inband_dbm`；新增 `RxFront60.p1db_oob_dbm`（基带高通之前的输入压缩点，None = 未指定）、`RxFront60.p1db_inband_by_gain()`；`describe()` / `faces()` 的键 `rx_p1db_in_dbm` 改成 `rx_p1db_inband_dbm`，新增 `rx_p1db_oob_dbm`。**配置 schema 增加字段** `frontend.rx_front.p1db_oob_dbm`（链路不消费）。
- `Frontend60.leakage_budget()`：`margin_to_p1db_db` 拆成 `margin_to_p1db_inband_db`（全双工的读法）与 `margin_to_p1db_oob_db`（雷达的读法；前端没给带外压缩点时是 None，不拿带内的数顶替）。
- 规范条目：新增 `rx60.radar_iwr6843_fig7_2`（spec，读图：NF 与带内 P1dB 随增益）；删除 `survey.antenna60_bgt60_an600_dbi`（提供方撤回）；`isolation.tx_rx_tue2018` 的备注里转述对方读正文的结果。未核实条目 52 → 51。
- 示例 08：§3 改成两个压缩点各自的余量，通信前端的带外一列写“未指定”；§4 去掉三行。
- **结论更正**：上一条里“雷达芯片的压缩点比通信前端高 17.6 dB，是两类前端的差别”不成立，那是带内对带外。同一种量法（带内）下只差 5.6 dB。
- `tests/test_frontend_faces.py`：+3（两个压缩点互不顶替、带内压缩点随档位、被撤回的条目不在表里）。预设不动，指纹不变，示例 00–07 的输出不变。

### 前端的三个面：接收前端、收发隔离、发 / 收天线增益 —— ROADMAP D4（2026-11-12）
- 起因：fmcw_radar 的消费清单（mmw60_trx#14）。三样都加在共享的 `Frontend60` 上，不为雷达改接口形状；倍频器底噪不进（雷达读剖面文件）。
- `config.RxFrontConfig`（`frontend.rx_front`：`wifi7_ladder` | `anchored`，`nf_db` / `iip3_dbm` / `gain_db`）、`FrontendConfig.antenna_gain_rx_dbi`（None = 与发射同一副天线）、`FrontendConfig.tx_rx_isolation_db`（None = 未指定）、`config.surveyed_frontend(cfg)`（把三个面换成查到的一档）。**配置 schema 增加了字段**，默认值就是原来的行为。
- `frontend/rxfront.py`（新）：`RxFront60`。`wifi7_ladder` 是 wifitrx 的 `DEFAULT_LNA_STATES` 原样（`sourced = False`）；`anchored` 把这张梯子整体平移，使最高增益档读到给定的 NF / IIP3 / 增益，换档电平按 wifitrx 自己的平衡点规则移动。面：`gain_db`、`nf_db`、`iip3_dbm`、`p1db_in_dbm`、`state_for(p_in)`。
- `Frontend60`：`rx_front`、`antenna_gain_tx_dbi`、`antenna_gain_rx_resolved_dbi`、`shared_antenna`、`tx_rx_isolation_db`、`tx_leak_at_rx_dbm()`、`leakage_budget()`、`faces()`。`describe()` 的形状不变。预设下接收链不传梯子（仍是 wifitrx 自己的默认），数字逐位不变。
- 规范条目 +11。**本库第一批 `source: spec` 条目（4 条，读过原文、带引文）**：`rx60.comm_asada2011`（A-SSCC 2011 论文）、`rx60.radar_iwr6843`（TI 数据手册 §7.9）、`isolation.tx_rx_tue2018`（IEEE TAP 2018 的摘要）、`dmg.rx_max_input_dbm`（ITU-R M.2003 2012 年版 §2.4.6）。另有 4 条 survey 只读到搜索摘要（未核实，只作灵敏度档），3 条 assumed（梯子形状、IIP3 到 P1dB 的 9.6 dB、基准档取哪几个数）。
- 基准档：接收增益 27 dB、NF 6.1 dB、IIP3 −20 dBm、发 / 收天线各 2 dBi（同一颗通信收发机，按“通信文献为主”），隔离 20 dB。雷达芯片只作对照。
- 示例 08（新）：三个面预设对查到的一档；接收 NF 五档的灵敏度 / SNR 轴上的链路 EVM / 校准读数；泄漏预算（隔离 20 / 25 / 40 dB）；天线增益对 EIRP 限值与可承受的路径损耗；拓扑 A 不消费接收面。每个数字后面标着条目名与 `[spec]` / `[survey, unverified]` / `[assumed]`。
- `tests/test_frontend_faces.py`：+17（预设不动、梯子平移、换档电平对着 wifitrx 的 `rebalance_thresholds` 核、P1dB 与链路里的三次项一致、NF 对灵敏度与 EVM、泄漏预算、两个天线字段、基准档只由规范条目组成、读过原文的条目带引文、配置校验）。
- 指纹不变，示例 00–07 的输出不变。

### PA 记忆的代价按回退读：示例 07 改以回退扫描为主表（2026-11-11）
- `pamemory`：`run_many`（同一行只跑一次，可多进程，数字与进程数无关）、`row_key` / `study_keys` / `cost_keys` / `sweep_keys` / `sweep_points`、`backoff_for_evm`（EVM 达到目标所需的最小回退，格点间线性插值）、`backoff_penalty`（两种记忆规律在同一 EVM 上各要退多少、差多少）。`study` / `cost_rows` 多一个 `jobs` 参数。
- 示例 07：新增“DPD 后 TX EVM 随回退”的扫描（K = 8、32）与“达到 −25 / −27 dB 要退多少”的表；记忆快慢的灵敏度改成按回退代价报；预设回退上的全表保留，但注明它在崖上。`--jobs` 默认最多 4 个进程。
- 规范条目：`assumed.pa_memory_obo_sensitivity_db` 换成 `assumed.pa_memory_obo_sweep_db`（细格点）、`assumed.pa_memory_obo_sweep_coarse_db`、`assumed.pa_memory_target_evm_db`。
- **结论更正（第三版）**：记忆按秒固定（12.5 ns）的代价是多退 0.5–2.3 dB（K = 8：1.6 / 2.3 dB；K = 32：0.5 / 0.6 dB），不是上一条写的“EVM 差 4.1 / 5.8 / 0.6 dB、隔 8–16 个样本最糟”。预设的 8 dB 回退在 DPD 的崖上，单点上的 EVM 差读到的是两条崖的间距。
- `tests/test_pamemory.py`：+3（插值、进程数无关、崖与回退代价的慢测试），去掉一条按旧结论写的慢测试。只动 `pamemory`、示例 07 与文档；其余示例输出与指纹不变。

### 重新 pin wifitrx@7b8d08e（0.7.40）：DPD 步留观测最好的一轮，`ScaledPA` 稳态定标（2026-11-11）
- `src/mmw60/vendor/wifitrx/` 重新同步到 `7b8d08eb9f11e426f9c99e079ebcbe06c2c64a02`（106 个文件 verbatim，3 个正文有变化：`cal/dpd_cal.py`、`pa/scaled.py`、`__init__.py`）。两处都是本库在 wifi_trx_cal#5 验收时报告、对方修掉的（B40、B41）。里程碑 0 指纹逐位不变。
- `pamemory.memory_pa`：去掉“在逐样本的 PA 上取定标再换模型”的绕法。
- `ifext.IfExtender.train_dpd_mmw`：不再循环 `n_iter` = 1 … N；调一次 `calibrate_dpd`（它自己留最好的一轮），再把它留下的与芯片上原有的预失真器在同一输出功率下比。**`dpd_mmw` 的键变了**：`observed_by_pass_db`、`kept_pass`、`evm_fitted_db` 取代 `evm_by_iterations_db`。
- **numbers-move**（示例 03、04、06、07；00 / 01 / 02 / 05 不变）：凡是旧版“开了 DPD 反而更差”的格都回到不差于不开的水平。示例 03 的 640 MHz 列最终 EVM −19.3 → −22.8 dB；示例 06 整套序列搬到 60 GHz 观测上的 DPD −14.1 → −21.7 dB；示例 04 只有拓扑 A 三行小动，MCS 不变。
- **结论更正（示例 07）**：上一条写的“记忆按秒固定时预设回退点上 DPD 基本失效，匹配间隔只在回退 ≥ 10.5 dB 的 K = 32 上赢”有一半是旧版 DPD 步写入发散的第 2 轮造成的。现在：K = 4 / 8 / 32 的代价 4.1 / 5.8 / 0.6 dB（原 7.3 / 6.0 / 3.2）；K = 32 上匹配间隔在预设回退上就追得上（−25.2 对 −25.8 dB）。代价由 PA 的抽头隔多少个样本决定，8–16 个样本最糟。

### 重新 pin wifitrx@da37888（DPD 抽头间隔透传）；PA 的电记忆研究 —— ROADMAP D3（2026-11-11）
- `src/mmw60/vendor/wifitrx/` 重新同步到 `da37888ab16f6a5f34d1d0f3d329a4b857b5f37b`（0.7.38；106 个文件 verbatim，9 个正文有变化：PA 模型更新到 PA_DPD@02ca433，`calibrate_dpd` / `run_full_cal` / `dpd_tracking` 可传抽头间隔）。pin 四处一起改。里程碑 0 指纹逐位不变，已有示例的输出不变。
- `src/mmw60/pamemory.py`（新）：带电记忆的参考 PA 进拓扑 B 的链路。`memory_pa`（按前端的增益 / Psat 定标；`fir_fs` 给定时抽头按秒固定，不给时随信号缩放）、`run_row` / `study` / `cost_rows`（wifitrx 的校准序列在该 PA 上真跑，DPD 关 / 各抽头间隔）、`candidate_spacings`、`best_spacing`。
- `calcheck.run_cal_at`：`pa=`（换发射 PA）、`dpd_tap_spacing=`（透传到 wifitrx 的 DPD 步，`CalRun.dpd_tap_spacing` 记的是该步自己写下的值）、`obo_db=`（把最终 EVM 检查放到指定的输出回退上：先修 VGA，落点不对就带修正重跑整套序列，`CalRun.passes` / `pout_dbm`）。默认参数下行为不变。
- 示例 07（新）：K = 4 / 8 / 32（11be 80 MHz 基准）× 两种记忆规律 × DPD 关 / 四个抽头间隔，全部在预设回退 8 dB 上；回退灵敏度（10.5 / 13 dB）；记忆快慢的灵敏度（抽头 12.5 / 3.125 / 0.78 ns）。
- 规范条目 +5，全是 assumed：`pa_memory_model`、`pa_memory_fir_fs_hz`（80 MS/s）及其灵敏度档、回退档、DPD 抽头间隔候选。预设与同台表不变（PA 仍是无记忆的 Rapp）。
- 数字：记忆按秒固定（12.5 ns）时，回退 8 dB 上 DPD 后 TX EVM 最好 −18.6 / −21.5 / −22.7 dB（K = 4 / 8 / 32），随信号缩放 −25.9 / −27.5 / −25.9 dB；匹配的抽头间隔只在回退 ≥ 10.5 dB 的 K = 32 上赢。
- `tests/test_pamemory.py` 新增（4 项快 + 2 项慢）。

### 重新 pin 两个上游：wifitrx@96078aa 的评分波形、pll_simulator@d67043e 的 ×10 剖面 —— ROADMAP D1 / D2（2026-11-11）
- `src/mmw60/vendor/wifitrx/` 重新同步到 `96078aa9438c590a24d13959472263ec5f9ab623`（0.7.37；106 个文件 verbatim，7 个文件的正文有变化），pin 在 `tools/vendor_check.py`、`tools/vendor_manifest.json`、`tests/test_vendor_check.py`、CI 四处一起改。里程碑 0 指纹逐位不变。
- `calcheck.upclocked_scoring_config`：没有标准导频表的带宽（640 MHz、2.56 GHz）用基准波形 × K 评分（基准的音与导频原样，音距 × K；靠 wifitrx 新的 `TonePlan(..., pilots=)`）。示例 03 原先 skipped 的两列跑出最终 EVM；
  `CalRun.final_views` 带出 wifitrx 最后一步的回环 / 仅发 / 仅收三个视图；采集长度成为显式参数（`n_symbols`，`assumed.cal_capture_symbols` = 8）并有 32 符号的灵敏度行。
- `impairments/phase_noise.py`：`load_clock_profile` 读出 `multiply_by` / `f_in_hz` / `floor_dbchz` / `spur_rejection_db`；`profile_at_carrier` 只接受整数的 f_c / f0（`profile_ratio`），带倍频器的文件只在自己的 f0 上用，非整数比与分频报错。**行为变化**：原先任意比值都按 20·log10 平移。
- 四个剖面文件入库（`data/clock_profiles/pllsim_wu19_x10_60p48g_floor{160,150,140,130}.yaml`，pll_simulator@d67043e 的 CLI 在本地生成）；规范条目 +4（`survey.clock_profile_wu19_x10`、`assumed.lo_multiplier_floor_dbchz`、`assumed.lo_multiplier_spur_rejection_db`、`assumed.cal_capture_symbols`），`assumed.lo_multiplier_law` 改写。
- **numbers-move**（示例 03、04）：示例 03 的 640 MHz / 2.56 GHz 两列整套换了激励，最终 EVM −19.3 / −26.0 dB，两列其余各步的数也动了（K = 1 / 4 / 8 / 16 四列不动）；示例 04 §5 的 pllsim 行从非整数的 ×9.672 换成 ×10 剖面（IPN −33.2 → −33.0 dBc，相噪 ICI 动 0.2–0.3 dB，MCS 上限不动），多三行底噪灵敏度；`derived.irr_after_cal_measured_db` 的 640 MHz / 2.56 GHz 两档改为 46.5 / 37.9 dB（同台表没有一格因此改变）。
- `tests/test_calcheck.py` 新增（5 项，含“640 MHz 的最终 EVM 是评分出来的，不是 skipped”，已做变异验证）；`tests/test_compare.py` +1（整数倍守卫）。

### 拓扑 A 的 DPD 结论更正：间接学习的迭代次数（2026-11-11）
- `IfExtender.train_dpd_mmw`：60 GHz 观测回环上的 DPD 不再只跑 wifitrx `calibrate_dpd` 的默认 2 次迭代，而是 1 … N 次各训一次，每个候选放回同一输出功率、在同一观测通路上读 EVM，
  连同芯片上原有的预失真器留最好的；`IfExtConfig.dpd_max_iterations`（`assumed.ifext_dpd_max_iterations` = 2）。候选之间的比较改在同一条件下做（第一版的基线带着固定 LO 的相噪，候选不带）。
- **更正（numbers-move，示例 06 §3）**：A1 写的“预设 8 dB 回退上观测回环值 0 dB、ILA 发散”是迭代 2 次造成的。迭代 1 次：回退 6 / 8 / 10 / 12 / 14 / 16 dB 处观测回环值 0 / +1.3 / +6.2 / +9.5 / +9.7 / +8.8 dB。
- 上游往来记入 ROADMAP D 节：pll_simulator#71 已落地并关闭（`d67043e`），PA_DPD#4 已落地并验收通过（`02ca433`，issue 留到链条走完），wifi_trx_cal#4 的正文需求已落地（`96078aa`）。本库的重新 pin 都还没做。
- `tests/test_ifext.py`：守护测试改为“留最好的一次迭代，且不比芯片上的差”。

### 拓扑 A：IF 延伸 —— ROADMAP A1（2026-11-11）
- `src/mmw60/ifext.py`：`IfExtenderTx` / `IfExtenderRx`（wifitrx `TxChain` / `RxChain` 的子类，60 GHz 级显式加在父类调用之后 / 之前，级关掉时逐位等于父类）；
  间级电平、IF 带通（Chebyshev-I 低通等效）、固定 LO 混频、共享 `Frontend60` 的 60 GHz PA；频率规划 `if_plan`；芯片按 wifitrx 自己的配方随机化并跑完 `run_full_cal`（铁律 4）；DPD 可在 60 GHz 观测回环上重训，比不过已有的不写入。
- `impairments/cfo.py::MloCfo`（铁律 3 的 A 接法）：sub-7 链路的 CFO 估计 × f_c / f_sub7 预补偿，残差 = 估计误差 × 频率比，估计器真跑；ppm = 0 时整项关掉。
- 配置：`topology: if_extender` 可运行（`if_extender_60ghz` 预设），`LoConfig.if_hz`、`IfExtConfig`、`frontend.model: if_extender_chain`；9 个 assumed 条目（IF、LO 方案、滤波器、镜像抑制、芯片 seed / 过采样、MLO 的 sub-7 链路、同源晶振）。**schema 变化**：`Mmw60Config` 多一个 `ifext` 块，`LinkSim` 对拓扑 A 不再抛 `NotImplementedError`。
- 同台表：拓扑 A 的行接入（`compare.PENDING` 里去掉那格），解析底板多“芯片残差”“芯片 LO”两项，功耗多“芯片 PA 当驱动级”一块、每端两个频综；示例 04 加拓扑 A 在 320 MHz 上的一行。
- 示例 06：频率规划、逐步校准（芯片耦合器 / 60 GHz 观测回环）、有无观测回环的 DPD、MCS 上限随 LO 相噪（对 `EvmBudget`）、级联回退、CFO、假设的灵敏度、PER 复核。
- **更正（numbers-move，示例 04 的 EvmBudget 列）**：`compare._pn_terms` 把 wifitrx 单边带口径的 IPN 当相位方差，少了 2 倍；A3 记下的“EvmBudget 乐观 3–4 dB”里 3.0 dB 是这个错。改正后每行 EvmBudget − 底板 = 0.0 dB。
- 数字：拓扑 A 11be 80 MHz 链路 EVM −18.2 dB、解码器上限 MCS4；同样 320 MHz、865 Mb/s 上 A 1127 对 B 628 pJ/bit；60 GHz 观测回环的 DPD 在回退 12 / 14 / 16 dB 值 +5.8 / +8.2 / +7.1 dB，在预设的 8 dB 上值 0；LO 扫描 EvmBudget 与时域差 ≤ 0.23 dB。
- `tests/test_ifext.py` +11；`test_laws.py` / `test_compare.py` / `test_examples.py` 跟着“拓扑 A 已建”更新。里程碑 0 指纹不变。

### 接收机精度 —— ROADMAP C1–C3（2026-11-11）
- C1 `rx/tracking.py::smoothed_cpe`：导频公共相位跨符号 MMSE 合并（窗内留一平均 + 按导频残差自己量出的收缩系数，残余 CFO 斜坡先去后加）；`RxConfig.cpe_window_symbols`，1 = wifitrx 逐符号估计（逐位相同）。
- C2 `rx/tracking.py::auto_smooth_span`：信道估计平滑跨度逐包从估计自己的音间自相关选（指数时延谱模型定 1 音还是 3 音，再宽看实测偏差）；`RxConfig.ce_smooth_auto / ce_smooth_max_tones`。
- C3 `per_sweep(refine_errors=…)` 把夹住目标 PER 的两点续跑到固定错包数，`snr_at_per_ci` 给 bootstrap 95 % 区间；`tools/external_check.py` 的判决三态（within / OUTSIDE / 分不出）。
- 预设：`zero_if_60ghz` 用改进的一档（`config.improved_rx`），`liu2025_table2` 保留里程碑 0 的接收机（对外校验与指纹钉在它上面，指纹 68 值逐位不变）。两个新 assumed 条目（窗 17 符号、跨度上限 9 音）。
- `per_thresholds.yaml` 用改进接收机重量（numbers-move）：11ac 20 MHz 降 1.0–2.8 dB，11be 降 0.1–2.1 dB；`decoder_floor_db`：未校准的解码器上限从解析底板与时域 EVM 中较差的一个起算。
- 数字：示例 00 改进接收机比里程碑 0 的好 2.7–3.7 dB；同台表最好的一行从 11be 80 MHz × 4（865 Mb/s、628 pJ/bit）变成 × 8（1729 Mb/s、467 pJ/bit）；2.56 GHz MCS0 的 PER 1e-2 点 5.16 → 0.60 dB。示例 00 / 02 / 04 / 05 的期望输出随之更新。
- `tests/test_tracking.py` +10、`test_thresholds.py` +1；非慢测试 133 → 144。ROADMAP 删 C1–C3，加 C6（过程中发现的三条）。

### 上游需求转交（2026-11-10）
- ROADMAP D1–D3 已作为 issue 交给 wifi_trx_cal#4、pll_simulator#71、PA_DPD#4，D 节加链接；D3 关于 `ReferencePA` 记忆的措辞按源码更正（固定抽头、无 `fs` 参数）。只改文档。

### 解码器上限列 —— ROADMAP A3 剩余项（2026-11-10）
- `tools/measure_thresholds.py` → `data/spec/per_thresholds.yaml`（source derived）：本库接收机在理想零中频链上 4096 B 包 PER 1e-2 的门限，11ac 20 MHz MCS 0–8 与 11be 20–320 MHz MCS 0–13 共 79 条曲线（约 16 分钟 / 4 核）。为什么：A2 证明“底板比 TX EVM 要求低 3 dB”的合规口径比解码器容忍度保守约 2 档，要换口径就得有每个 MCS 的门限；wifitrx `snr_req_db` 未审核且悲观 1–3.5 dB。
- `frontend/grid.py::decoder_cap`：EVM 底板当噪声，−floor ≥ T + 3 dB（`assumed.decoder_cap_margin_db`）判可达，给出所需 SNR 与底板的代价；示例 02 加 dec / dec-cal 两列，示例 04 加 §4b（上限、所需 SNR、该上限处的速率与 pJ/bit）与灵敏度里的“解码器上限动了几行”和余量 1 / 6 dB 两端；合规口径的列与结论列原样保留。
- 数字：11be 80 MHz × 4 解码器上限 MCS4（合规 MCS2），865 Mb/s、628 pJ/bit（合规口径 432 / 1241）；× 16 MCS2、1729 Mb/s；2.56 GHz 未校准能带 MCS0。示例 05 逐格复核：线性区预测与实测差 ≤ 0.06 dB（13.89 / 13.92、9.63 / 9.69、8.29 / 8.32），底板高于 −8 dB 的格所需 SNR 低估约 3 dB。
- 功率列的 LDPC 解码块改按该行上限 MCS 的码率计（原按 MCS0 的 R = 1/2）：11be 两行 pJ/bit 动 −7 / −8（numbers-move：2401 → 2393、1248 → 1241）；示例 02 / 04 / 05 的 expected 重新 accept。指纹逐位不变。
- `tests/test_thresholds.py` +4（文件标签与单调性、复量一个门限、上限算术、示例 05 的发现作守护）；`test_compare.py` 加解码器上限断言。

### 11be 编码 PER —— ROADMAP A2（2026-11-07）
- `phy/ldpc.py`：802.11 的 12 个 QC-LDPC 码（648 / 1296 / 1944 × 1/2 … 5/6），原型矩阵进 `data/spec/ldpc_80211.yaml`（source survey：simgunz/802.11n-ldpc 与 tavildar/LDPC 两份独立转录逐项相同，双对角结构逐张校验）；系统编码器（H_p 的 GF(2) 逆）；归一化 min-sum 解码器 numpy / numba 两内核逐位相同（`MMW60_NO_JIT=1`）。
- `phy/eht.py`：EHT MCS 0–13 × 20–320 MHz（N_SD 234 … 3920，MCS 9 / 11 在 996 音 RU 上的分数 N_DBPS 按规范保留）、LDPC PPDU 编码流程（码长 / 码字数 / 缩短 / 删余 / 重复 / 加符号）、音映射器（D_TM 9 / 12 / 20）、段解析器（160 / 320 MHz）、到 4096-QAM 的可分离 max-log LLR（≤ 256 阶保持里程碑 0 的算术）。为什么：11be 行以前只有 EVM，同台表和 PER 曲线都要它；ROADMAP 把它排在 ay 之前。
- `Mmw60Config.coded` 覆盖 11be 全部带宽；`RxConfig.ldpc_max_iterations / ldpc_minsum_scale`（assumed 条目）；`RxConfig.dc_removal`（在突发前的静默段上量 DC 再减掉——wifitrx rx_dc_offset 校准的量法；零中频预设开、默认关以保指纹）——**新发现**：−25 dBc 的 RX 自混频 DC 在 CFO 校正前把 L-STF 自相关估计偏置约 1 个子载波（SNR ≤ 10 dB），11be 80 MHz × 8 的 impaired 包全错；去 DC 后 2 dB 处就能解（`tests/test_frontend.py::test_dc_removal_keeps_the_stf_estimator_honest_at_low_snr`）。
- 功率列：11be 行有了 LDPC 解码块（每边每迭代 2 次加等效、按最大迭代数计）；示例 02 / 04 的 11be 格因数据域从随机 16-QAM 变成编码 MCS0 而数字微动（numbers-move，expected 重新 accept）。
- 示例 05：11be 80 MHz × 4 / 8、MCS 0 / 4 / 7、ideal / impaired / no-PA 的 PER–SNR，并与示例 04 的解析 MCS 上限对判——**上限口径被推翻**：TX-EVM 合规口径比解码器容忍度保守约 2 档，“底板当噪声”1/(1/SNR + 10^(floor/10)) 的预测与实测 PER 门限对上（MCS4 预测 13.9 / 15.2 vs 实测 13.88 / 15.05）；`tests/test_ldpc.py` +11 项，非慢测试 107 → 129。
- 数字：`cairn/LOG.md` 2026-11-07（A2）；`cairn/comparison-table.md` §2 的 11be 行更新。

### 同台表与预算报表 —— ROADMAP A3（2026-11-07）
- `mmw60.compare`：`scheme_matrix` 点名全部 8 个（拓扑 × 波形）格子（建好的有数字，没建的写里程碑 / n/a）；每行数字学、CFO 捕获、解析底板、时域 EVM、wifitrx `EvmBudget` 对账、MCS 上限（未校准 / 示例 03 实测 IRR）、速率与 b/s/Hz、EIRP 余量、功率分块；`sensitivity` 在每个系数的区间端点重跑并列出动了什么。为什么：铁律 2 要的是"每种方案在同一个实例上同台"，表必须把没建的方案也点名。
- `mmw60.power`（Halo 示例 41 口径）：PA 直流、两只频综、I/Q 转换器（Walden）、DPD（dsp_ip × Horowitz）、基准尺寸 FFT、Viterbi，读比值不读总量；系数全部进 `survey.yaml`（survey / assumed）。
- `PhaseNoiseConfig.model: pole_zero | wifitrx_wifi7 | profile | off`：WiFi 7 频综的 vendored 剖面，以及 pllsim 时钟剖面文件（Halo 的 wu19 原样复制到 `data/clock_profiles/`）按 20·log10 N 搬到载频（D2 的占位）；`FrontendConfig.pa_pae_max`；预设 `wifi7_chain_k1`（同一前端在 1× 的 WiFi 7 链）；`guispec` 19 个 Knob。
- 铁律 2 的完整测试 `test_law2_every_scheme_on_the_shared_frontend_reads_the_k1_evm_when_ideal`（理想实例共用、每种已建方案 < 0.1 dB；A / ay skip 并写明里程碑）；`tests/test_compare.py` +12 个函数（矩阵格参数化后非慢测试 84 → 107 项，6 项按里程碑 skip）；`tools/budget_report.py`（d2d 写法）；示例 04 + expected + 3 条 derived 引用。里程碑 0 / 1-B 指纹逐位不变。
- 数字与被推翻的判断：`cairn/comparison-table.md`、`cairn/LOG.md` 2026-11-07。

### 方案枚举与 ROADMAP 结构（2026-11-07）
- `Mmw60Config.waveform: be | be_upclocked | ay_ofdm | ay_sc`（ay 两项在里程碑 3 之前抛 NotImplementedError，与拓扑 A 在里程碑 1 之前同法）；铁律 1–4 的措辞改为"每种方案（拓扑 × 波形）"；守护测试 `test_law1_waveform_enum_is_complete_and_ay_refuses`；指纹逐位不变。
- CI 修复：示例 02 / 03 接受 `--jobs`（`pytest -q` 的 slow 冒烟测试传它）；`tools/fingerprint_walk.py` 适配本库 `compare` 返回列表（原先按 d2d 的二元组取 `[1]`，PR 的 fingerprint 作业因此 IndexError）。
- ROADMAP：新增"里程碑 3：802.11ay"（ay 是拓扑 B 硬件配第三、四种波形，不是第三条拓扑）；D 节改为"报回上游（等用户转）"，三条需求写成可直接贴进对方 ROADMAP 的格式，另收 fmcw_radar 的消费清单；array_tx 的 pin 可落实（e897c159）。

## 里程碑 1-B —— 拓扑 B：60 GHz 零中频前端、基准 × K 网格、校准逐项验（2026-11-07，0.1.0）

- **`frontend/`：两拓扑共用的 `Frontend60`**（铁律 2 的对象）：Rapp PA 在 dBm 域的 `ScaledRappPA`（wifitrx `ScaledPA` 对单调 Rapp 找不到饱和点）、
  `Lo60`（1 极 1 零剖面 + TX 泄漏 dBc + RX 自混频 DC dBc）、`ConverterLaw`（ENOB 随采样率 −0.5 bit/octave）、`IqMismatch`（wifitrx 绝对单位）、
  `EirpLimit`（FCC 15.255）、`zero_if_plan`、`dpd_cost`（dsp_ip dpd_poly P=4 综合数 + Horowitz 运算能耗）。
- **拓扑 B = wifitrx `TxChain`/`RxChain` 跑在 fs_eff**（`frontend.model: zero_if_chain`）：转换器位数按 ENOB(fs_eff)、LPF 角频按 K 倍带宽、
  IQ 失配 ps 绝对值、PA 工作点由模拟 VGA 调到 Psat − OBO（数字驱动固定 −16.5 dBFS 不削顶）、接收输入电平由 SNR 经 LNA 状态 NF 反算、
  包络互相关定时（复波形互相关在 2.94 MHz CFO 下失效）。为什么：这正是"WiFi 7 芯片的零中频架构时钟 ×K"，而且校准序列可以原样真跑。
  里程碑 0 的 behavioural 路径逐位不变（指纹相同）。
- **EVM-only 基准**：11ac 40/80/160、11be 20–320 MHz 走 wifitrx 随机 QAM + 导频，接收机对 `TxRef` 评分；编码 PER 仍只在 11ac 20 MHz。
- **示例 02 网格**：9 个基准 × K ∈ {4,8,16,32}，每格解析底板（相噪 ICI、IQ 镜像、转换器、PA、GI 外 ISI）、校准后 IQ 列、去 PA 列、
  MCS 上限、能/不能 + 原因、时域 EVM（全开 + 逐项隔离）、顶 MCS 的速率与 DPD pJ/bit、转换器 −1 bit/octave 灵敏度。
- **示例 03 校准表**：wifitrx 序列（poweron）在 K = 1/4/8/16/32 与 11be 80 MHz × 32 上逐步 ok/degraded/failed/skipped + 机理（`calcheck.MECHANISM`）。
- 规范表 +15 条（FCC 频带、11ay 信道、dsp_ip 数、Horowitz、N_SD 表、转换器 / PA / 泄漏 / IQ / 余量假设）；测试 +17（`tests/test_frontend.py`）。
- 数字与被推翻的判断：`cairn/LOG.md` 2026-11-07、`cairn/topology-b.md`。

## 里程碑 0 —— 对外校验：Liu 2025 Table II / Fig. 4（2026-11-06，0.0.1）

- **脚手架 + vendor**：`src/mmw60/vendor/wifitrx/` 是 `wifi_trx_cal@cc06b9ac8dafb5cbb261a59280e81ae0cfbf787c` 的 `src/wifitrx` 整包（106 文件，全 verbatim），
  每文件两行头；`tools/vendor_check.py`（polar_tx 的改编：只剥本库的两行头、查 `__init__.py`）+ `vendor_manifest.json`；CI `vendor-drift` 按完整 SHA checkout，
  private 仓库需 `SIBLING_READ_TOKEN`。Project Cairn 文件集（AGENTS / CLAUDE / .cairn / ROADMAP / CHANGELOG / cairn/LOG + 五篇专题）。
- **upclocking 层**（`upclock.py`）：基准数字学 + `fs_eff = fs_base × K`，K = 1 是未改动的 wifitrx 链（铁律 2 的锚）。为什么不改 SCS：wifitrx 的导频表精确匹配 SCS。
- **VHT 数据域编解码**（`phy/`）：扰码、BCC 133/171 + 删余、20 MHz 交织、Gray 映射 + max-log LLR、软判决 Viterbi（numpy 向量化 + numba 内核逐位相同，`MMW60_NO_JIT=1`）。
  为什么：wifitrx 是 EVM 级模型，没有 BPSK、没有信道编码，测不了 PER。
- **损伤**：1 极 1 零相噪 `PoleZeroPhase`（wifitrx `NoiseSource` 子类，用它的 `synth_from_psd`）、`CfoModel`（(ppm_tx + ppm_rx)·f_c，0 ppm 逐位为零）、
  `pa/rapp.py` 11ad EM 的 modified Rapp（OBO 参考点 psat / p1db 两档）、`channel.py`（flat / 指数 PDP + LOS K / 显式 tap 表）、每子载波 Es/N0 的加噪口径。
- **接收机**（`rx/`）：wifitrx 自由函数的组合 + 本库的 L-STF 粗 CFO 估计（±625 kHz × K）与整数子载波模糊解算（示例 01）；`cfo_estimation: off | ltf | stf_ltf | extended`；
  诊断用 `genie_csi`。
- **配置 / 规范表**：frozen `Mmw60Config`（两条拓扑都在枚举里，A 在里程碑 1 之前抛 NotImplementedError）、YAML 往返、`guispec.py` 18 个表单字段；
  `data/spec/survey.yaml` 48 条（33 survey / 10 assumed / 5 derived）+ `liu2025_fig4.yaml` 读图值。
- **示例与工具**：示例 00（Table II 三组曲线：字面 / 无损伤 / flat 信道 + 灵敏度行（含 OBO 自 P1dB、Rayleigh、PN rx-only、理想 PA、不平滑） + "CFO 估计全关"诊断行）、示例 01（扩展捕获范围）、
  `tools/external_check.py`（对 Fig. 4 逐条差值）、`fingerprint.py` / `fingerprint_walk.py`、`run_examples.py`、`example_drift.py`（d2d_link 原样）。
- **测试**：68 项（66 项 `pytest -m "not slow"` + 2 项示例冒烟 slow），铁律 1 / 3 / 5 / 6 / 7 各有守护测试，2 / 4 有锚；解码器压在 BCC 并集界上的解析 / 仿真交叉核对。
- **验收结果与被推翻的判断**：见 `cairn/LOG.md` 2026-11-06 与 `cairn/external-validation.md`。
