# ROADMAP

**这份文件只写还没做的事。** 做完即删，并在 `CHANGELOG.md` 记一笔、`cairn/LOG.md` 记数字。每条带证据（复现方式与数字）。

## A. 里程碑 1 —— 两条拓扑同台（主体都已落地；下面是剩余项）

### A1. 拓扑 A 的剩余项（主体已落地：`src/mmw60/ifext.py`、示例 06、`cairn/topology-a.md`）
- **芯片的 PA 当驱动级太贵**：芯片 PA 在 13.3 dBm 耗 294 mW（10.1 dBm 时 202 mW），而它的输出要先衰减 24 dB 才到 60 GHz PA 的驱动电平；同样 320 MHz、865 Mb/s，拓扑 A 1127 对拓扑 B 628 pJ/bit，其中芯片 PA 占 339。
  复现：`python examples/06_topology_a_if_extender.py` §5、`examples/04_comparison_table.py` §4。待做：芯片 PA 旁路（IF 从 PA 前取）的一档，wifitrx 的 `TxParams.pa_enabled = False` 加上它的 DPD / tx_power 两步怎么处理。
- **间接学习在软压缩 PA 上越迭代越差，靠近饱和时 1 次迭代也不够**：60 GHz 观测回环的 DPD 在回退 6 dB 上比不过芯片上的（−14.6 对 −16.9 dB），8 dB 上只值 +1.3 dB（示例 06 §3）；
  整套序列搬到 60 GHz 观测上更糟，IQ 校准的 IRR 从 55.7 掉到 37.8 dB（§2）。本库已改成 1 … N 次迭代里留最好的（`train_dpd_mmw`）。
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
- DPD 的 2.56 GHz 代价现在是 dsp_ip P=4 综合面积 + Horowitz 运算能耗的记账；PA_DPD 的带宽项到了再换（D）。

### A3. 同台表的剩余项（主体已落地：示例 04、`tools/budget_report.py`、`cairn/comparison-table.md`）
- WiFi 7 全链路四条整合里还没做的两条：PA_DPD 的 PA / DPD 进 wifitrx 链（K = 1 可行；K > 1 要先定 PA 的记忆是随信号缩放还是按秒固定，等 D3 的 `fir_fs` 与 `tap_spacing`）；Halo ADC 校准接入（要 vendor halo 的 `adc` 模块，现在转换器列是 ENOB 法则 + Walden 计价，没有通道失配项）。已做：pll 剖面替换解析相噪（`PhaseNoiseConfig.model: profile`）、`EvmBudget` 对账（A1 更正单边带换算后每行差 0.0 dB，相噪项差 0.1–1.3 dB）。
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
- **校准采集 8 个符号在窄基准 × 大 K 上不够**：`python examples/03_calibration_at_k.py` 的 K = 32、11ac 20 MHz 基准（640 MHz，52 音，1280 样本）一列，DPD 之后仅发 EVM −19.3 dB，不开 DPD −22.8 dB，采 32 个符号 −27.8 dB（同一示例的灵敏度节）；
  同样 640 MHz 用 11be 20 MHz 基准（242 音，4352 样本）−27.2 dB。默认值没改（`assumed.cal_capture_symbols` = 8，每列同一个符号数）。待做：采集长度按样本数而不是符号数给（或按 GMP 系数个数的倍数），K = 1 为什么够、K = 32 为什么不够要单独验证（候选是观测 ADC 的 ENOB 随 fs 下降）。
- **2.56 GHz 列的退化项没有被最终 EVM 惩罚**：RX 角频偏 8.7 %、LO 泄漏环检 −39.8 dBc、IRR 37.9 / 42.1 dB，而 modem 口径的最终 EVM 是 −26.0 dB（与 320 MHz 的 −26.1 持平），genie 口径的回环 EVM 只有 −12.9 dB。
  两个口径差 11 dB 的部分是接收机的信道估计与导频跟踪吸收掉的线性项；哪些项在真实链路（多径、每包重估）里仍然吸收得掉没有验证。
- **倍频器底噪在这张表上看不见**：示例 04 §5，底噪 −160 / −150 / −140 / −130 dBc/Hz 四档，IPN 都是 −33.0 dBc、底板与 MCS 上限一格不动；只有 K = 32 的相噪 ICI 项从 −36.1 到 −33.0 dB。在 OBO 8 dB 处 LO 不是瓶颈，底噪的取值（`assumed.lo_multiplier_floor_dbchz`，没有出处）目前不影响任何结论；PA 回退加大或换线性 PA 之后要重看。
- 剖面文件里的杂散表（4 MHz 小数杂散 ×10 后 −43.7 dBc、谐波抑制 40 dB）引擎不消费（铁律 6）；要看杂散得上逐周期引擎。

