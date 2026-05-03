# 计划：Claude Code 的 Research-Agent 增强层

> **状态**：可直接执行的详细方案，v0.1 范围 = Phase 0–6（从脚手架一直到文献压缩）。
> **目标机器**：Windows 11，项目路径为 `D:\aiscientist\claudescientist`（当前为空）。
> **原则**：不改动 Claude Code 本体。所有能力都通过外围接入的 MCP server、hook、skill 和 subagent 模板来提供。
>
> **已锁定决策**（细节见第 9 节）：
> - **Python 环境**：`uv`
> - **v0.1 范围**：Phase 0–6，约 15–18 个工作日
> - **文献 MCP**：原样安装 `arxiv-mcp-server` 和 `openalex-research-mcp`；我们的 `memory-mcp` 只是在外面包一层很薄的 `ingest_paper` 压缩逻辑
> - **Cockpit-MCP 传输方式**：HTTP，地址为 `http://localhost:7777/mcp`（把 fastmcp 子应用挂载到同一个 uvicorn 进程里的 REST/WS cockpit 中）

---

## 1. 背景

我们要在 Claude Code 之上，给统计 / DS / AI 研究自动化做一个“脑外挂（brain prosthesis）”。动机和最初的 brief 没变：

- 现有 AI-Scientist 系统（EvoScientist、AI Scientist v2、AI-Researcher、InternAgent）有 40–60% 的代码都花在 agent runtime 这类基础设施上，而 Claude Code 已经免费把这部分做好了。
- 它们所谓的“持久记忆”基本只是向量余弦相似度，没有只追加语义、没有矛盾信息、也没有时间维度。
- 它们所谓的“验证”基本只是“代码跑没跑起来”，没有 reward hacking 检查、没有泄漏检查、也没有结果溯源。

我们的判断是：只补真正缺失的那一层（memory、verification、cockpit UI），不去重造已经现成的运行时；同时让每个组件都能单独交付、单独发表。

最终交付物应该是一个单个研究者（也就是你，在 Windows 11 上）每天都能拿来跑真实研究任务的系统，并且未来可以自然升级到和 EvoScientist 做公开对比实验。

---

## 2. 技术栈速览

你前面说过，这里面有些组件你还不熟。下面每个组件都用 2 分钟讲清楚：它是什么、为什么选它、以及一个能跑的最小例子。

### 2.1 fastmcp 3.x — Python MCP SDK

**它是什么**：MCP（Model Context Protocol）是 Claude Code 和外部工具服务通信的协议。`fastmcp` 是一个基于装饰器的 Python 库，可以把普通 Python 函数直接暴露成 MCP 工具。截至 2026-04，当前版本是 **3.2.x**。

**为什么选它，而不是官方 `mcp` 包**：官方 `mcp` 包（1.27）要求你手写每个工具的 JSON Schema、自己处理底层请求/响应信封、还得自己管理 stdio server 循环。`fastmcp` 则直接从 Python 的类型注解和 docstring 里推导这些东西。我们这个项目大约有 3 个 server、20 个工具，用它能省掉几百行样板代码。

**最小示例**：

```python
from fastmcp import FastMCP

mcp = FastMCP("memory")

@mcp.tool
def record_failure(trigger: str, symptom: str, resolution: str) -> dict:
    """Record a failure for future signature matching."""
    # your logic here
    return {"failure_id": "f_42", "stored": True}

if __name__ == "__main__":
    mcp.run()  # defaults to stdio transport (what CC wants)
```

**在 Claude Code 中注册**（`.claude/settings.json`）：

```json
{
  "mcpServers": {
    "memory": {
      "command": "uv",
      "args": ["run", "python", "-m", "memory_mcp.dev_server"]
    }
  }
}
```

### 2.2 uv — Python 环境与脚本运行器

**它是什么**：`uv` 是 Astral（也是 `ruff` 的作者团队）用 Rust 写的 Python 包管理器 / venv 管理器 / 脚本运行器。基本相当于把 pip、virtualenv、pip-tools、pyenv、pipx 合并成了一个二进制工具，而且它连 Python 本身都能装。

**为什么它在 Windows 上尤其重要**：Claude Code 的 hook 本质上就是 shell 命令。如果 hook 写成 `python hooks/pre.py`，马上会踩进 Windows 的老坑里：`python` 可能没进 PATH，`python3` 默认不存在，项目的虚拟环境也不会自动激活。而 `uv run python hooks/pre.py` 会自动找到项目的 `pyproject.toml`，解析出正确解释器并运行脚本，行为稳定、跨平台。

**Windows 安装方式**：

```powershell
winget install --id=astral-sh.uv -e
```

**典型用法**：

```powershell
# in project root
uv init --lib                    # creates pyproject.toml + .python-version
uv add fastmcp fastapi uvicorn   # like pip install, also updates lockfile
uv add --dev pytest ruff
uv run python -m memory_mcp.dev_server   # runs in project env, no activate needed
uv run pytest                    # same
```

`uv.lock` 会把依赖图完整锁死，保证可复现。

### 2.3 SQLite + FTS5

**它是什么**：SQLite 是单文件嵌入式数据库。FTS5 是它内置的全文检索扩展（支持 BM25 排序）。两者都直接随 Python 标准库里的 `sqlite3` 一起带着走，不需要额外安装。

**为什么不用 Postgres / DuckDB / 向量数据库**：这是单用户、单项目、本地优先的系统。我们希望整个状态就是一个能直接 `cp` 复制的文件。对我们这个规模来说，SQLite 的 WAL 模式足够应付多个写入方（3 个 MCP + cockpit）。

**为什么用 FTS5，而不是 scikit-learn 的 TF-IDF**：FTS5 本来就已经在 SQLite 里了。我们要的是对 failure ledger 做短语检索、子串检索和 BM25 排序，这些 FTS5 用 SQL 就能干。换成 scikit-learn 的 TF-IDF 流水线，反而还要自己管理持久化和重建索引，复杂度至少是 10 倍，但没有额外收益。

**最小 schema 示例**：

```sql
PRAGMA journal_mode=WAL;

CREATE TABLE mem_failures (
  failure_id INTEGER PRIMARY KEY AUTOINCREMENT,
  trigger TEXT NOT NULL,
  symptom TEXT NOT NULL,
  root_cause TEXT,
  resolution TEXT,
  first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
  seen_count INTEGER DEFAULT 1
);

CREATE VIRTUAL TABLE mem_failures_fts USING fts5(
  trigger, symptom, root_cause, resolution,
  content='mem_failures', content_rowid='failure_id'
);

CREATE TRIGGER mem_failures_ai AFTER INSERT ON mem_failures BEGIN
  INSERT INTO mem_failures_fts(rowid, trigger, symptom, root_cause, resolution)
  VALUES (new.failure_id, new.trigger, new.symptom, new.root_cause, new.resolution);
END;
```

查询方式（按 BM25 排序，最相关的排前面）：

```sql
SELECT f.* FROM mem_failures f
JOIN mem_failures_fts fts ON fts.rowid = f.failure_id
WHERE mem_failures_fts MATCH ?
ORDER BY bm25(mem_failures_fts) LIMIT 5;
```

### 2.4 FastAPI + WebSocket + uvicorn（cockpit 后端）

**它是什么**：FastAPI 是现代 Python Web 框架（可以把它理解成 Flask 的 async-first 版本，而且会根据类型标注自动生成 OpenAPI）。uvicorn 是跑它的 ASGI server。WebSocket 则是浏览器和服务端之间双向实时推送的协议，cockpit 会用它。

**为什么用它**：cockpit 需要两条通道：一条 REST 给 React 前端拉初始状态（比如 `GET /graph`、`GET /claims`），另一条 WebSocket 用来在研究过程发生变化时做实时推送。FastAPI 用非常直接的方式就能把这两件事都做了，大约 50 行规模。

**我们会采用的关键模式**：`fastmcp` 和 FastAPI **可以跑在同一个 Python 进程里**。`fastmcp` 的 `mcp.http_app()` 返回一个 Starlette/ASGI app，我们可以把它挂在 uvicorn 里的 `/mcp/*` 路径下。两边共享同一个 SQLite 连接池。所以 cockpit server 最终只需要一条 `uv run uvicorn cockpit.server:app`，不需要两个独立进程。

### 2.5 Vite + React + @xyflow/react + Tailwind v4（cockpit 前端）

**它们分别是什么**：
- **Vite**：JS/TS 打包器 + 开发服务器，带 HMR，取代已经过时的 Create React App。
- **React**：UI 框架。这里直接用 TypeScript 模板，版本 19。
- **@xyflow/react**：React 下的图形 UI 库，以前叫 `reactflow`，2023 年改名。当前是 12.x，平移/缩放/自定义节点/边这些能力都是现成的。
- **Tailwind v4**：utility-first CSS。v4（2025 发布）取消了原先那套 PostCSS 配置；现在只需要安装 `@tailwindcss/vite`，然后在 CSS 里写一句 `@import "tailwindcss";`。

