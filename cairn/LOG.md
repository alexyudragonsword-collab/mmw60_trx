# Project Cairn 日志

本文件按倒序记录实质性进展 —— 最新条目在本行正下方。每条保持简短（摘要 + 指针），
结论沉淀进 `cairn/<topic>.md`。

## 2026-11-06 · 里程碑 0：引擎对上 Liu 2025 Fig. 4（ccr-65a5163d-bbo5rb，0.0.1）

（数字由示例 00 / 01 全量运行填入；见本条下方"验收表"与 `cairn/external-validation.md`。）

- 建库：vendored wifitrx@cc06b9ac 整包 verbatim；upclocking = 基准数字学 + fs_eff；自建 VHT 编解码（PER）、Rapp、1 极 1 零相噪、L-STF 粗估计。68 项测试，CI 五个作业。
- **解码器与并集界**：K = 8 flat MCS0，genie CSI、不跟踪时 PER 1e-2 在 1.5–2 dB（并集界 2.0 dB）；加 4 导频逐符号 CPE → 4.4 dB；加 L-LTF 估计（平滑 3 音）→ 4.9 dB；不平滑 → 6.0 dB；平滑 9 音 → 4.1 dB。
- **被推翻的判断 1**：原文"refrained from using estimation and compensation algorithms for CFO"按字面不可能——CFO 全关时 K = 4 / 8 / 16 在 SNR 20 dB 全部 PER = 1（示例 00 诊断行）；原文 V-B 的 4.7 论证以 L-STF 自相关估计器在跑为前提，示例 00 按此配置。
- **被推翻的判断 2**：CR 信道先取 15 ns rms 纯 Rayleigh 指数 PDP → K = 16 的 50 ns GI 外能量 −14 dB，EVM 底板 −14 dB，与 Fig. 4 "16× 不比 8× 差"矛盾；改 7 ns（GI 外 −31 dB）并加 LOS/散射 10 dB。即便如此，K = 8 的 LOS/散射信道仍比 flat 贵约 2 dB（MCS0 6.0 vs 4.1–5.0；MCS4 ideal 17.0 vs 15.1，80 包粗扫），原文曲线的陡度说明其信道是 AWGN 样的。
- **被推翻的判断 3**：OBO 8 dB 相对 Psat 用 11ad EM 的 CMOS Rapp（p = 0.81）等于平均功率在 P1dB 之上 1.5 dB，孤立 EVM −17 dB，MCS4 到 22 dB 仍 PER 1e-2 以上；P1dB 在 Psat 以下 9.5 dB。示例 00 的"口径解读"组用 flat + OBO 自 P1dB。
- **新发现**：示例 01 的整数子载波模糊解算让 K = 4 在 2.35 子载波 CFO 下工作（quick 模式 MCS0 3.5 dB、MCS4 13 dB 与 K = 8 同量级）——门槛是估计器的，不是波形的。
- 下一步：ROADMAP C1（跨符号 CPE 平滑）、C2（平滑跨度随相干带宽）、A1/A2（两条拓扑）。

## 2026-11-06 · Project Cairn 初始化

- `cairn init`：zh、track、provider 暂缓；AGENTS.md 七条铁律各括守护测试；ROADMAP 只写没做的。
