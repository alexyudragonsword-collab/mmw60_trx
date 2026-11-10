# 变更记录 / Changelog

按里程碑记录。每条写**做了什么**和**为什么**；数字原值在 `cairn/LOG.md`。

## 未发布

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