**为什么是这一套**：它足够“无聊”，但能稳定产出生产级 UI。cockpit 是整个系统里最小的一块自定义前端，我们不该在这里做额外实验。

**第一次在 Windows 上配置**：

```powershell
# prerequisite: Node.js 20+
winget install OpenJS.NodeJS

cd D:\aiscientist\claudescientist\src\cockpit
pnpm create vite frontend --template react-ts
cd frontend
pnpm install
pnpm add @xyflow/react
pnpm add -D tailwindcss @tailwindcss/vite
pnpm run dev   # opens http://localhost:5173
```

### 2.6 lean-lsp-mcp — 第三方 Lean MCP

**它是什么**：这是一个仍在积极维护的、包住 Lean 4 LSP 的 Python MCP 封装。暴露的工具包括 `lean_goal`、`lean_verify`、`lean_run_code`、`lean_loogle`（按类型搜前提）和 `lean_leansearch`（自然语言搜前提）。仓库是 `oOo0oOo/lean-lsp-mcp`，MIT 许可，大约 300 star，并固定在一个已知可用的 tag 上。

**为什么直接用它**：这是目前唯一还活跃的 Lean MCP。自己重写一套大概要白白花掉两周时间，而且没有任何差异化收益。所以直接原样安装。

**安装与注册**：

```powershell
# adds lean-lsp-mcp as a uv tool (isolated env)
uv tool install lean-lsp-mcp

# separately: install Lean toolchain
# (elan is Lean's version manager; Windows installer available from elan-lang.org)
```

```json
{
  "mcpServers": {
    "lean": {
      "command": "uv",
      "args": ["tool", "run", "lean-lsp-mcp"]
    }
  }
}
```

---

## 3. 自研 / 复用决策矩阵

这是你最核心的问题。下面给出基于 2026 年 4 月 GitHub 生态扫描后的明确结论：

| 组件 | 决策 | 原因 |
|---|---|---|
| **memory-mcp** | **自研** | Anthropic 官方的 `memory` server 是 TypeScript 写的，存的是 entity / relation / observation，没有只追加语义、没有矛盾检测、没有 failure ledger 概念，也没有文献压缩 schema。真要 fork，核心几乎得重写。直接用 Python 从头写，预计 ~600 LOC。 |
| **verify-mcp** | **自研** | GitHub 上找不到 ML 专用的 verification MCP。SonarQube-MCP 这类东西只能做通用代码审查，根本不覆盖数据泄漏 / seed 敏感性 / baseline 公平性。直接自研，预计 ~800 LOC。 |
| **cockpit**（FastAPI + React） | **自研** | 这是新组件，没有现成等价物。后端大约 ~400 LOC，前端大约 ~600 LOC。 |
| **lean-mcp** | **原样复用** | 固定 `lean-lsp-mcp` v0.x，零开发成本。 |
| **文献摄取** | **混合** | 把 `blazickjp/arxiv-mcp-server` 和 `oksure/openalex-research-mcp` 作为独立 `mcpServers` 安装进来，开发成本为零。我们自己的 `memory-mcp` 只增加一个很薄的 `ingest_paper` 工具：负责调用它们拿到原始内容，再让 Claude（通过 subagent 主模型）做结构化抽取并本地存储。我们真正拥有的只有*压缩层*。 |
| **Skills（3 个 SOP）** | **自研** | 这是面向研究工作流的专用文本，不可能泛化成通用模板。大约 3 个、每个 100 行左右的 markdown。 |
| **Subagents（5 个角色）** | **自研** | 本质是工具白名单 + system prompt，大约 5 个、每个 50 行左右的 markdown。 |
| **Hooks（PreToolUse、PostToolUse、Stop、UserPromptSubmit）** | **自研** | 这是和我们自己 schema 紧耦合的胶水代码，大约 5 个、每个 80 行左右的 Python 文件。 |

**一句话版**：memory、verify、cockpit、hooks、skills、subagents 都自己写；lean-lsp-mcp、arxiv-mcp、openalex-research-mcp 全部原样安装，不额外造轮子。

---

## 4. 架构（关键决策）

### 4.1 高层结构图

```text
┌────────────────────────────────────────────────────────────────────┐
│         Research Cockpit — browser at http://localhost:7777         │
│   Hypothesis Graph  │  Verification Dashboard  │  Intervention Btns │
└──────────────────────────────┬─────────────────────────────────────┘
                               │  WebSocket (live push)
                               │  REST (initial state)
┌──────────────────────────────▼─────────────────────────────────────┐
│        cockpit/server.py — ONE uvicorn process                      │
│   FastAPI REST + WS  │  fastmcp sub-app mounted at /mcp             │
└──────────────┬────────────────────────────┬────────────────────────┘
               │                            │ stdio MCP
               │ shared SQLite              │
               ▼                            ▼
┌────────────────────────────┐   ┌────────────────────────────────────┐
│  .research-agent/state.db  │   │   Claude Code (untouched)           │
│  — mem_* tables            │   │  ┌──────────┐  ┌──────────────────┐ │
│  — ver_* tables            │◄──┤  │ 5 sub-   │  │ 3 skills         │ │
│  — cockpit_* tables        │   │  │ agents   │  │ (SOPs)           │ │
│  (WAL mode, FTS5)          │   │  └──────────┘  └──────────────────┘ │
└────────────────────────────┘   │  ┌────────────────────────────────┐ │
               ▲                 │  │ 5 hooks (settings.json)        │ │
               │                 │  └────────────────────────────────┘ │
               │ stdio MCP       └──────┬──────────┬──────────┬────────┘
               │                        │          │          │
┌──────────────┴──────┐   ┌─────────────▼──┐  ┌────▼───────┐  ▼
│  memory-mcp         │   │  verify-mcp    │  │ lean-mcp   │ (arxiv,
│  (our code)         │   │  (our code)    │  │ (3rd party)│  openalex)
└─────────────────────┘   └────────────────┘  └────────────┘
```

### 4.2 关键决策 A — 状态共享

**决策**：只用 **一个** SQLite 文件，位置在 `.research-agent/state.db`，用表名前缀做命名空间区分（`mem_*`、`ver_*`、`cockpit_*`）。开启 WAL 模式，外键开启。每个 MCP 自己开自己的连接，`isolation_level=None`，并显式使用 `BEGIN IMMEDIATE` / `COMMIT`。

**为什么不是分成多个数据库文件**：cockpit 在渲染“节点 + 证据 + 溯源”视图时，天然要跨三个子系统查数据。如果拆成三个文件，它就得自己在应用层做 join。合成一个文件之后，原子性（假设和它的 provenance 同事务提交）和引用完整性都白送。以我们的规模，WAL 从来不会是瓶颈。

### 4.3 关键决策 B — 干预队列机制

**决策**：cockpit 把干预操作追加写入 `cockpit_interventions`。`UserPromptSubmit` 和 `Stop` 两个 hook 都执行同一个 `intervention_pump.py`，负责把尚未投递的行取出来，注入下一轮的 `additionalContext`。紧急中止（`kind='halt'`）还会被 `PreToolUse` hook 单独捞出来，必要时直接 `exit 2`，在中途阻断危险操作。

**为什么不是做成 skill 或 tool**：skill 依赖 Claude 自己记得去调用，这件事太脆弱。hook 才是机械的、强制的。并且 `Stop` hook 是最早一个能在不中断当前工具调用的前提下，把外部干预交回 Claude 的点。

### 4.4 关键决策 C — Held-out 预留集（Windows 友好）

