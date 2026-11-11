---
type: project_topic
status: active
summary: "拓扑 B（IMMW upclocking）在 60 GHz 零中频前端上的结论：基准 × K 网格里每格能不能、为什么；wifitrx 校准序列在每个 K 上哪步退化、机理是什么。"
tags: [mmw60, topology-b, upclocking, zero-if, calibration, grid]
contains: [comparison-table, finding, decision, pitfall]
created: "2026-11-07"
updated: "2026-11-11"
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
`Frontend60` 是两拓扑共用的实例（`LinkSim(cfg, frontend=fe)`，`tests/test_frontend.py::test_law2_*`）；拓扑 A 拿同一个对象做 60 GHz 级（`topology-a.md`）。

锚：前端全关时 K = 1 与 K = 8 的链路 EVM 相同（−39.9 dB，差 < 0.1 dB）——链路里剩下的是 LPF 群时延与信道估计平滑的偏差，K 只改时间尺度。
里程碑 0 的 behavioural 路径逐位不变（指纹 68 个值相同）。

## 2. 网格：基准带宽 × K（示例 02，`examples/expected/02_upclock_grid.txt`）

口径：解析底板 = 相噪 ICI（wifitrx `cpe_partition`，T_FFT/K，TX+RX）⊕ IQ 镜像（`irr_db` 在占用带上平均，TX+RX，未校准）⊕ 转换器（DAC+ADC，ENOB(fs_eff)，带内份额）⊕ PA（Rapp 在 OBO 8 dB 的隔离 EVM −18.1 dB）⊕ GI 外 ISI；
"能" = CFO 捕获 + 频率规划通过 + MCS0 的 TX EVM 要求（wifitrx `tx_evm_limit_db`）留 3 dB；"IQcal" 列把 IQ 换成校准后每侧 45 dB 残余（`assumed.irr_after_cal_db`）；"no-PA" 列去掉 PA 项（回退是设计者按 MCS 调的旋钮，其余不是）。
时域列 = 同一格在 wifitrx 链上、flat 信道、无噪声的 EVM（全开 + 逐项隔离）。

| 带宽 | 哪些格 | 解析 / 时域 EVM | 结论 |
|---|---|---|---|
| ≤ 0.32 GHz | 11ac 20×4/8/16、40×4/8、80×4；11be 20×4/8/16、40×4/8、80×4 | −17 / −17…−18 dB | PA 限 MCS2（去 PA：MCS4–5）；IQ −21…−31，相噪 −25…−30 |
| 0.64 GHz | 11ac 20×32、40×16、80×8、160×4；11be 20×32、40×16、80×8、160×4 | −15 / −15…−16 dB | 仍 PA 限；未校准 IQ 已到 −15 dB，去 PA 后 IQ 限 MCS2 |
| 1.28 GHz | 11ac 40×32、80×16、160×8；11be 40×32、80×16、160×8、320×4 | −11.5 / −11…−12 dB | IQ 限 MCS0（镜像 −8 dB）；校准后回到 PA 限 |
| 2.56 GHz | 11ac 80×32、160×16；11be 80×32、160×16、320×8 | −5.6 / −3.2…−4.5 dB | **不能**：未校准 IQ 镜像 −1 dB；校准后 MCS2 |
| 5.12 GHz | 11ac 160×32；11be 160×32、320×16 | +3 / +4…+13 dB | 不能：IQ；转换器 8.3 bit 仍只 −34 dB |
| 10.24 GHz | 11be 320×32 | — | 不能：超出 57–71 GHz 单信道，IQ |

