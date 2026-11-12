# ROADMAP

**这份文件只写还没做的事。** 做完即删，并在 `CHANGELOG.md` 记一笔、`cairn/LOG.md` 记数字。每条带证据（复现方式与数字）。

## A. 里程碑 1 —— 两条拓扑同台（主体都已落地；下面是剩余项）

### A1. 拓扑 A 的剩余项（主体已落地：`src/mmw60/ifext.py`、示例 06、`cairn/topology-a.md`）
- **芯片的 PA 当驱动级太贵**：芯片 PA 在 13.3 dBm 耗 294 mW（10.1 dBm 时 202 mW），而它的输出要先衰减 24 dB 才到 60 GHz PA 的驱动电平；同样 320 MHz、865 Mb/s，拓扑 A 1128 对拓扑 B 628 pJ/bit，其中芯片 PA 占 339。
  复现：`python examples/06_topology_a_if_extender.py` §5、`examples/04_comparison_table.py` §4。待做：芯片 PA 旁路（IF 从 PA 前取）的一档，wifitrx 的 `TxParams.pa_enabled = False` 加上它的 DPD / tx_power 两步怎么处理。
- **间接学习在软压缩 PA 上越迭代越差，靠近饱和时 1 轮也不够**：60 GHz 观测回环的 DPD 在回退 6 dB 上每一轮都不如不加（观测读数 不加 −16.0、第 1 轮 −14.6 dB），留芯片上的；8 dB 上只值 +1.2 dB（示例 06 §3）。
  整套序列搬到 60 GHz 观测上，IQ 校准的 IRR 从 55.7 掉到 37.9 dB，芯片自己输出端的 TX EVM 掉到 −11.9 dB（§2）。挑哪一轮现在由 wifitrx 的 DPD 步自己做（0.7.39），本库只再和芯片上原有的比（`train_dpd_mmw`）。
  待做：这类 PA 上换直接学习，或目标增益按可达的峰值输出折算（PA_DPD 有 `dpd/direct.py`，针对样条预失真器；已在 PA_DPD#4 上问对方要不要单开 issue）；
  或在观测通路里先把第二级 PA 的失真建模扣掉再做 IQ 校准。
- **拓扑 A 没有 pllsim 推出来的 LO 行**：pll_simulator 的模型只覆盖到 12 GHz，拓扑 A 的 18.0 GHz（×3）/ 13.5 GHz（×4）它不出（pll_simulator#71 的答复）；可行的是 6.0 GHz × 9 = 54.0 GHz（对方 CLI 能出，IPN −33.99 dBc）。现在的 LO 扫描用 1 极 1 零剖面直接给在 LO 输出端。待做：`LO_SCHEMES` 加 ×9 一档并生成该剖面；`make_profile` 现在对两条拓扑都传载频（60.48 GHz），拓扑 A 要改成传 LO 频率（54.0 GHz）才接得上，复现：`Frontend60.from_config(dc.replace(if_extender_60ghz(mcs=4), lo=LoConfig(phase_noise=PhaseNoiseConfig(model='profile', profile_path='pllsim_wu19_x10_60p48g_floor150.yaml'))))` 不报错，用的是 60.48 GHz 的剖面，比 54.0 GHz 的高 20·log10(60.48/54) = 1.0 dB。
- 没建的：60 GHz 级自己的 LNA 噪声系数（SNR 轴仍按芯片 LNA 的 NF 定义，与拓扑 B 同口径）、混频器的非线性、IF 滤波器的温漂、采样钟偏差（两条拓扑都没建）；MLO 的 sub-7 链路只有 AWGN（没有它自己的相噪和多径）。
- 11ac 20 MHz 的拓扑 A 行 pJ/bit 是 29291：20 Mb/s 的分母，不是硬件差（与 `comparison-table.md` §6 ① 同理）。

