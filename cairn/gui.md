---
type: project_topic
status: active
summary: "图形界面：形态（结果浏览 + 后台重算）、四层分工、计算层 guiutil 的数据接口（study / part / 签名 / 新鲜度 / 报告）、依赖表怎么由追踪守住、效果图阶段的决定与踩过的坑"
tags: [mmw60, gui, guiutil, guispec, freshness]
contains: [decision, lesson, pitfall]
created: "2026-11-19"
updated: "2026-11-19"
related: [comparison-table.md, topology-a.md, topology-b.md, array-layer.md, ay.md, architecture-invariants.md]
authoring_mode: ai_generated
---

# 图形界面

做法照 polar_tx（`cairn/gui-redesign.md`）与 array_tx（`cairn/gui.md`）：一份网页界面，桌面应用窗口、浏览器、Android WebView 三个宿主共用；
分层是 **描述（`guispec`）/ 计算（`guiutil`）/ 分发与队列（宿主，未建）/ 画（页面，未建）**。页面只画不算。

## 1. 形态：结果浏览，不是实时工作台（用户 2026-11-18 定）

本库和那两个库不一样的地方：单次运行慢（校准一遍几分钟，示例 10 约半小时），主要产出是表而不是图。所以首页是**算好的**同台表，
点进去看细节，重算走后台队列；改了参数不清空旧数，只标过期。

效果图阶段（2026-11-18 / 19，PR #81，没有界面代码）：两个子代理按同一份简报各出一份，用户选了方案 A 的风格，并入方案 B 的九处做法，
加一屏系统框图。三个私有页面的链接在 `LOG.md` 2026-11-18 / 19 两条里。定下来的界面要素：

- 同台表：一次突出一个指标（速率 / 距离 / pJ/bit），行首用形状标口径（链上实测 / 芯片残差实测 + 解析和 / 解析和 + IRR 查表），
  每行直接显示时域交叉核对，筛选（全部 / 拓扑 A / 拓扑 B / 802.11ay / 6 GHz 参考）；
- 过期标到列和格，过期条同时列“仍有效”的；运行台有“结果 × 旋钮”的点阵和依赖链；
- 行细节：EVM 分项、校准 12 步（两种判定都显示）、12 × 6 状态矩阵、功耗分块、可复现卡；
- 阵列页、SC 对 OFDM 页（先结论与前提，后支撑数据）；
- 系统框图：两条拓扑同图，共用的 60 GHz 前端只画一次；“× K 时钟域”画成范围——拓扑 B 罩到 DAC / ADC，拓扑 A 只罩芯片的数字基带；
  选中一行，贡献 EVM 分项的块点亮；
- 手机宽度：宽表变排名卡，底部导航。

## 2. 计算层 `src/mmw60/guiutil.py`（2026-11-19）

只返回能直接 `json.dumps` 的字典；不画、不排队、不落盘。命令行 `tools/gui_report.py` 读的是同一批函数。

### 2a. study：表单就是一组“与预设不同的共享旋钮”

`guispec` 的 22 个旋钮分两类（`ROW_KNOBS` / `SHARED_KNOBS`）：

- **行旋钮 4 个**（拓扑、波形、K、MCS）：同台表本身就跨着它们，它们只用来选哪一行，从不让结果过期；
- **共享旋钮 18 个**（载频、晶振、包长、本振 5 个、PA 3 个、信道 2 个、接收机 4 个）：一组取值就是一个 study，对同台表的**每一行**同时生效
  （`schemes(study)` = `compare.default_matrix` 的每个预设再套 `guispec.set_path`），共用的那个 `Frontend60` 也由它建（`frontend(study)`，铁律 2）。
  `study({})` 就是预设，也就是已验收的结果。等于预设的取值会被丢掉（7.5 dB 的回退不是一次改动）。
- 载频经矩阵的参数进去（行的名字里带载频）；6 GHz 的 K = 1 参考行不跟着改。
- **缺口**：表单里没有基准 PHY（标准、基准带宽）的旋钮，所以 22 个旋钮指不全 21 行；页面按行的名字选行。要不要给 `guispec` 加这两个旋钮，留给页面那一轮（ROADMAP）。

出处标签（铁律 5）：`KNOB_SOURCE` 记每个共享旋钮预设值背后的规范表条目，测试核对两者相等；`knob_tag` 在取值被 study 改掉之后返回 `assumed`，并留着原来的标签（`was`）。

### 2b. part：结果按“读哪些旋钮”拆开，依赖表由追踪守着

一份结果不是一个整体。`PARTS` 里每个 part 声明它读的共享旋钮（`reads`）和它建在哪些 part 之上（`upstream`）：

