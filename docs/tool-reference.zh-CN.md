# MCP 工具参考（v3.0）

> English version: [tool-reference.md](tool-reference.md)
> 项目内置的全部 MCP 工具的完整目录。工具按服务器分组。每个条目都给出了函数签名、用途、它会动到哪些状态、以及在什么场景下应该调用它。底层契约请参考 [`architecture.zh-CN.md`](architecture.zh-CN.md)；端到端流程请参考 [`workflows/`](workflows/)。

## 快速索引

- **memory MCP** — 23 个工具，覆盖假说图、BT 排名、校准、回放、失败记忆、文献
  - [假说图](#假说图) · [失败记忆](#失败记忆) · [BT 排名](#bradley-terry-排名) · [校准](#校准) · [回放](#回放) · [快照](#快照) · [文献](#文献)
- **verify MCP** — 13 个工具，覆盖泄漏、溯源、指标、预注册、held-out、预算
  - [泄漏检测](#泄漏检测) · [溯源](#溯源) · [指标 pin](#指标-pin) · [种子与公平性](#种子与公平性) · [Held-out](#held-out) · [预注册](#预注册) · [资源预算](#资源预算)
- **cockpit MCP** — 3 个工具，让 Claude 向 cockpit 推送
  - [Cockpit 桥](#cockpit-桥)

---

## memory MCP

由前缀为 `mem_*` 和 `meta_*` 的 SQLite 表支撑。在 Claude Code 中通过 `mcp__memory__<name>` 命名空间暴露。

### 假说图

#### `propose_hypothesis(text, parent_id=None, rationale="")`
向研究图中追加一个假说或问题节点。如果提供了 `parent_id`，会创建一条 `refines` 边。同时初始化一行 `mem_bt_ratings`，强度先验为 0、方差先验为 1.0。发出 `graph_delta` 事件。

**返回**：`{"node_id": "hyp_..."}`

**何时使用**：开启任何新研究方向时；或者从已有假说衍生子假说时。

#### `attach_evidence(node_id, evidence_text, polarity)`
创建一个证据节点，并通过 `supports` 或 `refutes` 边连接到 `node_id`。

**返回**：`{"evidence_id": "ev_..."}`

**何时使用**：每当一次实验产生与某个活跃假说相关的结果时。

#### `mark_refuted(node_id, reason, evidence_ids=None)`
把节点的 `state` 翻到 `refuted`。提供的证据 ID 会被记录为依据。

**返回**：`{"refuted": "<id>", "reason": "..."}`

**何时使用**：仅当证据足够确凿、值得退役该假说时。只有用一个新假说"取代（supersede）"它才能反转。

#### `get_active_frontier()`
返回最近的 50 个 `state='active'` 的假说或问题节点。

**返回**：`[{"node_id": ..., "kind": ..., "text": ..., "created_at": ...}, ...]`

**何时使用**：researcher 子智能体在提新假说之前，先看看当前还有什么在跑。

#### `get_ancestors(node_id)`
从 `node_id` 顺着 `parent` 链一直走到根。

**返回**：从子到根顺序的节点列表。

**何时使用**：在判断一个假说之前，需要先理解它完整的来龙去脉。

### 失败记忆

#### `record_failure(trigger, symptom, root_cause="", resolution="")`
向带 FTS5 索引的 `mem_failures` 表插入一条失败记录。同时计算确定性签名，重复失败会让 `seen_count` 累加，而不是堆叠成多行。

**返回**：`{"failure_id": <int>}`

**何时使用**：脚本失败时，尤其是根因不明显的那种。

#### `match_signatures(situation, k=5)`
对 `situation` 做 BM25 排名，返回最相关的 `k` 条历史失败。

**返回**：带 `score` 字段的失败记录列表。

**何时使用**：开始写新训练脚本之前，捕获"我之前已经踩过这个坑"的情况。

### Bradley-Terry 排名

#### `judge_hypotheses(hypothesis_a_id, hypothesis_b_id, criteria=None)`
拉取一对假说的标准比较 prompt。它本身**不**做比较——Claude 读取返回的 prompt 后自行判断。

**返回**：`{"prompt": "...", "criteria": [...], "a": {...}, "b": {...}}`

**何时使用**：作为 BT 比较的前半段，与 `record_judgement` 配对使用。

#### `record_judgement(a_node_id, b_node_id, winner_node_id, reason="", k_factor=32.0, weight=1.0, source="llm_judge")`
记录一次比较，并执行**双写**：更新 `mem_nodes.elo_score` 上的旧 Elo、追加到 `mem_judgements`、对 `mem_bt_ratings` 应用一次在线 BT 更新。发出 `bt_rating_updated` 事件。

**返回**：`{"judgement_id": <int>, "elo": {...}, "bt": {...}}`

**何时使用**：Claude 比较完两个假说之后（通常紧跟在 `judge_hypotheses` 之后）。

#### `update_bt_rating(winner_node_id, loser_node_id, source, weight=1.0, evidence_id=None, note="")`
直接的 BT 更新路径，**不**双写到 Elo 账本。接受比 `record_judgement` 更广的来源（`metric_diff`、`user_intervention`、`reviewer_critic`）。

**返回**：`{"comparison_id": <int>, "bt": {...}}`

**何时使用**：当比较的来源不是 LLM judge 时——例如某个实验结果直接证明一个假说更优。

#### `get_bt_leaderboard(top_k=20, include_paused=False)`
返回按 BT 强度排名的前 `top_k` 个假说，附带 95% LUCB 置信区间（`lcb`、`ucb`）。比较次数少于 3 的假说会带有 `insufficient_samples=True` 标记。

**返回**：排行榜行的列表。

**何时使用**：锦标赛一轮结束后，在决定哪些假说继续推进之前。

#### `suggest_pause_low_strength(ucb_threshold=-0.5, min_comparisons=6)`
找出所有 `n_comparisons >= min_comparisons` 且 `ucb < ucb_threshold` 的活跃假说。默认只发出 `branch_pause_suggested` 事件。设置 `RESEARCH_AGENT_AUTO_PRUNE=1` 后，它还会把 `mem_bt_ratings.status` 翻到 `paused` 并发出 `branch_paused`。

**返回**：`{"candidates": [...], "auto_pruned": bool}`

**何时使用**：长研究 session 中周期性运行，识别已经在锦标赛中败北的方向。

#### `resume_branch(node_id, reason)`
反转一次暂停：状态回到 `active`，发出 `branch_promoted`。

**返回**：`{"resumed": "<id>", "reason": "..."}`

**何时使用**：当新证据让某个先前被降级的方向重新有戏时。

#### `expected_information_gain(candidate_node_ids)`
对每个候选假说，计算"它与当前榜首假说做下一次成对比较"所能带来的预期方差缩减。

**返回**：`{"node_id": ..., "eig": float, "current_var": float}` 列表。

**何时使用**：当一次比较的成本不可忽略，需要挑选信息量最大的对子时。

### 校准

#### `record_calibration(agent_name, predicted_p, observed_outcome, context="")`
为某个 agent 追加一条校准样本。`predicted_p` 是这个 agent 声明的某事件发生的概率；`observed_outcome` 是实际是否发生（布尔值）。

**返回**：`{"recorded": True, "bucket": <float>}`

**何时使用**：每当一个 agent 做出一个事后可以核对的、带置信度的声明时。

#### `calibration_report(agent_name=None)`
把校准样本按 reliability diagram 的 10 个桶（0.05、0.15、…、0.95）聚合。如果省略 `agent_name`，就报告所有 agent。

**返回**：`{"agents": {<name>: {"buckets": [...], "brier_score": <float>, ...}}}`

**何时使用**：按固定节奏跑（例如每 50 次 judgement 之后），用来发现过度自信的漂移。

### 回放

#### `replay_counterfactual(snapshot_id, counterfactual)`
从一个保存的快照创建一个反事实分支。只写入 `mem_replay_branches`；主图 `mem_nodes` 与 `mem_bt_ratings` 不受影响。发出 `replay_branch_created`。

**返回**：`{"replay_id": "rep_...", "snapshot_id": "...", "counterfactual": "..."}`

**何时使用**：当你想问"如果当时追的是被剪掉的那条分支会怎样"，但不想冒险动到当前状态时。

#### `list_replay_branches(limit=20)`
返回最近的若干个 replay 分支。

**返回**：replay 行的列表。

**何时使用**：审计阶段，回顾过去的剪枝决策时。

### 快照

#### `snapshot(label="")`
把当前的图谱与 BT 评分凝固成一个快照行。

**返回**：`{"snapshot_id": "snap_...", "label": "...", "node_count": <int>}`

**何时使用**：在有意义的检查点——研究 session 结束、做出有风险的剪枝之前、发布结果之前。

### 文献

#### `ingest_paper(paper_id, source, structured)`
存储一篇论文的结构化压缩信息。`structured` 字典必须包含 `title`、`authors`、`year`、`venue`、`problem`、`method`、`claimed_results`、`assumptions`、`limitations`、`trust_level`、`raw_abstract`。`source` 只能是 `arxiv`、`openalex`、`manual` 之一。

**返回**：`{"ingested": "<paper_id>"}`

**何时使用**：在 librarian 子智能体内部，通过 `arxiv` 或 `openalex` 拉到摘要之后。

#### `query_literature(question, k=10)`
对论文做 BM25 排名，并按 `trust_level` 加权。

**返回**：论文字典列表。

**何时使用**：任何涉及文献的研究回合开始时。

#### `find_baselines_for(method_description, k=5)`
`query_literature` 的便利包装，用于查找方法相近的论文。

**返回**：与 `query_literature` 相同的形状。

**何时使用**：engineer 子智能体准备挑选对比 baseline 时。

#### `find_contradictions()`
浮现所有通过 `contradicts` 边相连的节点对。

**返回**：矛盾对的列表。

**何时使用**：reviewer 审查阶段，确认没有任何已发布结论与之前的结论相互矛盾。

---

## verify MCP

由 `ver_*` 与 `res_*` 表支撑。通过 `mcp__verify__<name>` 暴露。

### 泄漏检测

#### `leakage_check(script_path=None, script_text=None)`
对一个 Python 脚本进行 AST 扫描，检测已知泄漏模式：在 train+test 拼起来的数据上 `fit()`、读取 held-out 路径、常见的标签泄漏惯用法。

**返回**：`{"clean": bool, "findings": [{"rule": ..., "line": ..., "message": ...}]}`

**何时使用**：跑任何训练脚本之前，特别是涉及 train/test 拆分的。

### 溯源

#### `record_provenance(claim, value, session_id, source_command="", input_files=None, parent_prov_ids=None)`
为一个数值声明追加一条溯源记录。当提供 `input_files` 时，每个路径都会被 sha256 哈希，指纹存入 `ver_provenance_dag`，方便后续 `refresh_claim` 重新校验。

**返回**：`{"recorded": True, "provenance_id": <int>, "dag": {...}}`

**何时使用**：每次脚本报出一个未来可能被引用的数值结果时。

#### `check_provenance(claim)`
查找一个声明，返回它的 pin（如果有）、种子稳定性结论、来源命令。

**返回**：`{"status": "found"|"missing", "evidence": {...}}`

**何时使用**：写作流程中，任何数值声明进入手稿之前都要查一次。

#### `refresh_claim(claim)`
重新计算该声明的 provenance DAG 中每个输入文件的哈希，与存储的哈希对比。任何漂移都会发出 `prov_dag_stale` 事件。

**返回**：`{"status": "fresh"|"stale", "drifted_files": [...]}`

**何时使用**：写作时，以及任何上游数据文件被改动之后。

### 指标 pin

#### `pin_metric(claim, value, session_id, source_command="", note="")`
pin 住一个核心指标，让写作流程知道哪些数字是要紧的。会创建一行 provenance 和一行 `ver_metric_pins`，并把它们关联起来。发出 `claim_pinned`。

**返回**：`{"pinned": True, "pin_id": <int>, "provenance_id": <int>}`

**何时使用**：每个研究产物会报出的"头条数字"都对应一次 pin。

### 种子与公平性

#### `seed_perturb(script_path, seed_arg="--seed", seeds=None, metric_pattern=..., metric_pin_id=None, timeout_sec=600)`
对每个种子（默认 `[0, 1, 2]`）跑一遍 `script_path`。从每次的 stdout 抠出指标，计算均值和标准差，把 verdict 分类为 `stable` 或 `unstable`（阈值：std < 0.01）。提供 `metric_pin_id` 时，本次种子运行会被关联到那个 pin，这样写作检查能找到它。

**返回**：`{"ok": True, "values": [...], "mean": ..., "std": ..., "verdict": "stable"|"unstable"}`

**何时使用**：每个会进入手稿的指标 pin 都要跑。

#### `baseline_fairness(proposed_log, baseline_log, threshold_ratio=3.0)`
解析两份运行日志，提取 `epochs`、`lr_trials`、`param_count`。任意一个轴的比例超过 `threshold_ratio`，就把整体判为 `unfair`。

**返回**：`{"verdict": "fair"|"unfair", "ratios": {...}, "unfair_axes": {...}}`

**何时使用**：论文结果中只要涉及"提出方法 vs baseline"的比较，就要跑。

### Held-out

#### `query_heldout(dataset, model_path, batch_size=1)`
held-out 数据的唯一合法访问路径。在执行**之前**先预留预算，校验 manifest sha256，临时给脚本授权访问，记录查询，**仅**返回解析出的指标（不返回 stdout/stderr）。

**返回**：`{"ok": True, "metric": <float>, "remaining_budget": <int>}`

**何时使用**：仅在提案方法已经通过所有内部验证之后；通常每个项目对每个数据集只用一两次。

### 预注册

#### `preregister(hypothesis_id, metric, direction, threshold, mc_correction="bh", alpha=0.05, seeds=None, note="")`
**在任何实验开始之前**就锁定该假说的证伪目标。`direction` 只能是 `higher_better` 或 `lower_better`。`mc_correction` 只能是 `bh`、`bonferroni`、`none`；当前 `bh` 和 `bonferroni` 是同一套 Bonferroni-style 计算的 v3.0 兼容别名。发出 `prereg_locked`。

**返回**：`{"prereg_id": "preg_...", "alpha_adjusted": <float>}`

**何时使用**：作为 BT 锦标赛与 engineer 子智能体之间的门禁。任何实验都不应在没有它的情况下启动。

#### `resolve_preregistration(prereg_id, observed_value, observed_p_value=None, note="")`
拿 `observed_value` 与锁定的阈值和方向比对。如果给了 `observed_p_value`，就在所有当前打开的预注册上应用多重比较校正。发出 `prereg_resolved`。

**返回**：`{"status": "met"|"unmet", "adjusted_p_value": ..., ...}`

**何时使用**：实验跑完、指标 pin 完成之后。

#### `list_preregistrations(hypothesis_id=None, status=None)`
按假说或状态筛选活跃和历史预注册。

**返回**：预注册行的列表。

**何时使用**：reviewer agent 在 resolve 之前，先了解当前打开的全部测试空间。

### 资源预算

#### `budget_check(scope, resource, window)`
对一行 `(scope, resource, window)` 账本做只读检查。

- `scope`：通常是 `session`、`per_hypothesis` 或 `global`
- `resource`：`wallclock_sec`、`llm_tokens`、`heldout_queries`、`disk_mb` 之一
- `window`：时间窗口键

**返回**：`{"limit": ..., "used": ..., "remaining": ...}`

**何时使用**：启动任何昂贵操作之前。

#### `budget_consume(scope, resource, window, amount)`
原子地扣减预算。超额时返回 `{"ok": False, "error": "budget_exceeded"}` 并发出 `budget_exceeded`。

**返回**：成功时 `{"ok": True, "remaining": ...}`。

**何时使用**：由 budgeter agent 调用，或者由 engineer 在消耗资源前直接调用。

---

## cockpit MCP

一个小型 stdio 桥，让 Claude 能向 cockpit 推送内容。通过 `mcp__cockpit__<name>` 暴露。

### Cockpit 桥

#### `push_graph_delta(node_id, kind, text)`
插入一条合成的 `graph_delta` 事件，让 cockpit 在图变更并非来自 `memory_mcp` 的场景下也能亮起来。

**返回**：`{"ok": True}`

**何时使用**：很少用——memory MCP 通常自动发出这个事件。仅保留给特殊集成场景。

#### `queue_intervention(kind, target=None, payload="")`
等价于"用户在 cockpit 里按了一个键"的程序化版本。适合做脚本化干预。

**返回**：`{"ok": True, "intervention_id": <int>}`

**何时使用**：测试 fixture 或批量处理。

#### `record_note(text)`
向 cockpit 事件流追加一条自由形式的备注。

**返回**：`{"ok": True}`

**何时使用**：Claude 想在事件日志中留个标记供日后回看时。

---

## 外部 MCP

下列服务器以第三方包的形式安装，我们不拥有它们的 schema。在这里列出仅为完整性。

| 服务器 | 来源 | 用途 |
|---|---|---|
| `arxiv` | `arxiv-mcp-server` | 搜索和拉取 arXiv 论文 |
| `openalex` | `openalex-research-mcp`（npx） | 搜索和拉取 OpenAlex 文献 |

---

## 约定

- 所有工具都返回 JSON 可序列化的字典。
- 错误响应在适用时遵循 `{"ok": False, "error": "<reason>"}` 的形状。
- 发出 cockpit 事件的工具，会把事件写入与底层状态变更相同的 SQL 事务里。
- 工具签名很少改变；新能力一般以新工具的形式加入，而不是给已有工具加新参数。

如果你发现本文档与源代码不一致，**以源代码为准**——请提 issue 让本文档跟上。
