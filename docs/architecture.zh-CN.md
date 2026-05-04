# 架构与设计契约

> English version: [architecture.md](architecture.md)
> 这份文档描述了系统正确运行所必须维持的跨模块契约。请把每一节都视为不变量：除非有迁移脚本和配套测试，否则不要修改。

## 1. 模块全景

ClaudeScientist 由四个运行时层和一个共享状态文件组成。

| 层 | 包名 | 进程模型 | 与谁通信 |
|---|---|---|---|
| **运行时核心** | `claudescientist` | 库（不是常驻进程） | 所有其他层 |
| **Memory MCP** | `memory_mcp` | 每个 Claude Code 会话启动一个 stdio 子进程 | SQLite、通过 stdio 与 Claude 通信 |
| **Verify MCP** | `verify_mcp` | 每个 Claude Code 会话启动一个 stdio 子进程 | SQLite、通过 stdio 与 Claude 通信 |
| **Cockpit** | `cockpit` | TUI 进程（终端 B） **加** stdio MCP 桥 | SQLite |
| **Hooks** | `.claude/hooks/*.py` | Claude Code 在生命周期事件触发时启动的短生命周期进程 | SQLite |

这五层之间**从不直接互相调用**。它们只通过读写共享的 SQLite 文件 `.research-agent/state.db` 进行通信。

## 2. 共享运行时

`claudescientist.runtime` 模块拥有所有跨模块基础设施：

- **路径解析**：`state_db_path()`、`heldout_root()` 等函数是定位共享资源的**唯一**合法途径。功能包不得自己实现路径解析；特别是 held-out 数据根目录必须来自 `runtime.heldout_root()` 或注册过的 `ver_heldout_budgets.heldout_path` 行。
- **SQLite 连接配置**：`connect_sqlite()` 启用 WAL 模式、外键约束以及 5 秒的 busy timeout。请始终通过它连接，不要直接打开原始 `sqlite3` 连接。
- **Schema 迁移记账**：`ra_migrations` 表按组件记录 schema 版本号、schema 哈希、应用状态以及失败时的错误信息。任何无法用 `CREATE TABLE IF NOT EXISTS` 表达的结构性升级都必须使用显式的兼容性辅助函数，并附带测试。
- **Cockpit 事件写入**：`emit_cockpit_event()` 是向 cockpit 推送事件的标准方式。生产者应当在与底层状态变更相同的事务里调用它。

## 3. SQLite 状态契约

`.research-agent/state.db` 是 memory、verify、cockpit、hooks 四个模块的**唯一本地状态边界**。两条规则：

1. **每个组件仍然拥有自己的表**。请遵守前缀约定：`mem_*`、`ver_*`、`res_*`、`cockpit_*`，加上共享的 `ra_migrations` 和 `meta_*` 表。
2. **跨组件信号必须通过 `cockpit_events` 表**传递。只有在测试中做只读检查时，才允许直接读取其他模块的内部表。

### 当前的事件类型

cockpit 目前响应以下事件类型。生产者在写入 JSON payload 时，必须包含 `node_id`、`hypothesis_id` 之一或两者兼具（如果相关的话）：

| 事件类型 | 生产者 | 何时触发 |
|---|---|---|
| `graph_delta` | memory MCP | 创建了新节点或新边 |
| `failure_added` | memory MCP | 插入了一条新的失败记录 |
| `bt_rating_updated` | memory MCP | 应用了一次 Bradley-Terry 比较 |
| `branch_pause_suggested` | memory MCP | 低强度假说的 dry-run 建议 |
| `branch_paused` / `branch_promoted` | memory MCP | 真正切换状态（仅在自动剪枝模式下） |
| `prereg_locked` / `prereg_resolved` | verify MCP | 预注册生命周期事件 |
| `prov_dag_stale` | verify MCP | `refresh_claim` 检测到漂移 |
| `seed_run_recorded` | verify MCP | 一次 `seed_perturb` 调用完成 |
| `heldout_query_recorded` | verify MCP | 一次 held-out 查询消耗了预算 |
| `budget_exceeded` | verify MCP | 一次 `budget_consume` 触顶 |
| `replay_branch_created` | memory MCP | 创建了一个反事实分支 |
| `intervention` | cockpit | 用户写入了 `cockpit_interventions` |
| `note` | cockpit | 一条自由形式的 `:note` 备注 |
| `turn_end` | hook | `Stop` Hook 触发 |