| part | 读（共享旋钮） | 上游 | 谁算 |
|---|---|---|---|
| `calibration.be` | 载频、本振 5 个、PA 3 个（就是建 `Frontend60` 读的那些） | — | `calibration_be` |
| `table.analytic` | 除包长、平滑跨度自动选、固定跨度、CPE 窗口之外的全部 | `calibration.be`、`thresholds.be` | `table` / `table_analytic` |
| `table.td` | 全部 | — | `table` |
| `table.ay` | 除包长、两个平滑旋钮之外的全部 | — | `table` |
| `array` | 除两个平滑旋钮、两个信道旋钮之外的全部 | `thresholds.be`、`thresholds.ay` | `array` |
| `ay` | 除包长之外的全部（多径一节读信道） | `thresholds.be`、`thresholds.ay` | `ay` |
| `thresholds.be` | 接收机 4 个、包长 | — | 不在这里重算（`tools/measure_thresholds.py`，几小时） |
| `thresholds.ay` | 包长、信道 2 个 | — | 同上（`tools/measure_ay_thresholds.py`） |

**这张表不是读代码读出来的，是量出来的**：`tests/config_trace.py` 在配置的各个 dataclass 上挂 `__getattribute__`，记下一次计算实际读了哪些字段；
`tests/test_guiutil.py::test_parts_declare_*` 对每个 part 跑一遍，要求“追踪到的 ⊆ 声明的”。危险的方向只有一个——代码读了、声明里没有，过期的数就会被当成新鲜的——这个方向由测试挡住；
声明多了只是多重算一次。反方向另有一条（`test_a_knob_a_part_does_not_read_leaves_its_numbers_alone`）：没声明的旋钮拨一下，数字逐位不变。

追踪推翻的一处（效果图阶段我按读代码写的依赖表）：**同台表的解析列读信道**（GI 之外的 ISI 一项用 rms 时延），也读 CFO 估计方式和晶振；当时写的是“不读信道”。

追踪的三个坑：

- `dataclasses.replace`、`to_dict()`、`describe()` 会把整个对象的字段读一遍，追踪就成了“全读”。所以预设要在追踪块**外面**建好；`compare.row_dict` 里原来的 `dc.asdict(row)` 连带走了 `scheme.cfg`，为此改成先换掉 scheme 再转（数字不变）。
- 条件读：`rx.ce_smooth_tones` 只在自动选关掉时才读。预设下追踪不到，所以声明取保守的一侧（时域列读全部），不照追踪结果抄。
- 整张同台表当一个任务追踪时“几乎全读”，因为拓扑 A 的行建链就要跑芯片校准；按 part 分开追踪才有信息量。

### 2c. 签名、信封、新鲜度

- `signature(part, study)` = study 里该 part 读的那几个旋钮的取值的哈希。两个 study 签名相同，这个 part 的数就相同（在同一个代码版本上；版本记在出处里）。
- `envelope(part, study, payload)` / `job_result(job, study, report)`：一次计算的结果连同它读了什么（签名、上游的签名）和在哪算的（`provenance()`：版本、提交、vendored 库的版本与 pin、规范表文件的摘要、引擎声明）。
- `freshness(study, envelopes)`：逐 part 给 `fresh / stale`，带“是哪个旋钮动了它”（`changed`）和“哪个上游过期”（`upstream`）。没有信封的 part 按已验收的预设结果判：study 没动它读的旋钮就是新鲜的；
  两份解码门限永远这样判（这一层不重算它们，只给出重量的命令）。信封里记着上游的签名：校准重做之后，建在旧校准上的同台表仍是过期的。
- `field_states`：把过期落到同台表的字段组上（`BE_FIELDS`）。解析列自己的旋钮没动、只是门限过期时，过期的只有解码器上限那几列；校准过期时只有“校准后”那几列。

例（`python tools/gui_report.py freshness --set rx.cpe_window_symbols=33`）：时域列、ay 两行、be 门限过期；解析列里只有解码器上限那一组过期；校准不动。

### 2d. 报告

- `table_report(study, time_domain=, labels=, irr_table=)`：就是 `compare.build`，行保持 `compare` 自己的字段名（“界面画的是同一批字典”），另加口径类别 `footing`、配置哈希、种子、交叉核对。
  数字给全精度，`display` 给每个字段在已验收输出里的小数位——页面从全精度值舍入一次，就是示例印的那个数（效果图阶段的教训：先舍到两位再舍到一位，会和原输出差 0.1）。
  `irr_table` 接一份校准结果的 IRR；不给就用已验收的 `derived.irr_after_cal_measured_db`（它属于预设，study 离开预设时 `freshness` 会说）。
