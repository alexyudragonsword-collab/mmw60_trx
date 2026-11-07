# mmw60_trx 协作规则

> 本项目使用 Project Cairn：`AGENTS.md` 是规则与导航入口，`cairn/` 是项目知识/状态层。同目录 `CLAUDE.md` 只有一行 `@AGENTS.md`，使 Claude Code 读到同一份规则；Codex 直接读本文件。

## 项目一句话

60 GHz（57–71 GHz 免许可段）WiFi 收发机行为级仿真框架：拓扑 A（IF 延伸：WiFi 7 芯片原样 + 固定 LO 60 GHz 变频级）与拓扑 B（IMMW upclocking：PHY 不动、时钟 ×K，Liu 2025）在同一个 vendored wifitrx 引擎上同台可比——MCS 上限、吞吐、效率、pJ/bit、符号时长、CFO 鲁棒性。它不是 array_tx 的续集：array_tx 只在阵列层（里程碑 2）被 vendor；接收侧在姊妹库里是空白。

## Init 配置

- 毕业 provider：暂缓对接（首次毕业时再接知识库）
- 知识库索引 / 毕业目标：尚未配置

## 进入项目后的阅读顺序

1. 先读本文件（AGENTS.md）。
2. 读根目录 `ROADMAP.md`：只记没做的，每条附证据（复现方式与数字）。
3. 读 `cairn/LOG.md` 最新几条（新条目在顶部）：每轮的数字原值与被推翻的判断。
4. 按任务需要读 `cairn/` 专题文档（`upclocking.md`、`external-validation.md`、`topology-b.md`、`spec-sources.md`、`architecture-invariants.md`、`engineering-pitfalls.md`）。

## 文档职责

| 文件 | 角色 | 维护方式 |
|---|---|---|
| `AGENTS.md`（根） | 规则与导航 | 很少变，≤ 65 行 |
| `CLAUDE.md`（根） | 单行 `@AGENTS.md` 存根 | 写一次，不再改动 |
| `ROADMAP.md`（根） | 待办与优先级 | 只写没做的；完成即删除并在 LOG 记一笔；发现的问题带复现方式和数字 |
| `CHANGELOG.md`（根） | 已交付的演进 | 按里程碑追加 |
| `cairn/LOG.md` | 时间序日志 | 新条目加在顶部，每条 ≤ 20 行：数字原值、被推翻的判断、下一步 |
| `cairn/<topic>.md` | 知识专题文档（当前真相） | 就地更新；坑放正文小节并用 `contains` 标注 |
| `cairn/Reference/` | 外部原始输入（规范原文贴进来放这里） | 按需创建，只追加 |

> 工程资产（配置、规范数字表 `src/mmw60/data/spec/`、期望输出 `examples/expected/`）留在代码树里；`cairn/` 只放关于它们的知识。

## 项目铁律（每条都有测试守着；论证见 `cairn/architecture-invariants.md`）

1. **配置是唯一真值** —— `topology: if_extender | upclock_zero_if`、载频、K、基准 PHY、LO 方案、前端、信道、阵列全在一个 frozen `Mmw60Config`；示例和表单只读它，文献数字只经 `mmw60.spec` 进来（`tests/test_laws.py::test_law1_*`）。
2. **两条拓扑公平可比** —— 60 GHz 前端、LO 链、信道、EIRP 限值是同一个对象实例；毫米波级的插入点显式（A 在 wifitrx 的 RF 之后，B 替换它的 RF）；只对一条拓扑建的损伤在同台表里标出来。里程碑 0 的锚：K = 1 行就是未改动的 wifitrx 链（`test_law2_k1_chain_is_the_unmodified_wifitrx_chain`）；完整测试在里程碑 1（ROADMAP）。
3. **CFO 端到端建模** —— (ppm_tx + ppm_rx) × f_c，每条拓扑声明自己怎么接住它：B 靠大 SCS 与 L-STF/L-LTF 估计，A 靠 MLO sub-7 估计乘频率比预补偿 + 残差；ppm = 0 时该项逐位为零（`test_law3_*`）。
4. **校准是跑出来的，不是假设的** —— wifitrx 校准序列（`cal/deps.py` 顺序约束）在两条拓扑上都真跑，每步在毫米波级的结果进表；不许手填"已校准"（里程碑 1；锚 `test_law4_*`）。
5. **规范和文献数字只用原文** —— 全部在 `data/spec/survey.yaml`，`source: spec | survey | assumed | derived`；拿不到原文的标 survey 并注明出处，原文没说的标 assumed；`grep -c "source: survey"` 一次列全（`tests/test_spec_sources.py`）。
6. **杂散结论只能来自逐周期引擎** —— 本库是线性化的时域基带引擎，每个示例第一行打印引擎名，凡杂散 / 互调结论标"线性化引擎，不能背书"（`test_law6_*`）。
7. **数值指纹** —— 重构必须用 `tools/fingerprint.py` 证明逐位不变；CI 比较 base 与 head，`(numbers-move)` 标记是逃生口（`tests/test_fingerprint.py`）。

## 本仓库特有的硬规矩

- **`src/mmw60/vendor/` 是可校验的改编副本，不是 fork**：wifitrx 整包按完整 SHA pin，`tools/vendor_check.py --strict` 必须全 verbatim；需要上游改的（倍频器模型、PA 带宽项、两 DUT 级联）报回各自 ROADMAP，合并后重新 pin。PA_DPD 经 wifitrx / polar_tx 的 vendor 副本拿，不要第二份 pin。
- **numba 是性能层不是正确性层**：`MMW60_NO_JIT=1` 必须逐位相同（`tests/test_phy.py`）。
- **假设要可见**：原文没说的每个选择（基准带宽、SNR 口径、相噪加在哪一侧、CR 信道、OBO 参考点、信道估计平滑）都是 `source: assumed` 条目，示例里有对应的灵敏度行；对不上文献时查到原因写进 LOG，不调参数凑。
- 开发在指定分支上提交；不开 PR 除非用户要求。

## 冲突仲裁

- 优先级：**代码与实测数字 > 知识专题文档 > LOG 历史**；规则层面的冲突由本文件裁定。

## 知识沉淀规则

- 每次实质性推进后，在 `cairn/LOG.md` 顶部加一条（摘要+指针）；结论沉淀进 `cairn/` 专题文档。修正过去的判断时追加更正说明，不要静默覆盖。
- 每个里程碑结束：CHANGELOG 一条、LOG 一条、ROADMAP 删掉做完的条目并加上过程中发现的问题（带复现方式和数字）。
