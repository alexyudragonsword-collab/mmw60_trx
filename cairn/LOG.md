# Project Cairn 日志

本文件按倒序记录实质性进展 —— 最新条目在本行正下方。每条保持简短（摘要 + 指针），
结论沉淀进 `cairn/<topic>.md`。

## 2026-11-07 · A3 同台表：11 行有数字、6 格点名未建，三方对账，pJ/bit 与灵敏度（feat/a3-comparison-table）

- 一个 `Frontend60` 给每行。11ac 20 MHz 基准：K=1@6 GHz −17.2 / −17.5 dB MCS2 20 Mb/s 8720 pJ/bit；K=1@60.48 失锁（CFO 7.7 sc）；K=4/8/16 MCS2 78/156/312 Mb/s 3803/2456/1694 pJ/bit；K=32 MCS1（IQ）416 Mb/s 1869。11be 80 MHz：K=4 MCS2 432 Mb/s **1227**（全表最好）；K=8 MCS1 576 Mb/s 1359；K=16 MCS0 2141；K=32 不能（IQ −5.8 dB）。
- 对账：时域 − 底板 −0.3…+1.0 dB（线性区）；EvmBudget − 底板 −0.0…−0.4 dB，相噪口径差 3–4 dB（EvmBudget 不含 >100 MHz 底板与 1–10 kHz），被 PA 项 −18.1 盖住。
- LO 并排（K=8 底板）：pole_zero −17.4、wifitrx_wifi7 −17.8（IPN 好 16 dB 只买 0.4 dB）、pllsim wu19 ×N −17.7。
- 灵敏度：只有 PA 回退 ±2 dB 动 MCS 上限（7 / 8 行）；pJ/bit 排名被 7 nm 节点、1 bit/octave、PAE 10 % 改写，不被 Walden 38–120 fJ 与频综 ×0.5/×2 改写；实测 IRR 对假设 45 dB 一格不动。
- **被推翻的判断**：① K=1 WiFi 7 行不是效率参照而是最差（分母 20 Mb/s）；② 20 MHz 基准 K=32 比 K=16 差（DPD 711 > PA 151）；③ EvmBudget 与底板对得上不是口径一致而是 PA 主导；④ A2 实测 IRR 不改任何格；⑤ 铁律 2 完整测试必须共用**理想实例**，`cfg.ideal()` 改不了实例里的硬件。
- 指纹 68 值逐位不变；非慢测试 84 → 107 项（其中 6 项是 A / ay 的矩阵格，按里程碑 skip）。下一步：A1 的行接进 `PENDING` 那格；A3 剩余见 ROADMAP。

## 2026-11-07 · 方案枚举（waveform）与 ROADMAP 里程碑 3（feat/roadmap-ay-waveform-enum）

- 只改文字、一个占位枚举和 ROADMAP 结构：`waveform` 四值枚举（ay 两项拒绝运行）、铁律 1–4 "每种方案"、里程碑 3 ay 一节、D 节三条上游需求按可贴格式重写 + fmcw_radar 收件项。优先级不变：A1 → A3 → ay。
- 指纹 68 值逐位不变；`main` 已是默认分支，之后 `feat/*` 开 PR 合 `main`。

## 2026-11-07 · 里程碑 1-B：拓扑 B 的 60 GHz 零中频前端、网格、校准表（ccr-65a5163d-bbo5rb，0.1.0）

- 前端 = wifitrx `TxChain`/`RxChain` 跑在 fs_eff，`Frontend60` 一个实例两拓扑共用；锚：前端全关 K=1 与 K=8 EVM 同为 −39.9 dB；里程碑 0 指纹 68 值逐位不变。
- 逐项隔离（K=8，flat，无噪声）：PA（OBO 8 自 Psat）−18.6、相噪 TX+RX −26.2、IQ −25.1、转换器（11 bit）−39.7、CFO 40 ppm −39.8（全纠）、LO 泄漏 −30 dBc 对 EVM 不可见、RX DC −25 dBc 配 CFO 后 −30.2；全开 −17.4 dB。
- 网格（示例 02，36 格）：≤ 0.32 GHz 全部 PA 限 MCS2；1.28 GHz 处未校准 IQ 限 MCS0；2.56 GHz 及以上"不能"（IQ 镜像 ≥ −1 dB）；校准后回到 PA 限。解析 vs 时域 ≤ 1.2 dB（≤ 1.28 GHz）。11be 320×32（10.24 GHz）超出 57–71 GHz 单信道。
- 校准（示例 03）：K ≤ 16 全程 ok，最终 tx_evm_modem −25…−27 dB；K=32 / 2.56 GHz：LO 泄漏环检 −68 → −35 dBc、IQ 55 → 38–42 dB、DPD −27 → −22 dB、RX LPF 角频 13.6 % 误差；`final_loopback_evm` 无评分波形（上游需求 D）。没有一步抛异常。
- **被推翻的判断**：① 校准序列在 K≠1 不是直接失败而是退化（评分波形用标准带宽的表即可跑到 320 MHz）；② 60.48 GHz 上 K=4 不失锁（2.42 MHz < 2.5 MHz），门槛 K > 3.9 而非 4.7；③ `align_delay` 在 2.94 MHz CFO 下整包定时错，改包络互相关；④ `ScaledPA` 包不了 Rapp，自写 `ScaledRappPA`。
- 下一步：A 会话的拓扑 A（同一 `Frontend60` 的 60 GHz 级 + IF 级）；A3 同台表；ROADMAP A2 剩余项（实测 IRR 回填网格、11be 编码、ENOB 实测包络）。

