---
type: project_topic
status: active
summary: "拓扑 A（IF 延伸）：芯片原样 + 60 GHz 级的模型、插入点、频率规划、校准逐步结果、有无 60 GHz 观测回环的 DPD、MCS 上限随 LO 相噪、级联回退、MLO 预补偿后的 CFO 残差。"
tags: [mmw60, topology-a, if-extender, calibration, dpd, mlo]
contains: [comparison-table, finding, decision, pitfall]
created: "2026-11-11"
updated: "2026-11-11"
related: [topology-b.md, comparison-table.md, architecture-invariants.md, engineering-pitfalls.md]
authoring_mode: ai_generated
---

# 拓扑 A：IF 延伸（里程碑 1 / A1）

## 1. 模型与插入点（`src/mmw60/ifext.py`）

芯片 = wifitrx 自己的收发机，K = 1，按 wifitrx 自己的配方建（`handoff/runner.build_calibrated_trx`：随机化损伤、它自己的 PA 与频综），
再跑它交付的校准序列（`run_full_cal`，14 步）。芯片的 RF 输出在 6 GHz 段的一个信道上，这就是中频：

    芯片 TX（不改） → 间级电平 → IF 带通（纹波、群时延） → 固定 LO 混频（f_LO = f_c − f_IF，带相噪） → 60 GHz PA

接收侧镜像。`IfExtenderTx` / `IfExtenderRx` 是 wifitrx `TxChain` / `RxChain` 的子类，60 GHz 级加在父类 `__call__` 之后（接收侧之前）：
**级关掉时逐位等于父类**（`tests/test_ifext.py::test_law2_stage_off_*`）。因为它们仍是链，wifitrx 的回环和校准代码不用改就能跑在上面。

- 60 GHz PA、LO 相噪剖面、EIRP 限值是共享 `Frontend60` 里的同一批对象（铁律 2）。晶振、信道、接收机也与拓扑 B 相同。
- 基带转换器、IQ、LO 泄漏、RX DC 是芯片自己的（wifitrx 的，已校准），所以拓扑 A 的预设里前端那几个开关是关的。
- `ifext.chip` 另有一档 `frontend`：把共享前端自己在 1× 的链当芯片（PA 旁路、未校准，像拓扑 B）。`ideal()` 选它，铁律 2 的理想对比靠它。
- 只有拓扑 A 有的项：芯片校准后的残差（实测）、芯片自己的 LO、IF 滤波器、镜像带噪声。只有拓扑 B 有的项：未校准的基带 IQ 镜像、ENOB(fs_eff) 的转换器、LO 泄漏与 RX DC。同台表逐行标出。

## 2. 频率规划（示例 06 §1；位置而已，本引擎不背书杂散电平）

载频 60.48 GHz = IF 6.48 GHz + 固定 LO 54.00 GHz；×3 方案 PLL 在 18.0 GHz，×4 在 13.5 GHz（`assumed.ifext_lo_scheme`）。
镜像边带 47.52 GHz、LO 馈通 54.00 GHz，都在 57–71 GHz 之外。换信道靠芯片在 6 GHz 段内调 IF，固定 LO 不动。
相噪直接给在 LO 输出端（1 极 1 零剖面），所以 N 只进规划和 PLL 频率，不改相噪数字。

IF 带通：Chebyshev-I 5 阶、0.5 dB 纹波、通带 1.2 GHz（`assumed.ifext_filter`）。80 MHz 信道离通带中心 −45 MHz 时带内纹波 0.22 dB、群时延展宽 61 ps；
挪到通带边缘是 0.50 dB、1231 ps。它是线性的，接收机的信道估计把它均衡掉：链路 EVM 只动 0.02 dB。
接收侧镜像抑制 30 dB 时噪声系数恶化 0.004 dB，10 dB 时 0.41 dB。

## 3. 校准真跑（铁律 4；示例 06 §2）

同一颗未校准的芯片，同一套序列，两种观测：芯片自己的耦合器；60 GHz 观测回环（第二级 PA 后的耦合器，同一个固定 LO 下变频回芯片 RX，LO 相噪相消）。

