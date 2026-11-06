# Project Cairn 日志

本文件按倒序记录实质性进展 —— 最新条目在本行正下方。每条保持简短（摘要 + 指针），
结论沉淀进 `cairn/<topic>.md`。

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