### A2. 拓扑 B 的剩余项（主体已在里程碑 1-B 落地：`cairn/topology-b.md`）
- 示例 02 网格的 "IQcal" 列仍用 `assumed.irr_after_cal_db`（45 dB）；同台表（示例 04）已换成示例 03 实测的 `derived.irr_after_cal_measured_db`，一格结论都没动（`cairn/comparison-table.md` §6 ④），网格要不要跟着换只是口径统一的问题。
- 11ac 40 / 80 / 160 MHz 基准仍是 EVM-only（它们的 BCC 交织器未建；11be 全部带宽已有 LDPC 数据域，`phy/eht.py`）；要不要补只看有没有人要 11ac 宽带的 PER。
- 11be 数据域里没建的：HE/EHT 的预 FEC 填充 a 因子与 PE 字段（按 HT/VHT 流程，`assumed.eht_prefec_padding`）、EHT 11 位扰码器（PER 不感知）、MU-RU / 320 MHz 打孔 / DCM / 多流。
- 转换器 ENOB 随速率的法则（`assumed.converter_bits_per_octave`）换成 Murmann 调查表的实测包络（拿到表后标 survey）。
- DPD 的 2.56 GHz 代价现在是 dsp_ip P=4 综合面积 + Horowitz 运算能耗的记账，按逐样本的 GMP 算；带记忆的 PA 上基函数要改（C8 第一条），那时项数与代价要重算。

### A3. 同台表的剩余项（主体已落地：示例 04、`tools/budget_report.py`、`cairn/comparison-table.md`）
- WiFi 7 全链路四条整合：PA_DPD 的 PA / DPD 进 wifitrx 链在 K > 1 上已作为灵敏度研究接通（`pamemory.py`、示例 07：参考 PA 带记忆、wifitrx 的 DPD 步、抽头间隔透传），但预设与同台表的 PA 仍是无记忆的 Rapp，带记忆的 PA 没有进任何一行（C8）。还没做的一条：Halo ADC 校准接入（要 vendor halo 的 `adc` 模块，现在转换器列是 ENOB 法则 + Walden 计价，没有通道失配项）。已做：pll 剖面替换解析相噪（`PhaseNoiseConfig.model: profile`）、`EvmBudget` 对账（A1 更正单边带换算后每行差 0.0 dB，相噪项差 0.1–1.3 dB）。
- 解码器上限列（`decoder_cap`，已落地）的剩余：11ac 40 / 80 / 160 MHz 基准没有门限（n/a，要先建 BCC 宽带交织器）；示例 04 §6 的灵敏度从解析底板起算（每个旋钮不跑时域），2.56 GHz 行在那一节的基线是 MCS1、§4b 用时域底板是 MCS0；`per_thresholds.yaml` 是本库接收机的测量值，接收机再改要 `python tools/measure_thresholds.py --jobs 4` 重量（约 16 分钟）。
- 校准列现在是示例 03 实测 IRR 的查表，`calcheck.run_cal_at` 实跑进表要几分钟一列，留给需要它的那次。
- 表单字段：`guispec.py` 已有 19 个 Knob，桌面 GUI / Android 这一轮不做。

## B. 里程碑 2：阵列层
- vendor array_tx（按当时 main 完整 SHA；array_tx main 现为 `e897c159e5fc5b2e26af6336cf9f6164461ff7f5`，可以直接 pin），波束训练序列的 SNR 预算。

## 里程碑 3：802.11ay
ay 不是第三条拓扑，是拓扑 B 的硬件（zero_if_chain）配第三、四种波形：`waveform: ay_ofdm | ay_sc`，包在 vendored wifitrx 的 OFDM 机制外面，不进 polar_tx。同台表多两行，不多列。
- `ay_ofdm`：512 点 FFT、SCS 5.15625 MHz、2.64 GS/s、单信道 2.16 GHz，绑定 2 / 3 / 4 信道（4.32 / 6.48 / 8.64 GHz）；导频和前导（CEF）按 ay 的来，不复用 be 的表——所以它不等 D 节的 wifitrx 非标准带宽导频需求；绑定 4 时前端带宽是单信道的 4 倍，同台表加一列"绑定信道数 × 前端带宽"。
- `ay_sc`：单载波 PHY，π/2-BPSK 到 64-QAM，Golay 前导。最有价值的一行：SC 的 PAPR 比 OFDM 低 3–4 dB，正打在 PA 的 Psat 墙上；要回答"SC 用回退换来的 EIRP，够不够抵掉丢掉的频谱效率"。
- CFO：SCS 5.16 MHz 天然接住 2.4 MHz，不用 MLO 预补偿（铁律 3 仍要声明并有测试）。
- 波束训练：ay 原生自己做 sector sweep，没有 sub-7 链路；训练序列的 SNR 预算单算，和拓扑 B 靠 MLO 触发的那行对比。
- 校准：依赖 be 导频 / 音的步骤（逐音 ρ(f)、LO 泄漏环回、group_delay）为 ay 重写探针信号；算法和 `deps.py` 顺序不变；结果进"校准步骤 × 方案"表（示例 03 的表加列）。
- 数字来源：ay 的数字学、MCS、灵敏度表进 survey.yaml，拿不到原文全标 survey。

