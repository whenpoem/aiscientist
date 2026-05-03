# 计划：Research-Agent 增强层 v0.2

> **状态**：可执行的详细计划。v0.2 范围 = TUI cockpit 迁移 + 完整 v0.2 路线图（`seed_perturb`、research-taste、held-out budget）。
> **目标机器**：Windows 11，项目位于 `D:\aiscientist\claudescientist`（v0.1 已交付）。
> **原则（不变）**：Claude Code 本体不做改动。所有增强都外挂在它周围。
>
> **v0.2 的锁定决策**：
> - **UI**：用基于 Textual 的 TUI 替换 React/FastAPI WebUI。**不再使用浏览器、不再使用 Vite、不再使用 uvicorn、不再使用 7777 端口。**
> - **Cockpit-MCP 传输**：改为 stdio（与 memory/verify 一致）。`settings.json` 移除 HTTP 配置。
> - **DAG 视图**：使用 Textual Tree 作为导航主干，并配合 detail panel 展示 cross-edge（不做 2D ASCII 布局）。
> - **v0.2 范围**：TUI + `seed_perturb` + research-taste + held-out budget（4 条工作流，约 3 周）。
> - **计划文档产物**：此计划也会在执行的 Step 0 中复制到 `D:\aiscientist\claudescientist\docs\plan-v0.2.md`。

---

## 1. 背景

v0.1 已经交付了一套可工作的系统（memory-mcp + verify-mcp + 5 个 hook + 5 个 subagent + 3 个 skill + WebUI cockpit），并且 20 个测试全部通过。但在真实使用里暴露出两个问题：

1. **WebUI 对真实工作负载来说设计过度。** cockpit 实际只展示约 20 个 hypothesis 节点、约 50 个 failure、一小段 event stream，以及一个 intervention 表单。为了渲染这些内容，v0.1 却要运行 FastAPI + uvicorn + WebSocket + React 19 + Vite 8 + Tailwind v4 + `@xyflow/react`，等于三层构建/运行时、两个你必须记得启动的额外进程，以及一个挂载 bug（`app.mount("/", mcp_http_app)` 会吞掉 404，见 v0.1 review）。用户的主观反馈是“架构不稳定 / 重 / 不协调”。
2. **v0.1 中承诺的 v0.2 路线图被无限期推后。** seed-perturb verification、research-taste / Elo 选择，以及 held-out budget enforcement 都被写成了 “v0.2+” 而没有日期。现在 v0.1 已经稳定，是该把这些项正式落地的时候了。

这份计划同时解决这两个问题。TUI 迁移是最大的一块（大约占总工作量的 50%），但用户体验收益最高。其余三项路线图能力，则能真正让我们的 memory layer 与 v0.1 第 7.6 节中提到的 EvoScientist 对比目标拉开差异。

最终交付物应当是：单个研究者可以在两个终端中使用的 v0.2 cockpit（左侧 Claude Code，右侧 TUI），完全不依赖浏览器；同时具备 verification 与 research-taste 能力，使我们的 memory layer 相比 EvoScientist 有可测量的差异化。

---

## 2. 术语速览（仅包含相较 v0.1 新增的内容）

### 2.1 TUI / Textual

**TUI**：一种全屏、键盘驱动、在终端内部绘制界面的应用。典型例子：`lazygit`、`k9s`、`htop`、`btop`、`neomutt`。不要求鼠标（尽管 Textual 支持），不依赖 GPU，可以通过 SSH 运行。

**Textual**：当前 Python 生态中主流的 TUI 框架，由 Rich 的作者开发。截至 2026 年 4 月当前版本为 8.2.3。本计划中会用到的关键概念：

- **Widget tree + CSS**：布局是一棵由 `Widget` 子类组成的树，样式写在类 CSS 文件（`*.tcss`）里。边框、内边距、网格列、颜色都在 CSS 中定义。
- **Reactive state**：例如在类级别定义 `selected_node = reactive(None)`；赋值时会自动触发 `watch_selected_node(old, new)` 并刷新相关依赖。
- **Workers**：`@work(exclusive=True, thread=False)` 可以让异步协程脱离主循环运行。这里会用于 SQLite tail。
- **Messages**：widget 会发出类型化消息（如 `Tree.NodeSelected`）；App 通过 `on_tree_node_selected` 之类的 handler 处理。这就是键盘/点击事件管线。
- **Modals**：例如 `class HelpScreen(ModalScreen[None])` 加 `await self.push_screen_wait(HelpScreen())`，用于确认框和对话框。
- **Bindings**：类级别定义 `BINDINGS = [Binding("q", "quit", "Quit"), ...]`。Textual 会自动把它们渲染成 `Footer` 中的快捷键提示，正好符合 k9s/lazygit 用户的预期。

### 2.2 为什么要去掉 FastAPI

cockpit 的 REST + WebSocket 层之所以存在，只是因为 React 前端需要一个 HTTP origin。有了 TUI 之后，我们可以：

- 直接打开同一个 SQLite 文件（`src/claudescientist/runtime.py` 中已存在 `runtime.connect_sqlite()`）。
- 让 cockpit-MCP 通过 **stdio** 在 Claude Code 的 MCP launcher 下运行，和 `memory`、`verify` 一样。不再需要端口，不再有 `app.mount` bug，不再需要 CORS，也不再需要额外记住去启动 uvicorn。
- 在 TUI 中使用单个 1 秒轮询器：`SELECT id > last_seen FROM cockpit_events`。启用 WAL 模式后，它不会阻塞写入方。

净删除量：约 240 行的 `src/cockpit/server.py`，以及整个 `src/cockpit/frontend/` 子树（约 2.5k LOC + `node_modules`）。

### 2.3 `seed_perturb` / `baseline_fairness`（verify-mcp 新增）

**`seed_perturb`**：用 N 个不同随机种子（`--seed 0/1/2`）重复运行训练脚本，计算报告指标的均值和标准差。它可以抓出“单个幸运种子”结果，这类问题在 EvoScientist 论文里偶尔会出现。实现方式是 subprocess runner，不依赖具体模型结构。