| 步骤 | 芯片耦合器 | 60 GHz 观测回环 |
|---|---|---|
| tx / rx LPF 角频、RX DC | ok（0.18 % / 0.06 %，−69.1 dBFS） | 相同 |
| AGC 落点误差 | 0.41 dB | 0.46 dB |
| TX LO 泄漏（包络 / 回环） | −66.0 / −66.1 dBc | −64.2 / −63.0 dBc |
| RX IIP2 | 74.5 dBm | 70.3 dBm |
| TX IQ / RX IQ（irr_min） | 55.7 / 55.6 dB | **37.8 / 35.9 dB，degraded** |
| 群时延 | −30.0 ps | −25.9 ps |
| DPD（拟合后 EVM） | −41.2 dB | **−14.1 dB，发散** |
| 最终回环 EVM | −40.9 dB | −14.9 dB |
| 校准后：芯片输出 / 60 GHz PA 输出的 TX EVM | −40.9 / −19.9 dB | −9.6 / −14.7 dB |

未校准时 60 GHz PA 输出的 TX EVM 是 −18.25 dB。结论：**整套序列不能照搬到 60 GHz 观测回环上**。OBO 8 dB 的第二级 PA 在观测通路里，
IQ 校准把它的失真当成镜像去修（IRR 掉 18–20 dB），DPD 的间接学习发散，wifitrx 的序列照样把发散的预失真器写进去。
所以本库的做法是：全套校准在芯片自己的耦合器上跑；只有 DPD 一步可以选在 60 GHz 观测回环上重训，并且比不过已有的就不写入。

## 4. DPD：有无 60 GHz 观测回环（示例 06 §3；60 GHz PA 输出的 TX EVM，dB）

| 第二级回退 | 无 DPD | 只在芯片上观测 | 经 60 GHz 观测 | 观测回环的增益 | 写入的 |
|---|---|---|---|---|---|
| 6 dB | −16.2 | −16.9 | −0.7（发散） | 0 | 芯片上的 |
| 8 dB（预设） | −18.7 | −19.8 | −14.1（发散） | 0 | 芯片上的 |
| 10 dB | −21.1 | −22.8 | −22.2 | +0.2 | 60 GHz 观测的 |
| 12 dB | −23.4 | −25.9 | −32.1 | **+5.8** | 60 GHz 观测的 |
| 14 dB | −25.4 | −29.0 | −36.9 | **+8.2** | 60 GHz 观测的 |
| 16 dB | −27.1 | −32.0 | −39.0 | +7.1 | 60 GHz 观测的 |

观测回环在回退 ≥ 12 dB 时值 6–8 dB，在预设的 8 dB 回退上值 0 dB：这颗 Rapp（平滑度 0.81，P1dB 比 Psat 低 9.5 dB）压缩得太软，
wifitrx 的 ILA 在它上面靠近饱和就发散（wifitrx 自己的注释：“ILA diverges if driven past saturation”）。

## 5. MCS 上限随固定 LO 的相噪（示例 06 §4；11be 80 MHz，TX 与 RX 两个 LO）

| L(1 MHz) | 相噪 ICI：本库解析 / EvmBudget / 时域 | 全链路底板 / 时域 | 合规上限 | 解码器上限 |
|---|---|---|---|---|
| −85 dBc/Hz | −14.1 / −14.1 / −14.0 | −12.6 / −12.8 | MCS0 | MCS3（144 Mb/s） |
| −90 | −19.1 / −19.1 / −19.0 | −15.5 / −16.1 | MCS1 | MCS4（216） |
| −95 | −24.1 / −24.1 / −24.0 | −17.1 / −18.0 | MCS2 | MCS4 |
| −100 … −110 | −29.1 … −39.1 / 同 / −29.0 … −38.9 | −17.7 … −18.0 / −18.8 … −19.2 | MCS2 | MCS4 |

**验收**：LO 每差 5 dB，三者各动 5.00 / 5.00 / 5.00–5.06 dB；绝对值 EvmBudget 与时域差 −0.09 … −0.23 dB（要求 < 1 dB）。
−95 dBc/Hz 以下 LO 不再是瓶颈，上限由 60 GHz PA 定（隔离 EVM −18.1 dB）。预设的 Liu 剖面在 1 MHz 处是 −96 dBc/Hz。

## 6. 级联回退（示例 06 §5；链路 EVM / 解码器上限）

| 芯片 PA 输出（回退） | 芯片残差 | 第二级 6 dB | 8 dB | 10 dB | 12 dB | 芯片 PA 直流 |
|---|---|---|---|---|---|---|
| 10.1 dBm（17.9 dB） | −38.8 dB | −15.6 / MCS4 | −17.9 / MCS4 | −19.9 / MCS6 | −21.5 / MCS6 | 202 mW |
| 13.3 dBm（14.7 dB，芯片出厂增益） | −42.0 | −15.9 / MCS4 | −18.2 / MCS4 | −20.3 / MCS6 | −22.0 / MCS6 | 294 mW |
| 16.5 dBm（11.5 dB） | −37.5 | −15.8 / MCS4 | −18.1 / MCS4 | −20.2 / MCS5 | −21.9 / MCS6 | 421 mW |
| 18.9 dBm（9.1 dB，增益码上限） | −29.0 | −15.6 / MCS4 | −17.7 / MCS4 | −19.5 / MCS5 | −20.9 / MCS6 | 555 mW |