- 表里的“结论”是发射机合规口径。解码器口径（示例 02 的 dec / dec-cal 列，`comparison-table.md` §2b）高 1–3 档：≤ 0.64 GHz 的 11be 格 MCS4、11ac 20 MHz 格 MCS3；1.28 GHz 的 11be 格 MCS3（合规 MCS0）；2.56 GHz 的 11be 格 MCS0（合规“不能”）；5.12 GHz 及以上仍不能；校准后 11be 全部 MCS4。C1–C3 之前（逐符号 CPE、固定 3 音平滑的接收机）0.64 GHz 是 MCS3、1.28 GHz 是 MCS2–3。
- 解析与时域在 ≤ 1.28 GHz 内差 −1.1 … +0.5 dB；更宽时 IQ 镜像接近信号功率，线性叠加失效（时域更差，2.56 GHz 差 0.3–1.2 dB），解码器上限取两者中较差的一个（`decoder_floor_db`）。时域列是接收机看到的 EVM，所以跟着接收机走：C1–C3 的自动平滑跨度把 ≤ 2.56 GHz 的格的时域读数压低了 0.1–1.2 dB（信道估计里的失真被多平均了几个音），解析列与结论列一格没动。A2 之后 11be 格的时域列来自编码的 MCS0 数据域（不再是随机 16-QAM 载荷），并且前导多了 DC 测量用的静默段。
- **用户预期的"80 MHz × 32 或 160 MHz × 16 + CFO 估计"**：CFO 捕获在 60.48 GHz 上 K ≥ 4 都成立（2.42 MHz < ±2.5 MHz），它们的瓶颈不是 CFO 而是 2.56 GHz 上未校准的频率相关 IQ 不平衡（150 ps 群时延失配在 ±1.28 GHz 边缘是 1.2 rad）；校准后（示例 03 实测 2.56 GHz 上 irr_min 38–42 dB）回到 PA 限的 MCS2。
- 相噪项随 K 变好（T_FFT 变短，CPE 份额变大）：11ac 20 MHz 基准 −26.7（K=4）→ −31.6 dB（K=32）；11be 同带宽下比 11ac 差 1–2 dB（T_FFT 长 4 倍）。
- GI 外 ISI：7 ns 散射尾在 K=32 的 25 ns GI 外是 −25.9 dB，开始与 IQ 同量级。
- 转换器：按 −0.5 bit/octave，20 GS/s 处 7.8 bit → −34 dB，不是任何格的瓶颈；按 −1 bit/octave（Walden）11be 160×32 处 6.6 bit → −29.9 dB，仍非瓶颈。
- DPD 代价（dsp_ip dpd_poly P=4 DDR r=1 140 项，Horowitz 45 nm 运算能耗）：11ac 20×8 MCS2 156 Mb/s → 474 pJ/bit；11be 20×32 MCS1 551 Mb/s → 537 pJ/bit；2.56 GHz 带宽需 3.8 个 P=4 数据通路（2727 MSPS 各）。这是记账不是测量。

## 3. 校准：wifitrx 序列在每个 K 上（示例 03，`examples/expected/03_calibration_at_k.txt`）

链路 = 同一个 `Frontend60`，poweron 剖面，wifitrx@96078aa；K = 1/4/8/16（20/80/160/320 MHz，wifitrx 有标准导频的评分波形）、K = 32（640 MHz）与 11be 80 MHz × 32（2.56 GHz）。
后两列没有标准导频表，用**基准波形 × K**（`calcheck.upclocked_scoring_config`：基准带宽的音与导频原样，音距 × K；wifitrx 96078aa 起 `TonePlan` 自带导频，wifi_trx_cal#4），整套序列的激励与评分都是它。每次采集 8 个符号（`assumed.cal_capture_symbols`）。

| 步骤 | K=1 | K=4 | K=8 | K=16 | K=32 (640M) | 80M×32 (2.56G) | 机理 |
|---|---|---|---|---|---|---|---|
| tx_lpf_corner / rx_lpf_corner | ok / ok | ok / ok | ok / ok | ok / ok | ok / ok | ok / **退化 8.7 %** | 角频随 BW 缩放；2^14 样本的扫频分辨率随 fs 变粗 |
| rx_dc_offset（worst dBFS） | −78.8 | −72.9 | −69.9 | −67.1 | −63.8 | −57.8 | 读 DC 箱；残余随 fs 上的噪声带宽升高 |
| tx_lo_leak_loopback（dBc） | −68.5 | −72.2 | −68.1 | **−55.0** | **−56.9** | **−39.8** | RX LO 偏置固定 4.8 MHz：K ≥ 8 时泄漏箱落进信号带内 |
| loopback_delay（ns） | 71.7 | 23.3 | 14.7 | 10.5 | 8.2 | 6.8 | 6 ns 回环 + LPF 群时延；max_lag 32 样本在 ≥ 5.3 GS/s 越界（2.56 GHz 处 5.12 GS/s 刚好未越） |
| tx_iq（irr_min dB） | 55.3 | 55.8 | 50.4 | 51.1 | 46.9 | **37.9** | 绝对 ps 失配在宽带上相位误差 ∝ K，校正 FIR 抽头数不变 |
| rx_iq（irr_min dB） | 56.3 | 55.2 | 50.6 | 52.3 | 46.5 | **42.1** | 同上 |
| group_delay（误差 ps） | −6.1 | −27.6 | −40.8 | −17.9 | −8.6 | 8.1 | 容差 80 ps 内 |
| dpd（PA 输出 EVM dB） | −27.3 | −25.0 | −26.5 | −26.4 | **−19.7** | −25.2 | 观测 ADC ENOB 随 fs 下降；640 MHz 列见下面的采集长度 |
| agc_sweep（落点误差 dB） | 0.3 | 0.1 | 0.3 | 0.0 | 0.1 | 0.1 | 探针 23 MHz 固定，未受影响 |
| final_loopback_evm（tx_evm_modem dB） | −25.5 | −25.1 | −26.7 | −26.1 | **−19.3** | −26.0 | 标准带宽用标准波形，更宽的用基准波形 × K |