**`baseline_fairness`**：给定两份 run log，对比超参数预算（epochs × lr-trials × 参数量）。用于标记“提出的方法拿到了比 baseline 多 10 倍搜索预算”这类不公平对比。实现方式是日志解析 + 比率阈值。

### 2.4 Research-taste skill / Elo selection

**Elo selection**：当 researcher subagent 提出 K 个候选 hypothesis 时，在一个小型“judge”循环里执行两两比较（使用同一个模型，不额外 spawn agent），并给每个 hypothesis 分配 Elo 分数。最终挑选前 1 到 2 个。这和 Tournament-of-Reasoning、AlphaCode reranker 的思路一致。它将替代 v0.1 中“直接选第一个”的行为。

### 2.5 Held-out budget enforcement

这是一个小的 SQLite 表加一个 CLI 工具。`register_heldout_dataset` 会把数据移出工作树，放到 `~/.research-agent/heldout/<name>/`，并写入 manifest hash。`query_heldout(dataset, model, budget_units)` 则返回预测结果，同时扣减预算计数器（默认：每个 dataset 在每个项目生命周期内最多允许 5 个 query-batch）。如果 manifest hash 发生漂移，所有查询都直接失败。只有这样才能防止跨多次会话对测试集慢性过拟合。

---

## 3. v0.2 架构（相对 v0.1 的增量）

```text
+--------------------------------------------------------------------------+
| Terminal A（屏幕左半）                                                   |
|                                                                          |
|   claude  -->  Claude Code REPL                                          |
|      |                                                                   |
|      | stdio                                                             |
|      v                                                                   |
|   memory-mcp                                                             |
|   verify-mcp  ---------- 全部读写 ----------> state.db (SQLite)          |
|   cockpit-mcp                                                            |
|                                                                          |
| Terminal B（屏幕右半）                                                   |
|   uv run python -m cockpit.tui                                           |
|      |- tail cockpit_events   <---- 1 秒轮询，WAL 模式                   |
|      |- read mem_nodes / mem_edges / mem_failures / ver_*                |
|      \\- write cockpit_interventions（等价于原来的 POST）                |
+--------------------------------------------------------------------------+
```

**消失的部分**：uvicorn 进程、7777 端口、FastAPI app、WebSocket、整个 `src/cockpit/frontend/` 树、以及 `settings.json` 中 cockpit 的 HTTP-MCP transport 配置。

**保留的部分**：数据契约不变。`cockpit_events` 和 `cockpit_interventions` 的 schema 保持不变。hook（`intervention_pump.py`、`stop_flush.py`）不变。TUI 只是同一批 SQLite 表之上的一个新视图和写入端。

---

## 4. TUI 设计（核心内容）

### 4.1 屏幕布局

```text
+ research-cockpit  state.db: 23 nodes · 7 failures · 412 events · 14:32 --+
| 1 Hypothesis Tree                | 2 Node Detail                           |
| Q  Why does ViT scale poorly?    | H_07  hypothesis  state: active        |
|   H_07 dropout-rate hurts...     | -------------------------------------- |
|     E_12 mnist-proxy fail        | Per-head dropout 0.3 reduces test      |
|     E_15 cifar-proxy ok          | accuracy by 1.8pp on CIFAR-10 with     |
|   H_08 attention-pattern...      | ViT-S/16. p=0.04, n=3 seeds.           |
|     E_18 attn-mass               |                                        |
|   H_09 init-scale                | Parents: Q (root)                      |
| Q  follow-up: optimizer...       | Children: E_12, E_15                   |
|                                  | Cross-edges: -> H_08 (contradicts)     |
|                                  | Evidence: 2 attached, 1 refutes        |
+----------------------------------+----------------------------------------+
| 3 Event Stream                   | 4 Failures | Claims | Literature       |
| 14:32:11 graph_delta H_09 ...    | # trigger        symptom      seen      |
| 14:31:58 failure_added f_7       | 7 fit_on_concat  leakage      3         |
| 14:30:02 turn_end +2/-0/+1f      | 5 rm_dataset     destroy      1         |
| 14:28:44 intervention reject...  | 3 oom_batch_size crash        8         |
+-------------------------------------------------------------------------+
| :reject H_07 weak evidence on cifar                                      |
+ j/k nav · y approve · n reject · / filter · ? help · q quit ------------+
```

**Grid（Textual CSS）**：外层为纵向布局，包含 header（1 行）、中间主体、footer（1 行）。主体内部是一个 2 行 × 2 列网格。按下 `:` 时，底部一行由命令行覆盖。

**窗格编号**：1=tree，2=detail，3=events，4=右侧 tabs。按 `1` 到 `4` 直接聚焦。

### 4.2 交互模式

| 模式 | 进入方式 | 目的 |
|---|---|---|
| **Normal**（默认） | 默认进入 | 导航、切换、触发单键动作 |
| **Command** | `:` | 输入自由形式 intervention，类似 Vim |
| **Filter** | `/` | 对当前聚焦窗格的行做过滤 |
| **Modal** | `?`、`H`、`p`、`m` | 帮助、halt 确认、pin-metric 表单、mark-refuted 确认 |

按 `Esc` 总是返回 Normal。

### 4.3 快捷键（完整表）

#### 导航（Normal 模式）

| 键位 | 动作 |
|---|---|
| `j` / `k` | 在当前聚焦窗格中下移 / 上移 |
| `h` / `l` | 在窗格 1 中折叠 / 展开树节点；其他情况下向左 / 向右移动焦点 |
| `g` / `G` | 跳到当前窗格顶部 / 底部 |
| `Ctrl-D` / `Ctrl-U` | 半页下翻 / 上翻（长 event stream） |
| `Tab` / `Shift-Tab` | 将焦点切换到下一个 / 上一个窗格 |
| `1` / `2` / `3` / `4` | 直接跳到第 N 个窗格 |
| `f` | 在窗格 4 中切换 Failures -> Claims -> Literature -> Failures |
| `Enter` | 深入打开当前选中项（打开 evidence 详情、展开 failure 等） |
| `Esc` | 取消输入 / 关闭 modal / 清除过滤器 / 返回 Normal |

