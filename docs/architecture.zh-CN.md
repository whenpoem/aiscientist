# 架构与设计契约

> English version: [architecture.md](architecture.md)

这份文档描述了模块之间的契约——系统正确运行所依赖的规则。修改任何一条都必须配上迁移脚本和对应测试。

## 怎么用这份文档

**第一部分**讲的是动代码之前你需要理解的契约：模块是什么、怎么共享状态、什么受保护、什么故意留了弹性。先读这部分。

**第二部分**是参考资料：BT 数学公式、事件 schema、hook 接线、v4.0 主干布局。需要查细节的时候来这里翻。

---

## 第一部分 — 契约

### 1. 模块全景

ClaudeScientist 由四个运行时层和一个共享状态文件组成。

| 层 | 包名 | 进程模型 | 与谁通信 |
|---|---|---|---|
| **运行时核心** | `claudescientist` | 库（不是常驻进程） | 所有其他层 |
| **Memory MCP** | `memory_mcp` | 每个 Claude Code 会话启动一个 stdio 子进程 | SQLite、通过 stdio 与 Claude 通信 |
| **Verify MCP** | `verify_mcp` | 每个 Claude Code 会话启动一个 stdio 子进程 | SQLite、通过 stdio 与 Claude 通信 |
| **Cockpit** | `cockpit` | TUI 进程（终端 B） **加** stdio MCP 桥 | SQLite |
| **Hooks** | `.claude/hooks/*.py` | Claude Code 在生命周期事件触发时启动的短命进程 | SQLite |

这五层**从不直接互相调用**。它们全部通过 `.research-agent/state.db` 这个 SQLite 文件来通信。

### 2. 状态文件

`.research-agent/state.db` 是 memory、verify、cockpit、hooks 四个模块的**唯一本地状态边界**。两条规则：

1. **每个组件拥有自己的表。** 前缀约定：`mem_*`、`ver_*`、`res_*`、`cockpit_*`，加上共享的 `ra_migrations` 和 `meta_*` 表。
2. **跨组件信号走 `cockpit_events` 表。** 直接读其他模块的内部表只允许在测试中做只读检查。

长驻代码和 MCP tools 打开数据库请一律走 `connect_sqlite()`——它会设好 WAL 模式、外键约束、row factory 和 5 秒的 busy timeout。短生命周期 hooks 使用 `connect_existing_sqlite()`，这样首次运行 DB 缺失或损坏时会 fail-open，不会在 hook 里新建状态库。运行时代码不要自己开原始 `sqlite3` 连接。

### 3. Held-out 数据保护

held-out 数据（通常是测试集）受到双重保护。两层保护必须同时成立，契约才完整。

- **直接文件访问被 hook 拦截。** PreToolUse Hook `leakage_guard.py` 会拒绝任何路径解析到已注册 held-out 目录下的 `Read`/`Write`/`Edit`/`Bash` 调用。拦截是无条件的，唯一例外是环境变量 `RESEARCH_AGENT_VERIFY=1`——这个变量只允许 `verify_mcp` 自己设置。
- **`query_heldout` 是唯一合法的访问路径。** 它在运行模型脚本**之前**就预留预算，记录一行查询记录，**且不返回原始 stdout/stderr**——因为里面可能包含泄漏的标签或样本。即使脚本执行失败，预留的预算也会被消耗，因为脚本已经被授权访问过数据了。

如果某个 hook 或工具确实需要绕过这些保护，绕过本身必须附带书面理由和一个额外的单元测试。

### 4. 子智能体工具契约

子智能体的 prompt 和工具白名单是架构的一部分，不只是配置。两条规则：

1. **当一个 MCP 工具进入研究工作流时，必须更新对应的 agent 文件。** 给它加一个 smoke 断言——工具名是否出现在 agent prompt 里——让 prompt 和现实不会悄悄走偏。
2. **verifier 角色是验证工具的集成点。** 它必须能访问泄漏检测、provenance、种子稳定性、baseline 公平性以及 held-out 预算工具。其他角色只能访问严格的子集。

当前的角色分配定义在 `.claude/agents/` 目录下。请将其视为事实来源的一部分。

### 5. 这份契约故意留白的部分

以下内容刻意没有固定下来，因为它们预期会演化：

- **MCP 工具的具体集合。** 按照 v3.0 计划，新工具落地到现有的 memory 和 verify 服务器，无需新建 MCP 服务器。
- **Cockpit 面板布局。** 只要数据契约不变，网格、模态框、快捷键都可以调整。
- **子智能体 prompt。** 可以自由修改，前提是工具白名单与角色契约保持一致（§4）。
- **外部文献 MCP。** `arxiv-mcp-server` 与 `openalex-research-mcp` 按原样安装；我们只拥有 `memory_mcp` 中的 `ingest_paper` 压缩层。

