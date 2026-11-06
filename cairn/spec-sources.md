---
type: project_topic
status: active
summary: "规范 / 文献数字的来源制度：四种标签、Liu 2025 两个 arXiv 版本的差异、11ad EM 参数的出处与未核实之处、本库自己定的假设清单。"
tags: [mmw60, spec, provenance, liu2025]
contains: [reference, decision, open_question]
created: "2026-11-06"
updated: "2026-11-06"
related: [external-validation.md, upclocking.md]
authoring_mode: ai_generated
---

# 数字从哪里来

## 制度（铁律 5）

`src/mmw60/data/spec/survey.yaml` 一条一个数，`source` 四选一：`spec`（原文，必须带 quote + section）、`survey`（文献 / 搜索命中，一律"未核实"）、`assumed`（原文没说，本库定）、`derived`（公式推出）。
代码只经 `mmw60.spec.value(key)` 取，`liu2025_table2()` 预设就是这样建的。`grep -c "source: survey"` 等于未核实条目数（`tests/test_spec_sources.py`）。

## Liu 2025 的版本

| 版本 | 日期 | 有什么 |
|---|---|---|
| arXiv 2309.16813 **v1** | 2023-09-28 | Table I / II、**Fig. 4 PER 曲线**（只有"有损伤"一组）、§V-A 设定 |
| arXiv **v2** | 2024-07-08 | 同样的正文，加了"without considering these non-idealities"的描述，但**图被删了**，正文 "Fig." 引用悬空 |
| IEEE Commun. Mag. 2025-03 | — | 刊出版，**未取得** |

本库的读图值（`liu2025_fig4.yaml`）来自 v1 第 5 页 300 dpi 渲染，精度约 ±0.3 dB。v2 正文说的"无损伤"曲线在任何可得版本里都没有，所以示例 00 的 ideal 组没有外部参照。

## 原文给了的（survey）

MCS 0/1/4、VHT、11ad CR 信道、1T1R、73.44 GHz（11ay channel 8）、4096 B、20 + 20 ppm → ±2.94 MHz、相噪 1 极 1 零（1 MHz / 100 MHz / −93 dBc/Hz）、modified Rapp OBO 8 dB、STF/LTF 捕获 ±625 / ±156.25 kHz、门槛 5.88 MHz 与 4.7、PER 目标 1e-2、"refrained from using estimation and compensation algorithms for CFO and PN"。

## 原文没给、从别处拿的（survey，未核实）

- Rapp 参数：IEEE 802.11-09/0296r16（TGad EM）CMOS PA，g = 4.65、Asat = 0.58、p = 0.81、α = 2560、β = 0.114、q1 = 2.4、q2 = 2.3——来自搜索命中的文档摘录，.doc 原文未读（r09 版是 5 / 0.6 / 0.71）。公式形状按记忆。
- 相噪 PSD 形状 PSD0·(1+(f/f_z)²)/(1+(f/f_p)²)：TGad EM 的写法（它的 PSD0 是 −90，Liu 用 −93）。
- VHT MCS 表（N_SD = 52、N_DBPS 26/52/156）、交织 N_COL = 13、BCC 133/171、扰码 x⁷+x⁴+1：802.11 的通用知识，原文未贴入。
- FCC 15.255 的 40 / 43 dBm：里程碑 1 用。

## 本库自己定的（assumed；每条在示例 00 有灵敏度行或在 LOG 有数字）

基准带宽 20 MHz；SNR = 每有效子载波 Es/N0；相噪 TX/RX 各一份；CR 信道 = 指数 PDP 7 ns rms + LOS/散射 10 dB；OBO 参考 Psat（另给 P1dB）；信道估计平滑 3 音；genie 定时；只建 L-STF / L-LTF / Data；扰码种子 93。

## 要原文才能关掉的问题

1. Liu 2025 的 Rapp 参数与 OBO 定义（刊出版或作者）。
2. 11ad CR 信道的 tap 表（Maltsev 11-09/0334；拿到后 `TapTableChannel` 直接接，`cairn/Reference/` 放原文）。
3. IEEE 802.11-09/0296r16 原文：把 `tgad_em.*` 从 survey 改成 spec。
