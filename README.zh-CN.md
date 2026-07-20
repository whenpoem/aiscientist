# ClaudeScientist

**为 Claude Code 和 Codex 提供研究记录、结果验证和本地监控界面。**

[![version](https://img.shields.io/badge/version-v5.1.4-blue)](https://github.com/whenpoem/aiscientist/releases) [![python](https://img.shields.io/badge/python-%E2%89%A53.11-3776AB?logo=python&logoColor=white)](https://www.python.org/) [![CI](https://github.com/whenpoem/aiscientist/actions/workflows/ci.yml/badge.svg)](https://github.com/whenpoem/aiscientist/actions/workflows/ci.yml) [![license](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)

> English version: [README.md](README.md)

ClaudeScientist 为 Claude Code 和 Codex 提供持久化研究记录、结果检查、统计证明
工具和终端监控界面。每个研究项目都有自己的本地 SQLite 数据库，用来保存假说、
证据、比较记录、实验结果和用户干预。

Agent 可以根据这些记录比较假说、运行带检查的实验，并核对报告中的结果。用户可以
在第二个终端查看当前研究状态，也可以在任务运行期间批准、否决或修改研究方向。

**当前版本**：v5.1.4 把公开安装、每个研究项目的配置和源码开发分开。新增
`claudescientist configure`，自动读取 `.research-agent/config.toml`，把 Lean 作为
默认关闭的可选 MCP 加入插件，并把旧项目向导保留在 `dev-setup` 中供源码贡献者使用。
它保留 v5.1 的可信性校准与可移植性改动。BT 排名改为从完整
比较账本联合拟合，不再依赖写入顺序；区间明确标记为未经校准的近似。Bonferroni
family 在锁定时固定。核心运行会自动记录代码、输入、Git 状态、依赖、种子和运行
环境。公开 Codex 插件把核心 MCP、Skills、hooks 和本地 Cockpit 打包在一起，
不再要求从本仓库根目录启动。v5.0 的活动流式 Cockpit 完整保留。

**v4.2.0 的功能继续可用**(见 [retrospective-v4.2.zh-CN.md](docs/retrospective-v4.2.zh-CN.md)):tab 分三组(跨主干 / 实验 / 证明)、详情面板可折叠分节、`w`/`i`/`t` 按面板划分作用域;向量检索支持任何 OpenAI 兼容服务商([ADR 0010](docs/adr/0010-multi-provider-embeddings.zh-CN.md),DashScope / Jina / Voyage / GLM 已测,本地默认 `Qwen/Qwen3-Embedding-0.6B`);报告导出([ADR 0009](docs/adr/0009-reports-as-files-monitoring-as-tui.zh-CN.md))和冷启动 Welcome 屏不变。两主干切分见 [architecture.zh-CN.md §13](docs/architecture.zh-CN.md#13-共用内核与领域主干v40)。

## 长什么样

打开两个终端：一个运行 Codex 或 Claude Code，另一个运行 Cockpit。

<picture>
  <img alt="Cockpit TUI 截图" src="docs/assets/image2.png" width="800">
</picture>

*Cockpit TUI —— 假说树、证据、评分、事件流，一个终端窗口搞定。*

左右两个终端不直接通信，而是读写同一个 SQLite 文件。各个模块通过这个本地数据库
共享状态，不需要网络服务。

| 角色 | 在哪里 | 干什么 |
|---|---|---|
| **Claude Code / Codex** | 终端 A | 读取你的问题，调用工具，编写并运行代码 |
| **MCP 服务器** | 后台进程 | 给 agent 提供工具——记忆、验证、文献检索、证明生成 |
| **Hooks** | 启动时自动加载 | 每次工具调用前后自动跑安全检查（拦截数据泄漏、记录溯源） |
| **Cockpit TUI** | 终端 B | 实时显示状态；你可以在这里批准、否决、改方向 |
| **SQLite** | `.research-agent/state.db` | 所有状态都在这一个文件里：假说、证据、评分、指标、事件 |

## 你能用它做什么

- **保存研究决策。** 每一个假说、每一条证据和每一次分支决策都会持久保存在图中。已导入的论文可以检索。反事实回放可以检查以前的决策，同时不修改当前研究图。
- **对候选想法排序。** Bradley-Terry 比较会生成与比较顺序无关的排行榜，
  并明确给出未经校准的近似后验区间。它要和比较覆盖、领域证据一起使用，不能当成
  显著性检验。
- **实验之前先锁定标准。** 预注册机制要求你在看到结果之前就定好要看的指标、方向和阈值。多重比较校正自动完成。
- **检查报告中的数字。** 系统会检查随机种子稳定性、输入文件、代码和环境变化，以及 baseline 是否使用相当的计算预算。审稿 agent 会拒绝没有充分验证的核心数字。
- **保存调试记录。** 失败记录会保存问题特征、诊断过程和解决方法。再次遇到相似问题时，系统可以检索这些记录。
- **监控并提交干预。** Cockpit TUI 显示假说树、评分和事件流。用户可以否决假说或添加批注；Codex 会在下一个受支持的 hook 事件接收干预。
- **生成和验证统计证明**（v4.0）。证明主干负责起草、切片、对照历史错误模式做诊断，还可以选装 Lean 4 做形式化验证。

## 快速开始

### 为 Codex 安装

推荐先永久安装 `claudescientist` 命令，再安装对应版本的 Codex 插件。请先安装
`uv` 和 Codex，并确认两个命令都可用：

```powershell
uv --version
codex --version
```

安装 Python 包和公开插件：

```powershell
uv tool install claudescientist==5.1.4
claudescientist setup --scope user
```

第一条命令安装命令行工具、MCP 后端、Doctor 和 Cockpit。第二条命令从 GitHub
的 `v5.1.4` 标签安装 Codex 插件。插件包含 Skills、hooks 和 MCP 配置。安装完成后，
可以在任意研究项目中使用，不需要从 ClaudeScientist 源码仓库启动 Codex。

进入每个研究项目后，为这个工作区配置一次，再运行检查：

```powershell
cd D:\你的研究项目
claudescientist configure --workspace .
claudescientist doctor --workspace .
```

配置命令会把非敏感的项目设置写入 `.research-agent/config.toml`，包括 embedding
后端、held-out 数据目录、自动剪枝和可选的 Lean 项目路径。ClaudeScientist 会自动
读取这个文件，普通插件用户不需要手动加载项目 `.env`。

安装或修改配置后，新建一个 Codex 任务，并在 Codex 提示时查看和信任插件 hooks。
即使 hooks 尚未信任，MCP 与 Cockpit 仍能监控；但 Cockpit 干预只能处于
`monitor-only` 状态。

在这个项目中启动 Codex，并在第二个终端用同一个目录打开 Cockpit：

```powershell
codex -C .

# 在第二个终端运行
claudescientist cockpit --workspace . --lang zh
```

在 Codex 中输入 `$research-sop <研究问题>` 可以启动完整研究流程，也可以通过
`/skills` 选择具体 Skill。每个项目的状态独立保存在 `.research-agent/state.db`。

插件默认只启用 `memory`、`verify`、`prove`、`cockpit` 四个本地核心 MCP，同时携带
已固定版本、默认关闭的 arXiv、OpenAlex 和 Lean MCP 定义。用户可以直接在 Codex
设置中按需开启。Lean 还需要另行安装工具链并创建 mathlib 项目。
详细步骤见 [Codex 安装与使用指南](docs/setup-codex-plugin.zh-CN.md) 和
[Lean 安装指南](docs/setup-lean.zh-CN.md)。

普通插件用户不要运行 `claudescientist dev-setup`。旧命令
`claudescientist setup --scope project` 暂时保留为兼容入口，但会显示弃用提示。

### 从源码仓库开发

安装并运行设置向导：

```powershell
uv sync
uv run claudescientist dev-setup
```

向导会一步步引导你完成 AI 客户端选择（`claude`、`codex` 或 `both`）、embedding 后端、证明语料灌入、隔离数据目录、Lean 工具链和自动剪枝等配置。随时可以重新运行；已完成的步骤会自动跳过。

非交互式设置可以指定 `CLAUDESCIENTIST_SETUP_AGENT_HOST=codex` 或
`CLAUDESCIENTIST_SETUP_AGENT_HOST=both`。Codex 适配是项目本地的：setup
会从现有 Claude Code 资产生成 `.codex/config.toml`、`.codex/agents/*.toml`
以及 `.agents/skills/` 下的仓库技能。

文献检索依赖两个外部 MCP。arXiv 通过 `uv tool run arxiv-mcp-server==0.5.0`
启动；OpenAlex 通过 `npx -y openalex-research-mcp@0.5.0` 启动，所以如果要用
OpenAlex 相关 librarian 工具，需要先安装 Node.js/npm。当前开发分支的插件已携带
这两个定义，但默认保持关闭；启用方法见
[docs/setup-codex-plugin.zh-CN.md](docs/setup-codex-plugin.zh-CN.md)。

<details><summary>手动安装（不用向导）</summary>

```powershell
uv sync --extra proof    # 同时装 sentence-transformers，用于证明主干
uv run python scripts/seed_proof_corpus.py
uv run python scripts/seed_proof_failures.py
```

</details>

源码开发模式下，从仓库根目录打开两个终端：

```powershell
# 终端 A: Claude Code（在仓库根目录）
claude

# 或终端 A: Codex（setup 选择 codex/both 后）
codex -C .

# 终端 B: cockpit TUI（在仓库根目录）
uv run python -m cockpit.tui
```

Windows Terminal 上开中文 UI：

```powershell
chcp 65001
$env:PYTHONUTF8=1
uv run python -m cockpit.tui --lang zh
```

在 TUI 里按 `L` 切换中英文标签。

在 Codex 里，ClaudeScientist 的 skill 用 `/skills` 选择，或者用
`$skill-name` 直接写在提示里。例如：

```text
$research-sop 研究 per-head dropout 是否有助于 ViT 扩展
```

在 Codex 里不要输入 `/research-sop`；这个写法是给 Claude Code 用的。
如果看不到 `$research-sop`，先确认 `.agents/skills/research-sop/SKILL.md`
已经生成，然后重启 Codex。安装后的插件 Skills 可以在任意项目目录中使用。

Lean 形式化验证需要单独安装。Codex 生成的 Lean MCP 默认是关闭的，等你按文档
装好后再打开。见 [`docs/setup-lean.zh-CN.md`](docs/setup-lean.zh-CN.md)。

## 接下来读什么

新手建议按这个顺序：

1. **[`docs/overview.zh-CN.md`](docs/overview.zh-CN.md)** — 各个组件如何配合，以及研究任务如何被记录
2. **[`docs/workflows/first-research-task.zh-CN.md`](docs/workflows/first-research-task.zh-CN.md)** — 跟着一个完整任务从头做到尾
3. **[`docs/architecture.zh-CN.md`](docs/architecture.zh-CN.md)** — 模块间的契约（写代码前必读）
4. **[`docs/tool-reference.zh-CN.md`](docs/tool-reference.zh-CN.md)** — 所有 MCP 工具，附签名和用法说明
5. **[`docs/setup-codex-plugin.zh-CN.md`](docs/setup-codex-plugin.zh-CN.md)** — Codex 插件安装与 Cockpit 信任检查

更多：

- 每个重大决策的设计理由 → [`docs/adr/`](docs/adr/)
- 项目下一步要往哪走 → [`docs/roadmap.zh-CN.md`](docs/roadmap.zh-CN.md)
- 历史设计文档 → [`docs/archive/`](docs/archive/)
- Agent 和贡献者守则 → [`AGENTS.zh-CN.md`](AGENTS.zh-CN.md)

## 运行时细节

默认路径：

- 共享状态：当前研究工作区下的 `.research-agent/state.db`
- 生成报告：当前研究工作区下的 `reports/`，默认已加入 `.gitignore`；只有明确要分享时才对单个文件 `git add -f`
- 隔离数据集：`%USERPROFILE%\.research-agent\heldout`，可用 `RESEARCH_AGENT_HELDOUT_DIR` 改写
- Embedding 后端：`local`（sentence-transformers/Qwen/Qwen3-Embedding-0.6B）；用 `RESEARCH_AGENT_EMBED_BACKEND=mock|openai` 覆盖。测试自动使用 `mock`。

单个 MCP 模块的开发服务器命令：

```powershell
uv run python -m memory_mcp.dev_server
uv run python -m verify_mcp.dev_server
uv run python -m prove_mcp.dev_server
uv run python -m cockpit.mcp_server
uv run python -m claudescientist.heldout register <name> <path>
```

## 验证

提交改动之前跑一遍：

```powershell
uv run ruff check
uv run pytest tests/memory_mcp tests/verify_mcp tests/prove_mcp tests/hooks tests/cockpit tests/scripts tests/e2e
uv run python -m cockpit.tui --once --lang zh
uv run python -c "import memory_mcp.server; import verify_mcp.server; import prove_mcp.server; import cockpit.mcp_server; print('OK')"
```

## 当前状态

本仓库适合本地开发和集成工作。要称得上"生产就绪"，还需要一次完整的端到端验证。

几件需要知道的事：

- **自动剪枝默认只是建议。** 设置 `RESEARCH_AGENT_AUTO_PRUNE=1` 才会真正暂停弱势分支。
- **Cockpit 只有终端界面。** 没有浏览器前端，没有 Web 服务器。
- **Prover agent 不装 Lean 也能用。** 自然语言证明流程可以独立运行；Lean 是可以后续配置的形式化验证工具，见 [`docs/setup-lean.zh-CN.md`](docs/setup-lean.zh-CN.md)。
- **`mem_nodes.elo_score` 是遗留列。** 新代码应该读 `mem_bt_ratings.strength`。

保护强度会明确标注：`enforced` 表示代码会机械拦截；`agent_gated` 表示 agent
流程会拒绝或复核，但它不是安全边界；`advisory` 只发出提醒。运行
`claudescientist doctor --workspace .` 可以检查 Cockpit 干预 hooks 是否已信任，
以及当前是否降级为 `monitor-only`。

完整工具列表和范围详情见 [`docs/tool-reference.zh-CN.md`](docs/tool-reference.zh-CN.md) 和 [`AGENTS.zh-CN.md`](AGENTS.zh-CN.md)。
