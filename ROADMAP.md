# ROADMAP

**这份文件只写还没做的事。** 做完即删，并在 `CHANGELOG.md` 记一笔、`cairn/LOG.md` 记数字。每条带证据（复现方式与数字）。

## A. 里程碑 1 —— 两条拓扑同台（主体都已落地；下面是剩余项）

### A1. 拓扑 A 的剩余项（主体已落地：`src/mmw60/ifext.py`、示例 06、`cairn/topology-a.md`）
- **芯片 PA 旁路这一档留下的**（2026-11-14 已建：`ifext.chip_pa_bypass`，预设不开；`cairn/topology-a.md` §6b）：320 MHz 解码器口径 765 → 538 pJ/bit，拓扑 B 487；合规口径 1712 → 1200，比 B 的 1268 省。
  - 另一种做法没建：带着 PA 按交付方式校准、链路上再旁路（IIP2 照常，IQ 估计里混进 PA 失真，残差要在旁路模式下另量）。
  - 旁路后剩下的差：每端两个频综（芯片的 + 固定 LO）与 4 倍过采样的转换器。
- **间接学习越迭代越差，靠近饱和时 1 轮也不够**：60 GHz 观测回环的 DPD 在回退 6 dB 上每一轮都不如不加（观测读数 不加 −18.41、第 1 轮 −16.27 dB），留芯片上的；8 dB 上值 +1.63 dB（示例 06 §3）。换成压缩更陡的测量形状之后，第 2、3 轮照样越来越差。
  整套序列搬到 60 GHz 观测上，IQ 校准的 IRR 从 55.7 掉到 47.5 dB，芯片自己输出端的 TX EVM 掉到 −14.2 dB（§2）。（2026-11-13 回退改成 7.5 dB 之前：48.4 dB、−15.8 dB。2026-11-12 预设换成测量的 PA 之前：6 dB 上 −16.0 / −14.6，8 dB 上 +1.2；IRR 掉到 37.9 dB，芯片输出 −11.9 dB。）挑哪一轮现在由 wifitrx 的 DPD 步自己做（0.7.39），本库只再和芯片上原有的比（`train_dpd_mmw`）。
  待做：这类 PA 上换直接学习，或目标增益按可达的峰值输出折算（PA_DPD 有 `dpd/direct.py`，针对样条预失真器；已在 PA_DPD#4 上问对方要不要单开 issue）；
  或在观测通路里先把第二级 PA 的失真建模扣掉再做 IQ 校准。
- 没建的：60 GHz LNA 的增益台阶（2026-11-14 起它是共享前端最高增益档的一级固定增益，`assumed.ifext_rx_front60`；接收梯子只在芯片里）、混频器单独的非线性、IF 滤波器的温漂、采样钟偏差（两条拓扑都没建）；MLO 的 sub-7 链路只有 AWGN（没有它自己的相噪和多径）。
  预设用 WiFi 7 梯子时芯片前没有这一级（它就是芯片那颗梯子），所以预设的数与 60 GHz LNA 无关；换成查到的前端，拓扑 A 才在芯片前串一级。
- 11ac 20 MHz 的拓扑 A 行 pJ/bit 是 22419：26 Mb/s 的分母，不是硬件差（与 `comparison-table.md` §6 ① 同理）。（2026-11-13 回退改成 7.5 dB 之前 22259；2026-11-12 预设换成测量的 PA 之前：29291、20 Mb/s。）

### A2. 拓扑 B 的剩余项（主体已在里程碑 1-B 落地：`cairn/topology-b.md`）
- 示例 02 网格的 "IQcal" 列仍用 `assumed.irr_after_cal_db`（45 dB）；同台表（示例 04）已换成示例 03 实测的 `derived.irr_after_cal_measured_db`，一格结论都没动（`cairn/comparison-table.md` §6 ④），网格要不要跟着换只是口径统一的问题。
- 11ac 40 / 80 / 160 MHz 基准仍是 EVM-only（它们的 BCC 交织器未建；11be 全部带宽已有 LDPC 数据域，`phy/eht.py`）；要不要补只看有没有人要 11ac 宽带的 PER。
- 11be 数据域里没建的：HE/EHT 的预 FEC 填充 a 因子与 PE 字段（按 HT/VHT 流程，`assumed.eht_prefec_padding`）、EHT 11 位扰码器（PER 不感知）、MU-RU / 320 MHz 打孔 / DCM / 多流。
- 转换器 ENOB 随速率的法则（`assumed.converter_bits_per_octave`）换成 Murmann 调查表的实测包络（拿到表后标 survey）。
- DPD 的 2.56 GHz 代价现在是 dsp_ip P=4 综合面积 + Horowitz 运算能耗的记账，按逐样本的 GMP 算；带记忆的 PA 上基函数要改（C8 第一条），那时项数与代价要重算。