芯片的输出要先衰减 24 dB 才到第二级的驱动电平，所以芯片 PA 的回退几乎不进链路 EVM（一列之内差 ≤ 1.1 dB），它花的是直流功率：
**芯片 PA 作驱动级耗 202–555 mW，是 60 GHz PA（63 mW）的 3–9 倍**。链路 EVM 由第二级回退定，每 2 dB 约 2 dB，到 12 dB 处被相噪（−25 dB）压住。

## 7. CFO（铁律 3；示例 06 §6；`impairments/cfo.py::MloCfo`）

40 ppm × 60.48 GHz = 2.419 MHz = 31 个子载波，芯片的 L-STF 只到 ±625 kHz。接法：MLO 的 sub-7 链路（5.5 GHz）用 L-STF + L-LTF 估出自己的 CFO（220 kHz），
乘 f_c / f_sub7 = 11.0 预补偿 60 GHz 链路；残差 = sub-7 估计误差 × 11.0，再交给芯片自己的估计器。估计是真跑的（前导 + 偏移 + 噪声过本库的估计器），每包一次。

| sub-7 SNR | sub-7 估计误差 rms | 60 GHz 残差 rms / 最大 | 最大残差（子载波） |
|---|---|---|---|
| 5 dB | 4.5 kHz | 49.7 / 148.9 kHz | 1.91 |
| 10 dB | 2.3 kHz | 25.0 / 69.2 kHz | 0.89 |
| 20 dB（预设） | 0.68 kHz | 7.4 / 24.0 kHz | 0.31 |
| 30 dB | 0.21 kHz | 2.3 / 8.0 kHz | 0.10 |

链路 EVM：预补偿开 −18.26 dB；关掉 +4.10 dB（失败）；ppm = 0 时 −18.22 dB。ppm 为零时整项（偏移、估计、预补偿）关掉，信号逐位原样返回。
前提是每台设备的 sub-7 LO、芯片 IF LO 和 60 GHz 固定 LO 同源一颗晶振（`assumed.mlo_common_reference`）；不成立时预补偿失效。

## 8. 与拓扑 B 同台（`comparison-table.md` §2）

同样 320 MHz、同一颗 60 GHz PA、同一回退，解码器上限都是 MCS4、865 Mb/s：拓扑 A（11be 320 MHz，K = 1）1127 pJ/bit，拓扑 B（80 MHz × 4）628 pJ/bit。
A 每比特贵 1.8 倍，多出来的是芯片 PA（作驱动级）和每端两个频综。A 的带宽止于芯片的 320 MHz；B 还能到 640 MHz（1729 Mb/s、467 pJ/bit）。
A 换来的是芯片不用改，以及已校准的基带（芯片 IRR 55 dB；B 未校准时镜像项 −31 … −12 dB）；在 OBO 8 dB 处这点好处被 PA 盖住，只在 B 的宽带格里才显出来。

解码器上限用 PER 复核（示例 06 §8）：MCS4 预测 12.71 dB、实测 11.86 dB；MCS5 预测 18.99、实测 18.02。偏保守 0.9–1.0 dB，与拓扑 B 的 K = 4 一样。

## 9. 本库自己定的（assumed；示例 06 §7 逐条有灵敏度行）

IF 6.48 GHz、×3、滤波器的阶数 / 纹波 / 通带、镜像抑制 30 dB、芯片 seed 5、芯片 4 倍过采样、sub-7 链路 5.5 GHz / 20 dB、同源晶振。
灵敏度：滤波器关或信道在通带边缘 ≤ 0.02 dB；换一颗芯片 0.00 dB；芯片不带 DPD +0.86 dB；用共享前端的未校准链当芯片 +0.21 dB；相噪只加 RX 侧 −0.47 dB。

## 10. 坑

见 `engineering-pitfalls.md` 的“拓扑 A”一节（IPN 的单边带口径、`BoundedDPD` 不能 deepcopy、`tx_power` 步的参考驱动、整套序列不能搬到 60 GHz 观测回环）。