#### 对当前 hypothesis 的单键操作（Normal 模式）

| 键位 | 动作 | 写入 |
|---|---|---|
| `y` | 批准该 hypothesis | `cockpit_interventions(kind="approve", target=node_id, payload="")` |
| `n` | 拒绝该 hypothesis | `cockpit_interventions(kind="reject", target=node_id, payload="")` |
| `r` | 重定向（打开单行输入框） | `cockpit_interventions(kind="redirect", target=node_id, payload=<input>)` |
| `c` | 约束（打开单行输入框） | `cockpit_interventions(kind="constrain", target=node_id, payload=<input>)` |
| `m` | 标记为已证伪（打开确认框） | 通过 cockpit-mcp 工具写 `mem_nodes.state = 'refuted'` |
| `p` | Pin metric（打开表单：dataset / metric / value） | 通过 cockpit-mcp 工具写入 `ver_metric_pins` |
| `H` | **停止 agent**（大写 H，打开确认框） | `cockpit_interventions(kind="halt", target=NULL, payload=<reason>)` |

用大写 `H` 执行 halt 是刻意设计，和 lazygit 对破坏性动作使用大写的习惯一致。确认框要求输入 `y` 才真正提交。

#### 视图与元操作（Normal 模式）

| 键位 | 动作 |
|---|---|
| `/` | 进入当前窗格的 Filter 模式 |
| `?` | 打开帮助覆盖层（以 modal 形式显示所有绑定） |
| `:` | 进入 Command 模式（自由输入 intervention） |
| `t` | 切换 event stream 的时间戳格式（相对时间 <-> 绝对时间） |
| `s` | 切换 tree 中是否显示 refuted 节点（默认隐藏；显示时使用 dimmed-strikethrough） |
| `R` | 强制从 SQLite 刷新所有窗格（不等待下一次轮询） |
| `Ctrl-L` | 清空 event-stream 的滚动显示内容（仅视觉效果，不影响 DB） |
| `q` | 退出（若存在未发送 intervention，则先确认） |

#### Command 模式（按下 `:` 之后）

自由文本输入。按 `Enter` 时：

- `:reject H_07 reason text` -> reject intervention
- `:halt reason text` -> halt
- `:pin dataset metric value` -> pin metric
- `:note free text` -> 向 `cockpit_events(kind="note")` 写一条 note 事件，供事后追踪
- `:`（空输入后直接回车）-> no-op，并退出 Command 模式

#### Filter 模式（按下 `/` 之后）

对当前聚焦窗格可见列做子串匹配。输入时实时缩小范围。`Enter` 保留过滤器，`Esc` 清除过滤器。激活中的过滤器会显示在窗格标题里，例如：`1 Hypothesis Tree (filter: dropout)`。

### 4.4 颜色方案（GitHub Dark，定义于 `cockpit.tcss`）

| 角色 | Hex | 用途 |
|---|---|---|
| `--bg` | `#0d1117` | 应用背景 |
| `--fg` | `#c9d1d9` | 默认文本 |
| `--muted` | `#6e7681` | 非激活时间戳、父 breadcrumb、refuted 节点 |
| `--accent` | `#58a6ff` | 聚焦行、聚焦窗格边框、选中标签 |
| `--success` | `#3fb950` | 已验证 claim、approved intervention、support evidence 边 |
| `--danger` | `#f85149` | 被证伪节点、halt 动作、高频 failure |
| `--warning` | `#d29922` | 待处理 intervention、contradiction |
| `--border` | `#21262d` | 所有窗格边框 |
| `--cursor-bg` | `#1f6feb` | DataTable 选中行背景 |

**节点类型颜色**（tree 与 detail header 使用）：

- `question`：青色 `#79c0ff`
- `hypothesis`：蓝色 `#58a6ff`（active）/ 红色删除线 `#f85149`（refuted）/ 灰色 `#6e7681`（archived）
- `experiment`：琥珀色 `#d29922`
- `evidence`：绿色 `#3fb950`（supports）/ 红色 `#f85149`（refutes）
- `conclusion`：洋红色 `#bc8cff`

**排版规则**：

- 窗格标题：加粗；聚焦时使用 accent，未聚焦时使用 muted
- hypothesis 文本：常规字重，前缀显示 kind-color 标签（如 `H_07`）
- refuted 节点：删除线 + muted（仅在 `s` 打开时可见）
- event stream 时间戳：muted 灰色、等宽
- 数字（计数、ID）：使用 `Text("12", style="bold")` 以获得更稳的数字表现

### 4.5 各窗格规格

#### 窗格 1：Hypothesis Tree（`HypothesisTreePane`）

- Widget：`textual.widgets.Tree`
- 数据源：`mem_nodes` + `mem_edges`（只有 `relation='parent_of'` 的边用于构建树主干；其余关系显示在 detail pane）
- 根节点：所有没有传入 `parent_of` 边的 `question` 类型节点
- 子节点惰性加载（启动时不全部展开；在 `l` 或 `Enter` 时展开）
- 当收到 `graph_delta` 事件时，自动滚动到新到达节点，并用约 200ms 的 accent-color 闪烁提示（通过 `tree.styles.animate`）
- cross-edge（如 `contradicts`、`supports`）**不在此处绘制**；它们会出现在窗格 2 的 “Cross-edges:” 行

#### 窗格 2：Node Detail（`NodeDetailPane`）

- Widget：`Static`（渲染富文本）
- 当窗格 1 发出 `Tree.NodeSelected` 时更新
- 布局（自上而下）：
  1. Header 行：`<id>  <kind>  state: <state>`（kind 着色）
  2. 分隔线
  3. 节点全文（自动换行，不截断）
  4. 空行
  5. `Parents:` 行（逗号分隔 ID，可通过 `gP` 跳转）
  6. `Children:` 行（同上）
  7. `Cross-edges:` 行，格式如 `-> H_08 (contradicts)`；多条则分多行
  8. `Evidence:` 摘要计数
  9. `Created:` 时间戳，`Created by:` agent 名称
- 若没有选中节点：显示单行提示 “用 `j` / `k` 选择 hypothesis，或直接点击。”