**决策**：held-out 数据 **不放在项目树里**，统一放到 `%USERPROFILE%\.research-agent\held_out\<proj_hash>\<dataset>\`。项目目录里只留一个 manifest（SHA-256 + schema + 行数）。防御策略做成四层：

1. **位置隔离**：默认放树外。
2. **PreToolUse 泄漏 hook**：对所有写入 `.py` 的 `Write` / `Edit` 做 AST 解析；对所有 `Bash` 命令做路径模式匹配，只要指向 held-out 目录就拦截。唯一例外是显式设置 `RESEARCH_AGENT_VERIFY=1`，而这个环境变量只允许 verify-mcp 去设。
3. **verify-mcp 成为唯一读取入口**，并且由 `ver_heldout_budget` 做预算计数。
4. **项目打开时校验 manifest hash**：如果 held-out 文件和 manifest 漂移，就把整个系统硬锁住，直到人工重新确认。

不依赖 Windows ACL，也不依赖 `chmod 000` 这种 Windows 根本没有的东西。

### 4.5 关键决策 D — v0.1 范围

**决策**：v0.1 直接交付 Phase 0–6（脚手架 → subagents+skills → memory-mcp v1 → verify-mcp v1 → hooks 打通 → 只读 cockpit + reject 按钮 → **文献压缩**）。对一个开发者的预计工期是 15–18 个工作日。

文献压缩原本打算放到 v0.2，但现在提前进 v0.1，理由有三点：(a) 不做这个，`librarian` subagent 基本就是摆设；(b) 既然 arxiv-mcp 和 openalex-mcp 都能原样安装，额外成本只有 ~3 天；(c) 一个不能检索文献的研究系统，其实没法在真实任务上测试。

其他一切（`seed_perturb`、`baseline_fairness`、held-out 预算强约束、prover subagent、多项目支持）都延后到 v0.2+，并且应该在你真的用 v0.1 跑过真实研究之后再做。

### 4.6 关键决策 E — Skill、subagent、hook 的边界

| 职责 | 机制 | 原因 |
|---|---|---|
| 阻止带有未验证 claim 的正式报告写入 | **PreToolUse hook**，拦截写 `.md` 的 Write/Edit | 这必须是强制策略，而不是建议 |
| 在每轮结束时刷新 hypothesis graph 的增量 | **Stop hook** | 这是机械性收尾，不该依赖 Claude 记得去做 |
| “执行完整研究 SOP” 这种工作流 | **Skill**（`research-sop`） | 这是多步骤语义流程，需要主线程上下文 |
| 阻止破坏性 bash 命令 | **PreToolUse hook** on Bash | 这是策略问题，不是语义推理问题 |
| 在研究流程里做文献综述子任务 | **Subagent**（`librarian`） | 独立上下文、工具调用预算较大 |

通用规则就是：**机械且必须的事情交给 hook，语义型建议交给 skill，隔离开的子问题交给 subagent。**

### 4.7 关键决策 F — 开发态热重载

**问题**：Claude Code 会在会话启动时把 MCP server 作为子进程拉起来，并在整个会话期间一直持有。也就是说，正常情况下我们每改一次 MCP 代码，都得重启一次 CC。

**决策**：每个 MCP server（`memory_mcp`、`verify_mcp`）都做两个入口：
- `server.py`：生产入口，启动时一次性导入全部逻辑
- `dev_server.py`：开发入口，在每次工具调用前执行 `importlib.reload(impl)`，并由 `RESEARCH_AGENT_DEV=1` 控制

开发阶段就让 `.claude/settings.json` 指向 `dev_server.py`。这样改代码 → 保存 → 调工具，就会自动重新加载。工具的*实现体*可以热更新；只有工具*签名*变化时才需要重启。对 90% 的迭代场景来说已经够用了。

---

## 5. 项目目录布局

```text
D:\aiscientist\claudescientist\
├── .claude\
│   ├── settings.json                    # MCP + hook registration
│   ├── agents\
│   │   ├── researcher.md
│   │   ├── engineer.md
│   │   ├── verifier.md
│   │   ├── librarian.md
│   │   └── prover.md                    # stub in v0.1, activated in v0.2
│   ├── skills\
│   │   ├── research-sop\SKILL.md
│   │   ├── debug-sop\SKILL.md
│   │   └── writeup-sop\SKILL.md
│   └── hooks\
│       ├── intervention_pump.py         # Stop + UserPromptSubmit
│       ├── leakage_guard.py             # PreToolUse (Write/Edit/Bash)
│       ├── destructive_bash_guard.py    # PreToolUse (Bash)
│       ├── provenance_log.py            # PostToolUse (Bash/Write)
│       └── stop_flush.py                # Stop (graph deltas)
├── src\
│   ├── memory_mcp\
│   │   ├── __init__.py
│   │   ├── server.py                    # prod entry
│   │   ├── dev_server.py                # dev entry with importlib.reload
│   │   ├── impl.py                      # all tool implementations
│   │   ├── db.py                        # shared connection helper
│   │   └── schema.sql
│   ├── verify_mcp\
│   │   ├── __init__.py
│   │   ├── server.py
│   │   ├── dev_server.py
│   │   ├── impl.py
│   │   ├── leakage.py                   # AST scanner
│   │   ├── provenance.py                # number-token extractor
│   │   └── db.py
│   └── cockpit\
│       ├── server.py                    # FastAPI + WS + fastmcp sub-app
│       ├── db.py                        # shared helper
│       └── frontend\
│           ├── index.html
│           ├── vite.config.ts
│           ├── package.json
│           ├── tailwind.config.js       # (v4 minimal config)
│           └── src\
│               ├── main.tsx
│               ├── App.tsx
│               ├── components\
│               │   ├── HypothesisGraph.tsx    # @xyflow/react
│               │   ├── VerificationTable.tsx
│               │   └── InterventionPanel.tsx
│               ├── hooks\
│               │   └── useWebSocket.ts
│               └── types.ts
├── .research-agent\                     # gitignored runtime state
│   ├── state.db
│   ├── logs\
│   └── sessions\
├── tests\
│   ├── memory_mcp\test_graph.py
│   ├── memory_mcp\test_failures.py
│   ├── verify_mcp\test_leakage.py
│   ├── hooks\test_intervention_pump.py
│   └── e2e\test_smoke.py
├── pyproject.toml                       # uv init
├── uv.lock
├── .python-version                      # 3.11
├── .gitignore
└── README.md
```

---

## 6. v0.1 可执行计划（Phase 0–6）

每个 phase 结束时都要有一个具体的验收检查。总工期预估：**15–18 个工作日**，单人开发。

### Phase 0 — 脚手架与工具链（半天）

**目标**：从空目录开始，得到一个能安装、能启动且 Claude Code 配置不报错的项目。

**命令（PowerShell）**：

```powershell
# prerequisites (skip if already installed)
winget install --id=astral-sh.uv -e
winget install OpenJS.NodeJS

cd D:\aiscientist\claudescientist

# Python project init
uv init --lib --name claudescientist --python 3.11
uv add fastmcp fastapi "uvicorn[standard]" pydantic
uv add --dev pytest pytest-asyncio ruff

# Directory scaffolding
mkdir -p .claude\agents, .claude\skills, .claude\hooks
mkdir -p src\memory_mcp, src\verify_mcp, src\cockpit\frontend
mkdir -p .research-agent\logs, .research-agent\sessions
mkdir -p tests\memory_mcp, tests\verify_mcp, tests\hooks, tests\e2e
```

**这一阶段要创建的文件**：

`.gitignore`：
```
.research-agent/
__pycache__/
*.pyc
.pytest_cache/
node_modules/
dist/
.venv/
```

`.claude/settings.json`（骨架版，hooks 和 MCP 后面再加）：
```json
{
  "mcpServers": {},
  "hooks": {}
}
```

`README.md`：写一段话的项目摘要即可。

**验收**：
```powershell
uv run python -c "import fastmcp; import fastapi; print('OK')"
# should print OK
```

---

### Phase 1 — Subagents 与 Skills 脚手架（1 天）

**目标**：5 个 subagent 模板 + 3 个 skill stub 都存在，并且能从 Claude Code 中调用。

**Subagent 工具白名单**（注意：不能写 glob，必须把工具名逐个列全）：

#### `.claude/agents/researcher.md`
```markdown
---
name: researcher
description: Read-only literature review, idea generation, and hypothesis proposal. Cannot modify code or files.
tools: Read, Glob, Grep, WebFetch, mcp__memory__get_active_frontier, mcp__memory__get_ancestors, mcp__memory__query_literature, mcp__memory__match_signatures
model: sonnet
---

You are a research assistant focused on idea generation and literature synthesis.

Your job:
1. Read relevant files and prior work.
2. Query the hypothesis graph for current state (`mcp__memory__get_active_frontier`).
3. Propose new hypotheses or refinements, grounded in retrieved literature.
4. NEVER write, edit, or run code. If an idea requires implementation, say so and stop.

Output format: a markdown list of proposed hypotheses with rationale and supporting references.
```

#### `.claude/agents/engineer.md`
```markdown
---
name: engineer
description: Implementation and experimentation. Can write code, run scripts, and record findings to memory.
tools: Read, Write, Edit, Glob, Grep, Bash, mcp__memory__propose_hypothesis, mcp__memory__attach_evidence, mcp__memory__record_failure, mcp__memory__match_signatures, mcp__verify__leakage_check, mcp__verify__record_provenance
model: sonnet
---

You are an ML engineer executing a specific experiment.

Before writing code:
- Call `mcp__memory__match_signatures` with a description of what you're about to do. If a similar past failure exists, read it and change approach.

While implementing:
- Use scikit-learn / PyTorch / NumPy idiomatically.
- Never `fit` a scaler on concatenated train+test.
- Never early-stop on the test split.
- Never hardcode paths into `.research-agent/held_out/`.

After running:
- Call `mcp__verify__record_provenance` with the numeric results.
- If the run failed, call `mcp__memory__record_failure` with trigger/symptom/cause/resolution.
```

#### `.claude/agents/verifier.md`
```markdown
---
name: verifier
description: Independent verification of claims. Read-only access to code; can run verification tools but cannot edit.
tools: Read, Glob, Grep, Bash, mcp__verify__leakage_check, mcp__verify__check_provenance, mcp__verify__seed_perturb, mcp__verify__verify_metric
model: sonnet
---

You are an adversarial verifier. Assume the engineer's claims are wrong until proven otherwise.