### A3. 同台表的剩余项（主体已落地：示例 04、`tools/budget_report.py`、`cairn/comparison-table.md`）
- WiFi 7 全链路四条整合：PA_DPD 的 PA / DPD 进 wifitrx 链在 K > 1 上已作为灵敏度研究接通（`pamemory.py`、示例 07：参考 PA 带记忆、wifitrx 的 DPD 步、抽头间隔透传），但预设与同台表的 PA 仍是无记忆的 Rapp（2026-11-12 起是测量 PA 的幅度与压缩形状），带记忆的 PA 没有进任何一行（C8）。还没做的一条：Halo ADC 校准接入（要 vendor halo 的 `adc` 模块，现在转换器列是 ENOB 法则 + Walden 计价，没有通道失配项）。已做：pll 剖面替换解析相噪（`PhaseNoiseConfig.model: profile`）、`EvmBudget` 对账（A1 更正单边带换算后每行差 0.0 dB，相噪项差 0.1–1.3 dB）。
- 解码器上限列（`decoder_cap`，已落地）的剩余：11ac 40 / 80 / 160 MHz 基准没有门限（n/a，要先建 BCC 宽带交织器）；示例 04 §6 的灵敏度从解析底板起算（每个旋钮不跑时域），2.56 GHz 行在那一节的基线是 MCS1、§4b 用时域底板是 MCS0；`per_thresholds.yaml` 是本库接收机的测量值，接收机再改要 `python tools/measure_thresholds.py --jobs 4` 重量（约 16 分钟）。
- 校准列现在是示例 03 实测 IRR 的查表，`calcheck.run_cal_at` 实跑进表要几分钟一列，留给需要它的那次。
- 表单字段：`guispec.py` 已有 19 个 Knob，桌面 GUI / Android 这一轮不做。

## B. 里程碑 2：阵列层
- vendor array_tx（按当时 main 完整 SHA；array_tx main 现为 `e897c159e5fc5b2e26af6336cf9f6164461ff7f5`，可以直接 pin），波束训练序列的 SNR 预算。

## 里程碑 3：802.11ay
ay 不是第三条拓扑，是拓扑 B 的硬件（zero_if_chain）配第三、四种波形：`waveform: ay_ofdm | ay_sc`，包在 vendored wifitrx 的 OFDM 机制外面，不进 polar_tx。同台表多两行，不多列。
- `ay_ofdm`：512 点 FFT、SCS 5.15625 MHz、2.64 GS/s、单信道 2.16 GHz，绑定 2 / 3 / 4 信道（4.32 / 6.48 / 8.64 GHz）；导频和前导（CEF）按 ay 的来，不复用 be 的表——所以它不等 D 节的 wifitrx 非标准带宽导频需求；绑定 4 时前端带宽是单信道的 4 倍，同台表加一列"绑定信道数 × 前端带宽"。
- `ay_sc`：单载波 PHY，π/2-BPSK 到 64-QAM，Golay 前导。最有价值的一行：SC 的 PAPR 比 OFDM 低 3–4 dB，正打在 PA 的 Psat 墙上；要回答"SC 用回退换来的 EIRP，够不够抵掉丢掉的频谱效率"。
- CFO：SCS 5.16 MHz 天然接住 2.4 MHz，不用 MLO 预补偿（铁律 3 仍要声明并有测试）。
- 波束训练：ay 原生自己做 sector sweep，没有 sub-7 链路；训练序列的 SNR 预算单算，和拓扑 B 靠 MLO 触发的那行对比。
- 校准：依赖 be 导频 / 音的步骤（逐音 ρ(f)、LO 泄漏环回、group_delay）为 ay 重写探针信号；算法和 `deps.py` 顺序不变；结果进"校准步骤 × 方案"表（示例 03 的表加列）。
- 数字来源：ay 的数字学、MCS、灵敏度表进 survey.yaml，拿不到原文全标 survey。