#### 窗格 3：Event Stream（`EventStreamPane`）

- Widget：`RichLog(max_lines=2000, auto_scroll=True, wrap=False)`
- 由 `events_worker` 负责 tail（见 4.6）
- 每行格式：`HH:MM:SS  <kind>  <one-line summary>`
  - `graph_delta`：`graph_delta H_09 hypothesis init-scale matters`
  - `failure_added`：`failure_added f_7 fit_on_concat (signature: f8a3b2)`
  - `turn_end`：`turn_end +2/-0/+1f`（新增节点 / 证伪节点 / 新增 failure）
  - `intervention`：`intervention reject H_07 by user`
  - `note`：`note <text>`（用户写入）
- 颜色：kind 名用 accent，摘要用默认前景，时间戳用 muted
- `t` 切换为相对时间（例如 `-2m 14s ago`）
- 支持 `/` 过滤

#### 窗格 4：右侧标签窗格（`RightTabsPane`）

一个 `TabbedContent` widget，包含三个 tab。按 `f` 循环切换。

- **Tab "Failures"**（`DataTable`）
  - 列：`#`、`trigger`、`symptom`、`seen`
  - 默认排序：`seen DESC`，其次 `last_seen DESC`
  - 选中行 -> 将完整 failure 记录填入 detail panel（临时覆盖 node detail；按 `Esc` 恢复）
- **Tab "Claims"**（`DataTable`）
  - 数据源：`ver_metric_pins JOIN ver_provenance`
  - 列：`metric`、`value`、`dataset`、`verified`、`seeds`
  - `verified` 列根据是否已跑过 `seed_perturb` 显示 `✓`（success）或 `✗`（danger）
  - `seeds` 显示进行中的进度，如 `N/3`
- **Tab "Literature"**（`DataTable`）
  - 数据源：`mem_lit_compressed`
  - 列：`paper_id`、`title (truncated)`、`year`、`task`、`score`
  - `Enter` -> 打开压缩摘要 modal，展示全部结构化字段

### 4.6 实时更新机制（`events_worker`）

```python
class CockpitApp(App):
    last_event_id = reactive(0)

    @work(exclusive=True)
    async def events_worker(self) -> None:
        while True:
            new_rows = await asyncio.to_thread(
                self._fetch_new_events, self.last_event_id
            )
            if new_rows:
                for row in new_rows:
                    self.dispatch_event(row)
                self.last_event_id = new_rows[-1]["id"]
            await asyncio.sleep(1.0)

    def dispatch_event(self, row):
        # 写入 event-stream pane
        self.query_one(EventStreamPane).post(row)
        # 按需刷新受影响的窗格
        if row["kind"] == "graph_delta":
            self.query_one(HypothesisTreePane).refresh_node(row["payload"]["node_id"])
        elif row["kind"] == "failure_added":
            self.query_one(RightTabsPane).refresh_failures()
        elif row["kind"] == "turn_end":
            self.query_one(EventStreamPane).write_separator(row["payload"])
```

- 单个 1 秒轮询；成本就是每秒一次带索引的 `SELECT id > ?`，可以忽略。
- `asyncio.to_thread` 让 SQLite 调用脱离 event loop，因此 UI 不会卡顿。
- `last_event_id` 是 reactive，所以 watcher 会自动更新 header 里的计数。
- 用户按 `R` 时，通过一个 `asyncio.Event` 唤醒 worker 立即重轮询。

### 4.7 Modals

| Modal | 触发方式 | 行为 |
|---|---|---|
| **HelpScreen** | `?` | 只读覆盖层，按分组展示所有绑定。任意键关闭。 |
| **ConfirmModal** | `m`、`H`、quit-with-pending | “Are you sure? (y/n)”。返回 bool。 |
| **TextInputModal** | `r`、`c`、`:` | 单行输入框，针对不同动作显示不同 placeholder。返回字符串或 `None`。 |
| **PinMetricModal** | `p` | 三字段表单：dataset、metric、value。返回 dict 或 `None`。会校验 `value` 是否为浮点数。 |
| **NodeDrillModal** | 在 detail pane 中对 evidence 按 `Enter` | 展示完整 evidence 文本 + provenance hash + 关联 metric pin。按 `Esc` 关闭。 |

所有 modal 都遵守同一套颜色方案，并通过 `ModalScreen[T]` 返回类型化结果。

### 4.8 外观 / 易用性说明（吸取 k9s、lazygit、btop 的经验）

- **边框只使用 ASCII 或 box-drawing 范围字符**（U+2500 到 U+257F）。不要在 chrome 中使用 CJK 框线字符或 emoji。到 2026 年 4 月，Windows Terminal 对这些字符的对齐仍然不稳定（Textual issue #6025）。
- **Footer 是快捷键的唯一真相来源。** 不要把快捷键藏进 tooltip 或 hover。Footer 根据 `BINDINGS` 自动渲染，这样帮助与行为不会漂移。
- **聚焦窗格边框高亮 = 粗体 + accent；未聚焦 = muted。** 焦点切换时只改变这一点，不做弹窗，不做闪烁。
- **动画只保留 150 到 250ms 的 accent 闪烁。** 长动画会拖累长时间使用体验。
- **refuted 节点默认隐藏**，但可通过 `s` 切换显示（删除线 + muted），类似 lazygit 的 “show all”。
- **detail pane 不做截断。** 仅自动换行。截断只发生在表格中（用省略号并在 hover 时通过 Textual tooltip 展示完整内容）。
- **header 固定单行。** 格式：`app_name  state.db: <counts>  HH:MM`。
- **footer 固定单行。** 格式：`key  action · key  action · ...`，只展示最高频的 6 个动作；完整列表在 `?` 中查看。
- **空状态提示。** 每个 pane 在没有内容时都显示单行提示，例如：“还没有 hypothesis。请在 Claude Code 中触发一次 research session。” 不要留空白。
- **色盲兜底。** 所有语义颜色都配一个字形：`✓`、`✗`、`->`、`[]` 等，不能只靠颜色表达语义。
- **只有存在未发送输入时才弹退出确认。** 如果只是正常查看状态，`q` 应立即退出。

