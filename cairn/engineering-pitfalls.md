---
type: project_topic
status: active
summary: "开工前先读：vendored wifitrx 在 K ≠ 1 下会断在哪里、接收机里哪一步吃掉了多少 dB、YAML 浮点、numba 逐位相同的写法。"
tags: [mmw60, pitfalls, wifitrx, receiver]
contains: [pitfall, lesson, finding]
created: "2026-11-06"
updated: "2026-11-11"
related: [architecture-invariants.md, upclocking.md, external-validation.md]
authoring_mode: ai_generated
---

# 工程坑

## wifitrx 在 K ≠ 1 下的断点（都不改上游，在本库包一层）

- **`pilots._tables` 对 SCS 做精确相等匹配**（78.125e3 / 312.5e3），`tone_plan.standard`、`_ACTIVE_TONES*` 按 20/40/80/160/320e6 查表：
  把 `subcarrier_spacing_hz` 配成 312.5 kHz × K 直接 ValueError。→ 基准数字学 + `fs_eff`（upclocking.md §1）。
- **VHT 20 MHz 有 56 个有效音**（52 数据 + 4 导频），wifitrx 的 legacy 表给的是 11a 的 52：用 `tone_plan=contiguous(56)`，`pilot_positions` 在显式 plan 上按标准索引 ±7/±21 直接查，得到列 [21, 35, 7+28-1 …]；别用 `pilot_set="model"`。
- **`stf_waveform` 硬编码 0.8e-6 s 与 1.25e6 Hz**：在基准数字学上用没问题（K 只改 fs 的解释）。
- **wifitrx 的 `estimate_cfo` 只用 LTF 两段**（±SCS/2），STF 只是 AGC 激励："the estimators never look at it"。STF 粗估计是本库 `rx/cfo.py` 写的。
- **`run_full_cal` 在 K ≠ 1 直接失败**（第一步 `generate_ofdm_with_pilots`），另有绝对频偏探针（4.8 / 5.1 MHz、11 / 17 / 23 MHz）、固定样本窗（`max_lag = 32`）、320 MHz 调的阈值。里程碑 1 的校准表要逐项记这些。
- **`TDLChannel.k_db` 只让第一个 tap 变 Rician**，尾部功率不变；要 LOS 占优（抑制 GI 之外的 ISI）用本库 `channel.ExponentialTdl(los_k_db=…)`。
- `EvmBudget` 默认 `t_fft_s = 12.8e-6`：用时必须传 `1/SCS_eff`。

## 11be 编码路径里踩到的（A2，2026-11-07）

- **RX 自混频 DC 杀的不是 EVM 而是 CFO 估计**：−25 dBc 的 DC 在 EVM 上只在 CFO 把它搬进数据音后才显（−30 dB），但它在 CFO 校正之前就坐在 L-STF 自相关的输入里：
  SNR 5 dB 时估计偏 602 kHz（11be 80 MHz × 8 的 SCS 625 kHz，几乎整整一个子载波），SNR 2 dB 时偏 1.2 MHz，包全错；去掉 RX DC 项估计误差回到 3 kHz。
  修法是接收机的事，不是前端的：`RxConfig.dc_removal` 在突发前加一段静默（`N_SILENCE` 1024 样本），接收机在那上面量 DC 再减掉——这正是 wifitrx `rx_dc_offset` 校准步的量法。
  **第一版用整帧均值估 DC 是错的**：CFO 把一个数据音搬到离 0 Hz 只有 80 kHz（2.5 MHz − 2.42 MHz），16 个符号的短帧上 sinc(80 kHz × 8 µs) ≈ 0.47，半个数据音被当成 DC 减掉，
  11ac 40 × 8 "仅 CFO" 的隔离 EVM 从 −40 掉到 −26 dB；编码长帧看不出来，示例 02 的 EVM-only 短帧看得出来。默认关（里程碑 0 指纹），零中频预设开。`test_dc_removal_keeps_the_stf_estimator_honest_at_low_snr`。
- **11be 的 N_DBPS 不一定是整数**：996 音 RU 上 MCS 9 / 11（980 × 8 × 5/6 = 6533⅓、980 × 10 × 5/6）；规范就是这样写的，预 FEC 填充吃掉小数。`EhtMcs.n_dbps_exact` 是 Fraction，符号数用 ceil、载荷位数用 floor。
- **LDPC PPDU 流程的"加一个符号"分支会在短包上触发**：20 MHz MCS0 装 10 字节 → 1 个符号 234 个可用位、648 码缩短 207 删余 207 → 删余超过校验位的 10 % 且缩短不足 → 加符号、改为重复 27 位。写测试时按直觉猜"1 个符号"是错的，流程说 2 个。
- **4096-QAM 的 LLR 不能暴力搜**：n × 4096 距离矩阵在 980 音 × 几十符号上是 GB 级；wifitrx 的 Gray 方形星座前 m/2 位只看 I、后 m/2 位只看 Q，按轴搜是精确的（Q 项在两个假设下相同、相减抵消），`mapper.llr` 在 > 256 阶走这条，≤ 256 阶保持原算术（指纹）。

