# 复盘 — v4.1.0a4

> English version: [retrospective-v4.1a4.md](retrospective-v4.1a4.md)
>
> Cockpit TUI 第二轮翻新。第一轮（v4.1.0a0）做出了"看上去被设计过"的样子；这一轮把只有真用起来才显形的坑全部填上——内容被默默截断、modal 吞按键、长内容没地方完整阅读、UI 措辞带 AI 味。8 项视觉小修 + 6 项交互修复 + 一套完整的预览/详情双层视图。**测试：cockpit + e2e 148，仓库整体 370，全过**（cockpit + e2e 改动前 89，新增 59）。Ruff clean。schema 未改——MCP / hook / DDL 全部零改动。

---

## 落地内容

### 阶段 0 — 去 AI 化措辞

`research-cockpit` / `研究座舱` 与 `cockpit events` / `cockpit 事件` 是项目营销词渗入运行 UI 的 4 处。换成用户敲定的中性表述：`research state` / `研究状态`、`No events yet.` / `暂无事件。`。两个测试文件的硬断言同步更新；[tests/cockpit/test_no_hardcoded_strings.py](../tests/cockpit/test_no_hardcoded_strings.py) 的回归守护未动（它扫的是已知错的字面量，`cockpit` 不在列表里）。

### 阶段 1 — 视觉小修（8 子项）

| # | 改动 | 文件 |
|---|---|---|
| 1.1 | `RichLog(wrap=True)` 默认 + `w` 切换、持久化 | [events_pane.py:19](../src/cockpit/panes/events_pane.py:19) |
| 1.2 | 8 种节点 ASCII 图标升 Unicode（`◇▲▣•★■△▴`），refuted 用 `✗` | [i18n.py:486](../src/cockpit/i18n.py:486)、[tree_pane.py:201](../src/cockpit/panes/tree_pane.py:201) |
| 1.3 | 树标签紧凑模式默认（不显 BT/Elo） + `i` 切详情、持久化 | [tree_pane.py:163](../src/cockpit/panes/tree_pane.py:163) |
| 1.4 | DataTable `[:48]` / `[:56]` 硬截断 → 排印 `…` 省略号，列宽放宽到 64 / 72 | [tabs_pane.py:_truncate](../src/cockpit/panes/tabs_pane.py) |
| 1.5 | 状态条心跳点（●/○ 按事件新鲜度切换）+ 干预入队 toast | [app.py:_format_last_event, _track_intervention](../src/cockpit/app.py) |
| 1.6 | 树面板 border title 显示 `· N 活跃 / M 已反驳` 计数 | [tree_pane.py:set_counts](../src/cockpit/panes/tree_pane.py) |
| 1.7 | detail pane 的 BT 强度 mini bar（`bt: +0.34 [───▮──────] ±0.18 n=12`） | [details.py:_bt_line](../src/cockpit/details.py) |
| 1.8 | held-out 预算进度条（`imagenet ▓▓▓▓░░ 4/10`）出现在 HUD + risks 表 | [app.py:_format_heldout](../src/cockpit/app.py)、[bars.py](../src/cockpit/bars.py) |

新模块 [`cockpit/bars.py`](../src/cockpit/bars.py)：`progress_bar()` / `strength_bar()` 字符条原语。**没有**塞进 `i18n.py`，因为字符条不本地化。

### 阶段 2 — 交互修复（6 子项）