- `calibration_report(study, plan=)`：按示例 03 的做法真跑 wifitrx 的序列（铁律 4）。**两种判定分开**：`status_wifitrx` 是 wifitrx 自己的；`status_summary` 是示例 03 汇总表的——
  `calcheck.compare_runs` 把比第一列差 3 dB 以上的 ok 也记成 degraded，那是本库的规则。`irr_after_cal_db` 取 tx_iq / rx_iq 两步的较小值（`calcheck.irr_after_cal`），K = 1 / 4 两列算出来 53.6 / 53.8 dB，就是已验收的表。
- `row_detail(table, label, calibration)`：一行的数、在它自己的链上跑过的校准列（零中频 be 行才可能有）、IRR 查的是哪一列、可复现卡。
- `array_report(study)`：就是 `arrayreport.build`（示例 10 的每一个数；2026-11-19 起示例只负责印），跑在 study 的前端和方案上；另给每个方案对应同台表的哪一行（`table_row_of`）
  和 EIRP 上限从多少个单元起作用（`eirp_limit`：预设回退下 36，按真实阵列增益搜出来的，和示例一样）。阵列链路是视距、平坦信道，表单的信道旋钮不进来（`array_inputs`），多径只经存着的 ay 门限。
  `single_antenna_ranges(array)` 把 N = 1 的行并到同台表的行上——同台表的“距离”一列只有阵列报告带的那几行有。
- `ay_report(study)`：就是 `ay.report.build`（示例 15 的每一个数）。`sc_vs_ofdm_headline(array)`：**谁赢、赢多少由阵列报告的 ay 行算出来，不抄文档**——
  同调制同码率（16-QAM 3/4）与各取解码器上限两组的速率 × 距离，以及 SC 对 OFDM 的乘积优势；用已验收的 N = 64 行算出来是 8 % 与 9 %，就是 `cairn/ay.md` 开头的两个数。前提和被推翻的预期是文字，留给页面。
- `system_report(study)`：系统框图的事实。结构和文字在 `src/mmw60/data/gui/system.yaml`（跟着 vendored wifitrx 的 `TxChain` / `RxChain` 顺序和 `ifext` / `frontend` / `arraylink`），
  **那个文件里不写数**：每个参数只写它从哪来（`spec:` 规范表条目，`v:` 由 study 的前端 / 配置读出的量，`text:` 文字），由 `guiutil` 解析；测试守着“不写数”。
  拓扑 A 升频的四行、越界的一行、同一个带宽的三种做法都从矩阵里筛出来，不是手写的名单。
- `form(study)`、`sources()`、`freshness_matrix()`：表单、规范表条目、part × 旋钮的点阵。

### 2e. 没做的（见 ROADMAP）

宿主与队列、结果存在哪、要不要随包带一份预设的基线结果、页面本身。

### 2f. 示例 10、15 改成“先出数据、再印”（2026-11-19）

两个示例原来边算边印。`src/mmw60/arrayreport.py::build` 与 `src/mmw60/ay/report.py::build` 现在返回示例印的每一个数（全精度、可 JSON），示例只做格式化；
`build` 收前端和配置作参数（默认值就是示例原来建的），所以界面能把 study 套上去再跑。两份都由子代理在独立工作树里改，验收是输出逐字节不变：
快跑前后对比只差计时那一行；完整重跑与 `examples/expected` 一致（示例 10 560 s、示例 15 443 s；并入本分支后示例 10 又独立重跑一遍，567 s，一致）。指纹逐位相同。

过程中看到、没有动的（动了要改已验收的文本）：**示例 15 §3 的标题写“payload π/2-64-QAM for SC”，实际 SC 的预设是 MCS16，π/2-16-QAM**（`ay.report.PRESET_MCS`；
同一个 PA 单独读数 −28.4 dB 在示例 10 §3d 里标的就是“16-QAM payload”）。数没有错，标题错了；记在 ROADMAP 里程碑 3。

## 3. 效果图阶段留下的教训

- **数据说明也是会错的**：我写“校准表的 ok / degraded 是 wifitrx 自己的判定”，对逐列清单成立，对汇总表不成立；两份效果图各有一处照着写错。现在两种判定是两个字段。
- **依赖表不能靠读代码**：见 §2b，解析列读信道那一处当时写反了。
- **框图的事实漏了拓扑 A 的升频**（用户指出）：第一遍“时钟 × K”只画在拓扑 B 上。现在 `upclock_scope` 明说两条拓扑各走到哪。
- 页面上的数与数据逐个核对只证明“数在数据里”，不证明“放对了格”；位置要靠抽看。