验收：ay_ofdm 理想链路的 PAPR 和带内 EVM 与公开文献同量级；ay_sc 的 PAPR 比 ay_ofdm 低 ≥ 3 dB（物理，不对就是波形生错了）；同一 PA、同一 EIRP 上限下 ay_sc 对 ay_ofdm 的回退差和 EIRP 差进 LOG，"净吞吐 × 距离"谁赢一句话；校准表每步对 ay 的状态有记录；现有两拓扑的行逐位不变（指纹）。
不做：EDMG MIMO、ay 的 MAC 层、SC 与 OFDM 混合帧。
前置：A3 同台表已出。A2 里"11be 编码 PER 排在 ay 波形之前"保留。

## C. 里程碑 0 过程中发现的问题

### C4. 需要外部输入才能关掉的（见 `cairn/spec-sources.md` 末节）
Liu 2025 的 Rapp 参数与 OBO 定义；11ad CR 信道 tap 表；11-09/0296r16 原文。

### C5. 里程碑 1-B 发现的（见 `cairn/LOG.md` 2026-11-07）
- 60.48 GHz 上 40 ppm = 2.42 MHz，K = 4 的 L-STF 范围 ±2.5 MHz 刚好接住——Liu 的 K > 4.7 门槛是 73.44 GHz 的；通式 K > 2·Δf_max / 1.25 MHz。
- 回环定时：wifitrx `align_delay` 对复波形互相关，2.94 MHz CFO 下 1 µs 内去相关；本库用包络互相关定时（`sim/link.py::envelope_lag`）。

### C6. C1–C3 过程中发现的（见 `cairn/LOG.md` 2026-11-11）
- **门限表自己还没用上 C3 的逼近**：`tools/measure_thresholds.py` 仍是每点 ≤ 200 包 / 15 错、0.5 dB 步。同一格（11be 80 MHz MCS4 理想链）门限表读 11.40、示例 05 读 11.09；
  解码器上限的预测因此带约 ±0.3 dB（K = 4 的 MCS4 预测 12.97、实测 12.12）。待做：工具加 `--refine`（`per_sweep(refine_errors=…)` 已有，79 条曲线约多 3 倍时间），区间写进文件。
- **平滑跨度选择器在窄带上有散布**：flat 理想链 `zero_if_60ghz(k=8)`（11ac 20 MHz，56 音）120 包的 `RxResult.ce_span` 分布，SNR 3 dB 时 9 音 67 %、3 音 32 %，12 dB 时 56 % / 39 %；
  同样条件 11be 80 MHz（996 音）全部取 9 音。56 个音上“多于 3 音”那一步的偏差估计，自己的散布 W₃·√(2/N) 与要省的噪声同量级。待做：信道准静态时跨包平均自相关，或改 DFT 域去噪。

### C7. 重新 pin wifitrx@96078aa、接入 pllsim ×10 剖面时发现的（见 `cairn/LOG.md` 2026-11-11）
- **校准采集 8 个符号在窄基准 × 大 K 上不够**：`python examples/03_calibration_at_k.py` 的 K = 32、11ac 20 MHz 基准（640 MHz，52 音，1280 样本）一列，DPD 步每一轮都不如不加、一轮都没写入，仅发 EVM −22.8 dB（与不开 DPD 相同），采 32 个符号 −29.0 dB（同一示例的灵敏度节）。
  默认值没改（`assumed.cal_capture_symbols` = 8，每列同一个符号数）。待做：采集长度按样本数而不是符号数给（或按 GMP 系数个数的倍数），K = 1 为什么够、K = 32 为什么不够要单独验证（候选是观测 ADC 的 ENOB 随 fs 下降）。
