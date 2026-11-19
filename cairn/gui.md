---
type: project_topic
status: active
summary: "图形界面：形态（结果浏览 + 后台重算）、四层分工、计算层 guiutil（study / part / 签名 / 新鲜度 / 报告 / run_job）、依赖表怎么由追踪守住、结果仓库与随包基线、宿主与队列、页面的规矩、做页面查出来的接口问题"
tags: [mmw60, gui, guiutil, guispec, guistore, webhost, webui, freshness]
contains: [decision, lesson, pitfall]
created: "2026-11-19"
updated: "2026-11-19"
related: [comparison-table.md, topology-a.md, topology-b.md, array-layer.md, ay.md, architecture-invariants.md]
authoring_mode: ai_generated
---

# 图形界面

做法照 polar_tx（`cairn/gui-redesign.md`）与 array_tx（`cairn/gui.md`）：一份网页界面，桌面应用窗口、浏览器、Android WebView 三个宿主共用；
分层是 **描述（`guispec`）/ 计算（`guiutil`）/ 存（`guistore`）/ 分发与队列（`webhost`、`appbridge`）/ 画（`webui/www`）**。页面只画不算。

## 1. 形态：结果浏览，不是实时工作台（用户 2026-11-18 定）

本库和那两个库不一样的地方：单次运行慢（校准一遍几分钟，示例 10 约半小时），主要产出是表而不是图。
（更正，2026-11-19：“校准一遍几分钟”说的是示例 03 整个脚本，809 s；六列校准这个任务本身实测 42 s。形态的理由仍成立——阵列 560–1650 s、SC 对 OFDM 224–563 s、同台表 106 s——但校准不是慢的那一个。任务自己的耗时在 `guiutil.JOBS`。）所以首页是**算好的**同台表，
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

### 2e. 一个任务产出什么：`run_job`（2026-11-19 页面那一轮）

`run_job(job, study, quick=, progress=, calibration=)` 是“一个任务算什么”的唯一定义，命令行（`tools/gui_report.py`）和宿主的队列都只调它，返回 `job_result`。
进度统一成 `progress(done, total, text)`：同台表按行、校准按步（一列的步数是 wifitrx 的，第一列跑完才知道 total）、阵列与 SC 对 OFDM 按节。

**一份结果建在哪份上游上，要照实记**（这一轮改的；上一轮写错了）：`job_result(..., built_on={上游 part: 那份上游结果的 study})`，没写的上游就是预设的那份已验收结果
（门限永远是；没给校准结果的同台表查的是已验收的 IRR 表）。上一轮 `envelope` 把上游一律记成“本 study 的签名”——改了回退、没重做校准就算的同台表，
等校准重做之后会被判成新鲜，而它的 IRR 其实还是预设那份。现在它记的是预设的签名，校准重做之后仍然过期，直到在新校准上重算（`tests/test_guistore.py::test_a_result_records_*`）。
`run_job` 只在给它的校准结果与本 study 的校准签名相同、且不是试算规模时才用它，并写进 `built_on`。

### 2f. 示例 10、15 改成“先出数据、再印”（2026-11-19）

两个示例原来边算边印。`src/mmw60/arrayreport.py::build` 与 `src/mmw60/ay/report.py::build` 现在返回示例印的每一个数（全精度、可 JSON），示例只做格式化；
`build` 收前端和配置作参数（默认值就是示例原来建的），所以界面能把 study 套上去再跑。两份都由子代理在独立工作树里改，验收是输出逐字节不变：
快跑前后对比只差计时那一行；完整重跑与 `examples/expected` 一致（示例 10 560 s、示例 15 443 s；并入本分支后示例 10 又独立重跑一遍，567 s，一致）。指纹逐位相同。

过程中看到、没有动的（动了要改已验收的文本）：**示例 15 §3 的标题写“payload π/2-64-QAM for SC”，实际 SC 的预设是 MCS16，π/2-16-QAM**（`ay.report.PRESET_MCS`；
同一个 PA 单独读数 −28.4 dB 在示例 10 §3d 里标的就是“16-QAM payload”）。数没有错，标题错了；记在 ROADMAP 里程碑 3。

## 3. 结果放哪：`src/mmw60/guistore.py`（2026-11-19）

`guiutil` 不落盘，宿主只排队，`guistore.Store` 保管算出来的 `job_result`。两处：

- **随包的基线**（`src/mmw60/data/gui/baseline/<job>.json`，四份：`table` / `calibration_be` / `array` / `ay`）：四个任务在预设上按完整规模跑出来的结果，
  所以页面一打开就有同台表，不用现算。它是**代码生成的数据**（`python tools/gui_baseline.py build`，或 `import DIR` 收 `gui_report.py --json` 写的文件），不手改。
