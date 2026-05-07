# 复盘 — v4.1.0a0

> Plan v3 落地。Cockpit TUI 大刀阔斧升级：4 套主题（默认 warm-dark），三列自适应布局 + F 键焦点模式，3 个证明栈新页签（语料 / 诊断 / Lean），Ctrl+P 命令面板，6 处 i18n 回归修复 + 永久回归测试守卫。Tag `v4.1.0a0` 位于 `claudescientist` 分支头。
>
> 测试：**302 通过**（v4.0.0a1 时为 239；新增 63 项，未删除）。Ruff clean。Schema 与 v4.0.0a1 一致（memory_mcp v5 / verify_mcp v4 / cockpit v1 / prove_mcp v4）—— TUI 升级未触及任何 DB 表。

---

## 落地内容

### G1 — 设计系统基座

- `src/cockpit/theme/themes.py` — 通过 Textual 主题系统注册 4 套 `Theme`：`claude-warm-dark`（默认，Anthropic 暖橙 #d97757）、`claude-warm-light`、`claude-cool-dark`（保留早期 GitHub-dark 风味，给 SSH / 老终端用）、`claude-high-contrast`（WCAG AAA）。
- `src/cockpit/theme/tokens.py` — 运行时访问器（`color()` / `style()` / `kind_color()`），动态构造 Rich `Text` 风格的 widget 通过它从当前主题取色。模块级 `_CURRENT_VARS` 在主题切换时由 `update_theme_vars()` 回调刷新。
- `src/cockpit/theme/cockpit.tcss` — 完全重写。**零 hex 字面量**。只用 Textual 标准 `$variables`（`$primary`、`$surface`、`$panel`、`$boost`、`$foreground` 等），因为这个文件在 App 初始化注册自定义主题之前就被解析了。
- 所有 `modals/*.py` 的 `DEFAULT_CSS` 也清除了 hex。
- `src/cockpit/settings.py` — TOML 持久化到 `~/.config/claudescientist/cockpit.toml`（Windows 上是 `%APPDATA%`）。带 schema 版本号。`RESEARCH_AGENT_COCKPIT_CONFIG` 环境变量给测试用。
- `T` 键循环切主题；选择立即持久化。
- 测试：`test_themes.py`（16 项）、`test_settings.py`（9 项）。

### G2 — 布局 v3

- `src/cockpit/layout.py` — 3 个布局预设（`wide` / `narrow` / `single`）+ 断点逻辑（`WIDE_MIN_WIDTH=120`、`NARROW_MIN_WIDTH=80`）。`focus` 是面向用户的别名，不论终端多宽都解析为 `single`。
- TCSS 重写出 3 个 `#body-grid.layout-*` 规则集。compose 顺序改为 Tree → Detail → Tabs → Events，让 grid 自动布局在三种 layout 下都把每个面板放到正确的格子。
- `F` 键切换单面板焦点；`Esc` 恢复。设置持久化。焦点模式下切换面板 = 切换可见面板（不必退出焦点 → 切面板 → 再进焦点）。
- `App.on_resize` 在终端尺寸变化时重新解析布局类，但**只能向下降级，不会自动升级**——保留用户意图。
- 测试：`test_layout_adaptive.py`（16 项，含 2 个 160 列下的 `App.run_test` 集成测试）。

### G3 — 证明栈面板

- `RightTabsPane` 新增 3 个页签：**语料 (Corpus)**、**诊断 (Diagnostics)**、**Lean**。`TAB_ORDER` 现为 7 个；循环键 (`f`) 遍历全部。
- `src/cockpit/data.py` 新增 3 个 fetcher——`fetch_corpus_problems`、`fetch_diagnostic_manifests`、`fetch_lean_attempts`——各自被 `_table_exists` 守卫，所以 v3.x 的 DB（无 `prv_*` 表）返回 `[]` 而非报错。
- 状态图标：⏳ ✓ ✗（诊断）；✓ ✗ ⌛ ⏸ ▶（Lean）。状态标签按语言翻译。
- 详情下钻（`Enter`）在 `app._row_detail` 里通用化：现在同时处理 Corpus / Diagnostics / Lean 与既有的 Risks / Failures / Claims / Literature 行。
- 证明事件的细粒度刷新派发：`proof_corpus_ingested` → `_refresh_corpus()`，`proof_diagnosis_*` → `_refresh_diagnostics()`，`lean_proof_*` → `_refresh_lean()`。不再走全表刷新。
- ~32 个新 i18n 键（corpus_*、diagnostics_*、lean_*），en + zh 都齐。
- 测试：`test_proof_panes.py`（11 项）：空 DB 优雅、有数据时行解析正确、派发路由到正确页签、下钻产出本地化详情。