For every numeric claim in a report or commit message:
1. Check provenance: `mcp__verify__check_provenance`. Claim without provenance → red flag.
2. Check leakage: `mcp__verify__leakage_check` on the training script.
3. If the claim is central, run `mcp__verify__seed_perturb` to see if it survives.

You CANNOT edit files. If you find a problem, report it and stop — the engineer must fix it.
```

#### `.claude/agents/librarian.md`
```markdown
---
name: librarian
description: Discover and structurally ingest papers from arxiv / openalex. Populates the literature index.
tools: Read, WebFetch, mcp__arxiv__search_papers, mcp__arxiv__get_paper, mcp__openalex__search_works, mcp__openalex__get_citations, mcp__memory__ingest_paper, mcp__memory__query_literature
model: sonnet
---

You discover relevant papers for a research question.

Workflow:
1. Start with `mcp__memory__query_literature` to see what's already ingested.
2. If gaps, query `mcp__arxiv__search_papers` and `mcp__openalex__search_works`.
3. For each relevant paper, call `mcp__memory__ingest_paper` with the arxiv_id or DOI.
4. Return a ranked list of (paper_id, title, relevance-reason).

Never waste budget on papers already in the index.
```

#### `.claude/agents/prover.md`（v0.1 中为 stub）
```markdown
---
name: prover
description: Attempt formal proofs in Lean 4 for stated lemmas. Scope: small statistical identities.
tools: Read, Write, Edit, mcp__lean__lean_goal, mcp__lean__lean_verify, mcp__lean__lean_run_code, mcp__lean__lean_loogle, mcp__lean__lean_leansearch
model: sonnet
---

You are a formal-methods assistant. You take a mathematical lemma written in natural language and attempt to state + prove it in Lean 4 using mathlib.

> NOTE: This subagent is a stub in v0.1. Activated in v0.2 when lean-lsp-mcp is installed.
```

#### Skills（3 个 SOP，v0.1 先放 stub 内容）

`.claude/skills/research-sop/SKILL.md`：
```markdown
---
name: research-sop
description: End-to-end research loop. Use at the start of any new research task — triggers literature review, hypothesis generation, experimentation, verification.
---

# Research SOP

When the user asks a research-shaped question ("investigate X", "does X affect Y", "compare A and B"):

1. **Memory lookup** — call `mcp__memory__match_signatures` with the task description. If prior failures exist, read them first.
2. **Literature gap** — call `mcp__memory__query_literature`. If < 3 relevant papers, spawn the `librarian` subagent.
3. **Hypothesis generation** — spawn the `researcher` subagent with literature context. Ask for 3–5 hypotheses.
4. **Hypothesis selection** — present to user via cockpit (or inline if cockpit not up). Pick one.
5. **Implementation** — spawn the `engineer` subagent.
6. **Verification** — spawn the `verifier` subagent independently.
7. **Write-up** — only if verifier passes.

At every step, call `mcp__memory__propose_hypothesis` / `mcp__memory__attach_evidence` to keep the graph live.
```

`.claude/skills/debug-sop/SKILL.md`：
```markdown
---
name: debug-sop
description: Systematic debugging. Use when a script errors or produces unexpected results.
---

# Debug SOP

1. Call `mcp__memory__match_signatures` with the error message. Similar past failure? Use that resolution first.
2. If no match: minimal reproduction, then bisect.
3. On resolution: always call `mcp__memory__record_failure` with trigger/symptom/cause/resolution.
```

`.claude/skills/writeup-sop/SKILL.md`：
```markdown
---
name: writeup-sop
description: Writing reports / papers. Use when producing any .md file that makes claims about experimental results.
---

# Writeup SOP

HARD RULE: every numeric claim in a report must be traceable via `mcp__verify__check_provenance`. The PreToolUse hook will block unprovenanced claims on file write.

Workflow:
1. List every claim you want to make.
2. For each, call `mcp__verify__check_provenance`. Missing → re-run or remove the claim.
3. Write the report.
```

**验收**：在 Claude Code 会话里输入 `@researcher propose three hypotheses about dropout and ViT scaling`。确认 subagent 被正常调起，并且它的工具白名单生效。

---

### Phase 2 — memory-mcp v0.1（2–3 天）

**目标**：先跑起来一个基于 SQLite 的 MCP server，对外暴露 7 个工具。暂时还不做文献压缩，先把整体结构立住。

#### Schema（`src/memory_mcp/schema.sql`）

```sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- Hypothesis graph (append-only)
CREATE TABLE IF NOT EXISTS mem_nodes (
  node_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK(kind IN ('question','hypothesis','experiment','evidence','conclusion')),
  text TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'active' CHECK(state IN ('active','refuted','superseded','archived')),
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  created_by TEXT,
  parent_id TEXT REFERENCES mem_nodes(node_id)
);