验收：ay_ofdm 理想链路的 PAPR 和带内 EVM 与公开文献同量级；ay_sc 的 PAPR 比 ay_ofdm 低 ≥ 3 dB（物理，不对就是波形生错了）；同一 PA、同一 EIRP 上限下 ay_sc 对 ay_ofdm 的回退差和 EIRP 差进 LOG，"净吞吐 × 距离"谁赢一句话；校准表每步对 ay 的状态有记录；现有两拓扑的行逐位不变（指纹）。
不做：EDMG MIMO、ay 的 MAC 层、SC 与 OFDM 混合帧。
前置：A3 同台表已出。A2 里"11be 编码 PER 排在 ay 波形之前"保留。

## C. 里程碑 0 过程中发现的问题

### C4. 需要外部输入才能关掉的（见 `cairn/spec-sources.md` 末节）
Liu 2025 的 Rapp 参数与 OBO 定义（TGad 原文 2026-11-13 已读：回退从 Psat 算、推荐 8 dB；Liu 本人用的哪颗 PA 仍不知道）；11ad CR 信道 tap 表。

### C6. C1–C3 过程中发现的（见 `cairn/LOG.md` 2026-11-11）
- **门限表自己还没用上 C3 的逼近**：`tools/measure_thresholds.py` 仍是每点 ≤ 200 包 / 15 错、0.5 dB 步。同一格（11be 80 MHz MCS4 理想链）门限表读 11.40、示例 05 读 11.09；
  解码器上限的预测因此带约 ±0.3 dB（K = 4 的 MCS4 预测 12.97、实测 12.12）。待做：工具加 `--refine`（`per_sweep(refine_errors=…)` 已有，79 条曲线约多 3 倍时间），区间写进文件。
- **平滑跨度选择器在窄带上有散布**：flat 理想链 `zero_if_60ghz(k=8)`（11ac 20 MHz，56 音）120 包的 `RxResult.ce_span` 分布，SNR 3 dB 时 9 音 67 %、3 音 32 %，12 dB 时 56 % / 39 %；
  同样条件 11be 80 MHz（996 音）全部取 9 音。56 个音上“多于 3 音”那一步的偏差估计，自己的散布 W₃·√(2/N) 与要省的噪声同量级。待做：信道准静态时跨包平均自相关，或改 DFT 域去噪。

### C7. 重新 pin wifitrx@96078aa、接入 pllsim ×10 剖面时发现的（见 `cairn/LOG.md` 2026-11-11）
- **校准采集 8 个符号在窄基准 × 大 K 上不够**：`python examples/03_calibration_at_k.py` 的 K = 32、11ac 20 MHz 基准（640 MHz，52 音，1280 样本）一列，DPD 步每一轮都不如不加、一轮都没写入，仅发 EVM −21.9 dB（与不开 DPD 相同），采 32 个符号 −27.7 dB（同一示例的灵敏度节；2026-11-13 起示例 03 校准在预设工作点上，从 Psat 回退 7.5 dB）。同一工作点上 K = 1 的同一个 64 点波形 8 个符号够 DPD 拿回 2.4 dB（DPD 步读数 −24.2 dB）。（2026-11-13 之前跑在 wifitrx 的默认驱动上：−20.8 / −24.1 dB，那时落在回退 6.9 dB；2026-11-12 预设换成测量的 PA 之前落在 10.7 dB：−22.8 / −29.0 dB。三次的工作点不同，绝对值不能直接比；“8 个符号不够”三次都成立。）
  默认值没改（`assumed.cal_capture_symbols` = 8，每列同一个符号数）。待做：采集长度按样本数而不是符号数给（或按 GMP 系数个数的倍数），K = 1 为什么够、K = 32 为什么不够要单独验证（候选是观测 ADC 的 ENOB 随 fs 下降）。
