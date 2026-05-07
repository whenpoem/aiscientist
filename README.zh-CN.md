# ClaudeScientist

> English version: [README.md](README.md)

ClaudeScientist 是给 Claude Code 加装的一层科研增强层。它不替换 Claude Code 的运行时，而是补上 AI 科研系统普遍缺失的那一层：持久化记忆、可验证的实验结果、可中断的研究循环，以及实时的人机协作面板。

仓库当前交付的是 **v3.0** 计划：把研究流程做成一场带预算控制的 Bradley-Terry 锦标赛，配以诚实的 95% 置信区间、可刷新的溯源 DAG，以及带多重比较校正的预注册机制。

**v4.0.0a0（alpha）已发布**：项目已扩展为**两主干架构**——现有的 ML 可重复性接口是 *empirical 主干*，新增的 *proof 主干*（`prove_mcp`）负责统计证明生成，可选 Lean 形式化保险层。两条主干共用一个内核：假设图、错题本、BT 锦标赛、校准、replay、cockpit。冷启动数据放在 `data/`；Lean 是按需启用（详见 [`docs/setup-lean.zh-CN.md`](docs/setup-lean.zh-CN.md)）。详见 [ADR 0008](docs/adr/0008-two-trunk-domain-architecture.md) 与 [architecture.zh-CN.md §13](docs/architecture.zh-CN.md#13-共用内核与领域主干v40)。

## 五分钟入门

如果你是第一次接触本项目，建议按下面的顺序阅读：

1. **[`docs/overview.zh-CN.md`](docs/overview.zh-CN.md)** —— 完整的心智模型
2. **[`docs/workflows/first-research-task.zh-CN.md`](docs/workflows/first-research-task.zh-CN.md)** —— 跟着一个真实任务走一遍
3. **[`docs/architecture.zh-CN.md`](docs/architecture.zh-CN.md)** —— 跨模块契约
4. **[`docs/tool-reference.zh-CN.md`](docs/tool-reference.zh-CN.md)** —— 完整的 MCP 工具目录

每个核心决策的精炼理由：**[`docs/adr/`](docs/adr/)**。

展望未来：**[`docs/roadmap.zh-CN.md`](docs/roadmap.zh-CN.md)** 列出了 v3.0 之后的发展方向。

历史设计决策保存在 **[`docs/archive/`](docs/archive/)**。

## 项目里有什么

- **Memory MCP** —— 假说图（含 proof 主干 node kind）、Bradley-Terry 排名（hypothesis 与 proof_skeleton 跨 kind 互比）、校准账本、回放分支（覆盖 proof 子树）、错题本（跨域）、压缩文献笔记
- **Verify MCP** —— 泄漏检测、可刷新的溯源 DAG、指标 pin、种子扰动、baseline 公平性、隔离数据集预算控制、带 BH/Bonferroni 校正的预注册、资源账本
- **Prove MCP** *(v4.0)* —— 证明语料 + 双向 max-matching 检索、NL 工作流（切片 → 诊断 → 修正）、Lean 形式化保险层接口（triage + attempt log）
- **Hooks** —— PreToolUse 的泄漏与破坏性命令拦截、PostToolUse 的溯源记录、干预注入、感知 proof 事件的 stop flush
- **Cockpit TUI** —— 终端优先的监控与干预界面，支持中英文标签切换，自带实时 Bradley-Terry 排行榜，能渲染 proof 主干事件
- **冷启动数据** —— `data/proof_corpus_seed.jsonl`（≥80 道统计证明问题）+ `data/proof_failure_seed.jsonl`（≥60 条常见证明错误模式），由 `scripts/seed_proof_corpus.py` / `scripts/seed_proof_failures.py` 加载

## 快速开始

在仓库根目录安装依赖：

```powershell
uv sync                  # 只装 ML / empirical 主干
uv sync --extra proof    # 同时装 sentence-transformers，用于 proof 主干
```

`uv sync --extra proof` 之后，灌一次冷启动语料：

```powershell
uv run python scripts/seed_proof_corpus.py
uv run python scripts/seed_proof_failures.py
```

默认 embedding 后端是 `local`（sentence-transformers/all-MiniLM-L6-v2）。可用 `RESEARCH_AGENT_EMBED_BACKEND=mock|openai` 覆盖；测试自动 pin 为 `mock`。

Lean 形式化保险层是**按需启用**。需要时按 [`docs/setup-lean.zh-CN.md`](docs/setup-lean.zh-CN.md) 一次性安装 elan + mathlib + lean-lsp-mcp。

日常使用时，从仓库根目录打开两个终端。

**终端 A** 运行 Claude Code。它会按照 `.claude/settings.json` 启动 memory、verify、cockpit、arxiv、openalex 这几个 MCP 服务器：

```powershell
cd D:\aiscientist\claudescientist
claude
```

**终端 B** 运行 cockpit TUI：

```powershell
cd D:\aiscientist\claudescientist
uv run python -m cockpit.tui
```

在 Windows Terminal 上启用中文 UI：

```powershell
cd D:\aiscientist\claudescientist
chcp 65001
$env:PYTHONUTF8=1
uv run python -m cockpit.tui --lang zh
```

在 TUI 内部按 `L` 可以在中英文标签之间切换。

## 运行时布局

默认的本地状态：

- 共享运行时 DB 在仓库根目录下的 `.research-agent/state.db`
- 隔离数据集目录默认放在 `%USERPROFILE%` 下，可以用 `RESEARCH_AGENT_HELDOUT_DIR` 改写

常用命令：

```powershell
uv run python -m memory_mcp.dev_server
uv run python -m verify_mcp.dev_server
uv run python -m cockpit.mcp_server
uv run python -m claudescientist.heldout register <name> <path>
```

## 验证

提交改动之前的常规检查：

```powershell
uv run ruff check
uv run pytest tests/memory_mcp tests/verify_mcp tests/hooks tests/cockpit tests/e2e
uv run python -m cockpit.tui --once --lang zh
uv run python -c "import memory_mcp.server; import verify_mcp.server; import cockpit.mcp_server; print('OK')"
```

## 状态与范围限制

本仓库适合本地开发和集成工作，但在没有完整的端到端回归之前，不应被描述为"生产就绪"。

- **自动剪枝默认是 dry-run**。设置 `RESEARCH_AGENT_AUTO_PRUNE=1` 才会让 `suggest_pause_low_strength` 真正把 `mem_bt_ratings.status` 翻到 `paused`。
- **Cockpit 是终端优先**。没有受支持的浏览器前端，没有 Vite，也没有需要启动的 `uvicorn` 进程。
- **Prover agent 还是占位**。Lean MCP 在本仓库中尚未接入。
- **`mem_nodes.elo_score` 作为向后兼容列保留**。新代码应当读 `mem_bt_ratings.strength` 等字段。

完整的工具列表和已知范围限制请见 [`docs/tool-reference.zh-CN.md`](docs/tool-reference.zh-CN.md) 和 [`AGENTS.md`](AGENTS.md)。
