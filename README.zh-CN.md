# ClaudeScientist

**A research co-pilot that remembers, verifies, and lets you steer.**

[![version](https://img.shields.io/badge/version-v5.0.0-blue)](https://github.com/whenpoem/aiscientist/releases) [![python](https://img.shields.io/badge/python-%E2%89%A53.11-3776AB?logo=python&logoColor=white)](https://www.python.org/) [![tests](https://img.shields.io/badge/tests-729-green)](tests/) [![license](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)

> English version: [README.md](README.md)

ClaudeScientist 给 Claude Code 或 Codex 装上了 AI 科研系统普遍缺少的几样东西：记住你试过什么、验证你的数字是否靠谱、给你一个终端仪表盘让你实时盯着研究进展、随时插手。

你丢给 agent 一个研究问题，它会生成假说、让假说互相比赛排名、跑实验（自带安全检查），并且给每一个产出的数字记录来龙去脉。你在旁边的终端窗口全程看着，随时可以否决、改方向、放行。

**当前版本**：v5.0.0 —— 仪表盘变成「活动流式」研究监控。屏幕顶部是**阶段栏**（`idle / explore / select / experiment / verify / prove / review / narrate` 八态),从 `cockpit_events` 实时推断;主面板是**活动卡**(一张卡 = 一个研究动作——一次 BT 锦标赛、一次证明诊断、一次 Lean 尝试),取代原来的事件流水;新的 **Focus tab** 列出 agent 当下在搞的节点。原有事件流被保留为底部可折叠的**审计日志**(`A` 切换)。新增两个可选 MCP 原子工具:`cockpit__set_phase` 和 `cockpit__narrate`,让 SOP 驱动的 agent 在分支点显式标注上下文,而不耦合到 cockpit 的渲染细节。**无 schema 迁移**——阶段 / 焦点 / 活动卡都是 `cockpit_events` 之上的纯函数派生。详见 [ADR 0011](docs/adr/0011-cockpit-activity-streaming.md) 和 [architecture.zh-CN.md §14](docs/architecture.zh-CN.md#14-cockpit-activity-streaming-v50)。

**v4.2.0 的功能继续可用**(见 [retrospective-v4.2.zh-CN.md](docs/retrospective-v4.2.zh-CN.md)):tab 分三组(跨主干 / 实验 / 证明)、详情面板可折叠分节、`w`/`i`/`t` 按面板划分作用域;向量检索支持任何 OpenAI 兼容服务商([ADR 0010](docs/adr/0010-multi-provider-embeddings.zh-CN.md),DashScope / Jina / Voyage / GLM 已测,本地默认 `Qwen/Qwen3-Embedding-0.6B`);报告导出([ADR 0009](docs/adr/0009-reports-as-files-monitoring-as-tui.zh-CN.md))和冷启动 Welcome 屏不变。两主干切分见 [architecture.zh-CN.md §13](docs/architecture.zh-CN.md#13-共用内核与领域主干v40)。

## 长什么样

并排打开两个终端窗口，就是全部界面。

<picture>
  <img alt="Cockpit TUI 截图" src="docs/assets/image2.png" width="800">
</picture>

*Cockpit TUI —— 假说树、证据、评分、事件流，一个终端窗口搞定。*

左右两个终端不直接通信——它们都跟中间那个 SQLite 文件打交道。这是整个系统最核心的设计：所有模块通过一个共享数据库协作，不走网络。

| 角色 | 在哪里 | 干什么 |
|---|---|---|
| **Claude Code / Codex** | 终端 A | 研究主力：理解你的问题，调工具，写代码跑实验 |
| **MCP 服务器** | 后台进程 | 给 agent 提供工具——记忆、验证、文献检索、证明生成 |
| **Hooks** | 启动时自动加载 | 每次工具调用前后自动跑安全检查（拦截数据泄漏、记录溯源） |
| **Cockpit TUI** | 终端 B | 实时显示状态；你可以在这里批准、否决、改方向 |
| **SQLite** | `.research-agent/state.db` | 所有状态都在这一个文件里：假说、证据、评分、指标、事件 |

## 你能用它做什么

- **记住你的研究思路。** 每一个假说、每一条证据、每一次分支决策都持久保存在图里。读过的论文也会被压缩索引。下周回来，一切都还在。想回顾之前剪掉的方向？跑一次反事实回放，不动实际数据。
- **给竞争中的想法排名。** Bradley-Terry 锦标赛让假说两两对决，产出一张带置信区间的排行榜，让你看清哪个方向真正领先。
- **实验之前先锁定标准。** 预注册机制要求你在看到结果之前就定好要看的指标、方向和阈值。多重比较校正自动完成。
- **让你的数字站得住脚。** 每个上报的数字都会被核查：换随机种子还能复现吗？是哪些文件产出的？之后有没有改动过？baseline 比较有没有用相当的计算预算？审稿 agent 会拦下任何未经验证的数字。
- **不让同样的错误犯两次。** 错题本记住你每一次调试经历。下次碰到类似问题，系统会把上次的修复方案翻出来。
- **实时盯着、随时插手。** Cockpit TUI 实时展示假说树、评分和事件流。按一个键就能否决某个假说或者写一条批注——干预会在下一轮被 Claude 拾取。
- **生成和验证统计证明**（v4.0）。证明主干负责起草、切片、对照历史错误模式做诊断，还可以选装 Lean 4 做形式化验证。

## 快速开始

安装并运行设置向导：

```powershell
uv sync
uv run python -m claudescientist.setup
```

向导会一步步引导你完成 agent host 选择（`claude`、`codex` 或 `both`）、embedding 后端、证明语料灌入、隔离数据目录、Lean 工具链和自动剪枝等配置。随时可以重新运行；已完成的步骤会自动跳过。

非交互式设置可以指定 `CLAUDESCIENTIST_SETUP_AGENT_HOST=codex` 或
`CLAUDESCIENTIST_SETUP_AGENT_HOST=both`。Codex 适配是项目本地的：setup
会从现有 Claude Code 资产生成 `.codex/config.toml`、`.codex/agents/*.toml`
以及 `.agents/skills/` 下的仓库技能。

文献检索依赖两个外部 MCP。arXiv 通过 `uv tool run arxiv-mcp-server`
启动；OpenAlex 通过 `npx -y openalex-research-mcp` 启动，所以如果要用
OpenAlex 相关 librarian 工具，需要先安装 Node.js/npm。

<details><summary>手动安装（不用向导）</summary>

```powershell
uv sync --extra proof    # 同时装 sentence-transformers，用于证明主干
uv run python scripts/seed_proof_corpus.py
uv run python scripts/seed_proof_failures.py
```

</details>

运行——从仓库根目录打开两个终端：

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

在 Codex 里，ClaudeScientist 的 skill 要通过 `/skills` 选择，或者用 `$`
显式提及，例如：

```text
$research-sop 研究 per-head dropout 是否有助于 ViT 扩展
```

不要输入 `/research-sop`；`/...` 是 Codex 的 slash command 命名空间。
Claude Code 用户继续使用原有的 `/research-sop` 快捷入口。
如果看不到 `$research-sop`，先确认 `.agents/skills/research-sop/SKILL.md`
已经生成，然后重启 Codex，并从仓库根目录启动。

Lean 形式化验证需要单独安装——见 [`docs/setup-lean.zh-CN.md`](docs/setup-lean.zh-CN.md)。

## 接下来读什么

新手建议按这个顺序：

1. **[`docs/overview.zh-CN.md`](docs/overview.zh-CN.md)** — 完整的心智模型：各部分怎么配合、一次研究任务从头到尾走一遍、三条设计原则
2. **[`docs/workflows/first-research-task.zh-CN.md`](docs/workflows/first-research-task.zh-CN.md)** — 跟着一个完整任务从头做到尾
3. **[`docs/architecture.zh-CN.md`](docs/architecture.zh-CN.md)** — 模块间的契约（写代码前必读）
4. **[`docs/tool-reference.zh-CN.md`](docs/tool-reference.zh-CN.md)** — 所有 MCP 工具，附签名和用法说明

更多：

- 每个重大决策的设计理由 → [`docs/adr/`](docs/adr/)
- 项目下一步要往哪走 → [`docs/roadmap.zh-CN.md`](docs/roadmap.zh-CN.md)
- 历史设计文档 → [`docs/archive/`](docs/archive/)
- Agent 和贡献者守则 → [`AGENTS.zh-CN.md`](AGENTS.zh-CN.md)

## 运行时细节

默认路径：

- 共享状态：仓库根目录下的 `.research-agent/state.db`
- 生成报告：仓库根目录下的 `reports/`，默认已加入 `.gitignore`；只有明确要分享时才对单个文件 `git add -f`
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
- **Prover agent 不装 Lean 也能用。** NL 证明工作流独立运行；Lean 是可以后装的额外保险，见 [`docs/setup-lean.zh-CN.md`](docs/setup-lean.zh-CN.md)。
- **`mem_nodes.elo_score` 是遗留列。** 新代码应该读 `mem_bt_ratings.strength`。

完整工具列表和范围详情见 [`docs/tool-reference.zh-CN.md`](docs/tool-reference.zh-CN.md) 和 [`AGENTS.zh-CN.md`](AGENTS.zh-CN.md)。