- **2.56 GHz 列的退化项没有被最终 EVM 惩罚**：RX 角频偏 8.7 %、LO 泄漏环检 −39.8 dBc、IRR 40.2 / 45.9 dB，而 modem 口径的最终 EVM 是 −23.9 dB（比 320 MHz 的 −21.8 还好），genie 口径的回环 EVM 只有 −13.5 dB（modem 口径回环 −23.4 dB）。（2026-11-13 之前校准跑在默认驱动上，回退 6.9 dB：IRR 38.5 / 46.2，最终 −20.7 对 −20.5，genie −14.6、modem −20.5 dB。2026-11-12 预设换成测量的 PA 之前，回退 10.7 dB：IRR 37.9 / 42.1，最终 −26.0 对 −26.1，genie −12.9、modem −24.3 dB。）
  两个口径差约 10 dB（默认驱动时约 6 dB，换 PA 之前约 11 dB）的部分是接收机的信道估计与导频跟踪吸收掉的线性项；哪些项在真实链路（多径、每包重估）里仍然吸收得掉没有验证。
- **倍频器底噪在这张表上看不见**：示例 04 §5，底噪 −160 / −150 / −140 / −130 dBc/Hz 四档，IPN 都是 −33.0 dBc、底板与 MCS 上限一格不动；只有 K = 32 的相噪 ICI 项从 −36.1 到 −33.0 dB。在预设回退处（2026-11-13 前 8 dB，现在 7.5 dB）LO 不是瓶颈，底噪的取值（`assumed.lo_multiplier_floor_dbchz`，没有出处）目前不影响任何结论；PA 回退加大或换线性 PA 之后要重看。
- 剖面文件里的杂散表（4 MHz 小数杂散 ×10 后 −43.7 dBc、谐波抑制 40 dB）引擎不消费（铁律 6）；要看杂散得上逐周期引擎。

### C8. PA 记忆研究（示例 07）发现的（见 `cairn/LOG.md` 2026-11-11、`cairn/topology-b.md` §3b）
- **记忆按秒固定的代价是多退 0.2–2.3 dB，要按回退读**：`python examples/07_pa_memory_dpd.py`，参考 PA、抽头 12.5 ns。达到 DPD 后 TX EVM −25 / −27 dB，K = 8 上随信号缩放的要退 7.3 / 7.8 dB，按秒固定的要退 9.0 / 10.1 dB（代价 1.7 / 2.3 dB）；K = 32 上 7.7 / 8.5 对 7.9 / 9.0 dB（代价 0.2 / 0.5 dB）。（2026-11-12 预设换成测量的 PA 之前：K = 8 代价 1.6 / 2.3，K = 32 是 7.4 / 8.3 对 7.9 / 8.9、代价 0.5 / 0.6。参考 PA 按前端的增益 / Psat 定标，换 PA 后跟着变，所以有小的移动；结论不变。）
  预设回退正好在 DPD 的崖上（随信号缩放的那颗 7.0 → 7.5 dB 之间从 −22.1 跳到 −26.3 dB）：2026-11-13 之前的 8 dB 在崖顶，现在按工作点规则取的 7.5 dB 就在崖口。所以在这一个点上读 EVM 差会读到 6 dB（7.5 dB 上 K = 8：随信号缩放 −26.3、按秒固定最好 −20.5，按秒固定的那颗 DPD 一点也拿不回），那是两条崖的间距，不是代价。
  待做：预设回退点本身在崖上（多退 0.5 dB 与少退 0.5 dB，带记忆的参考 PA 上 DPD 后差 4 dB 以上），同台表的 PA 若换成带记忆的要重新定回退；混合间隔的基函数能不能把 K = 8 的 1.7–2.3 dB 收回来没有试（PA_DPD 的设计问题，要的话另开 issue）。
