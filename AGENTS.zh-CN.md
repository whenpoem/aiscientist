# AGENTS.md

> English version: [AGENTS.md](AGENTS.md)
> 这份文档是给后续在本仓库工作的 LLM 或编码 agent 看的操作守则。项目定位与架构请先读 [`README.zh-CN.md`](README.zh-CN.md) 和 [`docs/overview.zh-CN.md`](docs/overview.zh-CN.md)——本文档默认你已经知道项目是干什么的。

## 编辑规则

- **优先做小而明确的改动，避免大范围重写**。本仓库小到让人忍不住想重写，而重写几乎总是错的。
- **保持 Windows 兼容性**。目标机器是 Windows 11。除非文件本身已经要求其他编码，否则首选 ASCII。
- **改了行为，必须在同一区域更新或新增测试**。"改了行为不改测试"是埋雷。
- **没重跑相关命令之前，不要声称修复成功**。"应该没问题"和"确实没问题"不是一回事。
- **仅凭单元测试通过，不要说"生产就绪"**。单测绿是必要条件，不是充分条件。
- **不要修改 `.research-agent/` 下的文件**。那是运行时状态，不是源代码。要改请走 MCP 工具。
- **不要绕过 `query_heldout`** 去读取隔离数据集。leakage hook 总归会拦下你，绕过它只会留下审计盲点。

## 验证规则

宣告成功之前，先跑与改动相匹配的检查。

最低基线：

```powershell
uv run ruff check
uv run pytest tests/memory_mcp tests/verify_mcp tests/prove_mcp tests/hooks tests/cockpit tests/scripts tests/e2e
```

改了 cockpit 代码，再 smoke-test TUI 入口：

```powershell
uv run python -m cockpit.tui --once
uv run python -m cockpit.tui --once --lang zh
```

改了集成点，再 smoke-test 后端：

```powershell
uv run python -c "import memory_mcp.server; import verify_mcp.server; import prove_mcp.server; import cockpit.mcp_server; print('OK')"
```

## 做非平凡改动之前要读什么

按以下顺序：

1. [`README.zh-CN.md`](README.zh-CN.md) —— 入门定位
2. [`docs/overview.zh-CN.md`](docs/overview.zh-CN.md) —— 心智模型
3. [`docs/architecture.zh-CN.md`](docs/architecture.zh-CN.md) —— 跨模块契约（视为约束性条款）
4. [`.claude/settings.json`](.claude/settings.json) —— MCP 与 hook 的接线
5. `src/` 下相关的包
6. `tests/` 下对应的测试
7. [`docs/archive/`](docs/archive/) —— 仅当改动涉及历史范围时

## MCP 与工具的注意点

Claude 的设置已经接好了下列 MCP 服务器：`memory`、`verify`、`cockpit`、`arxiv`、`openalex`。两个偶尔会让人意外的细节：

- **`openalex-research-mcp` 是用 `npx -y openalex-research-mcp@0.5.0` 启动的**，不是 `uv`，因为这个环境里它的真实包是个 Node CLI。
- **Cockpit MCP 走 stdio**，通过 `uv run python -m cockpit.mcp_server` 启动。没有 HTTP 传输。

修改了 `.claude/settings.json` 之后，要假定 Claude Code 需要新开 session 才能重载 MCP 和 hook。

## 数据库与状态注意点

共享运行时状态默认在 `.research-agent/state.db`，或者你显式覆盖了 `RESEARCH_AGENT_DB_PATH` 时指向的位置。这同一个数据库被以下组件使用：

- memory MCP
- verify MCP 的 provenance 存储
- cockpit 事件与干预流
- hooks（`intervention_pump.py`、`stop_flush.py` 等）
- 隔离数据集的注册与预算计数

调试时不要随便删除或覆盖这个 DB。如果某个测试需要隔离，请使用测试 fixture，而不是动真实状态文件。

## 已知的脆弱区

- **Hook 行为依赖共享状态文件**。如果 `.research-agent/state.db` 或 stop-flush 状态文件缺失或损坏，部分保护会降级为放行或回退行为。
- **Cockpit 实时视图是轮询的**。它每秒读一次 SQLite 事件。简单可用，但不是高吞吐设计。
- **隔离数据集的保护有多个输入**。它依赖 `RESEARCH_AGENT_HELDOUT_DIR`、注册过的 `ver_heldout_budgets.heldout_path` 行、pointer 文件，以及 `leakage_guard.py`。任何一项都不要绕过；要读数据请走 `query_heldout`。
- **Cockpit UI 标签必须经过 `src/cockpit/i18n.py`**，以保证中英文模式始终对齐。在 widget 内部硬编码字符串是退化行为。