## D. 报回上游
本库不动这三个库；需求各开一个 issue 交给对方，对方合并后本库重新 pin 并删掉对应条目。三个库的需求登记处各不相同（wifi_trx_cal 是 `docs/backlog_zh.md`、pll_simulator 的 roadmap 是生成的不手改、PA_DPD 是 `docs/03_roadmap.md`），所以统一走 issue，不替对方改文件。
D1（wifi_trx_cal#4，非标准带宽的评分波形）与 D2（pll_simulator#71，倍频器模型）已落地并 pin 完（2026-11-11，`cairn/LOG.md`），条目已删；剩 D3 这一条链。

### D3 → PA_DPD：PA 电记忆定义在指定采样率上；两 DUT 级联 —— [PA_DPD#4](https://github.com/alexyudragonsword-collab/PA_DPD/issues/4)（**对方已落地并合进 main `02ca433`；issue 留着由本库验收后关**）
- 对方交付：`ReferencePA(fs=, fir_fs=)`（只接受正整数的 fs / fir_fs，否则报错；都不给时逐位不变）、`MemoryPolynomialModel` / `GMPModel(tap_spacing=)`（默认 1 不写进 `get_config`）、
  `CascadePA(first, second, interstage_backoff_db=)`（`stage_input_rms` / `stage_backoff_db` 可读；虚拟 DUT 的 `get_config` / `save` 报错）。级联的总小信号增益不是约 1（两个 `ReferencePA` 是 1.416），由外面的 `ScaledPA` 吸收。
- 本库验收（本地检出 `02ca433` 实跑，对着本库 vendored 的旧副本）：默认 `ReferencePA` 与默认 GMP 拟合逐位相同；20 MHz × K、`fir_fs` = 80 MHz 的记忆贡献 −12.80 / −11.87 / −12.47 dB（K = 4 / 8 / 32，与本库之前用补零量的逐位相同的三个数）；
  fs / fir_fs = 0.5 与 2.667 都报错；按 12.5 ns 记忆的 PA 上 GMP 拟合 `tap_spacing` 1 / 4 为 −29.2 / −41.0 dB；`CascadePA` 上未改动的 ILA −15.3 → −65.6 dB。**全部通过。**
- 链条还差两步，都不在 PA_DPD：① wifi_trx_cal 重新 vendor PA_DPD@02ca433 并给 `calibrate_dpd` / `dpd_tracking` 透传 `tap_spacing`——已单开 [wifi_trx_cal#5](https://github.com/alexyudragonsword-collab/wifi_trx_cal/issues/5)（2026-11-11，从 #4 拆出；同一条里报告了 `n_iter` 默认 2 在软压缩 PA 上发散）；② 本库重新 pin wifi_trx_cal。
- 本库用不上 `CascadePA`：拓扑 A 的级联是 `IfExtenderTx`（芯片链 + 间级电平 + IF 滤波 + 混频 + Rapp），两级之间有带记忆的线性级和 LO 相噪，`CascadePA` 表达不了，也不需要它表达。
- 落地后本库要做的：`fir_fs` 标 `assumed`，扫“记忆随信号缩放 / 按秒固定”两端；`fs / fir_fs` 要正整数，相关的格用 4 倍过采样；在 `tap_spacing` 通到 `calibrate_dpd` 之前不把固定秒数的 PA 与现有 DPD 配在一起出数字；做完删本条。

### D4 ← fmcw_radar：雷达消费清单（收件）
- fmcw_radar 会报一份"它能从本库 `Frontend60` 用什么、缺什么"的清单：能用 PA（`ScaledRappPA`）、LO 泄漏（`Lo60.tx_leak_dbc`）、LO 剖面形状（`PoleZeroPhase`）；缺天线增益、LNA NF、TX–RX 隔离、倍频器底噪。
- 处理：这几个面补进 `Frontend60`（`antenna_gain_dbi` 已有，LNA NF 现在藏在 wifitrx `DEFAULT_LNA_STATES` 里要显式化，TX–RX 隔离与倍频器底噪新增），排在 A1 之后，不插队；补的时候保持铁律 2 的同一实例（两拓扑与雷达拿到的是同一个对象）。

## E. 明确不做
MAC / MLO 调度、多用户、信道模型本身（用 11ad CR 现成表）、D-band、雷达（另开 fmcw_radar）；EIRP / 谱模板只做趋势比较，不替代认证测试；不把 vendor 变成 fork。

## 怎么用这份文件
改动落地后，把对应条目从这里删掉、在 `CHANGELOG.md` 里记一笔、在 `cairn/LOG.md` 顶部加一条带原始数字的记录。
分支：`main` 是默认分支；工作在 `feat/*` 分支上开 PR 合 `main`；旧分支 `ccr-65a5163d-bbo5rb` 与 `main` 同提交，不再往它推。
