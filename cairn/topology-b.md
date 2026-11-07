---
type: project_topic
status: active
summary: "拓扑 B（IMMW upclocking）在 60 GHz 零中频前端上的结论：基准 × K 网格里每格能不能、为什么；wifitrx 校准序列在每个 K 上哪步退化、机理是什么。"
tags: [mmw60, topology-b, upclocking, zero-if, calibration, grid]
contains: [comparison-table, finding, decision, pitfall]
created: "2026-11-07"
updated: "2026-11-07"
related: [upclocking.md, external-validation.md, architecture-invariants.md, engineering-pitfalls.md]
authoring_mode: ai_generated
---

# 拓扑 B：60 GHz 零中频前端

## 1. 前端怎么建（里程碑 1-B 的决定）

拓扑 B 的 60 GHz 收发机就是 wifitrx 的 `TxChain` / `RxChain` 跑在 `fs_eff = fs_base × K`（`frontend.model: zero_if_chain`）：
这既是"WiFi 7 芯片的零中频架构时钟 ×K"的字面含义，又让 wifitrx 的 14 步校准序列原样真跑（铁律 4）。
随 K 变的量全部在 `frontend/Frontend60` 里派生：转换器位数 = round(ENOB(fs_eff))，ENOB 每倍采样率降 0.5 bit（`assumed.converter_bits_per_octave`）；
LPF 角频 = wifitrx `recommended_lpf_corner_hz(BW × K)`；IQ 失配按绝对 ps / ns（同一器件在更宽的带上更差）；LO 泄漏 −30 dBc、RX 自混频 DC −25 dBc；
PA = 11ad EM Rapp 的 dBm 版 `ScaledRappPA`（Psat 15 dBm、增益 20 dB，都是 `assumed`），工作点由模拟 VGA 调到 Psat − OBO，数字驱动固定 −16.5 dBFS（DAC 不削顶）。
`Frontend60` 是两拓扑共用的实例（`LinkSim(cfg, frontend=fe)`，`tests/test_frontend.py::test_law2_*`）；A 会话拿同一个对象做 60 GHz 级。

锚：前端全关时 K = 1 与 K = 8 的链路 EVM 相同（−39.9 dB，差 < 0.1 dB）——链路里剩下的是 LPF 群时延与 3 音平滑的偏差，K 只改时间尺度。
里程碑 0 的 behavioural 路径逐位不变（指纹 68 个值相同）。

## 2. 网格：基准带宽 × K（示例 02，`examples/expected/02_upclock_grid.txt`）

口径：解析底板 = 相噪 ICI（wifitrx `cpe_partition`，T_FFT/K，TX+RX）⊕ IQ 镜像（`irr_db` 在占用带上平均，TX+RX，未校准）⊕ 转换器（DAC+ADC，ENOB(fs_eff)，带内份额）⊕ PA（Rapp 在 OBO 8 dB 的隔离 EVM −18.1 dB）⊕ GI 外 ISI；
"能" = CFO 捕获 + 频率规划通过 + MCS0 的 TX EVM 要求（wifitrx `tx_evm_limit_db`）留 3 dB；"IQcal" 列把 IQ 换成校准后每侧 45 dB 残余（`assumed.irr_after_cal_db`）；"no-PA" 列去掉 PA 项（回退是设计者按 MCS 调的旋钮，其余不是）。
时域列 = 同一格在 wifitrx 链上、flat 信道、无噪声的 EVM（全开 + 逐项隔离）。