### G4 — 收口与成熟化

- `src/cockpit/commands.py` — Textual `Provider` 子类把每个 cockpit 动作注册到内置命令面板（Ctrl+P）。`ThemeSwitcherCommands` 让用户直接跳到某个具体主题，不必 T 循环 4 次。`cockpit_action_entries(lang)` 抽成自由函数，单测枚举行为时无需 Provider 完整运行时。
- 6 处 i18n 回归全部修复（`docs/retrospective-v4.0a0.md` 审计的发现）：
  - `app.py:608` "Root cause:" → `t(lang, "failure_root_cause")`
  - `app.py:625` "Resolution:" → `t(lang, "failure_resolution")`
  - "Signature:" → `t(lang, "failure_signature")`
  - `app.py:634` "Venue:" / "Source:" → `t(lang, "lit_venue")` / `t(lang, "lit_source")`
  - claims 下钻里的 "Note:" / "Source:" → `t(lang, "claim_note")` / `t(lang, "claim_source")`
- `tests/cockpit/test_no_hardcoded_strings.py` — 永久回归守卫。扫描 5 个 cockpit 源文件，检查已知坏字面量（`"Root cause:"`、`"Venue:"` 等）是否再次出现，并断言每个新增 i18n 键都同时有 en / zh。再次引入 = CI 红。
- 测试：`test_commands.py`（4 项）、`test_no_hardcoded_strings.py`（7 项）。

---

## 终态指标

| 指标 | v4.0.0a1 | v4.1.0a0 | Δ |
|---|---|---|---|
| 测试数 | 239 | **302** | +63 |
| Cockpit 测试文件 | 3 | 8 | +5 |
| Cockpit 源文件 | 12 | 16 | +4 |
| i18n 键数（每语种） | ~140 | ~190 | +~50 |
| TCSS / modals / panes 中的 hex | 12 | **0** | -12 |
| 主题数量 | 1（硬编码） | 4（已注册） | +3 |
| 布局模式 | 1（固定 2×2） | 3（自适应） | +2 |
| 右侧页签 | 4 | 7 | +3 |
| 双语 UI 键覆盖 | 部分 | 完整 | — |

---

## 值得记录的设计选择

### 为什么默认 `claude-warm-dark`

