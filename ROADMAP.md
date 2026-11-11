# ROADMAP

**这份文件只写还没做的事。** 做完即删，并在 `CHANGELOG.md` 记一笔、`cairn/LOG.md` 记数字。每条带证据（复现方式与数字）。

## A. 里程碑 1 —— 两条拓扑同台（里程碑 0 验收后开；A / B 可两个会话并行）

### A1. 拓扑 A：IF 延伸
实 IF 级模型（镜像滤波带内纹波 / 群时延、LO ×N 相噪——pll 倍频器模型没到之前用 pll 剖面 + 20·log₁₀N 占位并标 assumed、两级 PA 级联）、MLO 预补偿的 CFO 残差（= sub-7 估计误差 × 频率比，铁律 3 的 A 测试）、60 GHz 观测回环有 / 无两种 DPD、wifitrx 全套校准真跑。
产出：MCS 上限随 LO 底噪（−85 … −110 dBc/Hz @ 1 MHz）和级联回退的表；校准步骤逐项结果表。
验收：LO 底噪每差 10 dB，MCS 上限变化方向与 `EvmBudget` 的 CPE / ICI 预算一致、差 < 1 dB；有观测回环比无回环好的 dB 数进 LOG。

### A2. 拓扑 B 的剩余项（主体已在里程碑 1-B 落地：`cairn/topology-b.md`）
- 示例 02 网格的 "IQcal" 列仍用 `assumed.irr_after_cal_db`（45 dB）；同台表（示例 04）已换成示例 03 实测的 `derived.irr_after_cal_measured_db`，一格结论都没动（`cairn/comparison-table.md` §6 ④），网格要不要跟着换只是口径统一的问题。
- 11ac 40 / 80 / 160 MHz 基准仍是 EVM-only（它们的 BCC 交织器未建；11be 全部带宽已有 LDPC 数据域，`phy/eht.py`）；要不要补只看有没有人要 11ac 宽带的 PER。
- 11be 数据域里没建的：HE/EHT 的预 FEC 填充 a 因子与 PE 字段（按 HT/VHT 流程，`assumed.eht_prefec_padding`）、EHT 11 位扰码器（PER 不感知）、MU-RU / 320 MHz 打孔 / DCM / 多流。
- 转换器 ENOB 随速率的法则（`assumed.converter_bits_per_octave`）换成 Murmann 调查表的实测包络（拿到表后标 survey）。
- DPD 的 2.56 GHz 代价现在是 dsp_ip P=4 综合面积 + Horowitz 运算能耗的记账；PA_DPD 的带宽项到了再换（D）。

### A3. 同台表的剩余项（主体已落地：示例 04、`tools/budget_report.py`、`cairn/comparison-table.md`）
- 拓扑 A 的行：`compare.PENDING[("if_extender", "be")]` 那格等 A1 落地后接入（同一个 `Frontend60` 实例；A 的 60 GHz 级在 wifitrx RF 之后插入）。
- WiFi 7 全链路四条整合里还没做的两条：PA_DPD 的 PA / DPD 进 wifitrx 链（K = 1 可行；K > 1 要先定 PA 的记忆是随信号缩放还是按秒固定，等 D3 的 `fir_fs` 与 `tap_spacing`）；Halo ADC 校准接入（要 vendor halo 的 `adc` 模块，现在转换器列是 ENOB 法则 + Walden 计价，没有通道失配项）。已做：pll 剖面替换解析相噪（`PhaseNoiseConfig.model: profile`）、`EvmBudget` 对账（差 ≤ 0.4 dB，相噪口径差 3–4 dB）。
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
- wifitrx 的 EVM 评分波形只在标准带宽（11ac 20–160、11be 20–320 MHz）上有导频表：640 MHz / 2.56 GHz 的 `final_loopback_evm` 无法运行（示例 03 标 skipped）。上游需求见 D。
- 60.48 GHz 上 40 ppm = 2.42 MHz，K = 4 的 L-STF 范围 ±2.5 MHz 刚好接住——Liu 的 K > 4.7 门槛是 73.44 GHz 的；通式 K > 2·Δf_max / 1.25 MHz。
- 回环定时：wifitrx `align_delay` 对复波形互相关，2.94 MHz CFO 下 1 µs 内去相关；本库用包络互相关定时（`sim/link.py::envelope_lag`）。

### C6. C1–C3 过程中发现的（见 `cairn/LOG.md` 2026-11-11）
- **门限表自己还没用上 C3 的逼近**：`tools/measure_thresholds.py` 仍是每点 ≤ 200 包 / 15 错、0.5 dB 步。同一格（11be 80 MHz MCS4 理想链）门限表读 11.40、示例 05 读 11.09；
  解码器上限的预测因此带约 ±0.3 dB（K = 4 的 MCS4 预测 12.97、实测 12.12）。待做：工具加 `--refine`（`per_sweep(refine_errors=…)` 已有，79 条曲线约多 3 倍时间），区间写进文件。
