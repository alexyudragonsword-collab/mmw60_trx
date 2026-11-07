# ROADMAP

**这份文件只写还没做的事。** 做完即删，并在 `CHANGELOG.md` 记一笔、`cairn/LOG.md` 记数字。每条带证据（复现方式与数字）。

## A. 里程碑 1 —— 两条拓扑同台（里程碑 0 验收后开；A / B 可两个会话并行）

### A1. 拓扑 A：IF 延伸
实 IF 级模型（镜像滤波带内纹波 / 群时延、LO ×N 相噪——pll 倍频器模型没到之前用 pll 剖面 + 20·log₁₀N 占位并标 assumed、两级 PA 级联）、MLO 预补偿的 CFO 残差（= sub-7 估计误差 × 频率比，铁律 3 的 A 测试）、60 GHz 观测回环有 / 无两种 DPD、wifitrx 全套校准真跑。
产出：MCS 上限随 LO 底噪（−85 … −110 dBc/Hz @ 1 MHz）和级联回退的表；校准步骤逐项结果表。
验收：LO 底噪每差 10 dB，MCS 上限变化方向与 `EvmBudget` 的 CPE / ICI 预算一致、差 < 1 dB；有观测回环比无回环好的 dB 数进 LOG。

### A2. 拓扑 B 的剩余项（主体已在里程碑 1-B 落地：`cairn/topology-b.md`）
- 校准后的 IQ 残余（示例 03 实测的 irr_min_db）回填网格的 "IQcal" 列，替代 `assumed.irr_after_cal_db`（45 dB）。
- 11be 基准的编码 PER（现在只有 11ac 20 MHz 有编码数据域，其余基准 EVM-only）：需要 EHT 的 LDPC / 交织表，排在 ay 波形之前。
- 转换器 ENOB 随速率的法则（`assumed.converter_bits_per_octave`）换成 Murmann 调查表的实测包络（拿到表后标 survey）。
- DPD 的 2.56 GHz 代价现在是 dsp_ip P=4 综合面积 + Horowitz 运算能耗的记账；PA_DPD 的带宽项到了再换（D）。

### A3. 同台表与预算报表
含 K = 1 基线行；60 GHz 前端、LO 链、信道、EIRP 限值是同一个对象实例（铁律 2 完整测试：ppm = 0、理想 LO、理想 PA 下两拓扑 EVM 与 K = 1 差 < 0.1 dB）；`tools/budget_report.py` 照 d2d_link；pJ/bit 口径照 Halo 示例 41；每格统计 / 时域（或解析 / 仿真）交叉核对，推导数进 `examples/derived.yaml`；测试累计 ≥ 60。
WiFi 7 全链路的四条整合也在这里做：pll 剖面替换解析相噪、PA_DPD 的 PA / DPD 进 wifitrx 链、`EvmBudget` 对账、Halo ADC 校准接入。
表单字段：`guispec.py` 已有 18 个 Knob，桌面 GUI / Android 这一轮不做。

## B. 里程碑 2 及以后
- 阵列层：vendor array_tx（按当时 main 完整 SHA），波束训练序列的 SNR 预算。
- 802.11ay 原生数字学当第三种波形，排最后。

## C. 里程碑 0 过程中发现的问题

### C1. 接收机：逐符号导频 CPE 的尾部代价 ≈ 2.5 dB（MCS0）
复现：`tests/test_link.py::test_full_receiver_costs_a_known_amount_over_the_decoder`；K = 8 flat MCS0，genie CSI 下 PER 1e-2 在 1.5–2 dB（压在并集界上），只加 4 导频逐符号 CPE 就到 4.4 dB。机理见 `cairn/engineering-pitfalls.md`。待做：跨符号平滑 / 跟踪环的 CPE（相噪在 K ≥ 8 的符号时长内相关性强，平滑不会丢跟踪），作为 `RxConfig` 的一档，并看它把示例 00 的 MCS0 曲线左移多少。

### C2. 信道估计平滑跨度应随相干带宽 / 音距缩放
复现：K = 16、15 ns rms Rayleigh、`ce_smooth_tones=3` → EVM −7 dB，`=1` → −14 dB（`tests/test_link.py::test_k16_symbol_*` 用 1 音）。待做：平滑跨度按 `coherence_bandwidth_hz / scs_eff` 自动选，或改成 DFT 域去噪。

### C3. PER = 1e-2 处 SNR 的统计散布约 ±0.5 dB
复现：示例 00 的 K = 8 MCS4 flat 配置，300 包 / 20 错的灵敏度行读 19.67 dB，600 包 / 30 错的正式曲线读 20.42 dB（同一代码、不同 RNG 消耗）。
1e-2 处每点只有 ~6–30 个错包，再经对数线性插值。待做：按固定错包数（≥ 100）收敛、给出 bootstrap 置信区间，并在 external_check 的差值旁打印它；验收门限 1 dB 与这个散布同量级，现在的"OUTSIDE/within"判决对 1.0–1.3 dB 的差没有分辨力。

### C4. 需要外部输入才能关掉的（见 `cairn/spec-sources.md` 末节）
Liu 2025 的 Rapp 参数与 OBO 定义；11ad CR 信道 tap 表；11-09/0296r16 原文。

### C5. 里程碑 1-B 发现的（见 `cairn/LOG.md` 2026-11-07）
- wifitrx 的 EVM 评分波形只在标准带宽（11ac 20–160、11be 20–320 MHz）上有导频表：640 MHz / 2.56 GHz 的 `final_loopback_evm` 无法运行（示例 03 标 skipped）。上游需求见 D。
- 60.48 GHz 上 40 ppm = 2.42 MHz，K = 4 的 L-STF 范围 ±2.5 MHz 刚好接住——Liu 的 K > 4.7 门槛是 73.44 GHz 的；通式 K > 2·Δf_max / 1.25 MHz。
- 回环定时：wifitrx `align_delay` 对复波形互相关，2.94 MHz CFO 下 1 µs 内去相关；本库用包络互相关定时（`sim/link.py::envelope_lag`）。

## D. 报回上游的需求（合并后重新 pin）
- wifi_trx_cal：非标准带宽（> 320 MHz，或任意 SCS × K）的导频集 / 音计划，或让 `pilot_positions` 接受显式导频列——否则 `scoring_frame` / `run_full_cal` 在 2.56 GHz 上没有评分波形。
- pll_simulator：倍频器（×N）模型，含 20·log₁₀N 之外的底噪项——拓扑 A 的 LO 链要用。
- PA_DPD：PA 带宽 / 记忆项随采样率的模型；两 DUT 级联（拓扑 A 的驱动 PA + 60 GHz PA）。

## E. 明确不做
MAC / MLO 调度、多用户、信道模型本身（用 11ad CR 现成表）、D-band、雷达（另开 fmcw_radar）；EIRP / 谱模板只做趋势比较，不替代认证测试；不把 vendor 变成 fork。

## 怎么用这份文件
改动落地后，把对应条目从这里删掉、在 `CHANGELOG.md` 里记一笔、在 `cairn/LOG.md` 顶部加一条带原始数字的记录。