### 4.9 文件布局（TUI 模块）

```text
src/cockpit/
|- __init__.py
|- tui.py                    # 入口：python -m cockpit.tui
|- app.py                    # CockpitApp(App)，根 widget tree、BINDINGS、workers
|- panes/
|  |- __init__.py
|  |- tree_pane.py          # HypothesisTreePane(Tree)
|  |- detail_pane.py        # NodeDetailPane(Static)
|  |- events_pane.py        # EventStreamPane(RichLog)
|  \- tabs_pane.py          # RightTabsPane(TabbedContent) + 3 个内部表格
|- modals/
|  |- __init__.py
|  |- help.py               # HelpScreen
|  |- confirm.py            # ConfirmModal
|  |- text_input.py         # TextInputModal
|  \- pin_metric.py         # PinMetricModal
|- data.py                  # _fetch_new_events / _fetch_graph / _fetch_failures / _fetch_claims / _fetch_literature / _write_intervention
|- theme/
|  \- cockpit.tcss          # 完整颜色与布局样式表
\- mcp_server.py            # cockpit-MCP（stdio）: push_graph_delta + write_intervention tools
```

`data.py` 是唯一直接接触 `runtime.connect_sqlite()` 的地方，从而把 SQL 从 widget 层隔离出去。

---

## 5. 后端改动（去掉 FastAPI，cockpit-MCP 改为 stdio）

### 5.1 需要删除的文件

```text
src/cockpit/server.py                      # FastAPI app + uvicorn 入口 -> DELETE
src/cockpit/frontend/                      # 整棵 React 子树 -> DELETE
  |- src/App.tsx
  |- src/components/HypothesisGraph.tsx
  |- src/components/InterventionPanel.tsx
  |- src/components/VerificationTable.tsx
  |- src/hooks/useWebSocket.ts
  |- package.json, vite.config.ts, tailwind.config.ts, tsconfig.json
  \- node_modules/                        # 也一起删掉（本来就 gitignored）
```

### 5.2 需要新增的文件

`src/cockpit/mcp_server.py`：用于替代原来 `server.py` 中的 FastMCP HTTP 子应用：

```python
from fastmcp import FastMCP
from claudescientist.runtime import connect_sqlite, state_db_path

mcp = FastMCP("cockpit")

@mcp.tool
def push_graph_delta(node_id: str, kind: str, text: str) -> dict:
    """当主 Claude 创建新节点时调用。"""
    with connect_sqlite(state_db_path()) as con:
        con.execute(
            "INSERT INTO cockpit_events(kind, payload) VALUES(?, ?)",
            ("graph_delta", json.dumps({"node_id": node_id, "kind": kind, "text": text})),
        )
    return {"ok": True}

@mcp.tool
def queue_intervention(kind: str, target: str | None, payload: str) -> dict:
    """程序化版本的 POST /intervene，可供脚本使用。"""
    # ... insert into cockpit_interventions ...
    return {"ok": True}

if __name__ == "__main__":
    mcp.run()  # stdio
```

### 5.3 `settings.json` 的变更

```diff
   "cockpit": {
-    "transport": {
-      "type": "http",
-      "url": "http://127.0.0.1:7777/mcp"
-    }
+    "command": "uv",
+    "args": ["run", "python", "-m", "cockpit.mcp_server"]
   },
```

### 5.4 `pyproject.toml` 的变更

移除不再需要的依赖（FastAPI、uvicorn，以及如果有固定版本的话 websockets），新增 Textual：

```diff
-fastapi>=0.115
-uvicorn>=0.34
+textual>=8.2.3
```

`fastmcp` 保留，因为 `cockpit/mcp_server.py` 仍然会用到。SQLite 继续使用标准库。

### 5.5 要删除 / 替换的测试

- 删除：`tests/cockpit/test_server.py`、`tests/cockpit/test_websocket.py` 中相关内容
- 新增：
  - `tests/cockpit/test_data.py`：数据层 SQL 测试，不依赖 Textual
  - `tests/cockpit/test_mcp_server.py`：测试 stdio MCP 行为是否与 memory/verify 一致（沿用 v0.1 MCP 测试中 `fastmcp.client` 的方式）
  - `tests/cockpit/test_app_smoke.py`：使用 Textual 的 `App.run_test()` 异步 harness 启动 app，模拟按键（`pilot.press("j", "y")`），然后断言 DB 状态

---

## 6. verify-mcp 中的 `seed_perturb` + `baseline_fairness`

### 6.1 `src/verify_mcp/impl.py` 中新增工具

```python
@mcp.tool
def seed_perturb(
    script_path: str,
    seed_arg: str = "--seed",
    seeds: list[int] | None = None,
    metric_pattern: str = r"test[_ ]acc(uracy)?[: =]+([\d.]+)",
    timeout_sec: int = 600,
) -> dict:
    """用 N 个 seed 运行脚本，并返回提取出的指标均值/标准差。"""
    seeds = seeds or [0, 1, 2]
    values = []
    for s in seeds:
        result = subprocess.run(
            ["uv", "run", "python", script_path, seed_arg, str(s)],
            capture_output=True, text=True, timeout=timeout_sec,
        )
        m = re.search(metric_pattern, result.stdout)
        if not m:
            return {"ok": False, "error": f"metric not found for seed {s}"}
        values.append(float(m.group(2)))
    return {
        "ok": True,
        "seeds": seeds,
        "values": values,
        "mean": statistics.mean(values),
        "std": statistics.stdev(values) if len(values) > 1 else 0.0,
        "verdict": "stable" if statistics.stdev(values) < 0.01 else "unstable",
    }

@mcp.tool
def baseline_fairness(
    proposed_log: str,
    baseline_log: str,
    threshold_ratio: float = 3.0,
) -> dict:
    """对比两个 run log 的超参数预算。"""
    p = _extract_budget(proposed_log)  # {"epochs": int, "lr_trials": int, "param_count": int}
    b = _extract_budget(baseline_log)
    ratios = {k: p[k] / max(b[k], 1) for k in p}
    unfair = {k: r for k, r in ratios.items() if r > threshold_ratio}
    return {
        "ok": True,
        "proposed": p,
        "baseline": b,
        "ratios": ratios,
        "verdict": "fair" if not unfair else "unfair",
        "unfair_axes": unfair,
    }
```