## 接收机里每一步的代价（K = 8、flat、MCS0、PER = 1e-2 处的 SNR；`tests/test_link.py`）

| 配置 | SNR@1e-2 |
|---|---|
| BCC 并集界（d_free = 10，32768 bit） | ≈ 2.0 dB |
| genie CSI、不做 CPE、不估 CFO（解码器本身） | 1.5–2 dB（压在并集界上） |
| genie CSI + 逐符号 4 导频 CPE | ≈ 4.4 dB |
| L-LTF 信道估计（平滑 3 音）+ CPE + STF/LTF CFO 估计（默认接收机） | ≈ 4.9 dB |
| 同上，不平滑 | ≈ 6.0 dB |
| 同上，平滑 9 音 | ≈ 4.1 dB |
| 改进的一档：跨符号 CPE 合并（17 符号）+ 平滑跨度自动选（示例 00 的 flat rx+，带 CFO / 相噪 / PA） | 2.54 dB [2.43, 2.62]（同一次运行里程碑 0 的接收机 5.25） |

- **逐符号导频 CPE 的代价来自尾部，不是方差**：4 个导频在 SNR 3 dB 下相位估计 σ ≈ 14°，平均损失只有 0.3 dB，但一个符号的 4 导频和碰巧抵消时整符号 52 bit 被转掉，交织只在符号内，Viterbi（d_free 10）救不回 → 这包就错。1262 符号 × 每符号 ~1e-4 的尾概率就是 PER 量级。跨符号合并已作为 `RxConfig.cpe_window_symbols` 落地（下节）。
- **CFO 估计开着就必须开 CPE**：估计残差（~0.02 SCS）的相位斜坡跨 1262 符号累积到多个弧度，没有 CPE 整包必错（`genie CSI, CPE off, CFO est on` → PER = 1）。
- **信道估计平滑要和相干带宽比**：K = 16 时音距 5 MHz，15 ns rms 的信道相干带宽 ~10 MHz，3 音平滑把估计拉偏到 EVM −7 dB；LOS 占优的默认信道纹波小才无妨。跨度逐包自动选已作为 `RxConfig.ce_smooth_auto` 落地（下节）。

## 改进接收机时踩到的（C1–C3，2026-11-11；`rx/tracking.py`、`tests/test_tracking.py`）

- **跨度选择的噪声估计不能用抛物线外推**：用 R(1)、R(2) 抛物线外推 R(0) 得信道功率 P，在选择性信道上把 P 读低（15 ns rms、5 MHz 音距：0.91 对 1.0），差额被记成“可平滑的噪声”，K = 16 Rayleigh 上选了 3 音。改成指数时延谱的自相关 P/(1 + a²d²) 拟合。
- **偏差只靠模型不行**：模型不知道链路自己滤波器的滚降。第二版在理想 20 MHz 链上选到 9 音，11ac MCS8 的门限从 25.9 掉到 28.0 dB。现在模型只决定 1 音还是 3 音；再宽要看实测的 mean|H_S − H|² 减去噪声份额后剩下的偏差，并且多让一个估计自身的散布 W₃·√(2/N)。
- **平手不等于不平滑**：看不到噪声（W 截在 0）且模型判平坦时，第三版落在“偏差 ≥ 节省”的等号上取 1 音，无噪声的 11be 20 MHz 链从固定 3 音的 −45.6 dB 掉到 −41.2 dB（LTF 估计里有一份 −41 dB 的音间不相关误差，W 的分辨力看不到它）。等号改归 3 音；示例 02 的隔离列（conv / cfo）当时读到的其实是这个底板。
- **窗口为 1 必须直接走 wifitrx 的 `correct_cpe_pilots`**：自己的实现在 window = 1 时算术等价但不逐位相同，里程碑 0 的指纹会动。
- **残余 CFO 的相位斜坡要先拿掉再平均**：否则 17 个符号的窗内相量互相抵消；用滞后 1 的乘积粗估、再用半窗滞后细化，平均后把斜坡加回去。
- **bootstrap 区间可能不含点估计**：下括点零错包时重抽的 PER 永远是 Jeffreys 后验的正数，插值点系统偏右。区间按定义放宽到包含点估计。
- **时域 EVM 列是接收机读到的 EVM**：换接收机它就动（≤ 2.56 GHz 的格低了 0.1–1.2 dB），解析列不动。拿它当“前端底板”时要记得里面有信道估计的份额。
- **归因先量再写**：2.56 GHz MCS0 从 5.42 到 1.06 dB，动手前猜是跨符号 CPE 的功劳；拆开量是自动平滑 3.4 dB、CPE 2.0 dB（理想链上反过来：0.85 / 1.7 dB）。