- **2.56 GHz 列的退化项没有被最终 EVM 惩罚**：RX 角频偏 8.7 %、LO 泄漏环检 −39.8 dBc、IRR 37.9 / 42.1 dB，而 modem 口径的最终 EVM 是 −26.0 dB（与 320 MHz 的 −26.1 持平），genie 口径的回环 EVM 只有 −12.9 dB。
  两个口径差 11 dB 的部分是接收机的信道估计与导频跟踪吸收掉的线性项；哪些项在真实链路（多径、每包重估）里仍然吸收得掉没有验证。
- **倍频器底噪在这张表上看不见**：示例 04 §5，底噪 −160 / −150 / −140 / −130 dBc/Hz 四档，IPN 都是 −33.0 dBc、底板与 MCS 上限一格不动；只有 K = 32 的相噪 ICI 项从 −36.1 到 −33.0 dB。在 OBO 8 dB 处 LO 不是瓶颈，底噪的取值（`assumed.lo_multiplier_floor_dbchz`，没有出处）目前不影响任何结论；PA 回退加大或换线性 PA 之后要重看。
- 剖面文件里的杂散表（4 MHz 小数杂散 ×10 后 −43.7 dBc、谐波抑制 40 dB）引擎不消费（铁律 6）；要看杂散得上逐周期引擎。

### C8. PA 记忆研究（示例 07）发现的（见 `cairn/LOG.md` 2026-11-11、`cairn/topology-b.md` §3b）
- **记忆按秒固定的代价是多退 0.5–2.3 dB，要按回退读**：`python examples/07_pa_memory_dpd.py`，参考 PA、抽头 12.5 ns。达到 DPD 后 TX EVM −25 / −27 dB，K = 8 上随信号缩放的要退 7.4 / 7.8 dB，按秒固定的要退 9.0 / 10.1 dB（代价 1.6 / 2.3 dB）；K = 32 上 7.4 / 8.3 对 7.9 / 8.9 dB（代价 0.5 / 0.6 dB）。
  预设的 8 dB 回退正好在 DPD 的崖上（随信号缩放的那颗 7.0 → 7.5 dB 之间从 −21.7 跳到 −26.1 dB），所以在这一个点上读 EVM 差会读到 6 dB，那是两条崖的间距，不是代价。
  待做：预设回退点本身离崖太近（多退 0.5 dB 与少退 0.5 dB，带记忆的参考 PA 上 DPD 后差 4 dB 以上），同台表的 PA 若换成带记忆的要重新定回退；混合间隔的基函数能不能把 K = 8 的 1.6–2.3 dB 收回来没有试（PA_DPD 的设计问题，要的话另开 issue）。
- **抽头间隔必须量着选**：K = 32 上逐样本的基函数到回退 12 dB 也只有 −25.5 dB，匹配间隔 8.9 dB 就到 −27 dB；K = 8 上回退 8.5 dB 以下逐样本好、9 dB 以上匹配间隔好（对方在自己的链路上没有这个交叉，匹配间隔处处好：交叉随链路而定）。`pamemory.candidate_spacings` 只量 1 / 2 / 4 / 匹配四个，没有扫全。
- **`fir_fs` 是整件事的未知数**：12.5 ns 是 sub-7 GHz WiFi PA 的时间常数原样搬过来。没有 60 GHz PA 记忆时间常数的出处，查到之前这张表只能读趋势。
- **预设的 Rapp 在回退 8 dB 上过 wifitrx 的 DPD 步几乎没有收益**：K = 4 / 8 上关 / 开是 −18.6 / −18.9、−18.9 / −18.9 dB（K = 32 −19.0 到 −22.4）。这颗 PA 的 P1dB 在 Psat 下 9.5 dB，回退 8 dB 时平均功率已在 P1dB 之上。
  同台表计了 DPD 的功耗、底板用的是未预失真的 Rapp，所以是“付了钱没拿到线性度”的记账，与 A1 第二条是同一件事。
- **示例 03 的校准表不在预设回退点上**：wifitrx 默认驱动在本库前端上落在回退 10.4–10.7 dB，不是预设的 8 dB。示例 07 已按预设回退重跑整套序列（`run_cal_at(obo_db=…)`）；示例 03 没改（改了全表都动），读它的 DPD / 最终 EVM 两行时要知道回退多了 2.5 dB。