- **用户的结果**（`<home>/results/<job>-<key>.json`；`home` = `MMW60_HOME`，否则用户缓存目录下的 `mmw60/`）：队列为别的 study 算出来的。键是任务、study、`built_on` 和是否试算的哈希——同一个任务对同一个 study 再跑一遍就是替换自己。
  `home=None` 的仓库只放内存（测试、只读安装）。

**页面画哪一份**只有一条规则（`Store.pick(report, study)`）：自己读的旋钮仍与 study 一致的 part 最多的那份，其次新鲜的 part 多的，其次完整运行先于只算一部分的，其次新的先于旧的。
所以表单往前走了，页面继续显示最近算的那份（由 `freshness` 标过期），不会空掉；回到预设，基线又是新鲜的。试算规模（`quick`）的结果存着但永远不被选中。

**基线不许和代码漂开**，两层守卫（`tests/test_guistore.py`）：

- `gui_baseline.check`：缺文件、规范表摘要变了、vendored pin 变了、不是预设、是试算——都红。修法是重建，时机就是示例的期望输出重新验收的那一刻。
- 与已验收输出逐项对：阵列与 SC 对 OFDM 两份直接**把示例 10 / 15 的打印函数在基线报告上重放一遍，要求与 `examples/expected` 逐行相同**（这两个示例本来就只负责印 `build` 返回的东西，
  所以这一条守住了两页上的每一个数）；同台表逐行对示例 04 的底板、时域 EVM、两个上限、速率、pJ/bit；校准逐列逐步对示例 03 的 wifitrx 判定和读数（6 × 12 格）。

## 4. 宿主与队列：`src/mmw60/webhost.py`、`src/mmw60/appbridge.py`（2026-11-19）

照 array_tx：`Api.get / post / call(route, req) -> (code, payload)` 与传输无关，HTTP 处理器和手机桥都只是传输；`JobQueue` 两种后端——
`process`（桌面：每个任务一个 spawn 出来的子进程，取消 = terminate）与 `thread`（手机上 Chaquopy 没有多进程；取消在两个进度步之间生效，正在跑的一步要跑完）。
启动：`mmw60-gui`（或 `python -m mmw60.webhost`），标准库的 HTTP 服务挂在 127.0.0.1，桌面开 Chromium 系浏览器的 `--app` 窗口，关窗即停。

路由（POST 要带 `X-MMW60: 1`，别的来源的页面加不上这个头）：`version`、`sources`、`parts`、`jobs`、`jobs/<id>`、`results`（GET）；
`state {study?}`、`report {report, study}`、`row {label, study}`、`system {study}`、`run {job, study}`、`jobs/<id>/cancel`、`results/<id>/delete`（POST）。

- **study 归页面拿着**，每个请求带上；宿主只记住最后一次收到的（重新加载的页面能找回表单）。`state` 一次给全：表单、每个 part 的新鲜度、字段组的状态、每种报告显示的是哪份结果。
- **`report` 从不计算**：只把 `Store.pick` 选中的那份报告连同它的出处和新鲜度交出去；没有就给 `null` 和能算它的任务名。同台表的“距离”一列由阵列结果的 N = 1 行现取（`single_antenna_ranges`），
  SC 对 OFDM 页的“谁赢”由阵列结果的 ay 行现算（`sc_vs_ofdm_headline`）——两处都带上它们取自哪份结果，那份过期了页面要能标出来。
- **`run`**：只排四个完整任务（`RUNNABLE`；只算解析列的同台表留给命令行，理由见 §5）。同台表任务**出队时**才去找为本 study 算过的校准结果（没有就查已验收的 IRR 表），所以紧跟在校准后面排的同台表建在那份校准上；结果的 `built_on` 照实记（§2e）。任务读“完成”之前结果已经进了仓库。
- **新鲜度按仓库里真有的判**：宿主以 `freshness(..., accepted=False)` 问，任务能算的 part 没有存着的结果就是 `missing`（不是“按已验收的预设算新鲜”）；上游缺失本身不让下游过期，下游自己记的 `built_on` 说了算。
- 一个坑（测试抓到的）：任务的状态先变成“完成”、结束时间后填，页面会读到“完成但没有结束时间”。现在两者在同一把锁里一起写。

手机的应用外壳（`android/`：Gradle、Activity）这一轮没有建，见 ROADMAP F；`appbridge.call(route, args_json) -> json` 和线程队列是它将来要调的全部。

