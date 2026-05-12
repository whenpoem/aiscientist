# ADR 0009：报告导出为文件，实时监控留在 TUI

- **状态**：Accepted (v4.2)
- **日期**：2026-05

## 背景

cockpit 在 v0.2 时只是一个轻量的实时状态面板。到了 v4.0–v4.1，它逐步
承载了假说树、BT 排行榜、证明语料、诊断清单、Lean 尝试记录和七个标签
页视图。v4.1.0a4 加了全屏详情视图来容纳长内容，v4.2.0a1 又加了标签页
分组和可折叠分节来应对下一轮增长。

但两类内容开始超出 TUI 能舒服承载的范围：

1. **长篇结构化报告。** 比如结题报告、完整的 LaTeX 草稿、并排的证明
   骨架对比集、级联跟踪日志。这些东西本质上是**文档**，需要能做层级
   折叠和自动排版的查看器，24 行的滚动面板装不下。
2. **内容共享的需要。** reviewer agent、写作流程和外部协作者都想拿到
   同一份证据快照。把内容嵌在 cockpit 里面，共享起来很不方便——没有
   一个稳定的路径可以指向。

ADR 0003 已经否决了给 cockpit 加 web UI。cockpit 要解决的问题（实时
监控 + 键盘干预）用 TUI 就够了，额外跑一个 web 服务加一套构建流程的
代价被反复评估为太高。

能同时满足"承载长文档"和"方便共享"，又不用推翻 ADR 0003 的做法只有
一种：**把报告写成文件存到磁盘，让用户用自己的编辑器或浏览器打开**。
不需要后台进程、不需要端口、不需要前端框架——cockpit 负责写 markdown
/ HTML 文件，路径交给用户已有的工具。

## 决策

报告变成文件产物，写到 `reports/<short-id>-<kind>.<format>`，索引在
新的 `cockpit_reports` 表里。cockpit 通过三个入口把它们暴露给用户：
Reports 标签页、详情面板的 Reports 分节、以及在节点上按 `e` 键弹出的
导出对话框。

cockpit 自身**不**内嵌任何格式的渲染器。在 Reports 列表里按 Enter 会
调用系统默认程序（Windows 上 `os.startfile`、macOS 上 `open`、Linux
上 `xdg-open`）。cockpit 管实时监控这一半；文档阅读那一半交给用户自
己的 markdown 或 HTML 查看器。

实现拆成三层——DTO、渲染器、管线——放在 `src/cockpit/export/` 下。
v4.2 首批支持五种报告（closure、draft、diagnostic、portfolio、
cascade）和两种格式（markdown、html）。每种组合都能从 SQLite 完整再
生：重新导出会确定性地覆盖旧文件。

reviewer agent 拿到一个可选的 `mcp__verify__export_report` 工具，调
的是同一条管线。这不会变成硬性要求——ADR 0006 / ADR 0008 定下的实验
和证明 checklist 保持原样——但 reviewer 可以在 `notes` 字段里附上结
题报告的路径，方便手稿作者查阅。

## 后果

### 正面

- cockpit 不用再硬撑它本来就不擅长显示的内容。长草稿、完整诊断清单、
  并排对比集都由用户自己选择的工具打开。
- 报告可以共享。路径是稳定的，用户可以把它 commit 进仓库、附在 issue
  里、或者直接转给协作者，不需要重跑 cockpit。
- Reports 标签页提供所有已生成报告的统一索引；详情面板也会在对应节点
  下显示相关报告。
- ADR 0003"不要 web UI"的立场不受影响。cockpit 仍然是纯 TUI，新文件
  由用户已有的工具打开，不引入新的后台进程。

### 负面

- `reports/` 目录由用户自己管理，文件不会自动清理。`cockpit_reports`
  表在文件被删后仍然保留记录（标记为 `missing`），审计历史不会丢；但
  磁盘清理需要用户手动做。
- 同一份证据会出现在两个地方：cockpit 的实时标签页和导出的报告文件。
  用户需要分清"实时监控"和"归档文件"的区别。这是拥有真正归档能力要付
  出的代价。
- 在报告列表里按 Enter 会跳出 TUI、启动用户的默认程序。对文档来说这
  是合理的行为，但打破了"所有操作都在一个终端里完成"的预期；在没有图
  形界面的服务器上，用户应该知道 markdown 是更合适的默认格式。

### 备选方案

- **把长内容直接渲染在 TUI 里**。否决——内容增长速度超线性。v4.1 的
  内容就已经逼出了折叠分节和全屏详情视图。每增加一种内容形态都要改一
  轮 TUI 结构。
- **起一个本地 web 服务**。否决——ADR 0003 担心的额外进程负担仍然成
  立。单独的 web 服务能解决共享问题，但代价是丢掉"整个系统只跑一个进
  程"的简洁模型。
- **在 cockpit 里嵌一个 markdown / HTML 渲染器**。否决——Textual 的
  控件不是为文档级排版设计的。cockpit 会变成在重新造一个简陋的浏览器。
- **所有导出都走 reviewer agent，不单独做模块**。否决——reviewer 只是
  消费者之一。`python -m cockpit.export` CLI 让用户不用启动 agent 也
  能生成报告。

## 引用

- 计划文件：`C:\Users\whenpoem\.claude\plans\iridescent-snuggling-matsumoto.md`
- 相关 ADR：[`0003-textual-tui-not-browser.md`](0003-textual-tui-not-browser.md)
- 相关 ADR：[`0007-tools-skills-hooks-layering.md`](0007-tools-skills-hooks-layering.md)
- Reviewer 接入：[`../../.claude/agents/reviewer.md`](../../.claude/agents/reviewer.md)
- 实现位置：`src/cockpit/export/`、`src/cockpit/db.py`、
  `src/cockpit/panes/tabs_pane.py`、`src/cockpit/modals/export.py`、
  `src/verify_mcp/tools/reporting.py`。