| 带宽 | 哪些格 | 解析 / 时域 EVM | 结论 |
|---|---|---|---|
| ≤ 0.32 GHz | 11ac 20×4/8/16、40×4/8、80×4；11be 20×4/8/16、40×4/8、80×4 | −17 / −17 dB | PA 限 MCS2（去 PA：MCS4–5）；IQ −21…−31，相噪 −25…−30 |
| 0.64 GHz | 11ac 20×32、40×16、80×8、160×4；11be 20×32、40×16、80×8、160×4 | −15 / −15 dB | 仍 PA 限；未校准 IQ 已到 −15 dB，去 PA 后 IQ 限 MCS2 |
| 1.28 GHz | 11ac 40×32、80×16、160×8；11be 40×32、80×16、160×8、320×4 | −11.5 / −10.4 dB | IQ 限 MCS0（镜像 −8 dB）；校准后回到 PA 限 |
| 2.56 GHz | 11ac 80×32、160×16；11be 80×32、160×16、320×8 | −5.6 / −3.2…−4.5 dB | **不能**：未校准 IQ 镜像 −1 dB；校准后 MCS2 |
| 5.12 GHz | 11ac 160×32；11be 160×32、320×16 | +3 / +4…+13 dB | 不能：IQ；转换器 8.3 bit 仍只 −34 dB |
| 10.24 GHz | 11be 320×32 | — | 不能：超出 57–71 GHz 单信道，IQ |

- 解析与时域在 ≤ 1.28 GHz 内差 ≤ 1.2 dB；更宽时 IQ 镜像接近信号功率，线性叠加失效（时域更差），无妨结论。A2 之后 11be 格的时域列来自编码的 MCS0 数据域（不再是随机 16-QAM 载荷），并且前导多了 DC 测量用的静默段，单包的时域读数随之动了 ≤ 0.3 dB；结论列一格没动。
- **用户预期的"80 MHz × 32 或 160 MHz × 16 + CFO 估计"**：CFO 捕获在 60.48 GHz 上 K ≥ 4 都成立（2.42 MHz < ±2.5 MHz），它们的瓶颈不是 CFO 而是 2.56 GHz 上未校准的频率相关 IQ 不平衡（150 ps 群时延失配在 ±1.28 GHz 边缘是 1.2 rad）；校准后（示例 03 实测 2.56 GHz 上 irr_min 38–42 dB）回到 PA 限的 MCS2。
- 相噪项随 K 变好（T_FFT 变短，CPE 份额变大）：11ac 20 MHz 基准 −26.7（K=4）→ −31.6 dB（K=32）；11be 同带宽下比 11ac 差 1–2 dB（T_FFT 长 4 倍）。
- GI 外 ISI：7 ns 散射尾在 K=32 的 25 ns GI 外是 −25.9 dB，开始与 IQ 同量级。
- 转换器：按 −0.5 bit/octave，20 GS/s 处 7.8 bit → −34 dB，不是任何格的瓶颈；按 −1 bit/octave（Walden）11be 160×32 处 6.6 bit → −29.9 dB，仍非瓶颈。
- DPD 代价（dsp_ip dpd_poly P=4 DDR r=1 140 项，Horowitz 45 nm 运算能耗）：11ac 20×8 MCS2 156 Mb/s → 474 pJ/bit；11be 20×32 MCS1 551 Mb/s → 537 pJ/bit；2.56 GHz 带宽需 3.8 个 P=4 数据通路（2727 MSPS 各）。这是记账不是测量。

## 3. 校准：wifitrx 序列在每个 K 上（示例 03，`examples/expected/03_calibration_at_k.txt`）

链路 = 同一个 `Frontend60`，poweron 剖面；K = 1/4/8/16（20/80/160/320 MHz，wifitrx 有标准导频的评分波形）、K = 32（640 MHz）与 11be 80 MHz × 32（2.56 GHz，无评分波形）。