## 5. 页面：`src/mmw60/webui/www/`（2026-11-19）

十个文件、248 kB，没有构建步骤、没有外部资源：`index.html`、`style.css`、`core.js`（`api()`、状态、语言、格式化、出处标签、过期标记）、`charts.js`（内联 SVG）、
`table.js`（同台表）、`detail.js`（行细节、校准）、`pages.js`（阵列、SC 对 OFDM）、`system.js`（框图）、`runs.js`（运行台、出处、表单抽屉）、`app.js`（导航、加载、轮询）。
由一个子代理照效果图合并稿对着真实的接口样例做出来；我定接口、写测试、逐条处理它报回的接口问题。

**页面的规矩**（`tests/test_webui.py` 的四条文本规则 + 六条浏览器测试守着）：

- **只画不算**。格式化（按报告的 `display` 从全精度值舍入一次、单位前缀）、按载荷里有的字段排序筛选，算画；dB 换算、派生指标、载荷没给的排名，不算画——缺了就报回来加进计算层，不在页面里补。
- **页面里不写任何结果数字**：用户看得到的字符串里，除了标准与符号的名字（802.11ay、60 GHz、16-QAM 3/4、MCS0…），不许有数字；带数的句子从载荷拼。效果图里从文档抄来的带数结论（“53.6 dB”“高 8 %”）全部去掉了。
- **过期只标不藏**：数留着，标到列和格；横幅同时列出仍有效的；没有存着的结果就说没有、给出能算它的任务（`missing`，与过期是两回事）。
- **两种校准判定分开显示**；引擎声明一直在页面顶上；出处标签来自载荷，改过的旋钮读 assumed 并留着原来的。
- 一个 `api(route, body)`、两种传输（本机服务 / 手机桥，照 array_tx 的异步回调约定）；页面里出现的每个路由都得是宿主答的（测试用正则抽出来对）。

**做页面这件事本身查出来的**（子代理逐格核对真实载荷时报回，2026-11-19 都修了，各有测试）：

- 同台表表头的接收前端三个数是空的（框图的 LNA 块同样）：`front_end_report` 向 `faces()` 要了它没有的键。上一轮的测试只看了“有这个字段”。现在读 27 dB / 6.1 dB / −20 dBm。
- 表单里载频的“预设值”跟着 study 变（横幅读成“62.64 → 62.64 GHz”）。
- `freshness` 从不说“缺失”：仓库是空的时候每个 part 都读新鲜（按已验收的预设判），而页面根本没有数可画。宿主现在以 `accepted=False` 问。
- 紧跟在校准后面排队的同台表没建在那份校准上（提交时就查了校准）；改成任务出队时才查。
- 只算解析列的同台表存在完整的旁边，会因为“有一个 part 新鲜”被选中，时域列和 ay 两行从页面上消失。宿主改成只排四个完整任务，解析列预览留给命令行。
- 页面自己定了“EVM 分项低于 −200 dB 算没有”，还从指标名的后缀读校准读数的单位。两样都改成随载荷给（`absent_below_db` = 示例 04 印横线的 −150 dB；每格带 `unit`）。

**合并稿里没搬过来的**（没有载荷支撑，或要页面自己算）：同台表的“哪些猜测改变排名”与三种本振模型并排；行细节里分项的功率占比条（要 dB → 线性）；
SC 对 OFDM 页逐项的胜负表、“对最好的 be 行”“没成立的预期”（都是带数的文档文字）；阵列页在 EIRP 上限起作用处的合成点；ay 行在框图上点亮哪些块（`evm_term_to_block` 只有 be 的分项）。
要补的话先在计算层出数据（ROADMAP F）。

**没有验证的**：`window.host` 那条传输（代码照约定写了，没有外壳能跑）；除 Chromium 之外的浏览器（CSS 用了 container query 和 `color-mix`）；页面上取消一个正在跑的任务、失败任务的报错卡。

## 6. 效果图阶段留下的教训

- **数据说明也是会错的**：我写“校准表的 ok / degraded 是 wifitrx 自己的判定”，对逐列清单成立，对汇总表不成立；两份效果图各有一处照着写错。现在两种判定是两个字段。
- **依赖表不能靠读代码**：见 §2b，解析列读信道那一处当时写反了。
- **框图的事实漏了拓扑 A 的升频**（用户指出）：第一遍“时钟 × K”只画在拓扑 B 上。现在 `upclock_scope` 明说两条拓扑各走到哪。
- 页面上的数与数据逐个核对只证明“数在数据里”，不证明“放对了格”；位置要靠抽看。