辅助函数（`_extract_budget`）放在新文件 `src/verify_mcp/budget.py` 中。实现以正则解析为主，策略偏保守。若解析失败，对未知轴返回 `None`，由调用方自行决定如何处理。

### 6.2 新表：`ver_seed_runs`

```sql
CREATE TABLE ver_seed_runs (
  run_id INTEGER PRIMARY KEY AUTOINCREMENT,
  script_path TEXT NOT NULL,
  seeds_json TEXT NOT NULL,        -- '[0,1,2]'
  values_json TEXT NOT NULL,       -- '[0.91, 0.89, 0.92]'
  mean_value REAL NOT NULL,
  std_value REAL NOT NULL,
  verdict TEXT NOT NULL,           -- 'stable' / 'unstable'
  metric_pin_id INTEGER,           -- FK ver_metric_pins (nullable)
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (metric_pin_id) REFERENCES ver_metric_pins(pin_id)
);
```

当 `seed_perturb` 运行的脚本与某个 pinned metric 相关时，它会反向补齐该 pin 的验证状态。TUI 的 “Claims” tab 会通过这个 join 读取结果。

### 6.3 测试

- `tests/verify_mcp/test_seed_perturb.py`：使用两个 fixture 脚本，一个确定性脚本（始终返回相同数值），一个带噪脚本（随 seed 变化）。断言 verdict。
- `tests/verify_mcp/test_baseline_fairness.py`：用合成日志构造已知预算比率。

---

## 7. Research-taste skill + SOP 精炼

### 7.1 新 skill：`.claude/skills/elo-select.md`

这个 skill 接收 K 个候选 hypothesis，使用同一 Claude 会话执行约 `O(K log K)` 次两两比较（不 spawn subagent，而是通过 memory-mcp 中的 `judge_hypotheses(a, b)` 工具），为它们分配 Elo 分数，并返回前 2 名及其理由。

触发条件：

- researcher subagent 在一个 turn 中刚刚产出至少 3 个 hypothesis 节点
- 或者用户显式运行 `/elo-select`

### 7.2 memory-mcp 中新增工具：`judge_hypotheses`

```python
@mcp.tool
def judge_hypotheses(
    hypothesis_a_id: str,
    hypothesis_b_id: str,
    criteria: list[str] = None,
) -> dict:
    """返回 winner_id 和 reason。默认 criteria：novelty、feasibility、falsifiability。"""
    # 取回两个节点的文本
    # 为同一个模型构建 prompt（不 spawn）——把 prompt 返回给调用方（Claude）
    # 由 Claude 在当前上下文中完成评估，然后再调用 `record_judgement`
```

这里采用两步模式：`judge_hypotheses` 返回 prompt；Claude 完成评估；Claude 再调用 `record_judgement(a, b, winner, reason)`。这样既避免了 subagent 成本，也保持在同一个模型上下文中。

### 7.3 Elo 存储：扩展 `mem_nodes`

```sql
ALTER TABLE mem_nodes ADD COLUMN elo_score REAL DEFAULT 1500.0;
```

再增加一个小型 ledger：

```sql
CREATE TABLE mem_judgements (
  judgement_id INTEGER PRIMARY KEY AUTOINCREMENT,
  a_node_id TEXT NOT NULL,
  b_node_id TEXT NOT NULL,
  winner_node_id TEXT NOT NULL,
  reason TEXT,
  k_factor REAL DEFAULT 32.0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (a_node_id) REFERENCES mem_nodes(node_id),
  FOREIGN KEY (b_node_id) REFERENCES mem_nodes(node_id),
  FOREIGN KEY (winner_node_id) REFERENCES mem_nodes(node_id)
);
```

`record_judgement` 会用标准 Elo 公式（K=32）同时更新两个节点的分数。

### 7.4 SOP 变更

- `research-sop`：在 researcher 提出 K 个 hypothesis 后，如果 `K >= 3`，先执行 elo-select，再把前 2 名交给 engineer。
- `writeup-sop`：在讨论每个 hypothesis 时，把 Elo 分数一起写出来。

### 7.5 测试

- `tests/memory_mcp/test_elo.py`：构造一个 5 hypothesis 的合成锦标赛，断言最终排名与预设真值一致。

---

## 8. Held-out budget enforcement

### 8.1 新 CLI：`uv run python -m claudescientist.heldout register <name> <path>`

它会把 `<path>` 移动到 `~/.research-agent/heldout/<name>/`，计算所有文件的 SHA-256，并写出 `manifest.json`。原位置则留下一个 `.heldout-pointer` 文件，指向新路径。`leakage_guard` hook 读取到 `.heldout-pointer` 时，**一律阻止读取它所指向的数据**，只有 `query_heldout` 可以访问。

### 8.2 新表与 MCP 工具

```sql
CREATE TABLE ver_heldout_budgets (
  dataset TEXT PRIMARY KEY,
  manifest_sha256 TEXT NOT NULL,
  budget_total INTEGER NOT NULL DEFAULT 5,
  budget_used INTEGER NOT NULL DEFAULT 0,
  registered_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE ver_heldout_queries (
  query_id INTEGER PRIMARY KEY AUTOINCREMENT,
  dataset TEXT NOT NULL,
  model_path TEXT NOT NULL,
  metric_value REAL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

```python
@mcp.tool
def query_heldout(dataset: str, model_path: str, batch_size: int = 1) -> dict:
    """在 heldout dataset 上运行 model_path，并扣减预算。"""
    # 1. 校验 manifest hash 与登记值一致
    # 2. 检查 budget_used < budget_total
    # 3. 通过 subprocess 执行：uv run python <model_path> --dataset <heldout_path>
    # 4. 从 stdout 解析单个 metric
    # 5. 插入 ver_heldout_queries，并递增 budget_used
    # 6. 返回 metric 和剩余预算