最后一步的三个视图（wifitrx 的 modem 口径，标准接收机读到的；回环 / 仅发 / 仅收，dB）：K = 1 −26.4 / −25.5 / −27.4；K = 16 −29.3 / −26.1 / −27.9；640 MHz −19.4 / −19.3 / −29.6；2.56 GHz −24.3 / −26.0 / −28.3。
2.56 GHz 列的 genie 口径回环 EVM 校准前后是 2.2 / −12.9 dB，modem 口径 −24.3 dB：差的那部分是标准接收机的信道估计与导频跟踪能吸收的线性项。

- 没有一步在 2.56 GHz 上抛异常；"失效"表现为退化：LO 泄漏环检从 −68 到 −40 dBc（4.8 MHz 固定偏置在 2.5 MHz 音距下落在第 2 个子载波上，泄漏箱被数据淹没），IQ 校准从 55 到 38–42 dB，RX 角频偏 8.7 %。最终 EVM 仍是 −26.0 dB，与 320 MHz 的 −26.1 持平。
- **640 MHz 那列差的是采集长度，不是带宽**：11ac 20 MHz 基准 × 32 只有 52 个音、64 点 FFT，8 个符号是 1280 个样本，GMP 拟合不够：DPD 之后仅发 EVM −19.3 dB，比不开 DPD 的 −22.8 dB 还差 3.5 dB；采 32 个符号（5120 样本）是 −27.8 dB。
  同样 640 MHz 换 11be 20 MHz 基准 × 32（242 音、2.5 MHz 音距，8 个符号 4352 样本）是 −27.2 dB。K = 1 的同一个 64 点波形 8 个符号够用（−25.5 dB）；K = 32 上为什么不够没有单独验证（候选：观测 ADC 的 ENOB 随 fs 下降，辨识噪声更大）。示例 03 有 32 符号的灵敏度行；默认值没有改（每列同一个符号数）。
- 末步 modem 口径的信道估计平滑固定 9 音（wifitrx 的默认；对方在 wifi_trx_cal#4 提醒这类音距下最优音数会变）。本库链上重读仅发 EVM，1 / 3 / 9 音：640 MHz 8 个符号 −15.4 / −17.5 / −19.3，32 个符号 −25.8 / −27.4 / −27.8，2.56 GHz −24.1 / −25.4 / −26.0 dB。
  三种情况都是 9 音最好，640 MHz 那列的差不是平滑造成的（隔离口径同样是 −22.3 对 −29.5 dB）。
- 校准后的 IRR 实测值（38–42 dB @ 2.56 GHz、46–47 @ 640 MHz、50–52 @ 160–320 MHz）比网格假设的 45 dB 在 2.56 GHz 处差 3–7 dB：网格 "IQcal" 列在 2.56 GHz 处偏乐观约 1 个 MCS（ROADMAP A2 第一条）。
  更正（2026-11-07，同台表）：把实测值真放进 IQcal 列后 2.56 GHz 仍是 PA 限的 MCS2——"偏乐观 1 个 MCS" 没有兑现，一格都没动（`comparison-table.md` §6 ④）；实测表在 `derived.irr_after_cal_measured_db`。
