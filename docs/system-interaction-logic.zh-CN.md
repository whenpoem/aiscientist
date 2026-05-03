# ClaudeScientist 系统交互过程与逻辑图

本文是一张面向后续开发者和使用者的系统总览图。重点不是列文件，而是解释一次研究任务如何在 Claude Code、MCP、hooks、SQLite 状态库、cockpit TUI 和验证机制之间流动。

## 1. 总览图

```mermaid
flowchart LR
  User["用户<br/>提出研究问题 / 干预 / 审阅结果"]
  Claude["Claude Code 主会话<br/>负责调度、解释、调用工具"]

  subgraph SOP["编排层：技能与子代理"]
    ResearchSOP["research-sop<br/>研究流程总控"]
    WriteupSOP["writeup-sop<br/>写作前检查"]
    BTSkill["bt-tournament<br/>候选假设排序"]
    PreregSkill["preregister<br/>实验前锁定指标"]
    ReplaySkill["replay<br/>反事实复盘"]
    Researcher["researcher<br/>提出假设"]
    Engineer["engineer<br/>实现实验"]
    Verifier["verifier<br/>验证结果"]
    Reviewer["reviewer<br/>论文式审稿"]
    Budgeter["budgeter<br/>资源预算门禁"]
  end

  subgraph Hooks["Claude hooks：实时安全与记录"]
    PreTool["PreToolUse<br/>leakage_guard<br/>destructive_bash_guard"]
    PostTool["PostToolUse<br/>provenance_log"]
    PromptHook["UserPromptSubmit<br/>intervention_pump"]
    StopHook["Stop<br/>stop_flush"]
  end

  subgraph MCP["MCP 工具层"]
    MemoryMCP["memory MCP<br/>假设图、BT 排名、失败记忆、文献压缩、校准、回放"]
    VerifyMCP["verify MCP<br/>泄漏检查、指标追踪、种子稳定性、公平性、held-out、预注册、预算"]
    CockpitMCP["cockpit MCP<br/>用户干预桥接"]
    Arxiv["arxiv MCP<br/>论文检索"]
    OpenAlex["openalex MCP<br/>文献网络检索"]
  end

  subgraph DB["共享状态边界：.research-agent/state.db"]
    MemTables["memory 表<br/>mem_nodes / mem_edges<br/>mem_bt_ratings / mem_bt_comparisons<br/>mem_failures / mem_lit_*<br/>meta_calibration / mem_replay_branches"]
    VerTables["verify 表<br/>ver_provenance / ver_metric_pins<br/>ver_seed_runs / ver_heldout_*<br/>ver_provenance_dag<br/>ver_preregistrations<br/>res_budget_ledger"]
    CockpitTables["cockpit 表<br/>cockpit_events<br/>cockpit_interventions"]
    Migrations["ra_migrations<br/>schema hash / version"]
  end

  subgraph UI["可观察与人工控制"]
    TUI["Textual cockpit TUI<br/>英文/中文切换<br/>实时图谱、风险、事件、预算"]
    HumanIntervention["人工干预<br/>approve / reject / note / pause / resume"]
  end

  subgraph External["外部与隔离资源"]
    Heldout["held-out 数据目录<br/>默认在用户目录 .research-agent/heldout"]
    Scripts["实验脚本 / 训练脚本"]
    Manuscript["报告 / 论文 / Markdown 写作文件"]
  end

  User --> Claude
  Claude --> ResearchSOP
  ResearchSOP --> Researcher
  ResearchSOP --> BTSkill
  ResearchSOP --> PreregSkill
  ResearchSOP --> Engineer
  ResearchSOP --> Verifier
  ResearchSOP --> Reviewer
  ResearchSOP --> WriteupSOP
  ResearchSOP --> ReplaySkill
  Engineer --> Budgeter

  Claude --> PreTool
  Claude --> PostTool
  User --> PromptHook
  Claude --> StopHook

  Researcher --> MemoryMCP
  BTSkill --> MemoryMCP
  ReplaySkill --> MemoryMCP
  Engineer --> VerifyMCP
  Verifier --> VerifyMCP
  Reviewer --> VerifyMCP
  Reviewer --> MemoryMCP
  Budgeter --> VerifyMCP
  ResearchSOP --> Arxiv
  ResearchSOP --> OpenAlex
  Claude --> CockpitMCP

  MemoryMCP <--> MemTables
  VerifyMCP <--> VerTables
  CockpitMCP <--> CockpitTables
  MemoryMCP --> CockpitTables
  VerifyMCP --> CockpitTables
  Hooks --> CockpitTables
  MemoryMCP --> Migrations
  VerifyMCP --> Migrations
  CockpitMCP --> Migrations

  TUI <--> CockpitTables
  TUI --> HumanIntervention
  HumanIntervention --> CockpitTables
  PromptHook --> CockpitTables
  CockpitTables --> Claude

  PreTool -.阻止直接访问.-> Heldout
  VerifyMCP --> Heldout
  VerifyMCP --> Scripts
  PostTool --> VerTables
  WriteupSOP --> Manuscript
  PreTool -.阻止无 provenance 数字写入.-> Manuscript
```