| # | 改动 | 文件 |
|---|---|---|
| 2.1 | 帮助 modal：仅 `escape / enter / space / ?` 关闭；其他键 `event.stop()`，避免用户瞥一眼快捷键时随手按 `y` 触发危险动作 | [help.py](../src/cockpit/modals/help.py) |
| 2.2 | 命令行按 mode 留草稿；Esc 收起后再按 `:` 草稿仍在；提交后清空 | [app.py:_show_command_line](../src/cockpit/app.py) |
| 2.3 | `<` / `>` 调整 wide 布局下树列宽（subpreset -1/0/+1，持久化；narrow / single 布局下提示让用户去到 wide） | [layout-wide TCSS classes](../src/cockpit/theme/cockpit.tcss)、[app.py:action_shrink_tree](../src/cockpit/app.py) |
| 2.4 | `u` 撤销最近一次干预（仅当 `delivered_at IS NULL`）；已被 hook 消费的话报"too late" toast。refute / pin 这种不写 interventions 表的动作会清空 undo 指针，避免误回滚 | [data.py:undo_intervention](../src/cockpit/data.py)、[app.py:action_undo_intervention](../src/cockpit/app.py) |
| 2.5 | `Tab` / `Shift+Tab` 设 priority=True 让 DataTable 内也能切面板；modal 在栈顶时 Tab 转发到 `top.focus_next()`，PinMetricModal / TextInputModal 字段循环不受影响 | [app.py:action_focus_next_pane](../src/cockpit/app.py) |
| 2.6 | `:goto <id>` 按完整 id 或唯一前缀跳转树焦点；多个候选 → warning toast 列出 | [app.py:_goto_node](../src/cockpit/app.py) |

### 阶段 3 — 预览 + 全屏详情

这一轮的形态级改动。列表型面板（树 / 事件 / tabs）现在有两层详情深度：

1. **预览**：主屏 detail pane 跟随光标更新（保持 v4.1.0a0 行为）
2. **完整阅读**：Enter 推一个全屏 [DetailScreen](../src/cockpit/screens/detail.py)，`h / l` 走兄弟、`j / k` 滚动、动作键 `y / n / r / c / m / p / H` 仍然由 App 处理。Esc / `q` 弹出。

三个 source 实现 `DetailSource` Protocol：
- `NodeDetailSource` —— 走可见 node-id 列表；接受 graph **callable**（不是 snapshot），所以动作键改了状态后，全屏视图下一次重绘自动用最新数据。
- `TabRowDetailSource` —— 直接复用 App 现有的 `_row_detail`，覆盖全部 7 种 tab（risks / failures / claims / literature / corpus / diagnostics / lean），不重复任何渲染逻辑。
- `EventDetailSource` —— 把事件 payload 用 JSON pretty-print 出来。

渲染建造器集中到 [`cockpit/details.py`](../src/cockpit/details.py)，主屏 detail pane 与全屏 viewer 共享 `node_detail_text()`。

### 阶段 4 — 跨阶段 review 修补

阶段评审过程暴露了 3 个潜伏 bug，已全部闭环：

1. **priority 字符键吞 Input 字符**。`L`/`T`/`F`/`w`/`i`/`u`/`q` 设了 `priority=True` 是为了在 DataTable 焦点下也能触发，但在 modal Input 里这些键被 priority binding 拦截，用户输入字符时被吞。修复：每个 priority 字符 handler 调用 `_yield_priority_letter_to_input()` 帮手——检测 Input 焦点时通过 `insert_text_at_cursor` 把字符塞进去，并提前返回不触发 toggle。
2. **DetailScreen 内动作后内容陈旧**。在 DetailScreen 内按 `y`，App 刷新了主图状态，但屏幕仍渲染按键前的内容。修复：`NodeDetailSource` 改用 graph callable，`refresh_state()` 末尾顺便重绘栈顶 DetailScreen。
3. **DetailScreen 退出忘记同步导航**。在 DetailScreen 里 `l` 走到兄弟节点后按 Esc，主屏树焦点仍停在原位。修复：`action_pop_detail` 退栈前把 source 当前 node id 推给 `tree_pane.select_node_id(...)`。

---

## 最终统计