CREATE TABLE IF NOT EXISTS mem_edges (
  edge_id INTEGER PRIMARY KEY AUTOINCREMENT,
  src TEXT NOT NULL REFERENCES mem_nodes(node_id),
  dst TEXT NOT NULL REFERENCES mem_nodes(node_id),
  relation TEXT NOT NULL CHECK(relation IN ('refines','contradicts','supports','refutes','supersedes','blocks')),
  rationale TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_edges_src ON mem_edges(src);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON mem_edges(dst);

-- Failure ledger
CREATE TABLE IF NOT EXISTS mem_failures (
  failure_id INTEGER PRIMARY KEY AUTOINCREMENT,
  trigger TEXT NOT NULL,
  symptom TEXT NOT NULL,
  root_cause TEXT,
  resolution TEXT,
  signature TEXT,
  seen_count INTEGER DEFAULT 1,
  first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
  last_seen TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE VIRTUAL TABLE IF NOT EXISTS mem_failures_fts USING fts5(
  trigger, symptom, root_cause, resolution,
  content='mem_failures', content_rowid='failure_id'
);

CREATE TRIGGER IF NOT EXISTS mem_failures_ai AFTER INSERT ON mem_failures BEGIN
  INSERT INTO mem_failures_fts(rowid, trigger, symptom, root_cause, resolution)
  VALUES (new.failure_id, new.trigger, new.symptom, new.root_cause, new.resolution);
END;

-- Literature (metadata stub; extended with compressed fields in Phase 6 — see section 6.3)
CREATE TABLE IF NOT EXISTS mem_lit (
  paper_id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  title TEXT,
  abstract TEXT,
  metadata TEXT,           -- JSON: {arxiv_id, doi, authors, year, venue, ...}
  trust_level REAL DEFAULT 0.5,
  added_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

#### 连接辅助（`src/memory_mcp/db.py`）

```python
import sqlite3
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path(".research-agent/state.db")
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

def _ensure_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not DB_PATH.exists():
        con = sqlite3.connect(str(DB_PATH))
        con.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        con.close()

def _connect():
    _ensure_db()
    con = sqlite3.connect(str(DB_PATH), timeout=5.0, isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.row_factory = sqlite3.Row
    return con

@contextmanager
def tx():
    con = _connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        yield con
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()
```

#### 工具接口（`src/memory_mcp/impl.py`）

```python
import uuid
from memory_mcp.db import tx, _connect

TOOL_NAMES = [
    "propose_hypothesis", "attach_evidence", "mark_refuted",
    "get_active_frontier", "get_ancestors",
    "record_failure", "match_signatures",
]

def propose_hypothesis(text: str, parent_id: str | None = None, rationale: str = "") -> dict:
    node_id = f"h_{uuid.uuid4().hex[:10]}"
    with tx() as con:
        con.execute(
            "INSERT INTO mem_nodes(node_id, kind, text, parent_id) VALUES(?,?,?,?)",
            (node_id, "hypothesis", text, parent_id),
        )
        if parent_id:
            con.execute(
                "INSERT INTO mem_edges(src, dst, relation, rationale) VALUES(?,?,?,?)",
                (parent_id, node_id, "refines", rationale),
            )
    return {"node_id": node_id}

def attach_evidence(node_id: str, evidence_text: str, polarity: str) -> dict:
    assert polarity in ("supports", "refutes")
    ev_id = f"e_{uuid.uuid4().hex[:10]}"
    with tx() as con:
        con.execute(
            "INSERT INTO mem_nodes(node_id, kind, text) VALUES(?,?,?)",
            (ev_id, "evidence", evidence_text),
        )
        con.execute(
            "INSERT INTO mem_edges(src, dst, relation) VALUES(?,?,?)",
            (ev_id, node_id, polarity),
        )
    return {"evidence_id": ev_id}

def mark_refuted(node_id: str, reason: str, evidence_ids: list[str]) -> dict:
    with tx() as con:
        con.execute(
            "UPDATE mem_nodes SET state='refuted' WHERE node_id=?",
            (node_id,),
        )
        # edges to evidence are created via attach_evidence; nothing mutated here
    return {"refuted": node_id, "reason": reason}

def get_active_frontier() -> list[dict]:
    con = _connect()
    rows = con.execute(
        "SELECT node_id, kind, text, created_at FROM mem_nodes "
        "WHERE state='active' AND kind IN ('hypothesis','question') "
        "ORDER BY created_at DESC LIMIT 50"
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]

def get_ancestors(node_id: str) -> list[dict]:
    con = _connect()
    result = []
    current = node_id
    while current:
        row = con.execute(
            "SELECT node_id, parent_id, kind, text FROM mem_nodes WHERE node_id=?",
            (current,),
        ).fetchone()
        if not row:
            break
        result.append(dict(row))
        current = row["parent_id"]
    con.close()
    return result

def record_failure(trigger: str, symptom: str, root_cause: str = "", resolution: str = "") -> dict:
    with tx() as con:
        cur = con.execute(
            "INSERT INTO mem_failures(trigger, symptom, root_cause, resolution) VALUES(?,?,?,?)",
            (trigger, symptom, root_cause, resolution),
        )
        fid = cur.lastrowid
    return {"failure_id": fid}

def match_signatures(situation: str, k: int = 5) -> list[dict]:
    con = _connect()
    rows = con.execute(
        """
        SELECT f.failure_id, f.trigger, f.symptom, f.root_cause, f.resolution,
               bm25(mem_failures_fts) AS score
        FROM mem_failures f
        JOIN mem_failures_fts fts ON fts.rowid = f.failure_id
        WHERE mem_failures_fts MATCH ?
        ORDER BY score LIMIT ?
        """,
        (situation, k),
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]
```

#### 生产 / 开发入口

`src/memory_mcp/server.py`：
```python
from fastmcp import FastMCP
import memory_mcp.impl as impl

mcp = FastMCP("memory")

for name in impl.TOOL_NAMES:
    mcp.tool(getattr(impl, name))

if __name__ == "__main__":
    mcp.run()
```

`src/memory_mcp/dev_server.py`：
```python
import importlib, os
from fastmcp import FastMCP
import memory_mcp.impl as impl

mcp = FastMCP("memory-dev")
DEV = os.environ.get("RESEARCH_AGENT_DEV") == "1"

def _wrap(name):
    def wrapper(**kwargs):
        if DEV:
            importlib.reload(impl)
        return getattr(impl, name)(**kwargs)
    wrapper.__name__ = name
    wrapper.__doc__ = getattr(impl, name).__doc__
    return wrapper

for name in impl.TOOL_NAMES:
    mcp.tool(_wrap(name))

if __name__ == "__main__":
    mcp.run()
```

#### 在 `.claude/settings.json` 中注册

```json
{
  "mcpServers": {
    "memory": {
      "command": "uv",
      "args": ["run", "python", "-m", "memory_mcp.dev_server"],
      "env": {"RESEARCH_AGENT_DEV": "1"}
    }
  },
  "hooks": {}
}
```

**验收**：
```powershell
# Unit test
uv run pytest tests/memory_mcp/

# In a fresh CC session:
# > call mcp__memory__record_failure with a fake failure
# > call mcp__memory__match_signatures with similar text
# > confirm the failure is returned ranked first
```

---

### Phase 3 — verify-mcp v0.1（2 天）

**目标**：先把数据泄漏检测和 provenance 工具接口做出来。`seed_perturb` / held-out 预算这类东西暂时不进这一版。

#### `src/verify_mcp/leakage.py` — AST 扫描器

```python
import ast
from dataclasses import dataclass

@dataclass
class Finding:
    rule: str
    line: int
    message: str

RISKY_IO = {"open", "read_csv", "read_parquet", "load", "loadtxt", "read_json"}

def scan_python(src: str) -> list[Finding]:
    findings: list[Finding] = []
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [Finding("syntax", e.lineno or 0, str(e))]

    # Rule 1: scaler fit before split
    # Rule 2: fit() on concatenated train+test
    # Rule 3: eval on test during training loop
    # Rule 4: held-out path access

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "attr", getattr(func, "id", ""))

            # held-out path access
            if name in RISKY_IO and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if "held_out" in arg.value or ".research-agent" in arg.value:
                        findings.append(Finding(
                            "heldout_access", node.lineno,
                            f"{name}() reads path containing held-out marker: {arg.value!r}"
                        ))

            # fit on pd.concat([train, test]) style
            if name == "fit" and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Call):
                    arg_name = getattr(arg.func, "attr", getattr(arg.func, "id", ""))
                    if arg_name in ("concat", "vstack", "hstack"):
                        findings.append(Finding(
                            "fit_on_concatenated", node.lineno,
                            f"fit() called on result of {arg_name}() — possible train+test leakage"
                        ))

    return findings

def scan_file(path: str) -> list[Finding]:
    return scan_python(open(path, encoding="utf-8").read())
```

#### `src/verify_mcp/impl.py`

```python
import json
from pathlib import Path
from datetime import datetime
from verify_mcp.leakage import scan_file, scan_python
from memory_mcp.db import tx, _connect  # share the same DB

TOOL_NAMES = ["leakage_check", "record_provenance", "check_provenance"]

def leakage_check(script_path: str | None = None, script_text: str | None = None) -> dict:
    assert script_path or script_text
    findings = scan_file(script_path) if script_path else scan_python(script_text)
    return {
        "clean": len(findings) == 0,
        "findings": [
            {"rule": f.rule, "line": f.line, "message": f.message}
            for f in findings
        ],
    }

def record_provenance(claim: str, value: str, session_id: str, source_command: str = "") -> dict:
    with tx() as con:
        con.execute(
            """INSERT INTO ver_provenance(claim, value, session_id, source_command, created_at)
               VALUES(?,?,?,?,?)""",
            (claim, value, session_id, source_command, datetime.utcnow().isoformat()),
        )
    return {"recorded": True}

def check_provenance(claim: str) -> dict:
    con = _connect()
    row = con.execute(
        "SELECT * FROM ver_provenance WHERE claim=? ORDER BY created_at DESC LIMIT 1",
        (claim,),
    ).fetchone()
    con.close()
    if row:
        return {"status": "found", "evidence": dict(row)}
    return {"status": "missing"}
```

#### 往 schema 里加入 `ver_*` 表

扩展 `src/memory_mcp/schema.sql`（或者单独建 `src/verify_mcp/schema.sql`，并在启动时一起执行）：

```sql
CREATE TABLE IF NOT EXISTS ver_provenance (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  claim TEXT NOT NULL,
  value TEXT,
  session_id TEXT,
  source_command TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_prov_claim ON ver_provenance(claim);
CREATE INDEX IF NOT EXISTS idx_prov_session ON ver_provenance(session_id);
```

**验收**：

```powershell
# Unit test: leakage detector against fixtures
uv run pytest tests/verify_mcp/test_leakage.py

# Fixture example:
# tests/verify_mcp/fixtures/leaky_scaler.py  (should trigger 1 finding)
# tests/verify_mcp/fixtures/clean_pipeline.py (should be clean)
```

---

### Phase 4 — Hook 打通（1 天）

**目标**：写出 4 个 hook 脚本，并把 `settings.json` 里的 wiring 真正接起来，让它在 Claude Code 里能触发。

#### `.claude/hooks/intervention_pump.py`
```python
#!/usr/bin/env python
"""
Runs on Stop and UserPromptSubmit.
Drains undelivered rows from cockpit_interventions and injects them as additionalContext.
"""
import json, sys, sqlite3
from pathlib import Path

DB = Path(".research-agent/state.db")

def drain():
    if not DB.exists():
        return None
    con = sqlite3.connect(str(DB), timeout=2.0)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT id, kind, target, payload FROM cockpit_interventions "
            "WHERE delivered_at IS NULL ORDER BY created_at"
        ).fetchall()
    except sqlite3.OperationalError:
        # table doesn't exist yet (cockpit not up)
        con.close()
        return None
    if not rows:
        con.close()
        return None
    ids = [r["id"] for r in rows]
    blocks = [f"[INTERVENTION {r['kind']}] target={r['target']}\n{r['payload']}" for r in rows]
    placeholders = ",".join("?" * len(ids))
    con.execute(
        f"UPDATE cockpit_interventions SET delivered_at = datetime('now') WHERE id IN ({placeholders})",
        ids,
    )
    con.commit()
    con.close()
    return (
        "Cockpit interventions to respect before continuing:\n\n" + "\n\n".join(blocks)
    )

def main():
    _ = json.loads(sys.stdin.read() or "{}")  # we don't actually read the payload
    text = drain()
    if text:
        print(json.dumps({"hookSpecificOutput": {"additionalContext": text}}))
    else:
        print("{}")

if __name__ == "__main__":
    main()
```

#### `.claude/hooks/leakage_guard.py`
```python
#!/usr/bin/env python
"""
PreToolUse hook. Blocks Write/Edit/Bash when held-out path patterns are detected.
Bypassed when RESEARCH_AGENT_VERIFY=1 is set (verify-mcp calls).
"""
import json, sys, os, re

HELDOUT_RE = re.compile(
    r"(\.research-agent[\\/]held_out|%USERPROFILE%[\\/]\.research-agent|~[\\/]\.research-agent[\\/]held_out)",
    re.IGNORECASE,
)

def main():
    if os.environ.get("RESEARCH_AGENT_VERIFY") == "1":
        print("{}")
        return
    payload = json.loads(sys.stdin.read() or "{}")
    ti = payload.get("tool_input", {})
    blob = " ".join(str(v) for v in ti.values() if isinstance(v, str))
    m = HELDOUT_RE.search(blob)
    if m:
        print(json.dumps({
            "hookSpecificOutput": {
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f"Held-out data access blocked (matched {m.group(0)!r}). "
                    "Use mcp__verify__query_heldout instead."
                )
            }
        }))
        sys.exit(2)
    print("{}")

if __name__ == "__main__":
    main()
```

#### `.claude/hooks/destructive_bash_guard.py`
```python
#!/usr/bin/env python
"""PreToolUse Bash guard. Blocks destructive commands unless a confirmation token is present."""
import json, sys, re

DANGEROUS = [
    r"\brm\s+-rf\b",
    r"\bRemove-Item\s+.*-Recurse",
    r"\bgit\s+push\s+.*--force\b",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\s+-fd?x?\b",
    r"\bDROP\s+TABLE\b",
    r"\bDROP\s+DATABASE\b",
    r"\bdel\s+/[sS]\b",
    r"\bformat\s+[a-zA-Z]:",
]

def main():
    payload = json.loads(sys.stdin.read() or "{}")
    cmd = payload.get("tool_input", {}).get("command", "")
    for pat in DANGEROUS:
        if re.search(pat, cmd, re.IGNORECASE):
            if "# CONFIRM_DESTRUCTIVE" not in cmd:
                print(json.dumps({
                    "hookSpecificOutput": {
                        "permissionDecision": "deny",
                        "permissionDecisionReason": (
                            f"Destructive command blocked ({pat}). "
                            "If intentional, append ' # CONFIRM_DESTRUCTIVE' to the command."
                        )
                    }
                }))
                sys.exit(2)
    print("{}")

if __name__ == "__main__":
    main()
```

#### `.claude/hooks/provenance_log.py`（Bash 的 PostToolUse）
```python
#!/usr/bin/env python
"""Extracts numeric tokens from Bash stdout and writes them to ver_provenance."""
import json, sys, re, sqlite3
from pathlib import Path
from datetime import datetime

DB = Path(".research-agent/state.db")
NUM_RE = re.compile(r"(?:accuracy|acc|loss|f1|auc|rmse|mae|score|p_value|pvalue)[\s:=]+(\-?\d+\.?\d*)", re.IGNORECASE)

def main():
    payload = json.loads(sys.stdin.read() or "{}")
    if payload.get("tool_name") != "Bash":
        print("{}")
        return
    response = payload.get("tool_response", {})
    stdout = response.get("stdout", "") if isinstance(response, dict) else ""
    session_id = payload.get("session_id", "unknown")
    command = payload.get("tool_input", {}).get("command", "")
    matches = NUM_RE.findall(stdout)
    if not matches:
        print("{}")
        return
    if not DB.exists():
        print("{}")
        return
    con = sqlite3.connect(str(DB), timeout=2.0)
    try:
        for v in matches:
            con.execute(
                """INSERT INTO ver_provenance(claim, value, session_id, source_command, created_at)
                   VALUES(?,?,?,?,?)""",
                (f"bash_number", v, session_id, command[:500], datetime.utcnow().isoformat()),
            )
        con.commit()
    except sqlite3.OperationalError:
        pass
    finally:
        con.close()
    print("{}")

if __name__ == "__main__":
    main()
```

#### `.claude/hooks/stop_flush.py`
```python
#!/usr/bin/env python
"""Stop hook — emits a sentinel event into cockpit_events for the WebSocket tail."""
import json, sys, sqlite3
from pathlib import Path
from datetime import datetime

DB = Path(".research-agent/state.db")

def main():
    _ = json.loads(sys.stdin.read() or "{}")
    if DB.exists():
        con = sqlite3.connect(str(DB), timeout=2.0)
        try:
            con.execute(
                "INSERT INTO cockpit_events(kind, payload, created_at) VALUES(?,?,?)",
                ("turn_end", "{}", datetime.utcnow().isoformat()),
            )
            con.commit()
        except sqlite3.OperationalError:
            pass
        finally:
            con.close()
    print("{}")

if __name__ == "__main__":
    main()
```

#### 接好 hook 的 `.claude/settings.json`

```json
{
  "mcpServers": {
    "memory": {
      "command": "uv",
      "args": ["run", "python", "-m", "memory_mcp.dev_server"],
      "env": {"RESEARCH_AGENT_DEV": "1"}
    },
    "verify": {
      "command": "uv",
      "args": ["run", "python", "-m", "verify_mcp.dev_server"],
      "env": {"RESEARCH_AGENT_DEV": "1"}
    }
  },
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit|Bash",
        "hooks": [
          {
            "type": "command",
            "command": "uv run python .claude/hooks/leakage_guard.py",
            "timeout": 5
          }
        ]
      },
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "uv run python .claude/hooks/destructive_bash_guard.py",
            "timeout": 5
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "uv run python .claude/hooks/provenance_log.py",
            "timeout": 5
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "uv run python .claude/hooks/intervention_pump.py",
            "timeout": 5
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "uv run python .claude/hooks/intervention_pump.py",
            "timeout": 5
          },
          {
            "type": "command",
            "command": "uv run python .claude/hooks/stop_flush.py",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

**验收**：
- 让 engineer subagent 去写一个故意泄漏的脚本，应该被 `leakage_guard.py` 拦下。
- 在 Bash 里试一下 `rm -rf test/`，应该会被拦；只有追加 `# CONFIRM_DESTRUCTIVE` 才能放行。
- 手动往 `cockpit_interventions` 里插一行，再随便发一个 prompt，Claude 应该能把这条干预作为上下文收到。

---

### Phase 5 — Cockpit MVP（3–4 天）

**目标**：在 `localhost:7777` 启一个浏览器可见的 cockpit，展示实时 hypothesis graph + failure ledger，并提供 **一个** 交互按钮：“reject hypothesis”（向 `cockpit_interventions` 写入）。

#### 后端：`src/cockpit/server.py`

```python
import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastmcp import FastMCP

DB = Path(".research-agent/state.db")

# --- cockpit schema bootstrap ---
COCKPIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS cockpit_interventions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,           -- 'reject', 'approve', 'redirect', 'constrain', 'info', 'halt'
  target TEXT,                  -- node_id or claim_id
  payload TEXT,                 -- instruction text
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  delivered_at TEXT
);
CREATE TABLE IF NOT EXISTS cockpit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  payload TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

def _con():
    con = sqlite3.connect(str(DB), timeout=5.0, isolation_level=None)
    con.row_factory = sqlite3.Row
    return con

def _ensure():
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = _con()
    con.executescript(COCKPIT_SCHEMA)
    con.close()

# --- fastmcp sub-app (for Claude Code) ---
cockpit_mcp = FastMCP("cockpit")

@cockpit_mcp.tool
def push_graph_delta(node_id: str, kind: str, text: str) -> dict:
    """Called by main Claude when a new node is created, for real-time cockpit push."""
    con = _con()
    con.execute(
        "INSERT INTO cockpit_events(kind, payload) VALUES(?,?)",
        ("graph_delta", json.dumps({"node_id": node_id, "kind": kind, "text": text})),
    )
    con.close()
    return {"pushed": True}

# --- FastAPI app ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    _ensure()
    yield

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount fastmcp as sub-app at /mcp
app.mount("/mcp", cockpit_mcp.http_app())

# --- REST endpoints ---
@app.get("/graph")
def get_graph():
    con = _con()
    nodes = [dict(r) for r in con.execute(
        "SELECT node_id, kind, text, state, created_at, parent_id FROM mem_nodes ORDER BY created_at"
    ).fetchall()]
    edges = [dict(r) for r in con.execute(
        "SELECT edge_id, src, dst, relation, rationale FROM mem_edges"
    ).fetchall()]
    con.close()
    return {"nodes": nodes, "edges": edges}

@app.get("/failures")
def get_failures():
    con = _con()
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM mem_failures ORDER BY last_seen DESC LIMIT 100"
    ).fetchall()]
    con.close()
    return rows

@app.post("/intervene")
def intervene(kind: str, target: str, payload: str):
    con = _con()
    con.execute(
        "INSERT INTO cockpit_interventions(kind, target, payload) VALUES(?,?,?)",
        (kind, target, payload),
    )
    con.close()
    return {"queued": True}

# --- WebSocket: tail cockpit_events ---
@app.websocket("/ws/state")
async def ws_state(ws: WebSocket):
    await ws.accept()
    last_id = 0
    try:
        while True:
            con = _con()
            rows = con.execute(
                "SELECT id, kind, payload, created_at FROM cockpit_events WHERE id > ? ORDER BY id",
                (last_id,),
            ).fetchall()
            con.close()
            for r in rows:
                await ws.send_json({
                    "id": r["id"],
                    "kind": r["kind"],
                    "payload": json.loads(r["payload"] or "{}"),
                    "ts": r["created_at"],
                })
                last_id = r["id"]
            await asyncio.sleep(0.3)
    except WebSocketDisconnect:
        return
```

在 `.claude/settings.json` 里把 cockpit-mcp 注册成一个 HTTP MCP，指向 `http://localhost:7777/mcp`（前提是 cockpit 已经在跑）。如果需要，v0.2 再补一个 stdio fallback。

#### 前端脚手架

```powershell
cd D:\aiscientist\claudescientist\src\cockpit
pnpm create vite frontend --template react-ts
cd frontend
pnpm install
pnpm add @xyflow/react
pnpm add -D tailwindcss @tailwindcss/vite
```

编辑 `vite.config.ts`：
```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173 },
})
```

`src/index.css`：
```css
@import "tailwindcss";
```

`src/hooks/useWebSocket.ts`：自动重连的 WS hook（实现可直接复用技术栈那一节里的思路，约 40 LOC）。

`src/components/HypothesisGraph.tsx`：基于 `GET /graph` 渲染 `@xyflow/react`，并在收到 WS 消息时更新。

`src/components/VerificationTable.tsx`：把 `GET /failures` 渲染成可排序表格。

`src/components/InterventionPanel.tsx`：选中图节点时，显示 5 类干预按钮。点击 REJECT 时，向 `POST /intervene` 发送 `{kind: 'reject', target: node_id, payload: 'user rejected this hypothesis'}`。

`src/App.tsx`：三栏布局，左边图（60%），右上 failure 表（40% × 50%），右下 intervention panel（40% × 50%）。

**运行方式**：
```powershell
# Terminal 1: backend
uv run uvicorn cockpit.server:app --port 7777

# Terminal 2: frontend
cd src\cockpit\frontend
pnpm run dev
# visit http://localhost:5173
```

**验收**：
- 后端能正常启动，`GET http://localhost:7777/graph` 返回 `{nodes: [...], edges: [...]}`。
- 前端能正常加载，并显示空状态图。
- 在 Claude Code 会话中调用 `mcp__memory__propose_hypothesis`，500ms 内浏览器里应该出现新节点。
- 点击某个节点 → 点击 REJECT → 下一轮 Claude 应该能通过 `additionalContext` 收到这条干预。

---

### Phase 6 — 文献压缩（3–4 天）

**目标**：让 `librarian` subagent 真正端到端可用。它需要能在 arxiv/openalex 上找论文，做结构化压缩后写进 `mem_lit`，并且能通过本地索引返回排序后的相关结果。

#### Step 6.1 — 安装第三方文献 MCP

```powershell
# arxiv MCP (blazickjp/arxiv-mcp-server): metadata + abstracts
uv tool install arxiv-mcp-server

# openalex MCP (oksure/openalex-research-mcp): 240M works, citation graphs
uv tool install openalex-research-mcp
```

> 如果这两个包在 PyPI 上没有用这个准确名字发布，就改用 git URL 安装：`uv tool install git+https://github.com/blazickjp/arxiv-mcp-server` 和 `uv tool install git+https://github.com/oksure/openalex-research-mcp`。命令里要钉住具体 commit，避免未来升级不受控。

#### Step 6.2 — 在 `.claude/settings.json` 中注册

扩展 `mcpServers`：

```json
{
  "mcpServers": {
    "memory": { "command": "uv", "args": ["run", "python", "-m", "memory_mcp.dev_server"], "env": {"RESEARCH_AGENT_DEV": "1"} },
    "verify": { "command": "uv", "args": ["run", "python", "-m", "verify_mcp.dev_server"], "env": {"RESEARCH_AGENT_DEV": "1"} },
    "arxiv": { "command": "uv", "args": ["tool", "run", "arxiv-mcp-server"] },
    "openalex": { "command": "uv", "args": ["tool", "run", "openalex-research-mcp"] }
  }
}
```

（cockpit 走 HTTP，需要单独注册，见 Phase 5 的说明。）

#### Step 6.3 — 为压缩后的文献扩展 schema

往 `src/memory_mcp/schema.sql` 里加下面这段（它是幂等的，因为用了 `IF NOT EXISTS`，重复执行也安全）：

```sql
-- Compressed literature (replaces the v0.1 stub)
CREATE TABLE IF NOT EXISTS mem_lit_compressed (
  paper_id TEXT PRIMARY KEY,               -- arxiv_id or openalex_id
  source TEXT NOT NULL CHECK(source IN ('arxiv','openalex','manual')),
  title TEXT,
  authors TEXT,                            -- JSON array
  year INTEGER,
  venue TEXT,
  problem TEXT,                            -- what problem the paper tackles
  method TEXT,                             -- the method in 2-3 sentences
  claimed_results TEXT,                    -- main quantitative claims
  assumptions TEXT,                        -- explicit assumptions / scope
  limitations TEXT,                        -- stated & inferred
  trust_level REAL DEFAULT 0.5,            -- 0..1 based on venue + reproducibility signals
  relates_to TEXT,                         -- JSON: {paper_id: relation}
  raw_abstract TEXT,
  ingested_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE VIRTUAL TABLE IF NOT EXISTS mem_lit_fts USING fts5(
  title, problem, method, claimed_results,
  content='mem_lit_compressed', content_rowid='rowid'
);
```

#### Step 6.4 — 往 `memory_mcp/impl.py` 里加工具

把 `TOOL_NAMES` 扩展成包含：`"ingest_paper"`、`"query_literature"`、`"find_baselines_for"`。

```python
import json

def ingest_paper(paper_id: str, source: str, structured: dict) -> dict:
    """
    Store a compressed paper. The `structured` dict is produced by the librarian
    subagent from raw arxiv/openalex MCP output + abstract text. Schema:
      { "title", "authors"(list), "year", "venue",
        "problem", "method", "claimed_results",
        "assumptions", "limitations", "trust_level", "raw_abstract" }
    """
    with tx() as con:
        con.execute(
            """INSERT OR REPLACE INTO mem_lit_compressed
               (paper_id, source, title, authors, year, venue, problem, method,
                claimed_results, assumptions, limitations, trust_level, raw_abstract)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                paper_id, source,
                structured.get("title", ""),
                json.dumps(structured.get("authors", [])),
                structured.get("year"),
                structured.get("venue", ""),
                structured.get("problem", ""),
                structured.get("method", ""),
                structured.get("claimed_results", ""),
                structured.get("assumptions", ""),
                structured.get("limitations", ""),
                structured.get("trust_level", 0.5),
                structured.get("raw_abstract", ""),
            ),
        )
    return {"ingested": paper_id}

def query_literature(question: str, k: int = 10) -> list[dict]:
    """Ranked list of papers by BM25 on problem+method+claimed_results, weighted by trust."""
    con = _connect()
    rows = con.execute(
        """
        SELECT p.paper_id, p.title, p.problem, p.method, p.claimed_results,
               p.assumptions, p.limitations, p.trust_level,
               bm25(mem_lit_fts) AS bm25_score
        FROM mem_lit_compressed p
        JOIN mem_lit_fts fts ON fts.rowid = p.rowid
        WHERE mem_lit_fts MATCH ?
        ORDER BY bm25_score * (1.0 / (0.5 + p.trust_level)) LIMIT ?
        """,
        (question, k),
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]

def find_baselines_for(method_description: str, k: int = 5) -> list[dict]:
    """Shortlist of papers whose 'method' field is nearest to the description.
    Used by engineer subagent when picking baselines for comparison."""
    return query_literature(method_description, k=k)
```

#### Step 6.5 — Librarian subagent 工作流（细化版）

Phase 1 里那个 `librarian` subagent 现在要升级成一个完整闭环：

1. 从主 Claude 那里接收问题。
2. 先调用 `mcp__memory__query_literature(question)`，检查本地已经摄取了什么。
3. 如果命中数少于 3，或者 BM25 分数不理想，再调用 `mcp__arxiv__search_papers(query)` 和 `mcp__openalex__search_works(query)`。
4. 对每篇本地还没有的候选论文，通过对应 MCP 抓摘要和元数据。
5. 让 subagent 自己产出结构化抽取结果（problem / method / claims / assumptions / limitations）。这里本质上就是 subagent 读自己的 SOP，再吐一个 JSON。
6. 对每一篇调用 `mcp__memory__ingest_paper(paper_id, source, structured)`。
7. 最后把排序后的结果返回给主 Claude。

结构化抽取的 prompt 直接写在 `librarian.md` 的 subagent prompt 里，不需要再单独发 Claude API 请求。因为这个 subagent 本身就是 Claude。

#### Step 6.6 — 更新 librarian subagent 文件

把 librarian 的工具白名单替换成真正可用的版本（不是 stub）：

```markdown
---
name: librarian
description: Discover and structurally ingest papers from arxiv / openalex. Populates the literature index.
tools: Read, WebFetch, mcp__arxiv__search_papers, mcp__arxiv__get_paper, mcp__openalex__search_works, mcp__openalex__get_work, mcp__openalex__get_citations, mcp__memory__ingest_paper, mcp__memory__query_literature
model: sonnet
---

You discover relevant papers for a research question and compress them into structured form.

Workflow for each question:
1. Call `mcp__memory__query_literature` first. Papers already indexed are off-limits.
2. For gaps, query `mcp__arxiv__search_papers` (CS/stats/math) and `mcp__openalex__search_works` (broader). Cap: 10 candidates per call to control cost.
3. For each candidate, fetch the full metadata (arxiv_id/doi, abstract, venue, year).
4. Produce a structured extraction. OUTPUT FORMAT MUST BE VALID JSON matching this schema:
   {"title": str, "authors": [str], "year": int, "venue": str,
    "problem": str (2-3 sentences: what they're solving),
    "method": str (2-3 sentences: how),
    "claimed_results": str (key numbers + direction),
    "assumptions": str (what they assume — be precise),
    "limitations": str (stated + anything I can spot),
    "trust_level": float in [0,1] (based on venue reputation + reproducibility signals),
    "raw_abstract": str}
5. For each, call `mcp__memory__ingest_paper(paper_id, source, structured)`.
6. Return to main Claude: a table of (paper_id, title, 1-line-relevance).

Rules:
- Never fabricate results. If something is unclear in the abstract, leave the field empty.
- Trust level: conference > workshop > arxiv-only. Reproducibility claims (code released, benchmarks) raise it.
- Never ingest a paper you haven't actually read the abstract of.
```

**验收**：
```powershell
# In a Claude Code session:
# > @librarian find and ingest 5 recent papers on "ViT dropout scaling"
# Expected: 5 rows appear in mem_lit_compressed with non-empty problem/method/assumptions.

# > mcp__memory__query_literature("dropout regularization in vision transformers")
# Expected: ranked list with the 5 new papers near the top.

# > mcp__memory__find_baselines_for("Vision Transformer with per-head dropout")
# Expected: same type of ranking, prioritized by method similarity.
```

---

## 7. v0.2+ 路线图（延期项）

按预期价值排序。注意：文献压缩**不**在这里，它已经进了 v0.1 的 Phase 6。

1. **在 verify-mcp 中加入 `seed_perturb` + `baseline_fairness`**（约 3 天）
   - 用子进程 runner 支持 `--seed` 覆盖，重复 3 次，返回均值 / 方差
   - baseline 公平性：比较两组 run log 里的超参预算

2. **Research taste skill 与 SOP 打磨**（约 3 天）
   - 用 Elo 方式在多个 hypothesis 之间做选择
   - 在 research-sop 里加入对 hypothesis graph 的感知式 prompt 注入

3. **Held-out 预算强约束**（约 3 天）
   - 做一个 `register_heldout_dataset` CLI，把数据挪到树外并写 manifest
   - 做 `query_heldout(dataset, model, budget_units)`，带预算跟踪
   - manifest 漂移即硬锁

4. **启用 prover subagent + lean-lsp-mcp**（约 1 周）
   - 安装 lean-lsp-mcp（`uv tool install lean-lsp-mcp`），安装 Lean toolchain + mathlib
   - 写测试：让 prover 证明 sample mean unbiasedness
   - 激活 prover subagent（v0.1 Phase 1 里已经占好了位）

5. **多项目支持**（约 3 天）
   - 区分 project-scoped `.research-agent/` 与 user-scoped memory
   - 支持跨项目 failure ledger 检索

6. **和 EvoScientist 的对比评估**（约 2 周，属于单独的发表工作）
   - 复现它们的 idea generation benchmark
   - 衡量我们的 memory layer 在 novelty 和 feasibility 上的增益
   - 作为第一篇 paper 的候选方向

---

## 8. 验证计划

### 每个 Phase 的验证
每个 phase 都以第 6 节列出的验收项作为结束标准。

### v0.1 端到端 smoke test

在完成 Phase 5 后，按一次真实 Claude Code 会话来跑：

```powershell
# Terminal 1: cockpit backend
uv run uvicorn cockpit.server:app --port 7777

# Terminal 2: frontend
cd src\cockpit\frontend && pnpm run dev

# Terminal 3: Claude Code
cd D:\aiscientist\claudescientist
# claude (start CC)
```

在 Claude Code 中：
1. `/research-sop investigate whether dropout rate affects ViT scaling`
   → 预期：`research-sop` skill 被触发，`librarian` 被拉起，5–10 篇论文进入 `mem_lit_compressed`，随后 `researcher` 提出 3 个 hypothesis。3 个 hypothesis 节点都应在 1 秒内依次出现在 cockpit 图里。
2. 在 cockpit 里点第一个 hypothesis 节点 → 点 REJECT → 确认
   → 预期：Claude 下一轮会收到这条 `additionalContext`，并丢弃该 hypothesis
3. `@engineer implement the remaining hypothesis as a MNIST-proxy training script`
   → 预期：`leakage_guard` 不会阻止干净代码；`provenance_log` 会从 Bash stdout 里提取训练数值
4. 故意要求 engineer 写一个对 `pd.concat([train, test])` 执行 `fit()` 的脚本
   → 预期：`mcp__verify__leakage_check` 会报问题，并且 `leakage_guard.py` 会阻止文件写入
5. 在 Bash 块里试 `rm -rf tests/`
   → 预期：`destructive_bash_guard` 会拦住；只有追加 ` # CONFIRM_DESTRUCTIVE` 才能放行
6. `mcp__memory__query_literature("dropout in ViT")`
   → 预期：返回已摄取论文的排序列表，并且能看到结构化字段
7. 结束会话，重启 Claude Code，再开一个新会话
   → 预期：cockpit 里的图状态仍然存在；`mcp__memory__match_signatures` 能返回跨会话的失败记录；文献索引保持完好

### 回归测试

- `tests/memory_mcp/test_graph.py`：测试 append-only 不变量和 ancestor walk
- `tests/memory_mcp/test_failures.py`：测试 FTS5 对合成 failure 的召回能力
- `tests/verify_mcp/test_leakage.py`：在标注好的 clean / leaky fixture 上测试 detector
- `tests/hooks/test_intervention_pump.py`：用 mock SQLite 测试 drain 语义
- `tests/e2e/test_smoke.py`：通过 subprocess 拉起全部 server，断言 happy path

---

## 9. 已解决的决策项

初始设计里的 4 个开放问题现在都已经定下来了：

- **D1 — Python 包管理**：✅ `uv`。所有 hook 和 MCP server 都通过 `uv run python -m <module>` 启动，从而在 Windows 上获得稳定可复现的运行环境。`uv.lock` 负责锁定依赖图。
- **D2 — v0.1 范围**：✅ Phase 0–6（从脚手架到文献压缩），约 15–18 个工作日。只有真正偏重的项目（`seed_perturb`、held-out 预算、Lean prover、多项目支持）被推迟到 v0.2+，并且会先经过真实使用反馈。
- **D3 — 文献 MCP 策略**：✅ `arxiv-mcp-server` 和 `openalex-research-mcp` 直接通过 `uv tool install` 原样安装，并和我们自己的 MCP 一起注册到 `.claude/settings.json`。我们的 `memory-mcp` 只增加一个 `ingest_paper`，负责接收 librarian subagent 的结构化抽取结果。这样第三方维护成本为零，职责边界也很干净。
- **D4 — Cockpit-MCP 传输方式**：✅ HTTP，地址为 `http://localhost:7777/mcp`。fastmcp 子应用直接挂在同一个 uvicorn 进程里的 FastAPI REST + WebSocket server 中。一个进程、一个 SQLite 连接池、一条 `uv run uvicorn` 命令。如果 cockpit 没启动，Claude Code 只会把该 MCP 标为 unavailable，这个降级模式是可以接受的。

还剩两件可以在实施中再定的事，但都不是 blocker：

- **`arxiv-mcp-server` 和 `openalex-research-mcp` 的固定版本**：在 Phase 6 开始时选一个最新稳定 tag，并把 commit hash 记到 `pyproject.toml` 注释里。
- **前端包管理器选 pnpm / npm / yarn 哪个**：推荐 `pnpm`，但哪个都能用。到 Phase 5 开始时根据机器上实际已经装了什么再决定。

---

## 10. 参考资料

- Claude Code docs: https://docs.claude.com/en/docs/claude-code
  - Hooks reference, Subagents, Skills, settings.json
- fastmcp: https://github.com/jlowin/fastmcp
- MCP protocol: https://modelcontextprotocol.io
- uv: https://docs.astral.sh/uv/
- @xyflow/react: https://reactflow.dev/
- Tailwind v4 + Vite: https://tailwindcss.com/docs/installation/using-vite
- lean-lsp-mcp: https://github.com/oOo0oOo/lean-lsp-mcp
- arxiv-mcp-server: https://github.com/blazickjp/arxiv-mcp-server
- openalex-research-mcp: https://github.com/oksure/openalex-research-mcp
- Anthropic official memory MCP (for contrast): https://github.com/modelcontextprotocol/servers/tree/main/src/memory