用户明确要求"与 Claude Code 搭配和谐"。Anthropic 品牌暖橙 (#d97757) 是显然的对齐方向。我们把它设为默认，但同时把 `claude-cool-dark`（之前的 GitHub-dark 配色）保留为一键切换的备选——老终端或习惯旧配色的用户不被强迫重学。T 键循环切换是免费的。

### 为什么三列宽屏布局而不是 2×2

原 2×2 把**事件流**放在右下，外周视觉最弱的位置，但事件流是变化最频繁的（1 秒一次轮询）。把事件流提到完整的右列（row-span 2），新事件总是落在视觉敏感区。Tabs 沉到 Detail 下面，因为 Tabs 变化最少（手动交互）。

### 为什么 F 键映射到 `single` 而不是单独的"focus" 预设

两种都试过。用户心智模型是"我想专注"，不是"我想 layout=single"。F 切到焦点后，调整窗口大小时如果焦点模式被自动 resolve 成其他 layout，会让用户惊讶。`focus` 作为永远 resolve 为 single 的预设保留契约。

### 为什么 TCSS 只用 Textual 标准变量

Textual 在 `App.__init__` 里运行 `register_theme()` **之前**就解析 `CSS_PATH`。自定义变量像 `$kind-hypothesis` 在 TCSS 里会无法解析。两个方案：(a) 把所有自定义 token 消费从 TCSS 移到 widget 里通过 `tokens.color()` 拿，(b) 想办法让 `register_theme()` 更早跑。我们选 (a)，因为分离更干净：TCSS 处理结构样式（边框、布局、padding）用 Textual 既定调色板；Rich Text 渲染处理语义样式（kind 图标、状态色）用 token。性能：`_CURRENT_VARS` 是进程内 dict，O(1) 访问，无可测开销。

### 为什么命令面板是叠加而非替代 `:` 模式

`:` 命令模式在 `docs/workflows/` 已有文档、有重度用户的肌肉记忆，且支持自由参数（`note <text>`、`pin <session> <metric> <value>`），不适合固定动作的面板条目。新增 Ctrl+P 提升发现性，不破坏既有工作流。两者面向同一动作集合，用户按心智模型自选。

---

## 推迟到 v4.1.0a1+（Tier 1，按 影响÷成本 排序）

| 项 | 推迟原因 | 工时 | 影响 |
|---|---|---|---|
| **Sparkline**（BT 排行榜 + Lean 时长 + 留出预算条） | 锦上添花；空态提示已覆盖数据发现的核心场景 | 1 天 | 中 |
| **PaneHeader** widget（kind 图标 + i18n 标题 + 计数器） | 现有 `set_title` 已能覆盖基础情况 | 0.5 天 | 低-中 |
| **鼠标支持**（点击聚焦、滚轮翻动、状态栏分段点击） | 键盘优先仍是首要契约；鼠标纯加分 | 1 天 | 中 |
| **动画**（事件行淡入、modal 滑入）+ 减弱动画环境变量 | 装饰性；当前绘制已经够快、视觉上也干净 | 0.5 天 | 低 |
| **Help v2 多 Tab modal** | 单页 help 仍可用；多 Tab 是收口 | 0.5 天 | 低 |
| **增量图拉取** (`fetch_graph_delta`) | 当前全表拉每秒 O(N)；N<1000 时不痛 | 1 天 | 节点数大时高，现在低 |
| **Detail 面板 memo** | 同上——目前没测到性能问题 | 0.5 天 | 低 |

### 故意不做的（v4.1 的设计选择，不是遗忘）

- **不做 web UI**（ADR 0003 重申）
- **不加新语种**（en/zh 之外）
- **不替换 `:` 命令模式**（仅叠加 palette）
- **不加多用户模式**
- **不做力导向图可视化**

---

## 反思

### 做得好的

1. **分阶段（G1→G4）每段都绿后再走下一段**。主题系统先以 25 个新测试落地，再动布局——没有交叉调试的痛苦。G2 → G3 → G4 同理。
2. **Token 解析器走模块级 dict 而不是 App introspection**。最早试 `App.get_running_app()` 风格的查找；第一个失败测试后切到 `update_theme_vars()` 回调。更简单、更可测、App 挂载前也能用。
3. **硬性的 hardcoded-string 回归测试**。20 分钟写完，将来省下小时级的"咦这个标签为什么不翻译"。v4.0a0 复盘审计找出的 6 处修复永久锁定。
4. **改 compose 顺序作为布局原语**。不用显式的 `column:` / `row:` 放置（Textual 的 grid 是顺序驱动而非坐标驱动），把 compose 从 Tree-Detail-Events-Tabs 改成 Tree-Detail-Tabs-Events，三种 layout 的 auto-flow 一次性都对了。CSS 更少、行为更显然。

### 做得不好的

1. **第一次 TCSS 重写试图用自定义 `$border-active` / `$kind-hypothesis` 变量**。失败因为 Textual 在 `register_theme()` 跑之前就解析了 TCSS。回退后切分：结构 CSS 用标准 `$variables`；语义色走 `tokens.color()` 在 Rich Text 渲染时取。耗时约 30 分钟。
2. **第一次 provider 测试试图 `Provider(app, screen)`**。新 Textual 加了 `match_style` kwarg 要求。把 `_entries` 抽成自由函数 `cockpit_action_entries(lang)`，单测不需要完整的 Provider 生命周期。本来就更干净——函数是单一来源、Provider 是薄包装。
3. **Textual `App.run_test()` 默认尺寸是 80×24**。第一个 layout 集成测试失败因为 app 解析为 `narrow` 而非 `wide`。解法：显式传 `size=(160, 40)`。在测试 docstring 里写明白让下一个人不再踩。
4. **`test_settings` 起初 monkeypatch `os.name`**。在 Windows 上想伪装成 posix；pytest 内部然后试图构造 `PosixPath` 崩了。去掉伪装、改为对路径片段断言。教训：测试中途别 monkeypatch `os.name`。

---

## 收尾

v4.1.0a0 是 cockpit 第一次"看上去像设计出来的"而不是"组装出来的"。暖色深色主题是有意的；布局自适应；证明栈有真正的可视入口；双语由 CI 强制；命令面板是可发现的。推迟项都是 polish——没有一项阻塞日常使用。

下一步自然的动作是在新 UI 上跑一遍真实端到端研究（Plan v2 推迟的、由用户拥有的事），把自动化测试发现不了的边角磨出来。在那之前，v4.1.0a0 站得住。

---

*复盘版本：1.0 · 2026-05-07 · 基础 commit：待定 · tag：`v4.1.0a0`*