- **抽头间隔必须量着选**：K = 32 上逐样本的基函数到回退 12 dB 也只有 −25.5 dB，匹配间隔 9.0 dB 就到 −27 dB；K = 8 上回退 7.0–8.5 dB 两种间隔互有胜负（差 ≤ 0.8 dB），9 dB 以上匹配间隔好（2026-11-12 预设换成测量的 PA 之前：匹配间隔 8.9 dB 到 −27 dB；K = 8 上 8.5 dB 以下逐样本好。）（对方在自己的链路上没有这个交叉，匹配间隔处处好：交叉随链路而定）。`pamemory.candidate_spacings` 只量 1 / 2 / 4 / 匹配四个，没有扫全。
- **`fir_fs` 是整件事的未知数**：12.5 ns 是 sub-7 GHz WiFi PA 的时间常数原样搬过来。没有 60 GHz PA 记忆时间常数的出处，查到之前这张表只能读趋势。
- **预设回退上 wifitrx 的 DPD 步能拿回多少**：示例 07 的 Rapp 行，回退 7.5 dB，K = 4 / 8 / 32 上关 / 开是 −21.1 / −21.8、−21.5 / −21.5、−21.8 / −23.9 dB（TX 单独），拿回 0.7 / 0.0 / 2.1 dB；DPD 步自己的读数 −22.8 / −21.8 / −23.3 dB。示例 09 §4（K = 8、11ac 20 MHz 基准）同样：7.5 dB 上拿回 0.0 dB，8 dB 上 2.0 dB。工作点规则选出的点正好在 DPD 崖的近侧。
  （2026-11-13 回退改成 7.5 dB 之前，8 dB：−21.9 / −22.9、−22.3 / −23.4、−22.6 / −25.4 dB，拿回 1.0–2.8 dB。2026-11-12 预设换成测量的 PA 之前：11ad 形状的 Rapp，−18.6 / −18.9、−18.9 / −18.9、−19.0 / −22.4，K ≤ 8 几乎拿不回东西；原因是那颗的 P1dB 在 Psat 下 9.5 dB，回退 8 dB 时已在 P1dB 之上，见 C10。）
  同台表计了 DPD 的功耗、底板用的是未预失真的 Rapp。在 7.5 dB 上 K ≤ 8 又回到“付了钱没拿到线性度”；K = 32 拿到 2 dB，但底板仍没有算进它。待做：工作点规则要不要把 DPD 算进去（按“发射机 DPD 后刚好 −21 dB”取点，要先知道 wifitrx 的 DPD 为什么在这里断崖，见本节第一条）。

