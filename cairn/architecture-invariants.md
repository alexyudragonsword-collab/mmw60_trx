---
type: project_topic
status: active
summary: "七条铁律各自的论证、实现位置与守护测试；里程碑 0 已守住的和留给里程碑 1 的。"
tags: [mmw60, invariants, tests]
contains: [decision, scope]
created: "2026-11-06"
updated: "2026-11-12"
related: [engineering-pitfalls.md, upclocking.md, external-validation.md]
authoring_mode: ai_generated
---

# 铁律 ↔ 实现位置 ↔ 守护测试

| # | 铁律 | 实现 | 守护测试 | 状态 |
|---|---|---|---|---|
| 1 | 配置是唯一真值 | `config.py::Mmw60Config`（frozen，嵌套 frozen；`topology` 与 `waveform` 两个枚举都完整列出，未建的项在其里程碑前抛 NotImplementedError），`guispec.py` 的表单默认值从 dataclass 读；文献数字只经 `spec.py` 进预设 | `test_laws.py::test_law1_form_defaults_reproduce_config / _yaml_configs_round_trip / _both_topologies_are_named / _waveform_enum_is_complete_and_ay_refuses / _examples_build_their_links_from_the_presets_only` | 守住 |
| 2 | 每种方案（拓扑 × 波形）公平可比 | `compare.scheme_matrix` 点名全部拓扑 × 波形格子；一个 `Frontend60` 实例（前端 / LO / EIRP）交给每个 `LinkSim`；K = 1 无毫米波级的行就是 wifitrx 链；拓扑 A 的 60 GHz 级是 `ifext.IfExtenderTx / Rx`（wifitrx 链的子类，级加在父类调用之后 / 之前），PA 与 LO 剖面取共享实例里的同一对象；接收前端 / 收发隔离 / 两个天线增益（D4）也是这个实例上的面，链路的接收机用的是 `fe.rx_front.states` 这个对象本身 | `test_law2_k1_chain_is_the_unmodified_wifitrx_chain`（锚，EVM < −100 dB）；`test_compare.py::test_law2_matrix_names_every_topology_x_waveform_pair`、`test_law2_every_scheme_on_the_shared_frontend_reads_the_k1_evm_when_ideal`（理想实例共用，每种已建方案与 K = 1 差 < 0.1 dB；A / ay 以里程碑为由 skip）、`test_law2_report_hands_one_instance_to_every_row_and_the_k1_row_is_the_anchor`；`test_ifext.py::test_law2_stage_off_is_the_unmodified_wifitrx_chain_bit_for_bit`、`test_law2_topology_a_runs_on_the_shared_front_end_instance`；`test_frontend_faces.py::test_law2_presets_keep_the_wifitrx_ladder_and_say_it_is_not_a_60ghz_figure`、`test_law2_the_chain_runs_on_the_shared_front_ends_ladder` | 守住（已建方案）；A / ay 的行在各自里程碑接入同一测试。**缺口**：拓扑 A 不消费接收前端这个面（预设下两拓扑同是 WiFi 7 梯子，换上查到的前端就不同口径，ROADMAP C9） |
| 3 | CFO 端到端 | `impairments/cfo.py::CfoModel`（(ppm_tx+ppm_rx)·f_c，0 ppm 返回同一数组）；B 的接法 = `rx/cfo.py` 的 STF 粗 + LTF 细；A 的接法 = `MloCfo`：sub-7 链路的估计（真跑估计器）× f_c / f_sub7 预补偿，残差 = 估计误差 × 频率比，0 ppm 时整项关掉返回同一数组 | `test_law3_cfo_term_is_exactly_zero_at_zero_ppm / _is_crystal_error_times_carrier / _topology_b_declares_how_it_catches_the_cfo`；`test_ifext.py::test_law3_topology_a_cfo_is_zero_at_zero_ppm_and_the_residual_is_the_sub7_error_times_the_ratio`、`test_law3_topology_a_link_declares_how_it_catches_the_cfo` | 守住（A、B） |
| 4 | 校准在每种方案上真跑 | vendored `cal/sequence.run_full_cal` 与 `cal/deps.py`；B：`calcheck.run_cal_at`（示例 03 的步骤 × K 表；没有标准导频表的带宽用基准波形 × K 评分，`tests/test_calcheck.py::test_law4_final_evm_is_scored_at_640mhz_not_skipped`）；A：`ifext.calibrated_chip` 建链时就跑完整套序列，`calcheck.run_cal_on` 把同一序列在芯片耦合器与 60 GHz 观测回环上各跑一遍（示例 06 §2） | `test_law4_calibration_steps_are_importable_from_the_vendor_tree`；`test_ifext.py::test_law4_the_chip_is_calibrated_by_running_wifitrx_sequence`、`test_dpd_through_the_60ghz_observation_helps_at_deep_back_off_and_is_not_programmed_when_it_diverges` | 守住（A 在链路里真跑；B 的同台表校准列仍是示例 03 实测 IRR 的查表） |
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