| 指标 | v4.1.0a0 | v4.1.0a4 | Δ |
|---|---|---|---|
| 测试数（cockpit + e2e） | 89 | **148** | +59 |
| 仓库整体测试数 | — | **370** | — |
| 新增测试文件 | 0 | 3 | +3 |
| Cockpit 源文件 | 16 | 19 | +3（`bars.py`、`details.py`、`screens/`） |
| i18n key（双语各） | ~190 | ~220 | +~30 |
| 公共 Screen 类型 | 1（仅 modals） | 2（modals + DetailScreen） | +1 |
| 视觉原语 | 0 | 2（progress / strength 条） | +2 |
| TCSS 中的 hex 字面量 | 0 | 0 | — |
| Cockpit DDL 改动 | 0 | 0 | — |
| Hook 契约改动 | 0 | 0 | — |

---

## 值得记录的设计决策

### 为什么把详情渲染抽到 `details.py`

最初 `NodeDetailPane.update_for_node` 把节点详情的全部布局都塞在一起：short-id 格式、BT 条、父子链、cross-edge 列表。当 DetailScreen 也需要相同内容时，要么继承 pane 类、要么 copy/paste，两种都不对。

正解是 `cockpit.details` —— 一个自由函数模块：输入 `(GraphSnapshot, node_id, lang)`，输出 `(title: str, body: Text)`。两个消费者（pane + screen）都走这条路径。`node_detail_text` 的单元测试不需要 Textual 生命周期。将来要加新消费者（比如导出 markdown），只需 import 一行。

### 为什么字符键既保 `priority=True` 又转发给 Input

v4.1.0a0 复盘文档里就记过这个权衡：priority=True 是为了 DataTable 焦点时不被 widget 吃。但代价——在 PinMetricModal 里输入大写 `L` 会切语言——是只有真用起来才看到的 bug。如果干脆去掉 priority，又会回到 v3.x 那个"在 tabs 面板里 L 似乎没反应"的旧问题。

折中方案：保留 priority；在每个 handler 里 `isinstance(self.focused, Input)` 判断；如果是，就用 `Input.insert_text_at_cursor(literal)` 把被 priority 偷走的字符还回去。用户两边都拿到：在 Input 之外随处可以触发 toggle，在 Input 里键能正常输入。

这是 workaround，不是 fix；Textual 没有 "priority but yield to Input" 这样的开关。如果将来支持，这块可以收敛成 `Binding(priority=True, yield_to_input=True)`。

### 为什么 DetailScreen 用 `_paint()` 而不是 `_render()`

Textual 的 `Widget._render()` 返回 `Visual`，是渲染管线的一部分。把自定义重绘方法命名为 `_render()`（沿袭 v4.1.0a0 panes 的习惯）会意外覆盖它并返回 `None`，导致整屏崩在 `NoneType.render_strips` 错误。改名 `_paint()`，留下文件注释解释来龙去脉，让下一位贡献者别再踩坑。

### 为什么 `q` 在有 modal/screen 时改成 pop 而非退出

计划里 `q` 在主屏退出 app、在 modal/DetailScreen 弹出。实现就是让 priority `q` binding 在 `screen_stack > 1` 时 `pop_screen()`。评审通过的理由：用户只学一个键（`q` = "返回 / 退出"）；纯键盘用户感觉 modal 比 `Esc` 更快收掉；通过 `len(screen_stack) > 1` 显式检查保留主屏不变量（`q` = quit）。

Input 焦点让出（见上一节）保证用户在 Input 里输入字符 `q` 仍然正常——priority binding 不会拦截字符。

### 为什么 `graph_provider` 传 callable 不传 snapshot

`NodeDetailSource` 第一版构造时就持有 `GraphSnapshot` 引用。当用户在 DetailScreen 内按 `y`，App 的 `refresh_state()` 重建了 `self.graph`（新的 GraphSnapshot 对象），但 source 还指向旧的——屏幕继续显示按键前的节点状态。

改成 callable（`lambda: self.graph`）让 source 每次 `current()` 都拿最新 snapshot。代价是每次重绘多一次方法调用；收益是正确性。`test_node_detail_source_reads_fresh_graph_each_call` 锁定这个行为。

---

## 本轮明确不做的项

下面是想过但确认本轮不做的：

