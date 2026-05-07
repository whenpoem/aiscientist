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
uv run pytest tests/memory_mcp tests/verify_mcp tests/hooks tests/cockpit tests/e2e
```

改了 cockpit 代码，再 smoke-test TUI 入口：

```powershell
uv run python -m cockpit.tui --once
uv run python -m cockpit.tui --once --lang zh
```

改了集成点，再 smoke-test 后端：

```powershell
uv run python -c "import memory_mcp.server; import verify_mcp.server; import cockpit.mcp_server; print('OK')"
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

- **`openalex-research-mcp` 是用 `npx -y openalex-research-mcp` 启动的**，不是 `uv`，因为这个环境里它的真实包是个 Node CLI。
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

本仓库已经交付了 v3.0 计划（[`docs/archive/plan-v3.0.md`](docs/archive/plan-v3.0.md)）。不要在没有亲自验证剩余产品和运维预期的情况下，把它随便改写成 "V1.0 complete" 或 "production-ready"。

**v4.0.0a0（证明主干，alpha）已交付。** `prove_mcp` MCP server、`prove-sop` skill、`prover` agent 定义、`scripts/` 下的冷启动种子脚本，以及 reviewer 的双 checklist 都已 land。Lean 形式化保险层保持 opt-in：`.claude/settings.json` 里的 `_lean` 默认禁用，需要用户按 [`docs/setup-lean.zh-CN.md`](docs/setup-lean.zh-CN.md) 手动安装 elan + mathlib + lean-lsp-mcp 后才启用。架构层面的决策见 [ADR 0008](docs/adr/0008-two-trunk-domain-architecture.md)；新增能力的入场纪律见 [ADR 0007](docs/adr/0007-tools-skills-hooks-layering.md)；内核/主干切分线见 [architecture.zh-CN.md §13](docs/architecture.zh-CN.md#13-共用内核与领域主干v40)。

完整的当前范围与 MCP 工具清单请见 [`docs/tool-reference.zh-CN.md`](docs/tool-reference.zh-CN.md)。