## Git 上下文

当前 checkout 的默认分支是 `claudescientist`，已经推送到：

- `https://github.com/whenpoem/aiscientist.git`

不要在没有验证的情况下假设有 PR 存在。除非被明确要求，否则不要 force-push 这个分支。

## 范围实情

**v5.1.1 是当前版本。** 本补丁把公开 marketplace 的插件源码固定到同一发布标签。v5.1 系列修正 BT 排名、固定预注册 family、自动记录代码与
运行环境、区分保护强度，并加入公开 Codex 插件、统一 CLI/doctor 和完整 Cockpit
支持。hooks 尚未被 Codex 信任时，Cockpit 会明确降级为只监控。核心 MCP 默认
启用；arXiv、OpenAlex、Lean 可选。下面的 v5.0 段落只记录仍然有效的 UI 架构，
不再表示当前发行版本。

本仓库已经交付了 v3.0 计划（[`docs/archive/plan-v3.0.md`](docs/archive/plan-v3.0.md)）。不要在没有亲自验证剩余产品和运维预期的情况下，把它随便改写成 "V1.0 complete" 或 "production-ready"。

**v5.0.0 是上一版 UI 架构的来源。** v5.0 把 cockpit 改造成"研究动作监控":顶部新增**阶段栏**(`idle / explore / select / experiment / verify / prove / review / narrate` 八态),从最近 200 条 `cockpit_events` 派生,带抗抖动逻辑。主区改为 **ActivityPane**,把事件按家族(graph / bt / verify / prove / lean / intervention / narrate / risk)聚合成卡片,带 critical → low 严重度色。右侧 tab 新增 **Focus** 作为首位,实时显示 agent 当下在搞的节点。原 EventStreamPane 原样保留但降级为底部可折叠的**审计日志**(`A` 展开)。新增两个可选 MCP 原子工具——`cockpit__set_phase(phase, focus_nodes, intent)` 和 `cockpit__narrate(text, scope)`——给 SOP 作者提供合规的"分支点标注"通道,**不强制、不阻塞**,符合 ADR 0007。settings 新增 `phase_strip_visible`(`P` 切换)、`animations_enabled`(`M` 切换)。旧 `focused_pane="events"` 在 load 时自动治愈为 `"activity"`。**无 schema 迁移**。详见 [ADR 0011](docs/adr/0011-cockpit-activity-streaming.md) 和 [architecture.zh-CN.md §14](docs/architecture.zh-CN.md#14-cockpit-activity-streaming-v50)。

**v4.2.0 是上一版本。** v4.2 分四个 alpha 落地：a0 给向量后端加了多服务商支持并打磨了设置向导；a1 重整了仪表盘的信息结构（tab 分组、可折叠详情分节、按面板划分快捷键作用域）；a2 新增了报告导出（`cockpit.export` 模块，5 种报告 × 2 种格式，Reports 标签页，导出弹窗，`verify_mcp.export_report` 工具）；a3 加了冷启动 Welcome 屏。结题报告、完整草稿、诊断摘要等长内容以 markdown / HTML 文件写到 `reports/`——见 [ADR 0009](docs/adr/0009-reports-as-files-monitoring-as-tui.zh-CN.md)。向量后端通过 `RESEARCH_AGENT_EMBED_BASE_URL` 对接任何 OpenAI 兼容服务商（已测试 DashScope / Jina / Voyage / GLM）——见 [ADR 0010](docs/adr/0010-multi-provider-embeddings.zh-CN.md)；默认本地模型 `Qwen/Qwen3-Embedding-0.6B`；语料行携带 `(backend, model, dim)` 三元组。证明主干在 v4.0 交付：`prove_mcp` MCP server、`prove-sop` skill、`prover` agent 定义、`scripts/` 下的冷启动种子脚本，以及 reviewer 的双 checklist。Lean 形式化保险层保持可选：`.claude/settings.json` 里的 `_lean` 默认禁用，需要用户按 [`docs/setup-lean.zh-CN.md`](docs/setup-lean.zh-CN.md) 手动安装 elan + mathlib + lean-lsp-mcp 后才启用。两主干架构见 [ADR 0008](docs/adr/0008-two-trunk-domain-architecture.md)；能力入场纪律见 [ADR 0007](docs/adr/0007-tools-skills-hooks-layering.md)；内核/主干切分线见 [architecture.zh-CN.md §13](docs/architecture.zh-CN.md#13-共用内核与领域主干v40)。

完整的当前范围与 MCP 工具清单请见 [`docs/tool-reference.zh-CN.md`](docs/tool-reference.zh-CN.md)。