### C9. 前端三个面（示例 08）发现的（见 `cairn/LOG.md` 2026-11-12 两条、`cairn/topology-b.md` §5）
- **还有三条文献数字没读到原文**：`python -c "from mmw60 import spec; print(len(spec.unverified()))"` 是 51（D4 前 48）。读过原文、已是 `spec` 的五条：`rx60.comm_asada2011`、`rx60.radar_iwr6843`、`rx60.radar_iwr6843_fig7_2`（读图）、`isolation.tx_rx_tue2018`（只读了摘要）、`dmg.rx_max_input_dbm`。没读到的三条：`survey.rx60_comm_iscas2015`、`survey.antenna60_okada2013_dbi`（都在 IEEE Xplore，对脚本访问返回空页，没有去绕）、`survey.dmg_sensitivity_assumptions`（802.11 条文）。都只作灵敏度档，基准档不用它们。原来的第四条（“Infineon AN600”的天线增益）已删：提供方读了原文后撤回，那份文件里没有这组数。
- **最大输入电平 −33 dBm 是 2012 年版的写法**：ITU-R M.2003 (03/2012) §2.4.6 是 −33 dBm；现行版 M.2003-2 (01/2018) 同一节改成接收天线处 10 µW/cm²。按 60.48 GHz 换算是 −37.1 dBm（0 dBi）/ −35.1 dBm（2 dBi）/ −31.1 dBm（6 dBi）。示例 08 §3 那一列还按 −33 dBm 画；要不要改成按天线增益换算的功率密度线，待定。
- **Asada 2011 的发射机比本库假设的小很多**：同一张表给发射 Psat 6.5 dBm、P1dB 5.4 dBm、变频增益 16 dB；本库的 60 GHz PA 是 Psat 15 dBm、增益 20 dB（`assumed.pa60_psat_dbm` / `assumed.pa60_gain_db`，没有出处）。本库回退 8 dB 后的 7 dBm 平均输出，已经高于这颗收发机的饱和功率。这一轮没有动 PA；要不要给 PA 也加一档“查到的”，待定。
- **拓扑 A 不消费接收前端这个面**：`python examples/08_frontend_faces.py` §5，拓扑 A（11be 80 MHz、MCS 0）的灵敏度预设 −92.5 dBm、换上查到的前端仍是 −92.5 dBm（差 0.00 dB）；拓扑 B 同一换法从 −87.0 变 −84.4 dBm（差 2.6 dB）。原因：`ifext.MmwRxStage` 是单位增益、自己不加噪声，SNR 轴上的 NF 是芯片的 WiFi 7 梯子。用预设时两拓扑都是 3.5 dB，同台表不受影响；一旦用查到的前端，两拓扑的接收噪声就不是同一个口径（铁律 2）。补法是在芯片前面加一级 60 GHz LNA / 混频器（增益、NF），级联 NF 由它定。
- **预设还在用 WiFi 7 的梯子**：换成查到的前端后，SNR 轴上的链路 EVM 不动（示例 08 §2，五档 NF 的散布 0.00 dB），动的是灵敏度（dB 对 dB）和校准表：K = 8 的回环 EVM −29.0 → −27.9 dB，NF 取 12 dB 时 −23.5 dB。也就是示例 03 的最终 EVM 是带着 3.5 dB 的接收机读的。要不要把预设换过去（示例 03 / 06 / 07 的数字会动），待定。
- **梯子的形状是假设**：原文只给高 / 低两档（变频增益 27 / 17 dB）和一个 NF 上界、一个 IIP3（没说哪一档），其余档位是 wifitrx 梯子整体平移（`assumed.rx60_ladder_shape`）。wifitrx 梯子的调节范围 42 dB，Asada 的接收机 10 dB、雷达芯片 18 dB。增益取 27 dB 后，灵敏度电平上基带 VGA 顶在 40 dB 的上限（ADC 输入比目标低约 7.5 dB），SNR 2 / 10 / 30 dB 上的链路 EVM 与 37 dB 时相同；增益再低到 17 dB，SNR 30 dB 上差 0.18 dB。查到的 IIP3（−20 dBm）与 wifitrx 顶档恰好相同，所以压缩这个面眼下和预设没有差别。
- **“校准读到的 RX NF”对换档电平很敏感**：回环电平正好落在第 1、2 档的换档点附近。换档电平按 wifitrx 的平衡点规则随 NF 移动 ΔNF / 3，所以 NF 6.1 dB 的那一行落在第 1 档、读 9.6 dB，比预设（第 2 档、10.8 dB）还低。读这一列时要连着档位读。
- **通信前端吃不吃得下雷达的泄漏，现有出处答不了**：压缩点是两个量。雷达的泄漏碰到的是基带高通之前的（带外），读过的通信文献只给带内的（IIP3）。`python examples/08_frontend_faces.py` §3：PA 输出 7 dBm、隔离 20 dB 时泄漏 −13 dBm；对通信前端的带内 P1dB（−29.6 dBm）余量 −16.6 dB，这是全双工的读法；带外那一列是“未指定”。雷达芯片两个量都有（带外 −12 dBm，带内 −24 … −42 dBm），隔离 20 dB 时带外余量 +1 dB。要补就得找一篇给带外压缩点或逐级线性度的 60 GHz 通信接收机文献。时分双工链路收发不同时，本库的链路仿真不注入泄漏。隔离度 20 / 25 dB 是摘要里两个数减出来的；对方读正文是 21–27 dB（仿真）/ 21–28 dB（天线级实测），本库没读到正文。
- **查到的前端不在数值指纹里**：`tools/fingerprint.py` 只跑 `configs/*.yaml`。加一份配置会改指纹文件，要用一次逃生口；现在由 `tests/test_frontend_faces.py` 守着。