cockpit 始终允许用户手动刷新，但常规工作流不应当依赖手动刷新来发现重要的状态变化。

### 用户可见标签

所有 cockpit 中可见的文本标签都必须经过 `cockpit.i18n` 模块，以保证英文和中文模式始终对齐。在 widget 内部硬编码字符串是退化行为。

## 4. Held-out 数据契约

held-out 数据（通常是测试集）受到双重保护。两层保护必须同时维持，契约才完整。

- **直接文件访问由 hooks 拦截**。PreToolUse Hook `leakage_guard.py` 会拒绝任何路径解析到已注册 held-out 目录下的 `Read`/`Write`/`Edit`/`Bash` 调用。这个拦截是无条件的，唯一例外是设置了环境变量 `RESEARCH_AGENT_VERIFY=1`——而这个环境变量只允许 `verify_mcp` 自己设置。
- **`query_heldout` 是唯一合法的访问路径**。它在运行模型脚本**之前**就预留预算，记录一行查询记录，**且不返回原始 stdout/stderr**——因为这些流可能包含泄漏的标签或样本。即使脚本执行失败，预留的预算也会被消耗，因为脚本已经被授权访问过 held-out 数据了。

如果某个 hook 或工具确实需要绕过这些保护，绕过本身必须附带书面理由和一个额外的单元测试。

## 5. 子智能体工具契约

子智能体的 prompt 和工具白名单是架构的一部分，不只是配置。两条规则：

1. **当一个 MCP 工具进入研究工作流时，必须更新对应的 agent 文件**。要为这个工具名是否出现在 agent prompt 里加一个 smoke 断言，避免 prompt 与现实悄悄走偏。
2. **verifier 角色是验证工具的集成点**。它必须能访问泄漏检测、provenance、种子稳定性、baseline 公平性以及 held-out 预算工具。其他角色只能访问严格的子集。

当前的角色分配定义在 `.claude/agents/` 目录下。请将其视为事实来源的一部分。

## 6. Bradley-Terry 排名层（v3.0）

这是替换了 v0.2 Elo 层的假说排名系统。

- **`mem_bt_ratings` 是假说排名的权威来源**。新读者应当优先使用 `strength`、`strength_var`、`n_comparisons` 三列。
- **`mem_nodes.elo_score` 仅作为向后兼容保留**。已有的 v0.2 读者（以及树形面板末尾的展示）仍然可以读取它，但任何新功能都不应依赖它。
- **`record_judgement` 是唯一进行双写的工具**——它同时写入旧的 `mem_judgements` 和新的 `mem_bt_comparisons`。`update_bt_rating` 只写新表，但接受更广泛的来源类型：`llm_judge`、`metric_diff`、`user_intervention`、`reviewer_critic`。
- **`suggest_pause_low_strength` 默认是 dry-run**。环境变量 `RESEARCH_AGENT_AUTO_PRUNE=1` 是唯一能把 `mem_bt_ratings.status` 改为 `paused` 的方式。`resume_branch` 是唯一允许的反向操作。
- **`replay_counterfactual` 不得修改 `mem_nodes` 或 `mem_bt_ratings`**。它只向 `mem_replay_branches` 写入一行。

### 数学简述

对于一次 `winner=i, loser=j` 的比较：

```
diff   = clip(theta_i - theta_j, [-30, 30])
p      = sigmoid(diff)
fisher = max(1e-6, p * (1-p)) * weight
delta  = lr * weight * (1 - p)            # lr = 0.5
theta_i := clip(theta_i + delta, [-12, 12])
theta_j := clip(theta_j - delta, [-12, 12])
var_i := 1 / (1/var_i + fisher)
var_j := 1 / (1/var_j + fisher)
```

排行榜上的置信区间为 `lcb = strength - 1.96 * sqrt(var)`、`ucb = strength + 1.96 * sqrt(var)`。初始 `strength_var = 1.0` 加上对 strength 的截断，相当于 Beta(1,1) 收缩先验，能在某节点总是赢的极端情况下避免数值爆炸。

## 7. 预注册与 Provenance DAG（v3.0）

这两个机制配合起来，构成了"可信数值"的工程化保证。

