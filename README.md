# mmw60_trx

60 GHz（57–71 GHz 免许可段）WiFi 收发机行为级仿真框架。两种拓扑在同一个引擎里同台：

- **A = IF 延伸**：WiFi 7 芯片原样，5–7 GHz 射频输出当实 IF，一级固定 LO（×3 / ×4）60 GHz 上下变频 + 镜像滤波 + PA / LNA；波形不变。（已建：示例 06）
- **B = IMMW upclocking**（Liu 等，"Wi-Fi 8: Embracing the Millimeter-Wave Era"，IEEE Comm. Mag. 2025-03）：PHY / MAC 不动，时钟 ×K，带宽和子载波间距同乘，宽带零中频 60 GHz transceiver。（里程碑 0 已建）

引擎是 vendored 的 [`wifi_trx_cal`](https://github.com/alexyudragonsword-collab/wifi_trx_cal)（`src/mmw60/vendor/wifitrx/`，按完整 SHA pin，整包 verbatim）；本库加的是 upclocking 层、VHT 数据域编解码（PER）、Rapp PA、L-STF 粗 CFO 估计、1 极 1 零相噪、信道与接收机组合。

## 安装与运行

```bash
pip install -e ".[test,jit]"          # numba 可选；MMW60_NO_JIT=1 走纯 numpy，结果逐位相同
pytest -q -m "not slow"               # 约 5 分钟
python examples/00_liu2025_per_vs_snr.py --quick     # 冒烟；去掉 --quick 全量约 80 分钟（4 核）
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

## PA 的电记忆与 DPD 抽头间隔（示例 07）

预设的 60 GHz PA 没有记忆。示例 07 把一颗带电记忆的参考 PA（wifitrx / PA_DPD 的 `ReferencePA`，假设）放进拓扑 B 的链路，在 K = 4 / 8 / 32 上真跑 wifitrx 的校准序列，回答两个问题：
PA 的记忆是随信号缩放还是按秒固定，代价差多少；DPD 基函数的抽头间隔该取多少（在链路上量，不直接取 fs_eff / fir_fs）。每一行都落在预设的输出回退上。

```bash
python examples/07_pa_memory_dpd.py                       # 全量约 5 分钟（默认最多 4 个进程，--jobs 可改）；--quick 冒烟
```

结论见 `cairn/topology-b.md` §3b：代价按回退读。达到同样的 DPD 后 EVM，记忆按秒固定（12.5 ns）的 PA 要多退 0.5–2.3 dB；预设的 8 dB 回退正好在 DPD 的崖上，在这一个点上读到的 EVM 差（最多 6 dB）不是代价。

## 前端的三个面：接收前端、收发隔离、天线增益（示例 08）

链路预算和雷达（fmcw_radar，mmw60_trx#14）要从共享的 `Frontend60` 读三样东西：60 GHz 接收前端在最高增益档的增益 / NF / 输入压缩点（`fe.rx_front`）、收发隔离（`fe.tx_rx_isolation_db`、`fe.leakage_budget()`）、发 / 收天线增益（两个字段）。
预设不动：接收机仍是 wifitrx 的 WiFi 7 梯子（`fe.rx_front.sourced` 为 False，不要当成 60 GHz 前端的数读），天线 0 dBi，隔离未指定。`config.surveyed_frontend(cfg)` 换成查到的一档（增益 27 dB、NF 6.1 dB、IIP3 −20 dBm、天线 2 dBi、隔离 20 dB）。

```bash
python examples/08_frontend_faces.py                      # 全量约 15 秒；--quick 冒烟
```

**出处**：基准档的接收机与天线取同一颗 60 GHz 通信收发机，读过论文原文；隔离取自一篇论文的摘要。另有四条只读到搜索摘要，示例里逐行标着 `[survey, unverified]`，只作灵敏度档。结论见 `cairn/topology-b.md` §5：接收 NF 动的是灵敏度（1 dB 对 1 dB）和校准表，不动 SNR 轴上的链路 EVM；隔离 20 dB 时发射泄漏比通信接收前端的压缩点高 16.6 dB（时分双工链路看不到，雷达看得到）。

## 里程碑 1 · A1：拓扑 A，IF 延伸（示例 06）

芯片是 wifitrx 自己的收发机（K = 1），按它自己的配方随机化损伤并跑完 14 步校准；60 GHz 级（间级电平、IF 带通、固定 LO 混频、共享前端的 PA）显式插在它的 RF 输出之后（`src/mmw60/ifext.py`）。
CFO 靠多链路的 sub-7 估计乘频率比预补偿（`impairments/cfo.py::MloCfo`）。示例 06 出八张表：频率规划、逐步校准（芯片耦合器 / 60 GHz 观测回环）、有无观测回环的 DPD、MCS 上限随 LO 相噪、级联回退、CFO、假设的灵敏度、PER 复核。

```bash
python examples/06_topology_a_if_extender.py --jobs 4     # 全量约 4 分钟；--quick 冒烟
```

结论见 `cairn/topology-a.md`。

## 里程碑 1 · A3：同台表（示例 04、`tools/budget_report.py`）

`mmw60.compare` 把每种方案（拓扑 × 波形，8 格全部点名；没建的写明里程碑）放在**同一个** `Frontend60` 实例上：K = 1 的 WiFi 7 链、拓扑 B 的 K = 1 … 32，
每行 MCS 上限、吞吐、b/s/Hz、EIRP 余量、pJ/bit（`mmw60.power`，Halo 示例 41 口径，读比值）；解析底板 / 时域 EVM / wifitrx `EvmBudget` 三方对账；
LO 三种剖面（11ad pole-zero、WiFi 7 频综、pllsim 6.048 GHz ×10 剖面，带倍频器底噪的四档）并排；`--sensitivity` 列出哪些系数和假设改写结论。

```bash
python examples/04_comparison_table.py                       # 约 10 s；写 examples/output/04_comparison_table.md
python tools/budget_report.py --base 11be:80e6 --k 4,8,16,32 --sensitivity -o table.md --json table.json
```

结论见 `cairn/comparison-table.md`。

## 解码器上限（示例 02 的 dec 列、示例 04 §4b）

网格和同台表里的“MCS 上限”有两个口径并排：**合规口径**（EVM 底板比规范的 TX EVM 要求低 3 dB——发射机过不过认证）和**解码器口径**
（底板当一层噪声，对着本库接收机实测的 ideal 门限 `data/spec/per_thresholds.yaml`——链路带不带得动）。后者高 1–3 档，示例 05 逐格用 PER 复核。未校准的解码器上限从解析底板与该格时域 EVM 中较差的一个起算。
改了接收机要重量门限：`python tools/measure_thresholds.py --jobs 4`（约 16 分钟），`--check` 只比对不写。

## 接收机两档与 PER 的置信区间（C1–C3）

`RxConfig` 有两档接收机。里程碑 0 的一档（逐符号导频 CPE、固定 3 音平滑）留给 `liu2025_table2` 预设，对外校验和数值指纹都钉在它上面。
`zero_if_60ghz` 预设用改进的一档（`config.improved_rx`）：导频公共相位跨符号 MMSE 合并（`cpe_window_symbols`），信道估计平滑跨度逐包按估计自己的音间自相关选（`ce_smooth_auto`），实现在 `rx/tracking.py`。
`per_sweep(refine_errors=…)` 把夹住 PER 1e-2 的两个点续跑到指定错包数，`snr_at_per_ci` 给 bootstrap 95 % 区间；`tools/external_check.py` 的判决有三态（within / OUTSIDE / 这个精度下分不出）。

## 里程碑 1 · A2：11be 编码 PER（示例 05）

11be 的每个带宽现在都带 EHT 数据域（`phy/ldpc.py` 的 12 个 802.11 LDPC 码 + `phy/eht.py` 的 PPDU 编码流程、音映射、段解析、到 4096-QAM 的 LLR），
`LinkSim` 对 11be 基准解出 PER 而不只是 EVM。示例 05 跑 80 MHz × 4 / 8、MCS 0 / 4 / 7 的 PER–SNR（ideal / impaired / no-PA），并对照示例 04 的解析 MCS 上限。
接收机多了一步 DC 去除（`RxConfig.dc_removal`，在突发前的静默段上量）：没有它，−25 dBc 的 RX DC 在低 SNR 下把 L-STF 的 CFO 估计偏掉一个子载波。

```bash
python examples/05_11be_ldpc_per.py --jobs 4      # 全量约 5 分钟（4 核）；--quick 冒烟
```

## 读什么

- `AGENTS.md`：规则与七条铁律（每条有测试守着）。
- `ROADMAP.md`：只写没做的。
- `cairn/LOG.md`：每轮的数字原值与被推翻的判断。
- `cairn/upclocking.md`：K 的建模方式与 5.88 MHz / 4.7 门槛的推导。
- `cairn/topology-a.md`、`cairn/topology-b.md`、`cairn/comparison-table.md`：两条拓扑各自的结论与同台表。
- `src/mmw60/data/spec/survey.yaml`：每一个文献数字的出处与标签。

## CI

lint、测试（jit / no-jit）、示例冒烟、vendor 漂移（需要能读 private 的 `wifi_trx_cal` 的 `SIBLING_READ_TOKEN` secret，否则该作业按设计是红的）、数值指纹（base vs head，`(numbers-move)` 标记是逃生口）。

MIT License。
