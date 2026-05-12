# 回顾 — v4.2.0

> English version: [retrospective-v4.2.md](retrospective-v4.2.md)
>
> v4.2 分四个 alpha 落地：信息结构重整（a1）、报告导出基础设施（a2）、
> 冷启动引导（a3），加上最先到位的向量后端改造（a0）。总计 559 条测试
> 全绿、ruff 无告警、从 v4.1 升级到 v4.2 的数据库迁移跑通。

---

## 交付内容

### a0 — 向量后端 + 向导打磨

- `OpenAIEmbedder` 现在接受任何 OpenAI 兼容端点的 `base_url`（通过构
  造函数参数或 `RESEARCH_AGENT_EMBED_BASE_URL`）。向量维度从首次响应
  里自动探测，不再写死。阿里云 DashScope、Jina、Voyage、智谱 GLM 和
  openai.com 默认都走同一套代码路径。
- 默认本地模型升级到 `Qwen/Qwen3-Embedding-0.6B`，支持多语言。想用
  更小的英文模型，可以通过 `RESEARCH_AGENT_EMBED_MODEL` 把
  `all-MiniLM-L6-v2` 指定回去。
- `prv_corpus_keywords` 新增 `embedding_model TEXT` 列（schema_version
  4 → 5）。检索按完整的 `(embed_backend, embedding_model, embed_dim)`
  三元组过滤，跨模型混用会给出明确的重建索引提示。
- 新增 `reindex_corpus` MCP 工具 + `scripts/reindex_proof_corpus.py`
  CLI，切换后端或模型后用来重新编码已有语料。
- 设置向导新增了服务商预设菜单（OpenAI / DashScope / Jina / Voyage
  / GLM / 其他），结束时主动问是否打开首任务教程；选了需要从
  Hugging Face 下载的模型时还会提示 `HF_ENDPOINT` 镜像。
- ADR 0010 记录了多服务商决策。

### a1 — 仪表盘信息结构重整

- 标签页分成跨主干 / 实验 / 证明三组。`f` 在当前组内循环；新增 `N`
  跳到下一组的第一个标签页。标签页上方加了分组标签条，标记当前组。
- 详情面板改在 Textual `Collapsible` 之上重写。五个分节（概览、BT
  强度、子节点、跨主干边、关联失败——a2 又加了报告）可以独立折叠和展
  开；状态记在 `CockpitSettings.detail_section_collapsed` 里。
- 快捷键改为面板级作用域：`w`（仅事件面板）切换自动换行；`i`（仅树
  面板）切换紧凑模式。之前的 App 级优先键位已经移除——在树面板按 `w`
  现在不会有反应，这是有意的。
- `docs/cockpit-keys.md` 是新的键位规范文档。

### a2 — 报告导出基础设施

- 新增 `cockpit.export` 模块，三层结构：DTO（读 SQLite，输出数据类）、
  渲染器（生成 markdown 或 HTML 字符串）、管线（组合前两层 + 写文件
  + 建索引）。5 种报告（closure / draft / diagnostic / portfolio
  / cascade）× 2 种格式（markdown / html）。ADR 0009 记录了"把报告
  写成文件"的决策。
- `cockpit_reports` 表（schema v1 → v2）按 `(file_path, kind,
  related_node_id, format, bytes, generated_by, generated_at)`
  索引每份生成的文件。cockpit 新增 Reports 标签页（在跨主干分组里）
  从这张表读取。
- 在节点上按 `e` 打开导出弹窗——选报告类型（自动过滤到当前节点适用
  的）、选格式（`m` / `h` / `b`），按 Enter 提交。管线跑完，文件写
  好，用户看到通知提示结果。
- `python -m cockpit.export` 把同一条管线暴露给命令行。
- `verify_mcp.export_report` 是给 reviewer agent（和写作流程）调用同
  一条管线的轻量门面，不需要导入 cockpit 模块。reviewer.md 增加了
  "可选附上结题报告"的步骤——**不**改动 ADR 0006 / 0008 的硬性规则。
- 生成的文件通过 `os.startfile` / `open` / `xdg-open` 调用用户的默认
  程序打开。cockpit 自身不内嵌 markdown / HTML 渲染器。

### a3 — 冷启动 Welcome

- 新增 `WelcomeScreen`：当 `state.db` 为空且
  `CockpitSettings.welcome_shown` 为 False 时显示一次。按 Enter 继续、
  按 `?` 打开首任务教程、按 `q` 退出。
- `RESEARCH_AGENT_COCKPIT_WELCOME=0` 可以关掉 Welcome 屏——给测试和
  熟练用户用。conftest 默认开启这个开关，防止 pilot 测试被叠在最上面
  的 Welcome 屏截获按键。

---

## 数据汇总

| 指标 | v4.1.0a6 | v4.2.0 | Δ |
|---|---|---|---|
| 测试数 | 479 | **559** | +80 |
| Cockpit 测试文件 | 12 | 18 | +6 |
| ADR 数 | 8 | 10 | +2 |
| cockpit schema 版本 | 1 | 2 | +1 |
| prove_mcp schema 版本 | 4 | 5 | +1 |
| 报告类型 | 0 | 5 | +5 |
| 文档化的嵌入服务商 | 1 (openai.com) | 5 + 其他 | +5 |
| 新增 verify_mcp 工具 | 0 | 1 (export_report) | +1 |
| 新增 prove_mcp 工具 | 0 | 2 (reindex_corpus, corpus_backend_signatures) | +2 |
| TCSS 行数 | 不变 | +14 | +14 |
| 每种语言的 i18n 条目 | ~220 | ~290 | +70 |