## 2. 一次研究任务的典型时序

```mermaid
sequenceDiagram
  autonumber
  participant U as 用户
  participant C as Claude Code
  participant H as Hooks
  participant M as memory MCP
  participant V as verify MCP
  participant DB as state.db
  participant T as cockpit TUI

  U->>C: 提出研究问题
  C->>H: UserPromptSubmit: 拉取 cockpit_interventions
  H->>DB: 读取待处理人工干预
  C->>M: match_signatures / query_literature
  M->>DB: 读取失败记忆和压缩文献
  C->>M: propose_hypothesis / attach_evidence
  M->>DB: 写入 mem_nodes / mem_edges
  M->>DB: 写入 cockpit_events(graph_delta)
  T->>DB: 轮询事件并刷新图谱

  Note over U,T: 研究过程中，用户可以随时在 TUI 里干预
  U->>T: 按 y/n，或输入 redirect/constrain/halt
  T->>DB: 写 cockpit_interventions(kind, target, payload)
  T->>DB: 同时写 cockpit_events(intervention)
  DB-->>T: 事件面板立刻显示“干预已排队”
  Note over DB,H: 干预先持久化排队，不直接抢占正在运行的工具

  U->>C: 下一次发送消息或要求继续
  C->>H: UserPromptSubmit: intervention_pump.drain()
  H->>DB: 读取 delivered_at IS NULL 的干预
  H->>DB: 标记 delivered_at，避免重复投递
  H-->>C: additionalContext 注入干预列表
  C->>C: 先消化 approve / reject / redirect / constrain / halt

  C->>M: judge_hypotheses / record_judgement
  M->>DB: 写 mem_judgements + mem_bt_comparisons
  M->>DB: 更新 mem_bt_ratings 强度和方差
  M->>DB: 写 cockpit_events(bt_rating_updated)

  C->>V: preregister
  V->>DB: 写 ver_preregistrations(open)
  V->>DB: 写 cockpit_events(prereg_locked)

  C->>V: budget_check(window=session)
  V->>DB: 读取 res_budget_ledger
  C->>V: budget_consume
  V->>DB: 原子扣减预算或发出 budget_exceeded

  C->>H: PreToolUse: 准备运行脚本或写文件
  H->>DB: 检查 held-out 根、provenance、危险命令
  C->>V: seed_perturb / baseline_fairness / query_heldout
  V->>DB: 写 ver_seed_runs / ver_heldout_queries
  V->>DB: 写 seed_run_recorded / heldout 事件
  C->>V: pin_metric / record_provenance(input_files)
  V->>DB: 写 ver_metric_pins / ver_provenance_dag

  C->>V: resolve_preregistration
  V->>DB: 写 observed_p_value / adjusted_p_value / status
  C->>V: refresh_claim
  V->>DB: 重算 input file sha256，标记 stale
  C->>M: get_bt_leaderboard / suggest_pause_low_strength
  M->>DB: dry-run 只发 branch_pause_suggested；显式开启后才 paused

  C->>V: check_provenance
  V->>DB: 返回 pins + seed_verdict + provenance
  C->>M: replay_counterfactual(可选)
  M->>DB: 只写 mem_replay_branches，不改主图
  C->>U: 输出结论或拒绝发布并说明 blockers
```

## 3. 核心机制索引