### C9. 前端三个面（示例 08）发现的（见 `cairn/LOG.md` 2026-11-12 两条、`cairn/topology-b.md` §5）
- **还有三条文献数字没读到原文**：`python -c "from mmw60 import spec; print(len(spec.unverified()))"` 是 42（D4 前 48，D4 后 51；2026-11-13 spec_sources 0.3.0 把 TGad 评估方法学的 9 条读成原文，降到 42）。读过原文、已是 `spec` 的五条：`rx60.comm_asada2011`、`rx60.radar_iwr6843`、`rx60.radar_iwr6843_fig7_2`（读图）、`isolation.tx_rx_tue2018`（只读了摘要）、`dmg.rx_max_input_dbm`。没读到的三条：`rx60.comm_iscas2015`、`antenna60.okada2013_dbi`（都在 IEEE Xplore，对脚本访问返回空页，没有去绕）、`dmg.sensitivity_assumptions`（802.11 条文）。都只作灵敏度档，基准档不用它们。原来的第四条（“Infineon AN600”的天线增益）已删：提供方读了原文后撤回，那份文件里没有这组数。
- **最大输入电平 −33 dBm 是 2012 年版的写法**：ITU-R M.2003 (03/2012) §2.4.6 是 −33 dBm；现行版 M.2003-2 (01/2018) 同一节改成接收天线处 10 µW/cm²。按 60.48 GHz 换算是 −37.1 dBm（0 dBi）/ −35.1 dBm（2 dBi）/ −31.1 dBm（6 dBi）。示例 08 §3 那一列还按 −33 dBm 画；要不要改成按天线增益换算的功率密度线，待定。
- **预设还在用 WiFi 7 的梯子**：换成查到的前端后，SNR 轴上的链路 EVM 不动（示例 08 §2，五档 NF 的散布 0.00 dB），动的是灵敏度（dB 对 dB），校准表几乎不动：K = 8 的回环 EVM −22.1 → −22.0 dB，NF 取 12 dB 时 −21.3 dB。校准落在预设工作点（PA 单独 −21 dB）上，回环被发射侧限住，接收 NF 的分量看不太出来。（2026-11-13 之前校准跑在 wifitrx 的默认驱动上，回退 6.9 dB：−21.0 → −20.9、NF 12 dB 时 −20.4 dB。2026-11-12 预设换成测量的 PA 之前，回退 10.7 dB：−29.0 → −27.9、NF 12 dB 时 −23.5 dB，那时回环是接收侧有分量的。）示例 03 的最终 EVM 仍是带着 3.5 dB 的接收机读的。要不要把预设换过去（示例 03 / 06 / 07 的数字会动），待定。
- **梯子的形状是假设**：原文只给高 / 低两档（变频增益 27 / 17 dB）和一个 NF 上界、一个 IIP3（没说哪一档），其余档位是 wifitrx 梯子整体平移（`assumed.rx60_ladder_shape`）。wifitrx 梯子的调节范围 42 dB，Asada 的接收机 10 dB、雷达芯片 18 dB。增益取 27 dB 后，灵敏度电平上基带 VGA 顶在 40 dB 的上限（ADC 输入比目标低约 7.5 dB），SNR 2 / 10 / 30 dB 上的链路 EVM 与 37 dB 时相同；增益再低到 17 dB，SNR 30 dB 上差 0.18 dB。查到的 IIP3（−20 dBm）与 wifitrx 顶档恰好相同，所以压缩这个面眼下和预设没有差别。
- **“校准读到的 RX NF”对换档电平很敏感**：回环电平正好落在第 1、2 档的换档点附近。换档电平按 wifitrx 的平衡点规则随 NF 移动 ΔNF / 3，换 PA 后回环电平也变了：现在 NF 6.1 dB 那一行读 13.4 dB、预设读 11.1 dB，顺序正常（2026-11-13 改在预设工作点上校准之前 13.5 / 11.2 dB）。（2026-11-12 预设换成测量的 PA 之前：NF 6.1 dB 那一行落在第 1 档、读 9.6 dB，比预设的 10.8 dB 还低。）读这一列时仍要连着档位读：回环电平一挪，档位就可能跳。
- **通信前端吃不吃得下雷达的泄漏，现有出处答不了**：压缩点是两个量。雷达的泄漏碰到的是基带高通之前的（带外），读过的通信文献只给带内的（IIP3）。`python examples/08_frontend_faces.py` §3：PA 输出 7.1 dBm、隔离 20 dB 时泄漏 −12.9 dBm；对通信前端的带内 P1dB（−29.6 dBm）余量 −16.7 dB，这是全双工的读法；带外那一列是“未指定”。雷达芯片两个量都有（带外 −12 dBm，带内 −24 … −42 dBm），隔离 20 dB 时带外余量 +0.9 dB。（2026-11-13 回退改成 7.5 dB 之前：PA 输出 6.6 dBm，泄漏 −13.4 dBm，余量 −16.2 / +1.4 dB。2026-11-12 预设换成测量的 PA 之前：PA 输出 7 dBm，泄漏 −13 dBm，余量 −16.6 / +1 dB。）要补就得找一篇给带外压缩点或逐级线性度的 60 GHz 通信接收机文献。时分双工链路收发不同时，本库的链路仿真不注入泄漏。隔离度 20 / 25 dB 是摘要里两个数减出来的；对方读正文是 21–27 dB（仿真）/ 21–28 dB（天线级实测），本库没读到正文。
- **查到的前端不在数值指纹里**：`tools/fingerprint.py` 只跑 `configs/*.yaml`。加一份配置会改指纹文件，要用一次逃生口；现在由 `tests/test_frontend_faces.py` 守着。