## 拓扑 A 踩到的（A1，2026-11-11；`src/mmw60/ifext.py`、`tests/test_ifext.py`）

- **wifitrx 的 `ipn_dbc` 是单边带口径**（相位功率 / 2，`impairments/phase_noise.py` 的 docstring 写着）：相位方差 = 2 × 10^(dBc/10)。A3 把 10^(dBc/10) 直接喂给 `EvmBudget.ipn_rad2`，
  相噪项读低 3.0 dB，当时还给它找了个物理解释（“不含 100 MHz 以上的底板”）。**一个恒定的 3.0 dB 差先查因子 2，再找物理。**
- **`BoundedDPD` 不能 `copy.deepcopy`**：它的 `__getattr__` 把未知属性转给 `self.model`，deepcopy 重建对象时 `model` 还没设，无限递归。预失真器是拟合好的无状态可调用对象，复制链时共享它。
- **`tx_power` 步的目标功率是在 wifitrx 自己的参考驱动（0.25 rms）上定义的**：链路跑在 0.15，差 4.4 dB。配置里的 `chip_pout_dbm` 指链路驱动下的输出，建链时换算。这颗芯片的增益码到 18.9 dBm 封顶。
- **整套校准不能照搬到 60 GHz 观测回环**：第二级 PA（OBO 8 dB）在观测通路里，IQ 校准把它的失真当镜像修（IRR 55.7 → 37.8 dB），DPD 的 ILA 发散后 wifitrx 照样把它写进链里（芯片输出 EVM −9.6 dB）。
  只把 DPD 一步放到 60 GHz 观测上，并且与已有的预失真器在同一观测通路上比过再决定写不写。
- **“这颗 PA 做不了 DPD”之前先扫迭代次数**：wifitrx 的 `calibrate_dpd` 默认迭代 2 次，在软压缩的 Rapp 上靠近饱和时第二次迭代把第一次的成果丢掉（8 dB 回退：1 / 2 / 3 次 −20.7 / −14.1 / +3.6 dB）。第一版只跑默认值，把发散归给了 PA。算法有旋钮时，结论要在旋钮的两端都成立才算 PA 的性质。比较候选时要放回同一输出功率：预失真把增益补回来，输出功率会变。
- **`ideal()` 改的是配置，芯片在缓存里**：拓扑 A 的理想链靠 `ifext.chip = "frontend"`（共享前端自己的 1× 链），不是把校准过的 wifitrx 芯片“关掉损伤”。铁律 2 的理想对比还要在同一过采样倍数上比（芯片 4 倍、拓扑 B 2 倍，LPF 群时延的份额不同：−43.0 对 −39.9 dB）。
- **拓扑 A 的 K = 1 @60.48 GHz 行与拓扑 B 的 K = 1 行硬件上看起来一样，差别全在 CFO**：B 的 K = 1 失锁（+13 dB），A 靠 MLO 预补偿（−18.2 dB）。

## 文献对不上时的几个"口径"而非"参数"

- **OBO 参考点**：11ad EM 的 CMOS Rapp（p = 0.81）P1dB 在 Psat 以下 9.5 dB；"OBO 8 dB" 相对 Psat 是平均功率在 P1dB 之上 1.5 dB（孤立 EVM −17 dB），相对 P1dB 则是 −26 dB 量级。两种都跑，哪种是原文的意思写进 external-validation。
- **SNR 口径**：每有效子载波 Es/N0 与每样本 SNR 差 10·log10(os·N_FFT/N_active) = 3.59 dB（os = 2，64 点，56 音）。
- **信道**："802.11ad CR 信道"在没有 tap 表时只能用 PDP 代替；选 rms / LOS 比的依据是原文曲线自己给出的可观测事实（16× 不比 8× 差 ⇒ 50 ns 之外能量可忽略；曲线 3 dB 内从 1 到 1e-3 ⇒ 近 AWGN）。

## 工具层

- **PyYAML 把 `73.44e9` 读成字符串**（YAML 1.1 要求有小数点且指数带符号）：spec 表里的浮点一律写成 `73.44e+9`；`spec.py` 的测试会在算术时暴露。
- **numba 与 numpy 内核逐位相同的写法**：两边都是"每个候选 = 一次加法 (metric[prev] + (a·la + b·lb))、严格 `c1 < c0` 选路"，不用 `np.minimum` 以外的归约、不改运算顺序；`MMW60_NO_JIT=1` 走 numpy 内核，`tests/test_phy.py` 比对解码比特。
- **polar_tx 的 vendor_check 会剥掉所有前导 `# ` 行**，而 wifitrx 自己的文件就以 `# Vendored from PA_DPD…` 开头：本库的检查器只剥自己加的两行头（`_strip_header`），并检查 `__init__.py`。
- `tools/example_drift.py` 与 `fingerprint_walk.py` 是 d2d_link 的文件原样（ruff 对它们放开 E501）。