## D. 报回上游
本库不动这三个库；需求各开一个 issue 交给对方，对方合并后本库重新 pin 并删掉对应条目。三个库的需求登记处各不相同（wifi_trx_cal 是 `docs/backlog_zh.md`、pll_simulator 的 roadmap 是生成的不手改、PA_DPD 是 `docs/03_roadmap.md`），所以统一走 issue，不替对方改文件。
D1（wifi_trx_cal#4，非标准带宽的评分波形）、D2（pll_simulator#71，倍频器模型）、D3（PA_DPD#4 的 `fs` / `fir_fs` 与 `tap_spacing`，经 wifi_trx_cal#5 透传）都已落地并 pin 完（2026-11-11，`cairn/LOG.md`），条目已删。现在没有等上游的事。
本库在验收时报告的两件对方已经修掉并 pin 进来（wifitrx@7b8d08e）：B40（DPD 步留观测通路上最好的一轮，都不如不加就不写入）与 B41（`ScaledPA` 对带记忆的 PA 逐电平读稳态）。对方自己还开着、与本库有关但不由本库推动的：B38（非标准音计划下 TX 视图 replay 的 gap）；`run_full_cal` 仍不透传 `n_iter`。

D4（fmcw_radar 的雷达消费清单，mmw60_trx#14）已落地并由对方关闭（2026-11-12，示例 08、`cairn/topology-b.md` §5）：接收前端、收发隔离、发 / 收天线增益三个面在 `Frontend60` 上，条目已删；过程中发现的在 C9。倍频器底噪不进 `Frontend60`（雷达直接读剖面文件）。对方最后读的是来源表而不是对象：它 vendor 了 `spec.py` 与 `survey.yaml`，按条目读三条 `spec`，哪几条、改之前要做什么见 `cairn/spec-sources.md` 的“被下游消费的条目”。

## E. 明确不做
MAC / MLO 调度、多用户、信道模型本身（用 11ad CR 现成表）、D-band、雷达（另开 fmcw_radar）；EIRP / 谱模板只做趋势比较，不替代认证测试；不把 vendor 变成 fork。

## 怎么用这份文件
改动落地后，把对应条目从这里删掉、在 `CHANGELOG.md` 里记一笔、在 `cairn/LOG.md` 顶部加一条带原始数字的记录。
分支：`main` 是默认分支；工作在 `feat/*` 分支上开 PR 合 `main`；旧分支 `ccr-65a5163d-bbo5rb` 与 `main` 同提交，不再往它推。