## 2026-11-06 · 里程碑 0：引擎对上 Liu 2025 Fig. 4（ccr-65a5163d-bbo5rb，0.0.1）

- **验收（PER = 1e-2 处 SNR，dB；原文读图 MCS0 4.2 / MCS1 7.5 / MCS4 19.7(8×) 19.0(16×)）**：字面读法（LOS/散射信道 + OBO 自 Psat）K=8 MCS0/1/4 = 6.59 / 9.83 / 21.00，K=16 = 6.68 / 9.80 / 21.83，差 +1.3 … +2.8 dB，**超过 1 dB**；
  flat 信道 K=8 = 5.35 / 8.59 / 20.42，K=16 = 5.18 / 8.82 / 19.84（差 +1.15 / +1.09 / +0.72；+0.98 / +1.32 / +0.84）；无损伤 K=8 = 6.10 / 9.00 / 17.00。K = 4 三组全 PER = 1 ✓。示例 00 全量 1582 s、01 1222 s（4 核）。

- 建库：vendored wifitrx@cc06b9ac 整包 verbatim；upclocking = 基准数字学 + fs_eff；自建 VHT 编解码（PER）、Rapp、1 极 1 零相噪、L-STF 粗估计。68 项测试，CI 五个作业。
- **解码器与并集界**：K = 8 flat MCS0，genie CSI、不跟踪时 PER 1e-2 在 1.5–2 dB（并集界 2.0 dB）；加 4 导频逐符号 CPE → 4.4 dB；加 L-LTF 估计（平滑 3 音）→ 4.9 dB；不平滑 → 6.0 dB；平滑 9 音 → 4.1 dB。
- **被推翻的判断 1**：原文"refrained from using estimation and compensation algorithms for CFO"按字面不可能——CFO 全关时 K = 4 / 8 / 16 在 SNR 20 dB 全部 PER = 1（示例 00 诊断行）；原文 V-B 的 4.7 论证以 L-STF 自相关估计器在跑为前提，示例 00 按此配置。
- **被推翻的判断 2**：CR 信道先取 15 ns rms 纯 Rayleigh 指数 PDP → K = 16 的 50 ns GI 外能量 −14 dB，EVM 底板 −14 dB，与 Fig. 4 "16× 不比 8× 差"矛盾；改 7 ns（GI 外 −31 dB）并加 LOS/散射 10 dB。即便如此，K = 8 的 LOS/散射信道仍比 flat 贵约 2 dB（MCS0 6.0 vs 4.1–5.0；MCS4 ideal 17.0 vs 15.1，80 包粗扫），原文曲线的陡度说明其信道是 AWGN 样的。
- **被推翻的判断 3**：OBO 8 dB 相对 Psat 用 11ad EM 的 CMOS Rapp（p = 0.81）等于平均功率在 P1dB 之上 1.5 dB，孤立 EVM −17 dB；以为要改成相对 P1dB 才对得上——全量跑出来 P1dB 口径 MCS4 16.39 / 16.04 dB，比原文**好** 3 dB，过度修正；而 flat 信道 + 字面 OBO 的灵敏度行 19.67 dB 与原文 19.7 差 0.03 dB。于是第三组改为 flat + 字面 OBO，P1dB 只留灵敏度行（17.27）。
- **被推翻的判断 4**：以为 16× 会像原文一样在 MCS4 比 8× 好——字面组 16× 反而差 0.8 dB（21.83 vs 21.00）：50 ns GI 外的散射尾 + 5 MHz 音距上的 3 音平滑偏差。
- **新发现**：示例 01 的整数子载波模糊解算让 K = 4 在 2.35 子载波 CFO 下工作：MCS0 6.00 / MCS1 9.21 / MCS4 22.00 dB，只比 K = 8 差 0.6 / 0.6 / 1.0 dB——门槛是估计器的，不是波形的。
- 下一步：ROADMAP C1（跨符号 CPE 平滑）、C2（平滑跨度随相干带宽）、C3（1e-2 点的统计精度，散布约 ±0.5 dB）、A1/A2（两条拓扑）。

## 2026-11-06 · Project Cairn 初始化

- `cairn init`：zh、track、provider 暂缓；AGENTS.md 七条铁律各括守护测试；ROADMAP 只写没做的。