### C10. PA 对照原文（示例 09）发现的（见 `cairn/LOG.md` 2026-11-12、2026-11-13，`cairn/comparison-table.md` §8）
（形状与回退两件已做：2026-11-12 预设换成测量的 PA；2026-11-13 回退按工作点规则取从 Psat 7.5 dB，`assumed.pa60_operating_rule`。下面是剩下的。）
- **工作点规则的 −21 dB 是从幻灯片上读的**：`pa60.wu_isscc2015` 的 TX EVM 图上标着 “IEEE802.11ad MCS12(16QAM) specification” 的 −21 dB 线，802.11ad 条文本身（DMG 发射 EVM 表）没有读。待做：读到条文后把限值改成 `spec` 条目，规则改引它。
- **规则读出来的数取决于两个没出处的选择**：`python examples/09_pa_against_the_literature.py` §2 的规则一节。同一个 −21 dB，测量形状 7.46 dB，去掉 AM/PM 7.06 dB（AM/PM 没有出处，下一条），换汇编表中位的形状（Psat − P1dB 3.3 dB）6.74 dB，11ad 形状 9.97 dB；包络的随机种子只动 0.13 dB。规则读的是 PA 单独、OFDM 样的高斯包络，读到的发射机是单载波 16-QAM（峰均比低得多），所以那篇只印证“按 EVM 限值定额定输出”这个读法，不印证 7.5 这个数。
- **TGad 原文推荐的 OFDM 回退是 8 dB**（`tgad_em.pa_backoff_recommended_db`，spec_sources 0.3.0 读原文，2026-11-13）：Liu 的 8 dB 就是它，回退也按它定义从 Psat 算。但那是配它自己那颗 PA 的（11ad 形状，P1dB 在 Psat 下 9.5 dB）：同一颗 PA 按本库的工作点规则要 10.0 dB 才到 −21 dB（示例 09 §2）。预设的 7.5 dB 是规则在测量的 PA 上的读数，与 TGad 的推荐值不同不算矛盾；要不要改成“按 TGad 推荐值、换 PA 也不动”，原文没有说推荐值依据什么。
- **规则选出的点在 DPD 的崖口**：7.5 dB 上 wifitrx 的 DPD 步在 K ≤ 8 拿回 0–0.7 dB，8 dB 上 1–2.8 dB（C8 最后一条）。规则没有把 DPD 算进去；要不要算，见 C8。
- **旧预设回退上 DPD 拿不回东西，原因是形状**：示例 09 §4，K = 8 回退 8 dB 上 wifitrx 的 DPD 步对 11ad 形状拿回 0.8 dB（−18.8 → −19.6），对测量形状（现在的预设）拿回 2.0 dB（−22.2 → −24.2）；回退 10 dB 时 4.5 / 2.6 dB。11ad 形状在 8 dB 处已在 P1dB 之上 1.5 dB。
- **AM/PM 没有出处**：三篇都不给，测量形状一档仍用 11ad 的 AM/PM。去掉 AM/PM，PA 单独的 EVM 在回退 4–12 dB 上好 0.2–0.5 dB（11ad 形状）/ 0.3–1.7 dB（测量形状），复现：`pa_isolated_evm_db(ModifiedRappPA(p=…, ampm=False), obo, "psat")` 对 `ampm=True`。AM/PM 在测量形状上分量更大，因为 AM/AM 的失真小了。它也直接进了工作点：去掉 AM/PM，规则给 7.06 dB 而不是 7.46 dB。
- **峰值 PAE**：预设现在取测量的 16.3 %（旧的假设 20 % 偏高）；同组三颗 14.3–16.3 %，汇编的中位 8.5 %。功耗列的 B 类回退规律对一颗偏乐观（P1dB 处测 7.9 %、折出 9.6 %），对另一颗偏保守（测 12.0 %、折出 11.0 %）。
- **汇编表还有 6 行是二手的**：`pa60.eumc2011_table1` 的 13 行别人的数是那篇论文转引的。2026-11-14 spec_sources 0.4.0 读了其中 7 行的原文（mmw60_trx#27），剩下 [5] [7] [8] [10] [12] [14] 只在别篇的对比表里出现过，数字相符但没逐篇读。只用来看分布。