- **任何最终写入手稿的数值声明都必须可追溯**到一个 `ver_preregistrations.prereg_id`（其 `status='met'`）以及一个 `ver_seed_runs.verdict='stable'`。`reviewer` 子智能体在写作阶段会强制执行这条规则。
- **`ver_provenance_dag.input_hashes` 在 record 时记录了每个被引用输入文件的 sha256 哈希**。`refresh_claim` 会重新计算哈希，发现漂移时发出 `prov_dag_stale` 事件。**provenance 过期是写作的硬阻断项**。
- **`resolve_preregistration` 基于"当前打开的预注册行数"计算校正**。一次性锁定多个预注册会有意收紧 alpha，这是保守的多重比较行为。当前 v3.0 兼容实现中，`bh` 和 `bonferroni` 是同一套 Bonferroni-style 计算的别名。

## 8. 资源账本契约（v3.0）

资源预算机制本身很小，但规范严格。

- **`res_budget_ledger` 行按 `(scope, resource, window)` 三元组唯一**。当前追踪四种资源：`wallclock_sec`、`llm_tokens`、`heldout_queries`、`disk_mb`。
- **`budget_consume` 是唯一的写入者**。超额尝试返回 `{ok: False, error: "budget_exceeded"}` 并发出 `budget_exceeded` 事件；调用者自行决定是停止还是升级处理。
- **`budget_check` 是只读的，永远不扣减**。它检查的 `(scope, resource, window)` 边界必须与 `budget_consume` 写入的边界一致，否则两者会在临界值上产生分歧。

## 9. Hook 链契约

Hook 是系统的机械保证。它们作为短生命周期子进程，由 Claude Code 在生命周期事件触发时启动。契约如下：

| 事件 | Hook | 效果 |
|---|---|---|
| `PreToolUse` (Write/Edit/Bash) | `leakage_guard.py` | 拒绝任何路径解析到 held-out 目录下的工具调用 |
| `PreToolUse` (Bash) | `destructive_bash_guard.py` | 拒绝破坏性命令，除非命令中出现 `# CONFIRM_DESTRUCTIVE` 标记 |
| `PostToolUse` (Bash) | `provenance_log.py` | 从 stdout 中抠出数值 token 写入 `ver_provenance` |
| `UserPromptSubmit` | `intervention_pump.py` | 排空 `cockpit_interventions` 注入到 `additionalContext` |
| `Stop` | `intervention_pump.py` + `stop_flush.py` | 同样排空，并额外发出一个 `turn_end` 事件 |

Hook 必须是幂等的，并且在数据库缺失或损坏时优雅降级（典型场景：首次运行，数据库还没建立）。读不到状态意味着"没有待处理的干预"，而不是崩溃。

## 10. 这份契约故意留白的部分

有些事情这份文档刻意没有固定下来，因为它们预期会演化：

- **MCP 工具的具体集合**。按照 v3.0 计划，新工具会落地到现有的 memory 和 verify 服务器，无需新建 MCP 服务器。
- **Cockpit 面板布局**。只要数据契约保持不变，网格、模态框、快捷键都可以调整。
- **子智能体 prompt**。可以自由修改，前提是工具白名单与对应角色的契约保持一致（参见 §5.1）。
- **外部文献 MCP**。`arxiv-mcp-server` 与 `openalex-research-mcp` 都是按原样安装；我们只拥有 `memory_mcp` 中的 `ingest_paper` 压缩层。

## 11. 何时可以打破契约

如果未来的修改必须打破上述某条契约，正确的流程是：

1. 提一个 issue，说明什么会被打破以及为什么。
2. 写迁移脚本，把数据库前推。
3. **在写代码之前**先更新本文档。
4. 添加或更新对应的测试，把新契约钉住。

悄无声息地修改契约，是这个项目里严重程度最高的 bug 类型。

## 12. 再深一层：各模块地图

这份文档讨论的是**跨模块**契约。每个模块的 `__init__.py`（hooks 目录则是 `README.md`）里写有一份结构化地图，列出该模块的公开接口、自有表、关键不变量和"绝对不要"清单。在模块内部做非平凡修改之前，请先阅读：

- [`src/claudescientist/__init__.py`](../src/claudescientist/__init__.py)
- [`src/memory_mcp/__init__.py`](../src/memory_mcp/__init__.py)
- [`src/verify_mcp/__init__.py`](../src/verify_mcp/__init__.py)
- [`src/cockpit/__init__.py`](../src/cockpit/__init__.py)
- [`.claude/hooks/README.md`](../.claude/hooks/README.md)