| 步骤 | K=1 | K=4 | K=8 | K=16 | K=32 (640M) | 80M×32 (2.56G) | 机理 |
|---|---|---|---|---|---|---|---|
| tx_lpf_corner / rx_lpf_corner | ok / ok | ok / ok | ok / ok | ok / ok | ok / **退化 6.4 %** | ok / **退化 13.6 %** | 角频随 BW 缩放；2^14 样本的扫频分辨率随 fs 变粗 |
| rx_dc_offset（worst dBFS） | −78.8 | −72.9 | −69.9 | −67.1 | −57.8 | −57.8 | 读 DC 箱；残余随 fs 上的噪声带宽升高 |
| tx_lo_leak_loopback（dBc） | −68.5 | −72.2 | −68.1 | **−55.0** | **−35.5** | **−35.5** | RX LO 偏置固定 4.8 MHz：K ≥ 8 时泄漏箱落进信号带内 |
| loopback_delay（ns） | 71.7 | 23.3 | 14.7 | 10.5 | 6.7 | 6.7 | 6 ns 回环 + LPF 群时延；max_lag 32 样本在 ≥ 5.3 GS/s 越界（2.56 GHz 处 5.12 GS/s 刚好未越） |
| tx_iq（irr_min dB） | 55.3 | 55.8 | 50.4 | 51.1 | 46.8 | **38.4** | 绝对 ps 失配在宽带上相位误差 ∝ K，校正 FIR 抽头数不变 |
| rx_iq（irr_min dB） | 56.3 | 55.2 | 50.6 | 52.3 | 47.8 | **41.8** | 同上 |
| group_delay（误差 ps） | −6.1 | −27.6 | −40.8 | −17.9 | 7.9 | 7.9 | 容差 80 ps 内 |
| dpd（PA 输出 EVM dB） | −27.3 | −25.0 | −26.5 | −26.4 | −18.4 | **−22.3** | 观测 ADC ENOB 随 fs 下降 + 无记忆 PA 的 GMP 冗余 |
| agc_sweep（落点误差 dB） | 0.3 | 0.1 | 0.3 | 0.0 | 0.1 | 0.1 | 探针 23 MHz 固定，未受影响 |
| final_loopback_evm（tx_evm_modem dB） | −25.5 | −25.1 | −26.7 | −26.1 | **skipped** | **skipped** | 无评分波形（wifitrx 导频表只到 320 MHz） |

- 没有一步在 2.56 GHz 上抛异常；"失效"表现为退化：LO 泄漏环检从 −68 到 −35 dBc（4.8 MHz 固定偏置在 2.5 MHz 音距下落在第 2 个子载波上，泄漏箱被数据淹没），IQ 校准从 55 到 38–42 dB，DPD 从 −27 到 −22 dB。
- 校准后的 IRR 实测值（38–42 dB @ 2.56 GHz、47–48 @ 640 MHz、50–52 @ 160–320 MHz）比网格假设的 45 dB 在 2.56 GHz 处差 3–7 dB：网格 "IQcal" 列在 2.56 GHz 处偏乐观约 1 个 MCS（ROADMAP A2 第一条）。
  更正（2026-11-07，同台表）：把实测值真放进 IQcal 列后 2.56 GHz 仍是 PA 限的 MCS2——"偏乐观 1 个 MCS" 没有兑现，一格都没动（`comparison-table.md` §6 ④）；实测表在 `derived.irr_after_cal_measured_db`。
- 评分波形的缺口是上游需求（ROADMAP D）：wifitrx 的 `pilot_positions` 只认标准带宽的表，640 MHz / 2.56 GHz 上 `scoring_frame` 无法构造。

## 4. 被推翻的判断

1. 以为校准序列会在 K ≠ 1 上直接失败（里程碑 0 读码的结论："run_full_cal 第一步就 ValueError"）——那是把 SCS 配成 312.5 kHz × K 的后果；用标准带宽的评分波形（160 MHz 11ac、320 MHz 11be）配链路跑在 fs_eff，序列全程能跑到 320 MHz。
2. 以为 K = 4 在拓扑 B 上一定失锁——那是 73.44 GHz 的数；60.48 GHz 上 40 ppm = 2.42 MHz，L-STF ±2.5 MHz 刚好接住，门槛通式 K > 2·Δf_max / 1.25 MHz = 3.9。
3. 以为 wifitrx 的 `align_delay` 能给链路定时——复波形互相关在 2.94 MHz CFO 下 1 µs 内去相关，整包定时错；改用包络互相关（`sim/link.py::envelope_lag`）。
4. 以为 wifitrx `ScaledPA` 能包 Rapp——它用 AM/AM 的 argmax 找饱和点、在 r_sat/100 读小信号增益，对单调的 Rapp 两个锚都错；自写 `ScaledRappPA` 按 Asat² 与 g 解析锚定。