| 机制 | 作用 | 主要入口 | 写入状态 | 设计约束 |
|---|---|---|---|---|
| 假设图谱 | 保存问题、假设、证据、反驳关系 | `propose_hypothesis`, `attach_evidence`, `mark_refuted` | `mem_nodes`, `mem_edges` | cockpit 通过 `graph_delta` 实时看到变化 |
| Bradley-Terry 排名 | 用成对比较形成可持续更新的假设强度 | `record_judgement`, `update_bt_rating`, `get_bt_leaderboard` | `mem_bt_ratings`, `mem_bt_comparisons` | 只比较 hypothesis；`elo_score` 仅兼容旧读者 |
| 实时暂停建议 | 发现低上界假设，建议暂停 | `suggest_pause_low_strength`, `resume_branch` | `mem_bt_ratings.status`, `cockpit_events` | 默认 dry-run；只有 `RESEARCH_AGENT_AUTO_PRUNE=1` 才真正暂停 |
| 预注册 | 实验前锁定指标、方向、阈值和多重比较校正 | `preregister`, `resolve_preregistration` | `ver_preregistrations` | 先锁定再实验；保存 raw p 和 adjusted p |
| 指标与来源 | 给数字结论建立可审计证据链 | `record_provenance`, `pin_metric`, `check_provenance` | `ver_provenance`, `ver_metric_pins` | `check_provenance` 返回 pin、seed verdict 和来源 |
| Provenance DAG | 检测输入文件是否漂移 | `record_provenance(input_files=...)`, `refresh_claim` | `ver_provenance_dag` | stale 是写作硬阻断项 |
| 种子稳定性 | 检查指标是否对随机种子敏感 | `seed_perturb` | `ver_seed_runs` | reviewer 只接受 stable 的核心指标 |
| Baseline 公平性 | 防止新方法用了更多训练预算却和 baseline 比 | `baseline_fairness` | 只返回检查结果 | 超预算比例会成为验证风险 |
| held-out 防泄漏 | 受控查询保留测试集，阻止直接读取 | `query_heldout`, `leakage_guard.py` | `ver_heldout_budgets`, `ver_heldout_queries` | 直接文件访问由 hook 拦截；失败查询也消耗预算 |
| 资源预算 | 控制 wallclock、tokens、held-out 查询和磁盘 | `budget_check`, `budget_consume` | `res_budget_ledger` | 边界是 `(scope, resource, window)` |
| 失败记忆 | 记录重复失败，下一次先检索 | `record_failure`, `match_signatures` | `mem_failures` | 防止重复踩坑 |
| 校准 | 记录 agent 自信度和真实结果 | `record_calibration`, `calibration_report` | `meta_calibration` | 用 reliability diagram / Brier score 看 agent 是否过度自信 |
| 反事实回放 | 对过去快照做“如果当时选另一条路”复盘 | `snapshot`, `replay_counterfactual`, `list_replay_branches` | `mem_snapshots`, `mem_replay_branches` | 不改 `mem_nodes` 和 `mem_bt_ratings` 主状态 |
| cockpit TUI | 实时观察图谱、事件、风险和人工干预 | `python -m cockpit.tui` | 读写 `cockpit_events`, `cockpit_interventions` | 终端优先；中英文标签走 `cockpit.i18n` |
| hooks | 在工具调用前后做安全控制和记录 | PreToolUse / PostToolUse / UserPromptSubmit / Stop | 多个状态表和事件表 | 防 held-out 泄漏、防危险命令、记录 provenance、刷新干预 |

## 4. 关键设计逻辑

### 4.1 单一状态边界

所有本地运行状态都落到 `.research-agent/state.db`。memory、verify、cockpit 和 hooks 各自拥有表，但跨模块通信尽量通过 `cockpit_events`，避免模块之间直接互相改内部表。

### 4.2 先决策，再实验，再写作

研究主线是：

1. 先生成和记录假设。
2. 用 BT tournament 给候选假设排序，并保留不确定性区间。
3. 在实验前预注册指标和阈值。
4. 运行实验前先过预算门禁。
5. 实验结果必须经过 seed stability、baseline fairness、provenance 和 held-out 保护。
6. 写作前 reviewer 检查每个核心数字是否有 pin、stable seed verdict、met prereg、fresh provenance。

### 4.3 自动化只做可逆或可审计的事

- 自动剪枝默认只是建议，不改变状态。
- 真正暂停需要显式环境变量。
- 暂停可以通过 `resume_branch` 反转。
- 反事实 replay 不改主图，只产生一个 replay branch。
- 预算消耗、held-out 查询、预注册 resolution 都写入持久 ledger。

### 4.4 防泄漏路径是闭环

held-out 数据不能被脚本或 agent 直接读。正确路径是：

```mermaid
flowchart LR
  Register["注册 held-out 数据集"] --> Budget["建立 held-out 查询预算"]
  Budget --> Query["query_heldout"]
  Query --> Manifest["校验 manifest sha256"]
  Manifest --> Run["临时授权脚本运行"]
  Run --> Record["记录 query row 和预算消耗"]
  Record --> Metric["只返回 metric，不返回原始 stdout/stderr"]

  Direct["直接读 held-out 文件"] --> Guard["leakage_guard"]
  Guard --> Deny["拒绝工具调用"]
```

### 4.5 当前明确不是浏览器产品

cockpit 是 Textual TUI，支持 `--lang en|zh` 和运行时按 `L` 切换语言。当前没有支持的浏览器前端，也没有需要启动的 `uvicorn` 或 Vite 服务。

## 5. 一句话心智模型

ClaudeScientist 把 Claude Code 的研究流程变成一个“带记忆、带预算、带预注册、带验证、可人工干预的本地研究控制回路”：Claude 负责推理和调度，MCP 负责结构化读写，hooks 负责实时守门，SQLite 负责可审计状态，cockpit 负责观察和干预。