### 6. 何时打破契约

如果未来的修改必须打破上述某条契约：

1. 提一个 issue，说明什么会被打破以及为什么。
2. 写迁移脚本，把数据库前推。
3. **在写代码之前**先更新本文档。
4. 添加或更新对应的测试，把新契约钉住。

悄无声息地修改契约，是这个项目里严重程度最高的 bug 类型。

---

## 第二部分 — 参考资料

### 7. 共享运行时细节

`claudescientist.runtime` 模块拥有所有跨模块基础设施：

- **路径解析。** `state_db_path()`、`heldout_root()` 等函数是定位共享资源的唯一合法途径。功能包不得自己实现路径解析；特别是 held-out 数据根目录必须来自 `runtime.heldout_root()` 或注册过的 `ver_heldout_budgets.heldout_path` 行。
- **SQLite 连接配置。** `connect_sqlite()` 启用 WAL 模式、外键约束、row factory 和 5 秒 busy timeout。`connect_existing_sqlite()` 是 hook 安全变体：状态缺失或损坏时返回 `None`，不创建新 DB。
- **Schema 迁移记账。** `ra_migrations` 表按组件记录 schema 版本号、schema 哈希、应用状态和失败错误信息。无法用 `CREATE TABLE IF NOT EXISTS` 表达的结构性升级必须使用显式兼容性辅助函数，并附带测试。
- **Cockpit 事件写入。** `emit_cockpit_event()` 是向 cockpit 推送事件的标准方式。生产者应当在与底层状态变更相同的事务里调用它。

### 8. 事件类型与 cockpit 标签

cockpit 响应以下事件类型。生产者在写入 JSON payload 时，如果相关，必须包含 `node_id`、`hypothesis_id` 之一或两者兼具：

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

cockpit 始终允许手动刷新，但常规工作流不应当依赖手动刷新来发现重要的状态变化。

**用户可见标签**：所有 cockpit 中可见的文本标签都必须经过 `cockpit.i18n` 模块，以保证英文和中文模式始终对齐。在 widget 内部硬编码字符串是退化行为。

### 9. Bradley-Terry 排名层（v3.0）

替换了 v0.2 Elo 层的假说排名系统。

- **`mem_bt_ratings` 是假说排名的权威来源。** 优先使用 `strength`、`strength_var`、`n_comparisons` 三列。
- **`mem_nodes.elo_score` 仅作为向后兼容保留。** 已有的 v0.2 读者（以及树形面板末尾的展示）仍然可以读取它，但任何新功能都不应依赖它。
- **`record_judgement` 是唯一进行双写的工具**——它同时写入旧的 `mem_judgements` 和新的 `mem_bt_comparisons`。`update_bt_rating` 只写新表，但接受更广泛的来源类型：`llm_judge`、`metric_diff`、`user_intervention`、`reviewer_critic`。
- **`suggest_pause_low_strength` 默认是 dry-run。** 环境变量 `RESEARCH_AGENT_AUTO_PRUNE=1` 是唯一能把 `mem_bt_ratings.status` 改为 `paused` 的方式。`resume_branch` 是唯一允许的反向操作。
- **`replay_counterfactual` 不得修改 `mem_nodes` 或 `mem_bt_ratings`。** 它只向 `mem_replay_branches` 写入一行。

#### 数学简述

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

### 10. 预注册与 Provenance DAG（v3.0）

这两个机制配合起来，构成了"可信数值"的工程化保证。

- **发布级核心数值声明要可追溯**到 pin 过的 provenance、稳定的 seed 证据，以及 confirmatory 声明的 `ver_preregistrations.prereg_id`（其 `status='met'`）。探索性结果必须标注为探索性，而非静默提升为主结论。`reviewer` 子智能体在写作阶段会强制执行这条规则。
- **`ver_provenance_dag.input_hashes` 在 record 时记录了每个被引用输入文件的 sha256 哈希。** `refresh_claim` 会重新计算哈希，发现漂移时发出 `prov_dag_stale` 事件。stale provenance 会阻断发布级核心声明；没有 DAG 的记录会作为 unchecked 审计信息暴露出来，不能自动当成 freshness 证明。
- **`resolve_preregistration` 基于"当前打开的预注册行数"计算校正。** 一次性锁定多个预注册会有意收紧 alpha，这是保守的多重比较行为。当前 v3.0 兼容实现中，`bh` 和 `bonferroni` 是同一套 Bonferroni-style 计算的别名。

### 11. 资源账本（v3.0）

资源预算机制本身很小，但规范严格。