```

### 8.3 Hook 集成

`leakage_guard.py` 增加一条规则：如果某次 Write/Edit 所包含的路径最终解析到 `~/.research-agent/heldout/<name>/`，则直接以 `permissionDecision: "deny"` 拒绝，并给出原因 “held-out dataset access only via query_heldout”。

### 8.4 测试

- `tests/verify_mcp/test_heldout.py`
  - 注册数据集，查询 5 次，第 6 次返回 `{"ok": False, "error": "budget_exceeded"}`
  - 篡改 manifest 后，再查询返回 `{"ok": False, "error": "manifest_drift"}`
- `tests/hooks/test_leakage_guard_heldout.py`
  - 对 heldout 路径发起 Write 事件 -> 被阻止

---

## 9. 项目布局（v0.2 差异）

```text
src/
|- claudescientist/
|  |- runtime.py                    # 不变
|  \- heldout_cli.py                # NEW
|- memory_mcp/
|  |- impl.py                       # +judge_hypotheses, +record_judgement
|  |- schema.sql                    # +mem_judgements, +elo_score 列
|  \- ...
|- verify_mcp/
|  |- impl.py                       # +seed_perturb, +baseline_fairness, +query_heldout
|  |- budget.py                     # NEW（日志解析器）
|  |- schema.sql                    # +ver_seed_runs, +ver_heldout_budgets, +ver_heldout_queries
|  \- ...
\- cockpit/
   |- tui.py                        # NEW 入口
   |- app.py                        # NEW
   |- data.py                       # NEW（原 server.py 中的 SQL 片段迁移到这里）
   |- mcp_server.py                 # NEW（替代 server.py 中的 MCP 子应用）
   |- theme/cockpit.tcss            # NEW
   |- panes/                        # NEW（4 个文件）
   |- modals/                       # NEW（4 个文件）
   |- server.py                     # DELETE
   \- frontend/                     # DELETE 整棵树

.claude/
|- settings.json                    # cockpit MCP 配置：HTTP -> stdio
|- skills/
|  \- elo-select.md                 # NEW
\- ...

docs/
\- plan-v0.2.md                     # NEW（本文件，在 Step 0 中复制入库）

tests/
|- cockpit/
|  |- test_data.py                  # NEW
|  |- test_mcp_server.py            # NEW
|  |- test_app_smoke.py             # NEW
|  |- test_server.py                # DELETE
|  \- test_websocket.py             # DELETE（若存在）
|- memory_mcp/test_elo.py           # NEW
|- verify_mcp/test_seed_perturb.py  # NEW
|- verify_mcp/test_baseline_fairness.py  # NEW
|- verify_mcp/test_heldout.py       # NEW
\- hooks/test_leakage_guard_heldout.py   # NEW
```

---

## 10. v0.2 可执行计划（Phase 7 到 10）

（v0.1 使用的是 Phase 0 到 6。）

### Phase 7：TUI 脚手架 + 只读视图对齐（3 天）

**目标**：TUI 能启动、能读 SQLite、能实时显示 graph + failures + events。暂不支持 interventions。

1. 在 `pyproject.toml` 中加入 `textual>=8.2.3`，执行 `uv sync`。
2. 创建 `src/cockpit/tui.py`、`app.py`、`data.py`、`theme/cockpit.tcss`，以及全部 4 个只读 pane。
3. 接上 1 秒 `events_worker`。确认 MCP 写入后 1 秒内 event-stream pane 会更新。
4. 验证：打开 TUI，从测试 session 调用 `mcp__memory__propose_hypothesis`，断言 tree 会更新、event 会滚入。

### Phase 8：TUI interventions + modals + cockpit-mcp stdio（3 天）

**目标**：达到 v0.1 WebUI 的完整功能对齐。此时 WebUI 文件可以删除。

1. 实现全部 modal（help、confirm、text-input、pin-metric）。
2. 接上所有 action keybinding（`y/n/r/c/m/p/H/:`）；写入经由 `data.py` -> `cockpit_interventions`。
3. 将 `src/cockpit/mcp_server.py` 重写为 stdio 版本。
4. 将 `.claude/settings.json` 中 cockpit 配置从 HTTP 改为 stdio。
5. 删除 `src/cockpit/server.py` 和 `src/cockpit/frontend/`。
6. 从 `pyproject.toml` 中删掉 FastAPI/uvicorn，执行 `uv sync`。
7. 验证：执行 v0.1 的完整 smoke test（见第 11 节），但使用 TUI 替代浏览器。end-to-end intervention round-trip 必须正常。

### Phase 9：verify-mcp 的 `seed_perturb` + `baseline_fairness`（4 天）

**目标**：工具交付、schema 完成迁移、TUI 的 Claims tab 能显示验证 verdict。

1. 在 `src/verify_mcp/impl.py` 中实现 `seed_perturb` 和 `baseline_fairness`，测试通过。
2. 通过 `apply_schema_migration` 增加 `ver_seed_runs` 表。
3. 更新 TUI Claims tab 的 SQL，使其 join `ver_seed_runs` 并展示 `✓` / `✗`。
4. 为 verifier-subagent 的 SOP 增加一步：在 `pin_metric` 之后，如果尚未跑过 `seed_perturb`，自动建议执行。
5. 验证：运行一个确定性脚本和一个带噪脚本，在 Claims tab 中看到 “stable” / “unstable” verdict。

### Phase 10：research-taste（Elo）+ held-out budget（5 天）

**目标**：通过 Elo 排序 hypothesis；held-out 数据访问完全受控。

1. 通过 migration 增加 `mem_judgements` 表和 `elo_score` 列。
2. 在 memory-mcp 中实现 `judge_hypotheses` 和 `record_judgement`。
3. 编写 `.claude/skills/elo-select.md`。
4. 更新 `research-sop`，使其在 `K >= 3` 时调用 elo-select。
5. 实现 `claudescientist.heldout_cli`（register/list/inspect）。
6. 增加 `ver_heldout_budgets` 和 `ver_heldout_queries` 表。
7. 实现 `query_heldout` MCP 工具。
8. 扩展 `leakage_guard.py`，阻止对 heldout 路径的 Read/Write/Edit。
9. 所有测试通过。
10. 验证：注册一个合成数据集，生成 5 个 hypothesis，在 TUI 中看到 Elo 排名，并确认读取 heldout dataset 会被阻止。

### v0.2 的 Step 0（在 Phase 7 前执行）

将这份计划文件复制到 `D:\aiscientist\claudescientist\docs\plan-v0.2.md`（若 `docs/` 不存在则创建）。这样计划本身成为仓库的一部分，CI 也可以用它做存在性检查。

---

## 11. 验证计划

### v0.2 端到端 smoke test

```powershell
# Terminal A:
cd D:\aiscientist\claudescientist
claude   # 启动 Claude Code