---

## 值得记录的设计决策

### 报告为什么不嵌进 cockpit 面板

ADR 0009 有完整理由。简单说：cockpit 擅长展示实时状态，但长草稿、并
排对比集、级联跟踪这类文档形态的内容需要真正的文档查看器。硬塞进
TUI 里是在跟终端界面的天然特点较劲。把 markdown / HTML 文件写出来、
交给用户自己的工具打开，既绕开了这个矛盾，也不需要推翻 ADR 0003。

### 为什么是 `(backend, model, dim)` 三元组

v4.1 每行关键词只存 `(embed_backend, embed_dim)` 两个字段。引入
OpenAI 兼容服务商之后，这两个字段不再唯一——比如 DashScope 的
`text-embedding-v3` 和 OpenAI 的 `text-embedding-3-small` 都是
"openai 后端 / 1024 维"，但产出的向量语义完全不同。加上模型名组成三
元组，能在检索返回乱码之前就拦住这种错配。

### 为什么面板级的 `w` / `i` 是一个实际的行为变化

开发计划里认可了这次对操作习惯的打破。从 v4.1 升上来的用户需要先切到
对应面板再按键（按 `3` 聚焦事件面板再按 `w`，按 `1` 聚焦树面板再按
`i`）。`docs/cockpit-keys.md` 和 v4.2.0 发布说明都标注了这一点。

### 为什么导出弹窗让用户选类型但格式默认 `md`

大多数导出场景面向 reviewer 或者要提交进 git。markdown 对这两种场景
都更合适。想要 HTML 按 `h`；两个都要按 `b`。默认值让最常见的情况按键
最少。

### 为什么 Welcome 屏复用了 splash 的关闭模式

v4.1.0a6 上线后，splash 的"按任意键继续"模式没收到什么投诉。复用同一
套机制（优先级键位 + on_key 兜底 + 一次性持久标记）让用户不用学第二
种关闭方式。

---

## 反思

### 做对了什么

- **四个 alpha 的节奏。** 每个 alpha 上线前都是 ruff 无告警、测试全
  绿。a0 和 a2 的 schema 升级在隔离测试里跑通，v4.1 → v4.2 整体升级
  时也顺利。
- **DTO / 渲染器 / 管线三层拆分。** 以后加一种新报告类型就是在 `dto/`
  下加一个文件加上 `BUILDERS` 加一行。加一种新格式就是一个新的渲染器
  类加上 `RENDERERS` 加一项。管线本身不用动。
- **conftest 默认关掉新屏。** splash 和 welcome 都靠环境变量默认值来
  在测试中禁用。welcome 的专项测试再显式打开。代价是 conftest 多两
  行；好处是 pilot 测试不会因为多了一层屏幕而变得不稳定。
- **动手改之前先读已有代码。** DTO 层之所以敢直接读 SQLite，是因为
  `cockpit.data` 和 `prove_mcp.tools.corpus` 里的模式已经稳定了。管
  线复用了 `claudescientist.runtime` 里现成的
  `apply_schema_migration` 和 `emit_cockpit_event`。

### 做错了什么

- **第一次 Welcome 按键测试走 `pilot.press('enter')` 路线失败了**——
  这个版本的 Textual 的屏幕栈按键路由没有按预期冒泡。改成直接调
  action 方法才是测试屏幕行为的正确姿势，但前面调试花了大约 20 分钟。
- **第一版 schema.sql 把新索引内联了**，结果破坏了从 v4 旧数据库迁移
  的路径——迁移代码还没加列，索引就要引用那个列。把索引挪到迁移代码
  里跟列一起加就好了。`test_migration_adds_column_to_legacy_table`
  当场抓到。
- **第一遍 ruff 漏了 HTML 渲染器里一行 E501（CSS 行太长）。** 把
  font-family 规则拆成两行，修复很简单；lint 抓到说明流程没问题。
- **i18n 条目增长超出预估。** v4.2 加了每种语言约 70 个条目，原计划
  估的是总共约 80 个。虽然控制在预算内，但每条都需要仔细推敲措辞——
  用户明确要求中文写法要自然，默认的"逐词直译"做法会产出别扭的结果。

### 明确没做的事

- 没做 `claudescientist start` 启动器。计划期间用户明确决定永久移出
  路线图。两个终端手动启动仍然是约定做法。
- 没做 web UI。ADR 0009 加上 ADR 0003 守住了这条底线。
- 没做 V5.0 的机制（claim_facets、closure 状态机、跨主干传播）。v4.2
  相当于一个诊断实验：如果用户经常按 `e` 导出、生成结题报告、reviewer
  在审稿时附上报告路径——那 V5.0"用 claim graph 做真相源"的论点就有了
  支撑；如果用户不怎么用，说明 v4.x 就够了。

---

## 接着读什么

- v4.2 计划：`C:\Users\whenpoem\.claude\plans\iridescent-snuggling-matsumoto.md`
- ADR 0009：[`adr/0009-reports-as-files-monitoring-as-tui.zh-CN.md`](adr/0009-reports-as-files-monitoring-as-tui.zh-CN.md)
- ADR 0010：[`adr/0010-multi-provider-embeddings.zh-CN.md`](adr/0010-multi-provider-embeddings.zh-CN.md)
- 键位表：[`cockpit-keys.zh-CN.md`](cockpit-keys.zh-CN.md)
- 服务商预设表：[`embedding-providers.zh-CN.md`](embedding-providers.zh-CN.md)

---

*回顾版本：1.0 · 2026-05-11 · tag：`v4.2.0`*