- **平滑跨度选择器在窄带上有散布**：flat 理想链 `zero_if_60ghz(k=8)`（11ac 20 MHz，56 音）120 包的 `RxResult.ce_span` 分布，SNR 3 dB 时 9 音 67 %、3 音 32 %，12 dB 时 56 % / 39 %；
  同样条件 11be 80 MHz（996 音）全部取 9 音。56 个音上“多于 3 音”那一步的偏差估计，自己的散布 W₃·√(2/N) 与要省的噪声同量级。待做：信道准静态时跨包平均自相关，或改 DFT 域去噪。

## D. 报回上游（2026-11-10 已转交，等对方落地）
本库不动这三个库；三条已各开一个 issue 交给对方（下面每条标题后的链接），对方合并后本库重新 pin 并删掉对应条目。三个库的需求登记处各不相同（wifi_trx_cal 是 `docs/backlog_zh.md`、pll_simulator 的 roadmap 是生成的不手改、PA_DPD 是 `docs/03_roadmap.md`），所以统一走 issue，不替对方改文件。

### D1 → wifi_trx_cal：非标准带宽的评分波形（导频集 / 音计划，或 `pilot_positions` 接受显式导频列）—— [wifi_trx_cal#4](https://github.com/alexyudragonsword-collab/wifi_trx_cal/issues/4)
- 现象：`waveform/pilots._tables` / `_pilot_half` 只认 78.125 kHz 与 312.5 kHz 两套 SCS 和 20/40/80/160/(320) MHz 的带宽键；`pilot_set="model"` 也先调 `standard_pilot_tones`。任何其他带宽（640 MHz、2.56 GHz）或 SCS × K 的 `OFDMConfig` 在 `generate_ofdm_with_pilots` 处 `ValueError`，于是 `scoring_frame` / `loopback_snapshot` / `run_full_cal` 没有评分波形。
- 复现（mmw60_trx@a968ef7）：`python examples/03_calibration_at_k.py`，K = 32（640 MHz）与 11be 80 MHz × 32（2.56 GHz）两列的 `final_loopback_evm` 为 skipped，其余 11 步照跑；`python -c "from mmw60.vendor.wifitrx.waveform.ofdm import OFDMConfig; from mmw60.vendor.wifitrx.waveform.pilots import generate_ofdm_with_pilots; from mmw60.vendor.wifitrx.waveform.tone_plan import contiguous; generate_ofdm_with_pilots(OFDMConfig(bandwidth_hz=160e6, subcarrier_spacing_hz=2.5e6, cp_fraction=1/4, tone_plan=contiguous(56), pilot_set='model'))"` 抛 "no pilot table for a 2500 kHz subcarrier spacing"。
- 数字：K = 32 时其余步骤已退化到 LO 泄漏环检 −35 dBc（K = 1 为 −68）、IQ irr_min 38–42 dB（55），正是最需要最终 EVM 裁决的地方。
- 要的最小改动：`pilot_positions(config, explicit_cols=None)` 或 `TonePlan` 携带导频列；本库 `calcheck.scoring_config` 与示例 03 的 skipped 两列在等它。

- 追加（2026-11-11，同一 issue 的评论）：`calibrate_dpd` 与 `dpd_tracking` 的 `GMPModel(...)` 写死了、没有抽头间隔参数；PA_DPD#4 给 MP / GMP 加 `tap_spacing` 之后要本库重新 vendor 并透传，排在 D3 之后。

### D2 → pll_simulator：倍频器（×N）模型 —— [pll_simulator#71](https://github.com/alexyudragonsword-collab/pll_simulator/issues/71)（对方已答复，2026-11-11 双方谈定接口，等剖面）
- 现象：`arch/` 里只有 ILCM、MDLL 与参考倍频器占空比误差，没有"PLL 剖面经 ×N 倍频后的输出相噪"块；拓扑 A 的固定 LO 是 sub-7 PLL ×3 / ×4 到 60 GHz。
- **本库的前提错了**：`profile_at_carrier` 把 6.253 GHz 的 wu19 剖面按 20·log₁₀(60.48 / 6.253) 搬移，等于 ×9.672，不是能实现的倍频器。量级（+19.7 dB）没错，同台表 §5 那三行的结论大概不动，但它不对应一条真实的 LO 链。
  正确做法是 PLL 调到 f_c/N 重新 analyze 再整数倍频。拓扑 B 已向对方要 f_c = 60.48 GHz、N = 10（PLL 6.048 GHz）；拓扑 A 的 (f_LO, N) 等 A1 定中频后在 issue 上补。
- 谈定的接口：`write_clock_profile(..., multiply_by=N, floor_dbchz=…, spur_rejection_db=…)`，N 非整数报错，底噪与抑制度必填、不给默认值（对方没有实测数据）；
  f_in/2 以内是 N²·S + 底噪，以上只有底噪（本库最宽的格积分到 5.12 GHz，N = 10 时 f_in/2 = 3.024 GHz，会用到这一段）；已请对方把 N、f_in、底噪、抑制度写成独立字段。
