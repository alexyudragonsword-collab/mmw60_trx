# mmw60_trx

60 GHz（57–71 GHz 免许可段）WiFi 收发机行为级仿真框架。两种拓扑在同一个引擎里同台：

- **A = IF 延伸**：WiFi 7 芯片原样，5–7 GHz 射频输出当实 IF，一级固定 LO（×3 / ×4）60 GHz 上下变频 + 镜像滤波 + PA / LNA；波形不变。（里程碑 1）
- **B = IMMW upclocking**（Liu 等，"Wi-Fi 8: Embracing the Millimeter-Wave Era"，IEEE Comm. Mag. 2025-03）：PHY / MAC 不动，时钟 ×K，带宽和子载波间距同乘，宽带零中频 60 GHz transceiver。（里程碑 0 已建）

引擎是 vendored 的 [`wifi_trx_cal`](https://github.com/alexyudragonsword-collab/wifi_trx_cal)（`src/mmw60/vendor/wifitrx/`，按完整 SHA pin，整包 verbatim）；本库加的是 upclocking 层、VHT 数据域编解码（PER）、Rapp PA、L-STF 粗 CFO 估计、1 极 1 零相噪、信道与接收机组合。

## 安装与运行

```bash
pip install -e ".[test,jit]"          # numba 可选；MMW60_NO_JIT=1 走纯 numpy，结果逐位相同
pytest -q -m "not slow"               # 约 5 分钟
python examples/00_liu2025_per_vs_snr.py --quick     # 冒烟；去掉 --quick 全量约 1 小时（4 核）
python tools/external_check.py        # 与 Liu 2025 Fig. 4 读图值对表
python tools/vendor_check.py --strict --siblings wifi_trx_cal=/path/to/wifi_trx_cal
```

每个示例第一行打印引擎名：这是线性化的时域基带引擎，杂散 / 互调结论不能背书。

## 里程碑 0：对外校验（示例 00 / 01）

按 Liu 2025 Table II 配置拓扑 B：VHT 20 MHz × K、MCS 0 / 1 / 4、4096 B、73.44 GHz、40 ppm、相噪 −93 dBc/Hz（1 MHz / 100 MHz）、modified Rapp OBO 8 dB，K = 4 / 8 / 16 的 PER–SNR 曲线。
结果、与原文 Fig. 4 的逐条差值、以及原文没说而本库自己定的每一个假设（`grep "source: assumed" src/mmw60/data/spec/survey.yaml`）见 `cairn/external-validation.md` 与 `examples/expected/`。

示例 01 回答原文没问的问题：把 L-LTF 的整数子载波模糊解开后，K = 4 能不能活。

## 里程碑 1-B：拓扑 B 的 60 GHz 零中频前端（示例 02 / 03）

`frontend.model: zero_if_chain` 把 wifitrx 的 `TxChain`/`RxChain` 跑在 `fs_eff` 上——转换器位数按 ENOB(fs_eff)、IQ 失配按绝对 ps、PA 回退由模拟 VGA 调到位——这正是"WiFi 7 芯片的零中频架构时钟 ×K"。
示例 02 是 "基准带宽 × K" 网格（11ac 20–160、11be 20–320 MHz × K 4–32）：每格解析底板与时域 EVM 交叉核对、能/不能 + 原因、MCS 上限、DPD pJ/bit；
示例 03 把 wifitrx 的校准序列在每个 K 上逐步真跑。结论见 `cairn/topology-b.md`。

## 里程碑 1 · A3：同台表（示例 04、`tools/budget_report.py`）

`mmw60.compare` 把每种方案（拓扑 × 波形，8 格全部点名；没建的写明里程碑）放在**同一个** `Frontend60` 实例上：K = 1 的 WiFi 7 链、拓扑 B 的 K = 1 … 32，
每行 MCS 上限、吞吐、b/s/Hz、EIRP 余量、pJ/bit（`mmw60.power`，Halo 示例 41 口径，读比值）；解析底板 / 时域 EVM / wifitrx `EvmBudget` 三方对账；
LO 三种剖面（11ad pole-zero、WiFi 7 频综、pllsim 剖面 ×N）并排；`--sensitivity` 列出哪些系数和假设改写结论。

```bash
python examples/04_comparison_table.py                       # 约 10 s；写 examples/output/04_comparison_table.md
python tools/budget_report.py --base 11be:80e6 --k 4,8,16,32 --sensitivity -o table.md --json table.json
```

结论见 `cairn/comparison-table.md`。

## 里程碑 1 · A2：11be 编码 PER（示例 05）

11be 的每个带宽现在都带 EHT 数据域（`phy/ldpc.py` 的 12 个 802.11 LDPC 码 + `phy/eht.py` 的 PPDU 编码流程、音映射、段解析、到 4096-QAM 的 LLR），
`LinkSim` 对 11be 基准解出 PER 而不只是 EVM。示例 05 跑 80 MHz × 4 / 8、MCS 0 / 4 / 7 的 PER–SNR（ideal / impaired / no-PA），并对照示例 04 的解析 MCS 上限。
接收机多了一步 DC 去除（`RxConfig.dc_removal`，在突发前的静默段上量）：没有它，−25 dBc 的 RX DC 在低 SNR 下把 L-STF 的 CFO 估计偏掉一个子载波。

```bash
python examples/05_11be_ldpc_per.py --jobs 4      # 全量约 40 分钟（4 核）；--quick 冒烟
```

## 读什么

- `AGENTS.md`：规则与七条铁律（每条有测试守着）。
- `ROADMAP.md`：只写没做的。
- `cairn/LOG.md`：每轮的数字原值与被推翻的判断。
- `cairn/upclocking.md`：K 的建模方式与 5.88 MHz / 4.7 门槛的推导。
- `cairn/topology-b.md`、`cairn/comparison-table.md`：拓扑 B 的网格 / 校准结论与同台表。
- `src/mmw60/data/spec/survey.yaml`：每一个文献数字的出处与标签。

## CI

lint、测试（jit / no-jit）、示例冒烟、vendor 漂移（需要能读 private 的 `wifi_trx_cal` 的 `SIBLING_READ_TOKEN` secret，否则该作业按设计是红的）、数值指纹（base vs head，`(numbers-move)` 标记是逃生口）。

MIT License。