- **`res_budget_ledger` 行按 `(scope, resource, window)` 三元组唯一。** 当前追踪四种资源：`wallclock_sec`、`llm_tokens`、`heldout_queries`、`disk_mb`。
- **`budget_consume` 是唯一的写入者。** 超额尝试返回 `{ok: False, error: "budget_exceeded"}` 并发出 `budget_exceeded` 事件；调用者自行决定是停止还是升级处理。
- **`budget_check` 是只读的，永远不扣减。** 它检查的 `(scope, resource, window)` 边界必须与 `budget_consume` 写入的边界一致，否则两者会在临界值上产生分歧。

### 12. Hook 链

Hook 是系统的机械保证。它们作为短命子进程，由 Claude Code 在生命周期事件触发时启动。

| 事件 | Hook | 效果 |
|---|---|---|
| `PreToolUse` (Write/Edit/Bash) | `leakage_guard.py` | 拒绝任何路径解析到 held-out 目录下的工具调用 |
| `PreToolUse` (Bash) | `destructive_bash_guard.py` | 拒绝破坏性命令，除非命令中出现 `# CONFIRM_DESTRUCTIVE` 标记 |
| `PostToolUse` (Bash) | `provenance_log.py` | 从 stdout 中抠出数值 token 写入 `ver_provenance` |
| `UserPromptSubmit` | `intervention_pump.py` | 排空 `cockpit_interventions` 注入到 `additionalContext` |
| `Stop` | `intervention_pump.py` + `stop_flush.py` | 同样排空，并额外发出一个 `turn_end` 事件 |

Hook 必须是幂等的，并且在数据库缺失或损坏时优雅降级（典型场景：首次运行，数据库还没建立）。读不到状态意味着"没有待处理的干预"，不是崩溃。

### 13. 共用内核与领域主干（v4.0）

ClaudeScientist v4.0 把架构显式拆成**一个共用内核**加**两条领域主干**。切分线的正式记录在 [ADR 0008](adr/0008-two-trunk-domain-architecture.md)；本节把现有接口归类到内核 / empirical / proof，并列出 v4.0 新增的 proof 主干表面。

#### 内核里有什么

内核就是**不知道当前工作是 ML 实证还是统计证明**的那部分。它是项目的护城河——两条主干都靠它复利，跨域共用一本错题本本身就是 v4.0 的真实差异化。

| 接口 | 组件 | 为什么属于内核 |
|---|---|---|
| `claudescientist.runtime` | 路径、SQLite、迁移、事件 | 与领域无关的基础设施 |
| `mem_nodes` / `mem_edges` | 假设/命题图 | `kind` 字段携带领域；表本身不区分 |
| `mem_failures` + FTS5 | 跨域错题本 | 新增 `domain` 列做过滤；匹配算法本身领域无关 |
| `mem_bt_ratings` + 锦标赛工具 | 排序 + LUCB 区间 | 跨 kind 比较仍被禁止；同 kind 比较对 `hypothesis` 与 `proof_skeleton` 同样适用 |
| `meta_calibration` | 单 agent 可靠性 | 校准按裁判记录，与领域无关 |
| `mem_replay_branches` | 反事实快照 | 领域无关 |
| `cockpit` + `cockpit_events` | 实时 UI + 事件总线 | 一棵树承载两条主干 |
| 钩子: `destructive_bash_guard`、`intervention_pump`、`stop_flush` | 安全 + 生命周期 | 领域无关 |

#### Empirical 主干里有什么

| 接口 | 文件/表 | 备注 |
|---|---|---|
| `verify_mcp` | leakage / heldout / seed_perturb / baseline_fairness / 预注册 / provenance DAG / pin_metric / budget | 现有 v3.0 工具集 |
| 钩子: `leakage_guard.py`、`provenance_log.py` | `.claude/hooks/` | ML 专属（heldout 路径、指标提取） |
| Agents: engineer、verifier | `.claude/agents/` | ML 专属角色 |

这些工具与角色在各模块地图里被标 `[empirical]`。仅做证明工作的用户在工具目录里会看到它们，但通常不会调用。

#### Proof 主干里有什么

v4.0 新增；位于 [`src/prove_mcp/`](../src/prove_mcp/)：

| 接口 | 备注 |
|---|---|
| `prv_corpus_problems`、`prv_corpus_keywords` | StatEval 风格的检索语料；双关键词（lexical + semantic）+ 向量 |
| `prv_diagnostic_manifests` | 片段级诊断的输出 |
| `prv_lean_attempts` | 记录每一次 Lean 形式化尝试，无论成败 |
| 工具 | `ingest_proof_corpus`、`retrieve_skeletons`、`segment_proof`、`diagnose_snippet`（调用 `mem_failures` 时带 `domain='proof'`）、`apply_correction`、`triage_for_formalization` |
| Agents | prover（v0.1 stub 在 v4.0 真正激活，挂 `lean-lsp-mcp`） |
| Skills | `prove-sop` |
| 第三方 MCP | `lean-lsp-mcp` 与 `arxiv` / `openalex` 并列注册；只有触发规则放行后才会被调用 |