- 剖面到了以后本库要做的：重新 pin；`profile_at_carrier` 拒绝非整数的 f_c / f0；`floor_dbchz` 由本库给、标 `assumed`、在示例 04 §6 加灵敏度行（wu19 远端 −154 dBc/Hz，×10 后 −134，底噪高过它才看得见）；
  同台表 `pllsim wu19 profile x N` 三行换成新剖面；A1 的"MCS 上限随 LO 相噪 −85 … −110 dBc/Hz @ 1 MHz"表与它是两回事（那是 1 MHz 处的 LO 相噪电平，wu19 ×10 后是 −98.5），不要混用。

### D3 → PA_DPD：PA 电记忆定义在指定采样率上；两 DUT 级联 —— [PA_DPD#4](https://github.com/alexyudragonsword-collab/PA_DPD/issues/4)（对方已答复，2026-11-11 接口谈定，等落地）
- 现象：`ReferencePA` 的电记忆是固定抽头的 FIR（输入 3 抽头、输出 2 抽头，没有采样率参数）；没有两 DUT 级联的 `PAModel`（拓扑 A 的 WiFi 7 驱动 PA + 60 GHz PA）。本库的 DPD 代价至今用无记忆 Rapp + dsp_ip 综合数记账（示例 02 的 DPD pJ/bit 列、示例 03 的 dpd 行）。
- **本库原先的说法错了**：“在 fs_eff 上跨度缩成 0.78–0.1 ns，等于无记忆”。upclocking 下信号带宽也宽 K 倍、每符号样本数不变，逐样本抽头相对信号的记忆和 K = 1 一样，隐含的是“PA 的记忆时间随 K 缩短”。
  按对方的定义（两个 FIR 换成只留直流增益，比输出之差）在 vendored `ReferencePA` 上量：逐样本 4 倍过采样 −21.4 dB、2 倍过采样（本库默认）−16.1 dB；抽头固定 12.5 ns、信号 20 MHz × K（K = 4 / 8 / 32）−12.8 / −11.9 / −12.5 dB。
  有意义的是这两端：记忆随信号缩放（换了一颗宽带的 PA），与记忆按秒固定（同一颗 PA，记忆更重而不是更轻）。
- 谈定的接口：`ReferencePA(fs=…, fir_fs=…)`，都不给时逐位不变，`fir_fs` 由调用方给、不写死；MP / GMP 加 `tap_spacing`（对方实测 2.56 GS/s 上只改 PA 不改基函数 DPD 差约 10 dB：−42.5 对 −52.7 dB）；
  `CascadePA(first, second, interstage_backoff_db)`：第二级相对标称 drive 再降多少 dB，总小信号增益归一到约 1，`calibrate_dpd` 只需要 `__call__`。**级联回退的定义还要 A1 会话在 issue 上确认一次。**
- 落地后本库要做的：等 wifi_trx_cal 重新 vendor 并透传 `tap_spacing`（D1 追加项）再重新 pin；`fir_fs` 标 `assumed`，扫上面两端；`fs / fir_fs` 先只支持正整数，本库默认 2 倍过采样时相关的格换 4 倍过采样跑；在 `tap_spacing` 通到 `calibrate_dpd` 之前不把固定秒数的 PA 与现有 DPD 配在一起出数字。

### D4 ← fmcw_radar：雷达消费清单（收件）
- fmcw_radar 会报一份"它能从本库 `Frontend60` 用什么、缺什么"的清单：能用 PA（`ScaledRappPA`）、LO 泄漏（`Lo60.tx_leak_dbc`）、LO 剖面形状（`PoleZeroPhase`）；缺天线增益、LNA NF、TX–RX 隔离、倍频器底噪。
- 处理：这几个面补进 `Frontend60`（`antenna_gain_dbi` 已有，LNA NF 现在藏在 wifitrx `DEFAULT_LNA_STATES` 里要显式化，TX–RX 隔离与倍频器底噪新增），排在 A1 之后，不插队；补的时候保持铁律 2 的同一实例（两拓扑与雷达拿到的是同一个对象）。

## E. 明确不做
MAC / MLO 调度、多用户、信道模型本身（用 11ad CR 现成表）、D-band、雷达（另开 fmcw_radar）；EIRP / 谱模板只做趋势比较，不替代认证测试；不把 vendor 变成 fork。

## 怎么用这份文件
改动落地后，把对应条目从这里删掉、在 `CHANGELOG.md` 里记一笔、在 `cairn/LOG.md` 顶部加一条带原始数字的记录。
分支：`main` 是默认分支；工作在 `feat/*` 分支上开 PR 合 `main`；旧分支 `ccr-65a5163d-bbo5rb` 与 `main` 同提交，不再往它推。