# Terminal B:
cd D:\aiscientist\claudescientist
uv run python -m cockpit.tui
```

在 Terminal A 中：

1. `/research-sop investigate whether dropout rate affects ViT scaling`
   -> 预期（在 TUI 的 Terminal B 中）：5 秒内 tree 出现 question + 5 个 hypotheses；events pane 中持续出现 `graph_delta`；elo-select skill 自动触发（因为 hypothesis 数 >= 3）；detail pane 中可看到前 2 个 hypothesis 的 Elo 分数。
2. 在 Terminal B 中：聚焦 tree（`1`），导航到最弱的 hypothesis（按若干次 `j`），按 `n`（reject）
   -> 预期：立即出现 `intervention` 事件；Claude 在 Terminal A 的下一个 turn 中会把 rejection 注入 `additionalContext`，并放弃该 hypothesis。
3. 在 Terminal A 中：`@engineer implement the remaining hypothesis as a MNIST-proxy training script with --seed argument`
   -> 预期：代码能通过 `leakage_guard`，脚本被正常保存。
4. 在 Terminal A 中：`mcp__verify__seed_perturb script_path=mnist_proxy.py seeds=[0,1,2]`
   -> 预期：TUI Claims tab 中出现该 metric，并显示 `✓ verified` 以及 mean/std。
5. 在 Terminal A 中：`uv run python -m claudescientist.heldout register mnist-test ./data/mnist-test/`
   -> 预期：目录被移动，原位置留下 pointer。
6. 在 Terminal A 中：要求 Claude 读取 `./data/mnist-test/labels.csv`
   -> 预期：`leakage_guard` 阻止访问，并建议改用 `query_heldout`。
7. 结束会话并重启，再重启 TUI
   -> 预期：graph 状态、Elo 分数、seed-run 历史、budget 计数器都能持久化。

### v0.2 新增回归测试

- `tests/cockpit/test_data.py`：纯 SQL 层
- `tests/cockpit/test_mcp_server.py`：stdio MCP 是否与 v0.1 行为一致
- `tests/cockpit/test_app_smoke.py`：`App.run_test()` + `pilot.press` 按键模拟
- `tests/memory_mcp/test_elo.py`：Elo 更新公式、judgement ledger
- `tests/verify_mcp/test_seed_perturb.py`：稳定 / 不稳定 fixture
- `tests/verify_mcp/test_baseline_fairness.py`：公平 / 不公平预算日志
- `tests/verify_mcp/test_heldout.py`：预算耗尽 + manifest 漂移
- `tests/hooks/test_leakage_guard_heldout.py`：对 heldout-pointer 的阻止

目标：v0.1 的全部测试继续通过，再加上 7 个新增测试文件全部为绿。

### 手工 TUI 易用性检查（约 20 分钟）

在 Phase 8 完成后，用 TUI 做 20 分钟真实操作：

- 不打开 `?` 的情况下，是否仍能找到常用绑定
- 在 120 × 40 的 Windows Terminal 中，pane 边框是否有任何错位
- 是否有任何颜色在你的显示器上对比度不足
- 1 秒的 event pane 延迟是否可感知（理论上不应明显）
- `q` 是否会因为误触未确认退出 modal 而影响使用

在宣告 v0.2 完成前，把结果以 “ergonomics review” 形式记录到 `docs/plan-v0.2.md` 附录。

---

## 12. 回滚 / 迁移说明

- TUI 与已删除的 WebUI 都写入同一个 `cockpit_interventions` schema。如果用户在 Phase 8 中途想回退到 WebUI，只需要 `git revert` 删除提交，再在 `frontend/` 中执行 `npm install` 即可恢复。两个方向都不需要 DB migration。
- `runtime.py` 中已有的 `apply_schema_migration` 可以幂等地处理这 4 处新 schema 变更。对现有 v0.1 DB 重复执行 v0.2 setup 是安全的。
- cockpit-MCP 的 transport 变更（HTTP -> stdio）是唯一一个要求重启 Claude Code 才能生效的改动（因为要重新加载 `settings.json`）。

---

## 13. 未决项（执行过程中决定，不构成 blocker）

- **Textual 版本约束**：8.2.3 是当前版本；建议宽松锁定为 `>=8.2,<9.0`，允许补丁更新。
- **两两判断的 K-factor**：默认 32 借用自国际象棋 Elo；如果排序噪声偏大，在 Phase 10 验证中可降到 16。
- **Held-out 默认预算 5**：目前只是经验值，不是测量结果。`register` 时应支持按数据集调整。
- **TUI 的 dark/light theme 切换**：延期到 v0.3，除非用户明确要求。v0.2 只做 dark。

---

## 14. 参考资料

- Textual 文档：[https://textual.textualize.io](https://textual.textualize.io)
- k9s 快捷键速查：[https://k9scli.io/topics/commands/](https://k9scli.io/topics/commands/)
- lazygit 的快捷键设计哲学：[https://github.com/jesseduffield/lazygit/blob/master/docs/keybindings/Keybindings_en.md](https://github.com/jesseduffield/lazygit/blob/master/docs/keybindings/Keybindings_en.md)
- Elo rating 公式：[https://en.wikipedia.org/wiki/Elo_rating_system](https://en.wikipedia.org/wiki/Elo_rating_system)
- （沿用 v0.1）Claude Code hooks、fastmcp、uv、MCP protocol
