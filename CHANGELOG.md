# 变更记录 / Changelog

按里程碑记录。每条写**做了什么**和**为什么**；数字原值在 `cairn/LOG.md`。

## 里程碑 0 —— 对外校验：Liu 2025 Table II / Fig. 4（2026-11-06，0.0.1）

- **脚手架 + vendor**：`src/mmw60/vendor/wifitrx/` 是 `wifi_trx_cal@cc06b9ac8dafb5cbb261a59280e81ae0cfbf787c` 的 `src/wifitrx` 整包（106 文件，全 verbatim），
  每文件两行头；`tools/vendor_check.py`（polar_tx 的改编：只剥本库的两行头、查 `__init__.py`）+ `vendor_manifest.json`；CI `vendor-drift` 按完整 SHA checkout，
  private 仓库需 `SIBLING_READ_TOKEN`。Project Cairn 文件集（AGENTS / CLAUDE / .cairn / ROADMAP / CHANGELOG / cairn/LOG + 五篇专题）。
- **upclocking 层**（`upclock.py`）：基准数字学 + `fs_eff = fs_base × K`，K = 1 是未改动的 wifitrx 链（铁律 2 的锚）。为什么不改 SCS：wifitrx 的导频表精确匹配 SCS。
- **VHT 数据域编解码**（`phy/`）：扰码、BCC 133/171 + 删余、20 MHz 交织、Gray 映射 + max-log LLR、软判决 Viterbi（numpy 向量化 + numba 内核逐位相同，`MMW60_NO_JIT=1`）。
  为什么：wifitrx 是 EVM 级模型，没有 BPSK、没有信道编码，测不了 PER。
- **损伤**：1 极 1 零相噪 `PoleZeroPhase`（wifitrx `NoiseSource` 子类，用它的 `synth_from_psd`）、`CfoModel`（(ppm_tx + ppm_rx)·f_c，0 ppm 逐位为零）、
  `pa/rapp.py` 11ad EM 的 modified Rapp（OBO 参考点 psat / p1db 两档）、`channel.py`（flat / 指数 PDP + LOS K / 显式 tap 表）、每子载波 Es/N0 的加噪口径。
- **接收机**（`rx/`）：wifitrx 自由函数的组合 + 本库的 L-STF 粗 CFO 估计（±625 kHz × K）与整数子载波模糊解算（示例 01）；`cfo_estimation: off | ltf | stf_ltf | extended`；
  诊断用 `genie_csi`。
- **配置 / 规范表**：frozen `Mmw60Config`（两条拓扑都在枚举里，A 在里程碑 1 之前抛 NotImplementedError）、YAML 往返、`guispec.py` 18 个表单字段；
  `data/spec/survey.yaml` 48 条（33 survey / 10 assumed / 5 derived）+ `liu2025_fig4.yaml` 读图值。
- **示例与工具**：示例 00（Table II 三组曲线：字面 / 无损伤 / flat 信道 + 灵敏度行（含 OBO 自 P1dB、Rayleigh、PN rx-only、理想 PA、不平滑） + "CFO 估计全关"诊断行）、示例 01（扩展捕获范围）、
  `tools/external_check.py`（对 Fig. 4 逐条差值）、`fingerprint.py` / `fingerprint_walk.py`、`run_examples.py`、`example_drift.py`（d2d_link 原样）。
- **测试**：68 项（66 项 `pytest -m "not slow"` + 2 项示例冒烟 slow），铁律 1 / 3 / 5 / 6 / 7 各有守护测试，2 / 4 有锚；解码器压在 BCC 并集界上的解析 / 仿真交叉核对。
- **验收结果与被推翻的判断**：见 `cairn/LOG.md` 2026-11-06 与 `cairn/external-validation.md`。
