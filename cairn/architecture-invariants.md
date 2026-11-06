---
type: project_topic
status: active
summary: "七条铁律各自的论证、实现位置与守护测试；里程碑 0 已守住的和留给里程碑 1 的。"
tags: [mmw60, invariants, tests]
contains: [decision, scope]
created: "2026-11-06"
updated: "2026-11-06"
related: [engineering-pitfalls.md, upclocking.md, external-validation.md]
authoring_mode: ai_generated
---

# 铁律 ↔ 实现位置 ↔ 守护测试

| # | 铁律 | 实现 | 守护测试 | 状态 |
|---|---|---|---|---|
| 1 | 配置是唯一真值 | `config.py::Mmw60Config`（frozen，嵌套 frozen），`guispec.py` 的表单默认值从 dataclass 读；文献数字只经 `spec.py` 进 `liu2025_table2()` | `test_laws.py::test_law1_form_defaults_reproduce_config / _yaml_configs_round_trip / _both_topologies_are_named / _examples_build_their_links_from_the_presets_only` | 守住 |
| 2 | 两拓扑公平可比 | 里程碑 0 只有 B；K = 1、无毫米波级的行就是 wifitrx 链 | `test_law2_k1_chain_is_the_unmodified_wifitrx_chain`（EVM < −100 dB、星座逐点相等） | 锚；完整测试（同一前端 / LO / 信道 / EIRP 实例，ppm = 0 理想 LO/PA 下两拓扑 EVM 与 K = 1 差 < 0.1 dB）在里程碑 1 |
| 3 | CFO 端到端 | `impairments/cfo.py::CfoModel`（(ppm_tx+ppm_rx)·f_c，0 ppm 返回同一数组）；B 的接法 = `rx/cfo.py` 的 STF 粗 + LTF 细 | `test_law3_cfo_term_is_exactly_zero_at_zero_ppm / _is_crystal_error_times_carrier / _topology_b_declares_how_it_catches_the_cfo` | 守住（B）；A 的"预补偿 + 残差 = sub-7 估计误差 × 频率比"在里程碑 1 |
| 4 | 校准是跑出来的 | 用 vendored `cal/sequence.run_full_cal` 与 `cal/deps.py` | `test_law4_calibration_steps_are_importable_from_the_vendor_tree` | 锚；逐步结果表在里程碑 1（见 engineering-pitfalls：`run_full_cal` 在 K ≠ 1 直接失败的原因） |
| 5 | 数字只用原文 | `data/spec/survey.yaml` + `spec.py`（spec/survey/assumed/derived），`SpecNumber` 校验 | `test_spec_sources.py`（grep 计数 == 条目数、survey 必须写未核实、derived 按公式复算） | 守住 |
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