- **Sparkline 节奏带**（roadmap Direction 7）—— 价值高但需要新渲染原语
- **Visual mode 多选**批量批准/拒绝
- **OSC 52 复制到剪贴板**
- **终端标题写实时状态**
- **暂停子树整链 dim**
- **主屏 detail pane 30 行预览模式**—— drill-in 已经覆盖长内容场景，预览面板继续保持完整
- **基于订阅的 DetailScreen 刷新**—— 当前是 `refresh_state()` 末尾轮询；用 Textual 的 reactive watcher 更优雅但加机制收益小

涉及 schema、hooks、MCP server 的都被设计性地排除——本轮严格只动 UI。

---

## 反思

### 做得好

1. **分阶段。** 阶段 0 → 1 → 2 → 3 每段都先全绿再进下一段。阶段 3（结构改动）建在已验证的基础上，所以 priority binding 回归一冒头就能马上判定是阶段 3 的锅，不是和 1/2 的相互作用。
2. **自由函数式详情建造器。** `details.py` 是最小化重构（没引入类层级、渲染侧不需要 protocol，只是 `(args) → (title, body)`）。已经在测试简单度（直接 `assert "..." in body.plain`）上回报，未来加导出特性也是天然扩展点。
3. **每个 forwarding bug 都配回归测试。** 每个 priority binding 修复都附带一个测试，复现确切的键序与上下文。`test_priority_letters_yield_to_input_focus` 和 `test_enter_inside_text_input_modal_submits_value` 锁住正确行为；将来谁把 priority 翻回去或者删 yield helper，CI 立刻挂。
4. **改名走 `AskUserQuestion`。** 命名是品味问题；把候选项摆出来让用户拍板，避免反复改文案的循环。

### 做得不好

1. **把 screen 重绘命名 `_render()`。** 浪费 ~20 分钟在 `NoneType.render_strips` 错误上才注意到方法名冲突。已在文件注释里记下来，避免重蹈。
2. **DetailScreen 第一版 CSS 用了 `dock: top` / `dock: bottom`。** 同样的 null-visual 症状但是另一个原因——Textual docked 子节点跟 Screen 基类布局交互。改成 vertical layout 加显式 `1fr` 高度就干净了。
3. **`Tab` 加 priority=True 但没做 modal 转发。** 立刻把 PinMetricModal 字段循环搞断了。被 `test_cockpit_app_smoke` 第一时间抓到——那个测试就是 p / Tab / Tab / Tab 走 metric modal。修复就是 4 行 + 一段注释。
4. **Enter 转发起初不知道 async。** 当前 Textual 的 `Input.action_submit` 是 coroutine；我直接调而没 `await`，产生 `RuntimeWarning: coroutine ... was never awaited`，input 也没真提交。把 App action 改成 async，转发的 coroutine 用 `await` 处理。

### 一处中途发现，标记给 v4.2

`EventDetailSource` 走的是 events pane 的 `_rows` 私有属性。tabs 同样走 `_filtered_rows`。能跑，因为 row 本身就是简单 list；但属于抽象泄漏——两个面板都应该暴露 `current_rows() -> list[dict]` 公共方法。不阻塞、不在本轮范围，但下次改动这两个面板时值得顺手做掉。

---

## 收尾

v4.1.0a4 是 cockpit 从"看起来被设计过"过渡到"用起来像被人提前用过"的那个补丁。drill-in 屏幕填上了 v4.1.0a0 复盘里 deferred 列表中唯一的大 UX 缺口（长内容可读性）。去 AI 化的措辞是个小改动但带来真实的感知提升。其他都是"第一次用之后才显形的微摩擦"——而那些恰恰是值得修的。

schema 没动；hook 契约没动；公共 MCP 接口没动。这次补丁的 blast radius 就是 cockpit 自己的键盘事件和像素。

---

*复盘版本：1.0 · 2026-05-08 · 基础 commit：待定 · tag：`v4.1.0a4`*
