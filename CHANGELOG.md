# 变更记录 / Changelog

按里程碑记录。每条写**做了什么**和**为什么**；数字原值在 `cairn/LOG.md`。

## 未发布

### 重新 pin 两个上游：wifitrx@96078aa 的评分波形、pll_simulator@d67043e 的 ×10 剖面 —— ROADMAP D1 / D2（2026-11-11）
- `src/mmw60/vendor/wifitrx/` 重新同步到 `96078aa9438c590a24d13959472263ec5f9ab623`（0.7.37；106 个文件 verbatim，7 个文件的正文有变化），pin 在 `tools/vendor_check.py`、`tools/vendor_manifest.json`、`tests/test_vendor_check.py`、CI 四处一起改。里程碑 0 指纹逐位不变。
- `calcheck.upclocked_scoring_config`：没有标准导频表的带宽（640 MHz、2.56 GHz）用基准波形 × K 评分（基准的音与导频原样，音距 × K；靠 wifitrx 新的 `TonePlan(..., pilots=)`）。示例 03 原先 skipped 的两列跑出最终 EVM；
  `CalRun.final_views` 带出 wifitrx 最后一步的回环 / 仅发 / 仅收三个视图；采集长度成为显式参数（`n_symbols`，`assumed.cal_capture_symbols` = 8）并有 32 符号的灵敏度行。
- `impairments/phase_noise.py`：`load_clock_profile` 读出 `multiply_by` / `f_in_hz` / `floor_dbchz` / `spur_rejection_db`；`profile_at_carrier` 只接受整数的 f_c / f0（`profile_ratio`），带倍频器的文件只在自己的 f0 上用，非整数比与分频报错。**行为变化**：原先任意比值都按 20·log10 平移。
- 四个剖面文件入库（`data/clock_profiles/pllsim_wu19_x10_60p48g_floor{160,150,140,130}.yaml`，pll_simulator@d67043e 的 CLI 在本地生成）；规范条目 +4（`survey.clock_profile_wu19_x10`、`assumed.lo_multiplier_floor_dbchz`、`assumed.lo_multiplier_spur_rejection_db`、`assumed.cal_capture_symbols`），`assumed.lo_multiplier_law` 改写。
- **numbers-move**（示例 03、04）：示例 03 的 640 MHz / 2.56 GHz 两列整套换了激励，最终 EVM −19.3 / −26.0 dB，两列其余各步的数也动了（K = 1 / 4 / 8 / 16 四列不动）；示例 04 §5 的 pllsim 行从非整数的 ×9.672 换成 ×10 剖面（IPN −33.2 → −33.0 dBc，相噪 ICI 动 0.2–0.3 dB，MCS 上限不动），多三行底噪灵敏度；`derived.irr_after_cal_measured_db` 的 640 MHz / 2.56 GHz 两档改为 46.5 / 37.9 dB（同台表没有一格因此改变）。
- CI `vendor-drift`：checkout 姊妹库多认一个 secret `SIBLING_READ_KEY`（wifi_trx_cal 上只读 deploy key 的私钥，走 SSH，不过期、只读这一个仓库）；原有的 `SIBLING_READ_TOKEN` 仍可用。
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