#### 四个合作接口

两条主干通过**且仅通过**这四个共享接口合作。任何想加第五个的人，请先写一份覆盖 ADR 0008 的新 ADR。

1. **同一棵树。** `mem_nodes.kind` 接受 `proposition`、`proof_skeleton`、`proof_snippet` 与原有 empirical kind。命题节点可以与 hypothesis 节点作为同一个 question 节点的兄弟。
2. **同一本错题本。** `mem_failures.domain` 给记录分域；`match_signatures` 接受可选 `domain` 过滤，默认跨域查询。脚本崩溃留下的 off-by-one 签名可以匹配证明片段里的 off-by-one 签名。
3. **同一张排行榜。** BT 比较同时接受 `hypothesis` 与 `proof_skeleton`（仅同 kind）。跨 kind 比较仍被禁止以避免语义混乱。
4. **同一个评审，两份清单。** `reviewer.md` 按 manuscript 内容自动切清单——empirical 中心声明使用相关证据锚点（pin / seed verdict / confirmatory 声明的 met preregistration / 未变旧 provenance）；theorem 断言新增"诊断 manifest 为空 + 已 Lean 验证或显式 `unverified` 标记"两条。`unverified` 是 manuscript 级标注，不是 `prv_diagnostic_manifests.status` 的取值。

`prove_mcp.tools.nodes` 是 proof trunk 唯一允许写入 shared graph tables（`mem_nodes`、`mem_edges`，以及 proof-skeleton 的 `mem_bt_ratings` seed）的入口。这个窄例外让"同一棵树"接口真正可用，但不会让 `prove_mcp` 其它部分变成 memory table owner。

#### 模块地图标签的读法

`src/memory_mcp/__init__.py` 与 `src/verify_mcp/__init__.py` 给每个公开工具与每张自有表加上下列三种标签之一：

- `[core]`：领域无关，两条主干都能用。
- `[empirical]`：只在 empirical 工作流下有意义。
- `[proof]`：v4.0 新增，位于 `prove_mcp`。

修改任何工具或表前，先看这个标签——它直接告诉你这次改动需要回归哪几条主干。

#### 跨主干的 snapshot 范围

`memory_mcp.snapshot()` 写出的 payload 同时覆盖两条主干，确保 `replay_counterfactual` 回放某条 proof 分支时不丢上下文：

- `active_frontier` 把 `proposition` 节点与 `question` / `hypothesis` 一起列出。
- `proof_drafts` / `proof_manifests` / `proof_lean_attempts` 分别快照最近若干行 `mem_nodes(kind='proof_skeleton')`、`prv_diagnostic_manifests`、`prv_lean_attempts`。
- `counts.proof_corpus` 是 `prv_corpus_problems` 的总行数。
- 所有读 `prv_*` 的语句都包了 `sqlite3.OperationalError`，所以一个 v3.0 老库（没有证明 schema）也能正常出快照，proof 字段全为空。

`stop_flush.py` 的回合摘要遵循同样的模式：digest 中的 `proof_manifests_*`、`lean_attempts_*`、`lean_wallclock_used_sec` 聚合在老库下回退为 0。

#### budgeter 覆盖

证明主干与 empirical 主干共用 `verify_mcp.budget_check` / `budget_consume` 节流。`.claude/agents/prover.md` § Budget 与 `prove-sop` skill 都要求：

1. 用 `prove_mcp.triage_for_formalization` 的 `estimated_difficulty` 估算 wallclock。
2. 较长的 Lean 尝试（>= 5 分钟）先调 `budget_check(scope='hypothesis:<proposition_id>', resource='wallclock_sec', requested=<估算>)`。低成本尝试在没有预算配置时可以直接执行，留审计提醒即可。
3. 尝试结束后用真实 `duration_sec` 调 `budget_consume`，让 `res_budget_ledger` 与 `prv_lean_attempts` 保持一致。

直接 `record_lean_attempt(status='timeout')` 而事先没过 `budget_check` 是审计提醒，但不影响 NL 证明本身的有效性。

### 14. 各模块地图

这份文档讨论的是**跨模块**契约。每个模块的 `__init__.py`（hooks 目录则是 `README.md`）里写有一份结构化地图，列出该模块的公开接口、自有表、关键不变量和"不要做"清单。在模块内部做改动之前请先阅读：

- [`src/claudescientist/__init__.py`](../src/claudescientist/__init__.py)
- [`src/memory_mcp/__init__.py`](../src/memory_mcp/__init__.py)
- [`src/verify_mcp/__init__.py`](../src/verify_mcp/__init__.py)
- [`src/cockpit/__init__.py`](../src/cockpit/__init__.py)
- [`.claude/hooks/README.md`](../.claude/hooks/README.md)