- 更正（2026-11-11，重新 pin wifitrx@96078aa）：本节原先写 640 MHz 与 2.56 GHz 两列的 `final_loopback_evm` 是 skipped（wifitrx 的导频表只到 320 MHz），其余步骤在无导频的纯 OFDM 激励上跑。现在两列整套都用基准波形 × K，
  所以这两列的其他数字也动了：640 MHz 的 rx_lpf_corner 6.4 % → 0.0、LO 泄漏 −50.8 → −56.9 dBc、dpd −18.4 → −19.7；2.56 GHz 的 rx_lpf_corner 13.6 % → 8.7、LO 泄漏 −35.5 → −39.8、tx_iq 38.4 → 37.9、rx_iq 41.8 → 42.1、dpd −22.3 → −25.2。
  K = 1 / 4 / 8 / 16 四列一个数没动。原表 640 MHz 列的 rx_dc / LO 泄漏 / 回环延迟 / 群时延四格抄成了 2.56 GHz 列的数（−57.8 / −35.5 / 6.7 / 7.9），当时的实测是 −64.1 / −50.8 / 8.1 / −8.7。

## 3b. PA 的电记忆与 DPD 抽头间隔（示例 07，`src/mmw60/pamemory.py`）

预设的 60 GHz PA 是无记忆的 Rapp。时钟 ×K 之后多出一个标准速率链路碰不到的问题：PA 的记忆跟不跟着时钟走？两端：

- **随信号缩放**：抽头永远隔一个样本（PA 是为它承载的带宽设计的）。预失真器在每个 K 上面对同一个问题。
- **按秒固定**：抽头隔 1 / fir_fs 秒，在 fs_eff 上隔 fs_eff / fir_fs 个样本，逐样本的 GMP 基函数够不着。

模型是 wifitrx 的 `ReferencePA`（PA_DPD 的参考 PA：3 抽头输入 FIR → Saleh → 2 抽头输出 FIR，`fs` / `fir_fs` 来自 PA_DPD@02ca433），按本库前端的增益 / Psat 定标；预失真器是 wifitrx 自己的 DPD 步，GMP 的抽头间隔从 wifi_trx_cal@da37888 起可传（`run_cal_at(dpd_tap_spacing=…)`）。
PA 模型与 `fir_fs` = 80 MS/s（12.5 ns 一个抽头）都是假设（`assumed.pa_memory_model` / `assumed.pa_memory_fir_fs_hz`）：这是只在一种方案上做的灵敏度研究，预设与同台表不变。11be 80 MHz 基准，2 倍过采样，每一行的最终 EVM 都落在同一个输出回退上（预设的 8 dB，自 Psat）。

DPD 后的 TX EVM（dB，标准接收机口径）：

| K（带宽，一个抽头的样本数） | 随信号缩放：关 / 开 | 按秒固定：关 | ×1（逐样本） | ×2 | ×4 | 匹配（×fs_eff / fir_fs） | 代价（最好的间隔 − 随信号缩放） |
|---|---|---|---|---|---|---|---|
| 4（320 MHz，8） | −20.9 / −25.9 | −20.6 | −14.8 | −16.1 | −17.4 | −18.6 | 7.3 dB，且全部比不开 DPD 差 |
| 8（640 MHz，16） | −21.2 / −27.5 | −20.9 | −21.5 | −20.9 | −20.8 | −20.9 | 6.0 dB |
| 32（2.56 GHz，64） | −21.5 / −25.9 | −20.7 | −22.7 | −17.8 | −16.6 | −18.5 | 3.2 dB |

预设的 Rapp（无记忆）在同一回退上：关 / 开 DPD 为 −18.6 / −18.6（K = 4）、−18.9 / −19.0（K = 8）、−19.0 / −22.4 dB（K = 32）。

回退的灵敏度（随信号缩放 / 按秒固定 ×1 / 按秒固定匹配，dB）：

| K | 回退 8 dB | 10.5 dB | 13 dB |
|---|---|---|---|
| 8 | −27.5 / −21.5 / −20.9 | −28.5 / −25.9 / −26.4 | −28.6 / −27.4 / −27.8 |
| 32 | −25.9 / −22.7 / −18.5 | −28.6 / −24.2 / −27.9 | −28.2 / −25.0 / −28.5 |

记忆有多快（K = 32，回退 8 dB；×1 / 匹配）：抽头 12.5 ns −22.7 / −18.5，3.125 ns −20.5 / −21.3，0.78 ns −24.2 / −25.8，随信号缩放 −25.9 dB。

