---
type: project_topic
status: active
summary: "七条铁律各自的论证、实现位置与守护测试；里程碑 0 已守住的和留给里程碑 1 的。"
tags: [mmw60, invariants, tests]
contains: [decision, scope]
created: "2026-11-06"
updated: "2026-11-15"
related: [engineering-pitfalls.md, upclocking.md, external-validation.md]
authoring_mode: ai_generated
---

# 铁律 ↔ 实现位置 ↔ 守护测试

| # | 铁律 | 实现 | 守护测试 | 状态 |
|---|---|---|---|---|
| 1 | 配置是唯一真值 | `config.py::Mmw60Config`（frozen，嵌套 frozen；`topology` 与 `waveform` 两个枚举都完整列出；2026-11-16 起四种波形都已建，ay 两种只在拓扑 B、EDMG 信道中心、K = 1 上，其余组合配置直接拒绝），`guispec.py` 的表单默认值从 dataclass 读；文献数字只经 `spec.py` 进预设 | `test_laws.py::test_law1_form_defaults_reproduce_config / _yaml_configs_round_trip / _both_topologies_are_named / _waveform_enum_is_complete_and_ay_runs_on_topology_b_only / _examples_build_their_links_from_the_presets_only`；`test_ifext.py::test_law1_a_upclocked_names_its_waveform_and_stays_on_the_chips_channels`（拓扑 A 的升频只在芯片信道上，2026-11-15） | 守住 |
| 2 | 每种方案（拓扑 × 波形）公平可比 | `compare.scheme_matrix` 点名全部拓扑 × 波形格子；一个 `Frontend60` 实例（前端 / LO / EIRP）交给每个 `LinkSim`；K = 1 无毫米波级的行就是 wifitrx 链；拓扑 A 的 60 GHz 级是 `ifext.IfExtenderTx / Rx`（wifitrx 链的子类，级加在父类调用之后 / 之前），PA 与 LO 剖面取共享实例里的同一对象（pllsim 剖面例外：同一个频综设计放到拓扑 A 的 LO 频率 f_c − f_IF 上，`Lo60.at`，2026-11-14）；接收前端 / 收发隔离 / 两个天线增益（D4）也是这个实例上的面，链路的接收机用的是 `fe.rx_front.states` 这个对象本身；2026-11-18 起（C9）预设的接收前端是 60 GHz 的，拓扑 A 在芯片前串它的最高增益档，芯片取共享前端自己的链时（理想行）不再串（否则同一个前端算两遍：理想行 −39.4 dB 对 K = 1 链 −43.0 dB，就是被下面的理想实例测试抓到的）；同台表的 K = 1 行跑在这个实例上，自己的 WiFi 7 梯子只在单独仿真时用，与它自己的 LO 剖面同一个待遇 | `test_law2_k1_chain_is_the_unmodified_wifitrx_chain`（锚，EVM < −100 dB）；`test_compare.py::test_law2_matrix_names_every_topology_x_waveform_pair`、`test_law2_every_scheme_on_the_shared_frontend_reads_the_k1_evm_when_ideal`（理想实例共用，每种已建方案与 K = 1 差 < 0.1 dB；ay 是另一套数字学，锚是它自己的：同一个理想实例上 < −35 dB；只 skip 三个 n/a 格。更正 2026-11-16：原写“A / ay 以里程碑为由 skip”）；`test_ay_link.py::test_law2_both_ay_waveforms_run_on_the_shared_front_end_and_one_chain`（ay 两种波形同一个前端实例、同一条 5.28 GS/s 的链、同一组滤波器、同一个 PA 工作点，2026-11-16）、`test_law2_report_hands_one_instance_to_every_row_and_the_k1_row_is_the_anchor`；`test_ay_link.py::test_the_two_ay_rows_of_the_comparison_table`（同台表的 ay 两行：同一个实例、合规上限与 be 行同一条余量规则 `assumed.mcs_evm_margin_db`，2026-11-16）、`test_the_ay_array_budget_runs_on_the_shared_instance_with_the_be_rule`（阵列上的 ay：同一个阵列与前端，EIRP 上限处一起回退，be 行的解码器上限规则，2026-11-16）；`test_ifext.py::test_law2_stage_off_is_the_unmodified_wifitrx_chain_bit_for_bit`、`test_law2_topology_a_runs_on_the_shared_front_end_instance`、`test_the_fixed_lo_noise_sits_at_the_lo_frequency_not_the_carrier`；`test_frontend_faces.py::test_law2_presets_carry_the_60ghz_receive_front_end_and_nothing_else_of_the_three_faces`（2026-11-18，C9：60 GHz 预设——B、A、A × be_upclocked、ay 两种波形——带同一个接收前端，天线与隔离不进预设；之前是 `test_law2_presets_keep_the_wifitrx_ladder_and_say_it_is_not_a_60ghz_figure`）、`test_law2_the_wifi7_ladder_is_still_wifitrx_own_on_the_k1_row_and_as_a_sensitivity_row`（6 GHz 的 K = 1 行与 `wifi7_rx_ladder` 用的是 wifitrx 的梯子对象本身）、`test_law2_the_chain_runs_on_the_shared_front_ends_ladder` | 守住（已建方案；A 与 ay 的行都已接入同一测试）。同台表上 ay 行与 be 行的校准读法不对称（be：IRR 查表加解析和；ay：校准链上的时域），已在表里与 `comparison-table.md` §2c 标出，ROADMAP A3。阵列的每个单元都是这个实例（`frontend/array60.py`，两条拓扑同一个 `Array60`，一个单元即原单元件链路，`tests/test_array60.py`，2026-11-14）；拓扑 A 消费接收前端：共享前端是 60 GHz 前端时，它的最高增益档串在芯片前（`test_ifext.py::test_law2_topology_a_consumes_the_shared_receive_front_end`，2026-11-14；此前是缺口，ROADMAP C9）；A × be_upclocked 的芯片、校准与 60 GHz 级就是原生信道那一行的（`test_ifext.py::test_law2_law4_a_upclocked_is_the_native_channels_chip_and_its_calibration`，芯片输出逐位相同，2026-11-15） |
| 3 | CFO 端到端 | `impairments/cfo.py::CfoModel`（(ppm_tx+ppm_rx)·f_c，0 ppm 返回同一数组）；B 的接法 = `rx/cfo.py` 的 STF 粗 + LTF 细；A 的接法 = `MloCfo`：sub-7 链路的估计（真跑估计器）× f_c / f_sub7 预补偿，残差 = 估计误差 × 频率比，0 ppm 时整项关掉返回同一数组；ay 的接法 = `sim/ay_link.py` 自己的 STF（128 点 Golay × 16，lag 128 自相关，范围 ±fs/256）+ OFDM 导频 / SC 两段 GI 之间插值的相位跟踪（2026-11-16；原写的“靠 5.16 MHz SCS 本身”不成立：2.42 MHz 是 0.47 个子载波，不估计时两种波形都 PER = 1 量级的 EVM） | `test_law3_cfo_term_is_exactly_zero_at_zero_ppm / _is_crystal_error_times_carrier / _topology_b_declares_how_it_catches_the_cfo`；`test_ifext.py::test_law3_topology_a_cfo_is_zero_at_zero_ppm_and_the_residual_is_the_sub7_error_times_the_ratio`、`test_law3_topology_a_link_declares_how_it_catches_the_cfo`、`test_law3_a_upclocked_catches_the_cfo_with_the_chips_own_l_stf`（A × be_upclocked：K ≥ 4 时芯片 L-STF 不靠 MLO 也接住，K = 2 不行，0 ppm 时开关 MLO 逐位相同；K = 4 只余 81 kHz，低 SNR 按包丢，示例 11 §2b 量的丢包率不进测试）；`test_ay_link.py::test_law3_the_ay_links_catch_the_cfo_with_their_own_stf`（0 ppm 时估计为零；40 ppm 时 STF 接住、误差 < 5 kHz；关掉估计两种波形都坏） | 守住（A、B） |
| 4 | 校准在每种方案上真跑 | vendored `cal/sequence.run_full_cal` 与 `cal/deps.py`；B：`calcheck.run_cal_at`（示例 03 的步骤 × K 表；没有标准导频表的带宽用基准波形 × K 评分，`tests/test_calcheck.py::test_law4_final_evm_is_scored_at_640mhz_not_skipped`）；A：`ifext.calibrated_chip` 建链时就跑完整套序列（A × be_upclocked 用原生信道的同一份校准），`calcheck.run_cal_on` 把同一序列在芯片耦合器与 60 GHz 观测回环上各跑一遍（示例 06 §2） | `test_law4_calibration_steps_are_importable_from_the_vendor_tree`；`test_ifext.py::test_law4_the_chip_is_calibrated_by_running_wifitrx_sequence`、`test_dpd_through_the_60ghz_observation_helps_at_deep_back_off_and_is_not_programmed_when_it_diverges` | 守住（A 在链路里真跑；B 的同台表校准列仍是示例 03 实测 IRR 的查表）；ay（2026-11-16）：`calcheck.run_cal_ay` 在 ay 的链上用 `assumed.ay_cal_probe` 的探针真跑序列，`LinkSim(..., chains=)` 在校准过的链上跑 ay 波形，`test_ay_link.py::test_law4_the_ay_chain_is_calibrated_by_running_wifitrx_sequence` |
| 5 | 数字只用原文 | 外部的数在 vendored spec_sources（`vendor/spec_sources/data/*.yaml`，2026-11-13 起），本库的取舍与产出在 `data/spec/survey.yaml`；`spec.py` 是垫片，合并两张表、同键报错（spec/survey/assumed/derived），`SpecNumber` 校验 | `test_spec_sources.py`（每张表四个标签的 grep 计数 == 条目数、本地表只剩该剩的、survey 必须写未核实、derived 按公式复算）、`test_vendor_check.py`（共享表逐字对 pin） | 守住 |
| 6 | 杂散结论只来自逐周期引擎 | `mmw60.ENGINE_BANNER`，每个示例 `main()` 第一句 | `test_law6_every_example_prints_the_engine_banner_first / _is_the_first_line_at_run_time` | 守住 |
| 7 | 数值指纹 | `tools/fingerprint.py`（configs + 原语）、`fingerprint_walk.py`、CI `fingerprint` 作业 | `test_fingerprint.py` | 守住 |

## 为什么 K 走"时钟重解释"而不是改 SCS

见 upclocking.md §1。补一句架构上的理由：这样 wifitrx 的每一个函数都在它被验证过的数字学上运行，本库加的只是"物理量按 fs_eff 施加"这一层；铁律 2 的 K = 1 锚因此是逐位的，而不是"近似相同"。

## 分层

```
mmw60.config  ──►  mmw60.sim.link.LinkSim  ──►  (tx) vendor.wifitrx.waveform  +  mmw60.phy（编码）
                          │                      (air) mmw60.pa.rapp / impairments / channel   @ fs_eff
                          └──────────────────►  (rx) mmw60.rx.receiver = wifitrx 自由函数 + mmw60.rx.cfo + mmw60.phy 解码
```

`vendor/` 只被 import，不被改（`tools/vendor_check.py --strict`）。