### C11. 规范表迁到 spec_sources 时留下的（见 `cairn/LOG.md` 2026-11-13 两条、`cairn/spec-sources.md` §制度，mmw60_trx#21 / #23）
- **留在本地的 4 条 survey 不是文献**：`survey.clock_profile_wu19`、`survey.clock_profile_wu19_x10`、`survey.clock_profile_wu19_x9`（2026-11-14 加，拓扑 A 的 54.0 GHz LO）的值是本仓库 `data/clock_profiles/` 里的文件名（pll_simulator 的模型输出），`survey.dsp_ip_dpd_poly_p4` 是姊妹库 dsp_ip 的综合估计。标的是 survey，但“未核实的文献数字”这个意思对它们不成立；spec_sources 不收（`tests/test_extraction.py::MMW60_STAYS`），标签由本库定。改标签就得改键名（`survey.` 前缀），示例 04 / 06 打印这些键名，期望输出会动，所以搬家（#21）和 0.2.0 的改名（#23）都没有动它们；共享库改名用的别名机制只在它自己的表里，本地表要改名得自己留旧名的读法。复现：`python -c "from mmw60 import spec; print(sorted(spec.load_table()))"` 里的四条 `survey.`。

## D. 报回上游
本库不动这三个库；需求各开一个 issue 交给对方，对方合并后本库重新 pin 并删掉对应条目。三个库的需求登记处各不相同（wifi_trx_cal 是 `docs/backlog_zh.md`、pll_simulator 的 roadmap 是生成的不手改、PA_DPD 是 `docs/03_roadmap.md`），所以统一走 issue，不替对方改文件。
D1（wifi_trx_cal#4，非标准带宽的评分波形）、D2（pll_simulator#71，倍频器模型）、D3（PA_DPD#4 的 `fs` / `fir_fs` 与 `tap_spacing`，经 wifi_trx_cal#5 透传）都已落地并 pin 完（2026-11-11，`cairn/LOG.md`），条目已删。现在没有等上游的事。
本库在验收时报告的两件对方已经修掉并 pin 进来（wifitrx@7b8d08e）：B40（DPD 步留观测通路上最好的一轮，都不如不加就不写入）与 B41（`ScaledPA` 对带记忆的 PA 逐电平读稳态）。对方自己还开着、与本库有关但不由本库推动的：B38（非标准音计划下 TX 视图 replay 的 gap）；`run_full_cal` 仍不透传 `n_iter`。

D4（fmcw_radar 的雷达消费清单，mmw60_trx#14）已落地并由对方关闭（2026-11-12，示例 08、`cairn/topology-b.md` §5）：接收前端、收发隔离、发 / 收天线增益三个面在 `Frontend60` 上，条目已删；过程中发现的在 C9。倍频器底噪不进 `Frontend60`（雷达直接读剖面文件）。对方最后读的是来源表而不是对象：它 vendor 了 `spec.py` 与 `survey.yaml`，按条目读三条 `spec`，哪几条、改之前要做什么见 `cairn/spec-sources.md` 的“被下游消费的条目”。这三条 2026-11-13 已随迁移进了 spec_sources；fmcw_radar 也已迁完，本库那条下游守卫已删（mmw60_trx#23）。

## E. 明确不做
MAC / MLO 调度、多用户、信道模型本身（用 11ad CR 现成表）、D-band、雷达（另开 fmcw_radar）；EIRP / 谱模板只做趋势比较，不替代认证测试；不把 vendor 变成 fork。
芯片 PA 旁路链上 IIP2 校准不收敛这件不报 wifi_trx_cal（2026-11-14 用户定）：wifitrx 序列里 IIP2 耦合器衰减的 30 dB 绝对下限按 PA 电平的双音定，耦合器在 PA 前时下限顶住、`rx_iip2` 判失败（74.5 → 42.9 dBm）；链路仿真里没有阻塞信号，不进链路 EVM。发现记在 `cairn/topology-a.md` §6b，`tests/test_ifext.py::test_law4_a_bypassed_chip_pa_is_calibrated_on_its_own_chain` 守着。
示例 09 “汇编中位形状”灵敏度行按“偏置正常、60 GHz”重算中位（原 C10 末条；2026-11-14 用户定不做）：那一行的中位含 Table I 的 [1]（偏置不当）与 [11]（48 / 52 GHz），只用来看分布，说明在 `cairn/comparison-table.md` §8。

## 怎么用这份文件
改动落地后，把对应条目从这里删掉、在 `CHANGELOG.md` 里记一笔、在 `cairn/LOG.md` 顶部加一条带原始数字的记录。
分支：`main` 是默认分支；工作在 `feat/*` 分支上开 PR 合 `main`；旧分支 `ccr-65a5163d-bbo5rb` 与 `main` 同提交，不再往它推。