- **记忆按秒固定时，预设回退点上 DPD 基本失效**：最好只比不开 DPD 好 0.6–2.0 dB（K = 8 / 32），K = 4 上还更差；对随信号缩放的同一颗 PA 损失 3.2–7.3 dB。换抽头间隔救不回来。
- **匹配的抽头间隔只在退得够、K 够大时才赢**：K = 32 上回退 10.5 / 13 dB 时匹配间隔 −27.9 / −28.5 dB，追平随信号缩放的 −28.6 / −28.2；回退 8 dB 时反而比逐样本差 4.1 dB。K = 8 上三档回退里逐样本与匹配只差 0.4–0.6 dB。
  对方在 wifi_trx_cal#5 给了原因：预失真器与 PA 之间的发射基带低通带来逐样本的记忆，PA 的记忆隔几十个样本，等间隔的基函数只能顾一头。所以抽头间隔要在链路上量着选，不能直接取 fs_eff / fir_fs（`pamemory.candidate_spacings`）。
- **两种记忆规律在同样的驱动下输出功率差约 1 dB**：抽头拉开后 FIR 的响应在信号带内成了纹波，带内平均增益是各抽头功率之和（输入 FIR +0.08 dB），逐样本时在带内接近相干和（直流处 +1.3 dB）。不把每一行放到同一个回退上，比较的就是两个工作点。
  `run_cal_at(obo_db=…)` 先在评分波形上修 VGA，跑完看最终检查实际落在哪，差了就带着修正重跑整套序列（示例 07 每行 1–3 遍）。
- **wifitrx 的 `ScaledPA` 对抽头拉开的 PA 定标偏 1.80 dB**（它在幅度斜坡上找小信号增益，抽头隔 ≥ 2 个样本时只读到主抽头）。`pamemory.memory_pa` 在逐样本的同一颗 PA 上取定标再换模型，两种规律的静态曲线因此逐点相同。
- 没建的：60 GHz PA 记忆时间常数的出处（`fir_fs` 是假设）；热记忆与偏置记忆（参考 PA 只有电记忆）；混合间隔的基函数；带记忆的 PA 进同台表（现在一行都没有，ROADMAP C8）。

## 4. 被推翻的判断

1. 以为校准序列会在 K ≠ 1 上直接失败（里程碑 0 读码的结论："run_full_cal 第一步就 ValueError"）——那是把 SCS 配成 312.5 kHz × K 的后果；用标准带宽的评分波形（160 MHz 11ac、320 MHz 11be）配链路跑在 fs_eff，序列全程能跑到 320 MHz。
2. 以为 K = 4 在拓扑 B 上一定失锁——那是 73.44 GHz 的数；60.48 GHz 上 40 ppm = 2.42 MHz，L-STF ±2.5 MHz 刚好接住，门槛通式 K > 2·Δf_max / 1.25 MHz = 3.9。
3. 以为 wifitrx 的 `align_delay` 能给链路定时——复波形互相关在 2.94 MHz CFO 下 1 µs 内去相关，整包定时错；改用包络互相关（`sim/link.py::envelope_lag`）。
4. 以为 wifitrx `ScaledPA` 能包 Rapp——它用 AM/AM 的 argmax 找饱和点、在 r_sat/100 读小信号增益，对单调的 Rapp 两个锚都错；自写 `ScaledRappPA` 按 Asat² 与 g 解析锚定。
5. 以为把 DPD 的抽头间隔设成 fs_eff / fir_fs 就接得住按秒固定的记忆（给 PA_DPD#4 / wifi_trx_cal#5 提需求时的出发点；PA_DPD 单拟合 PA 时 `tap_spacing` 1 → 4 是 −29.2 → −41.0 dB）——放进链路，预设回退上匹配间隔在 K = 8 / 32 都不如逐样本，K = 4 上全部比不开 DPD 差；只有回退 ≥ 10.5 dB 的 K = 32 上它才赢（§3b）。
6. PA 记忆研究的第一轮读数（不对齐回退、两种规律各自过 `ScaledPA` 定标）是“代价 2.3 / 2.3 / 1.1 dB，K = 32 上匹配间隔好 4.4 dB”——比的是两个工作点：按秒固定的那颗小信号增益被定高了 1.80 dB、回退少 0.7 dB。统一定标并把每一行放到回退 8 dB 上之后是 7.3 / 6.0 / 3.2 dB，匹配间隔在这个回退上反而差。测试里一条增益断言先红了才查出来。
