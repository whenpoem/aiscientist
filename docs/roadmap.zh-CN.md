# 后续发展方向

> English version: [roadmap.md](roadmap.md)
> 这份文档汇总了 v3.0 之后的中长期发展方向。它不是承诺清单，而是设计判断：在已有架构基础上，下一步最值得做什么、为什么、以及可能的实现路径。每条方向都标注了"价值"与"复杂度"的初步评估。

## 写在前面：当前的成熟度坐标

ClaudeScientist v3.0 已经把"研究流程的工程化"做到了一个可用的程度：

- **机械层成熟**：MCP 工具、Hook 链、SQLite 状态、TUI 面板都跑通且有测试覆盖
- **方法学层成熟**：Bradley-Terry 排名、预注册、溯源 DAG、多重比较校正都已就位
- **生态层尚浅**：还是单用户、单会话、纯本地的工具；没有跨项目协作、没有云端同步、没有对外发布的对比基准

下面的方向大致可以分成三个层次：**深化现有能力**（方向 1-4）、**补齐相邻能力**（方向 5-7）、**走向生态**（方向 8-10）。方向 11 是 v4.0 的承诺级方向，会推翻原本"不做 Lean"的判断、加上 proof 主干，相关决策记录在 [ADR 0008](adr/0008-two-trunk-domain-architecture.md) 与 v4.0 分期计划里。

---

## 一、深化现有能力

### 方向 1：把 BT 排名从被动排序升级为主动实验设计

**当前**：`expected_information_gain` 已经能计算每个候选与榜首比较的预期方差缩减量，但调用是手动的，且只用了贪心策略。

**建议**：引入 Thompson Sampling（汤普森采样）替代贪心选择。每次需要决定"下一对比较哪两个假说"时，对每个假说从其后验分布 N(strength, strength_var) 中采样，然后选采样值最高的两个。

**价值**：高。Thompson Sampling 在 multi-armed bandit 设定下有 O(√(K ln K · T)) 的 regret bound，能在探索（高方差黑马）与利用（已确认的强势假说）之间自动平衡。这把 BT 锦标赛从"事后排序"变成"主动实验设计"，节省可观的比较次数。

**复杂度**：低。在 `memory_mcp/impl.py` 加一个 `thompson_select_pair` 工具即可，核心实现仅几行 `random.gauss`。

**约束**：需要决定何时触发——可以做成 `bt-tournament` skill 的可选模式，或者在 `expected_information_gain` 旁提供并行选项。

---

### 方向 2：Meta-Calibration 闭环

**当前**：`meta_calibration` 表记录了判断者的校准数据，可以输出 reliability diagram 和 Brier Score，但这些数据只供展示，未反馈到决策。

**建议**：将校准信息接入 `update_bt_rating` 的权重逻辑。当一次比较来源是 `llm_judge` 时，根据该 judge 在对应置信度区间的历史校准误差，动态调整 `weight`：

```
weight *= 1 - calibration_error_at_bucket(judge_name, predicted_p)
```

校准好的 judge 权重不变，校准差的 judge 权重被自动降低。

**价值**：中高。这实现了系统对自身判断质量的自适应信任管理。多模型协作场景（如 researcher 用 Sonnet、reviewer 用 Opus）的差异化处理也变得自然。

**复杂度**：中。需要决定校准误差的衰减窗口（最近 N 次还是全部历史）、最小样本量阈值（避免新 agent 一进来就被歧视），以及如何在 cockpit 暴露这种动态权重。

---

### 方向 3：假说谱系的"遗传距离"传播

**当前**：`suggest_pause_low_strength` 逐个假说独立判断 UCB。但假说图是树状的，子假说与父假说共享前提；父假说被证伪时，子假说的先验概率应当下调。

**建议**：当假说 H_parent 的 BT 强度大幅下降时，按深度衰减传播给后代：

```python
for child in descendants(H_parent):
    depth = path_length(H_parent, child)
    decay = 0.5 ** depth
    child.strength -= delta_parent * decay
    child.strength_var += abs(delta_parent * decay) * 0.1
```

**价值**：中高。在研究树较深（5-6 层）时显著节省人工干预成本。在研究树较浅时基本无副作用。

**复杂度**：中。需要谨慎设计衰减系数（0.5 是直觉值），以及"传播事件"在 cockpit 中的可视化方式（不能让用户看到一堆假说同时变弱却不知道为什么）。

**风险**：如果父假说本身只是被错误地证伪，谱系传播会放大错误。需要保证 `mark_refuted` 是可逆的，或者引入"传播置信度"概念。

---

### 方向 4：溯源链扩展到实验脚本

**当前**：`ver_provenance_dag` 只追踪输入数据文件的哈希。实验脚本本身被改了之后重跑，`refresh_claim` 检测不到。

**建议**：分级追踪脚本：

- **Level 1**：脚本文件 SHA-256（任何改动都触发）
- **Level 2**：AST 哈希，忽略注释和空白（只有逻辑变更触发）
- **Level 3**：训练/评估关键路径哈希——只哈希 `fit`/`predict`/`forward` 等调用点（只有核心逻辑变更触发）

不同级别触发不同严重度的事件：Level 2 → "建议重跑"，Level 3 → "强制重跑"。

**价值**：高。当前是"已知漏洞"——文档里写的是 provenance 闭环，实际只闭了一半（数据闭环、代码不闭）。

**复杂度**：中。Python `ast` 模块直接可用；需要决定 AST 序列化的规范形式以保证哈希稳定。

---

## 二、补齐相邻能力

### 方向 5：预注册的序贯分析（Sequential Analysis）

**当前**：预注册采用固定样本量设计——锁定阈值，跑完所有种子后一次性判定。

**建议**：引入 Alpha-Spending 函数（O'Brien-Fleming 风格），允许提前终止：

- 预注册时锁定 `spending_function='obrien_fleming'`
- 每跑完一个种子后调用 `interim_check(prereg_id, current_values)`
- 函数根据 spending schedule 分配到当前检查点的 alpha 额度，计算 Z 统计量
- 效果极显著时可提前宣告成功（efficacy stop）
- 效果极差时可提前终止（futility stop）

**价值**：高。在深度学习实验中，单次训练动辄几小时甚至几天；能提前停止意味着省下可观的计算预算。

**复杂度**：中高。需要正确实现 spending function 数学（不复杂，但容易出错），并设计与现有预注册校正的正交组合方式。真正 rank-based BH 仍然是单独的行为变更。

**参考**：真正 rank-based BH 控制跨假说的 FDR，Alpha-Spending 控制单假说内跨多次检查的 FWER。两者在数学上独立，可以叠加。

---

### 方向 6：失败签名的语义化升级

**当前**：`match_signatures` 用 SQLite FTS5 的 BM25 文本匹配。"CUDA out of memory" 与 "GPU memory exhausted" 在 BM25 下匹配很差，但它们是同一类问题。

**建议**：在 FTS5 之上叠一层语义匹配：

- 用本地小模型（如 all-MiniLM-L6-v2，~80MB）为每条失败生成向量
- 存入 `mem_failures` 新增列 `embedding BLOB`
- 在 `match_signatures` 中做混合排名：`final = 0.6 * bm25_norm + 0.4 * cosine`
- 定期跑 HDBSCAN 聚类，自动归类相似失败

**价值**：中高。失败记忆是"复利最高的部分"，提升其召回率直接转化为 debug 时间的节省。

**复杂度**：中。需要引入一个本地 embedding 模型依赖；权重 0.6/0.4 需要调参。

**约束**：必须保证向量化是异步的，不能让 `record_failure` 因为模型加载而阻塞。

---

### 方向 7：Cockpit 增加"研究节奏"可视化

**当前**：Event Stream 是线性时间流，能看到"发生了什么"，但无法一眼看出"研究处于什么阶段"。

**建议**：新增一个 Rhythm Pane（节奏面板），用 Textual 自带的 Sparkline 展示几条时间序列：

- **假说产出速率**（每小时新增假说数）—— 反映探索强度
- **剪枝速率**（每小时被证伪/暂停的假说数）—— 反映收敛趋势
- **BT 不确定性总量**（所有活跃假说的 strength_var 之和）—— 反映全局信心水平
- **预算消耗曲线**（wallclock / token / heldout query 的进度条）

合在一起就是一张研究的"心电图"，让用户一眼判断当前是发散探索期（高产出、低剪枝、高不确定性）还是收敛确认期（低产出、高剪枝、不确定性快速下降）。

**价值**：中。对长 session 用户价值明显。

**复杂度**：低。Textual 的 `Sparkline` 组件直接可用，数据从已有的 `cockpit_events` 聚合即可。

---

## 三、走向生态

### 方向 8：多会话/多用户的乐观并发控制

**当前**：设计假定单用户单会话。两个 Claude Code 会话同时写同一个 `state.db` 时，`ver_preregistrations` 的预注册阈值校正可能因为读到相同的 open_count 而被低估。

**建议**：在关键表（`ver_preregistrations`、`mem_bt_ratings`、`res_budget_ledger`）加一列 `version INTEGER DEFAULT 0`。所有写操作改用 CAS（Compare-And-Swap）：

```sql
UPDATE ver_preregistrations
SET status = 'met', version = version + 1
WHERE prereg_id = ? AND version = ?;
-- 如果 affected_rows == 0 说明有并发修改, 需要重读后重试
```

**价值**：中。当前没有真实多用户场景，但这是任何"扩展到团队协作"的前置条件。

**复杂度**：中高。CAS 模式本身不难，但需要审计所有现有写入点，确保没有遗漏；并发场景的测试设计也比较繁琐。

---

### 方向 9：从 Git 历史自动重建假说图

**当前**：系统对存量项目的"冷启动"成本高——一个已经做了半年的项目，迁移到 ClaudeScientist 后假说图是空的。

**建议**：新增 `archaeologist` skill 或 CLI 工具，扫描项目 Git 历史，半自动重建回顾性假说图：

- 每次 commit 中被创建/修改的实验脚本 → 候选 hypothesis 节点
- commit message 中的数值声明（用 `provenance_log.py` 的同款正则） → 候选 evidence
- 被 revert 或 abandoned 的分支 → 候选 refuted hypotheses
- branch 名称中的关键词 → 候选 question 节点

提取完成后由用户人工 confirm/reject 每个候选，写入主图。

**价值**：高。决定了项目能否在新用户的真实研究场景中使用，而不是只在 fresh start 中使用。

**复杂度**：高。Git 历史的语义提取需要一定 NLP 处理；用户体验设计也需要打磨（一次性导入半年的内容会非常嘈杂，需要分阶段或按标签筛选）。

---

### 方向 10：发表对比基准

**当前**：项目已经具备了与 EvoScientist、AI Scientist v2 等系统对比的所有要素，但没有公开的对比基准。

**建议**：选择 1-2 个标准任务（如 idea generation benchmark、experiment reproducibility benchmark），在统一条件下与 EvoScientist 对比，量化 ClaudeScientist 在以下维度的差异：

- **Idea novelty**：通过文献检索后的"未被覆盖"程度衡量
- **Idea feasibility**：用 reviewer agent 打分
- **Reproducibility**：multi-seed verdict 的稳定率
- **Memory leverage**：失败记忆命中带来的 debug 时间节省

**价值**：高。对外部用户而言，"为什么用这个而不用其他"需要一个客观答案。

**复杂度**：高。两周以上的独立工作，且需要重现 EvoScientist 的运行环境。

**前置条件**：方向 9（自动重建）大概率是这个对比的实验对象。

---

## IV. 领域扩展（v4.0）

### 方向 11：证明主干 —— NL 主路 + Lean 保险层

**现状**：ClaudeScientist 是单主干系统，专注于 ML 实证可重复性。`prover` agent 从 v0.1 开始就是 stub，Lean 接入此前位列"不做"清单（见本文件最后被划掉的那一条）。

**提议**：采用两主干架构（已在 [ADR 0008](adr/0008-two-trunk-domain-architecture.md) 正式记录）。现有 v3.0 接口成为 **empirical 主干**；新增 **proof 主干**位于 `src/prove_mcp/`。proof 主干的主路径是 StatProver 风格的：语料检索（双向 max-matching、双关键词 embedding）、草稿生成、片段切片、对照 `mem_failures(domain='proof')` 诊断、延迟全局修正。Lean 形式化层作为**保险**而非主路径：只有通过 `triage_for_formalization` 触发规则的命题才被送给 prover agent（背后是 `lean-lsp-mcp`）；Lean 验证成功 = 强证据 attach；失败 = 反向写入跨域错题本。

两条主干通过且仅通过四个合作接口（一棵树 / 一本错题本 / 一张排行榜 / 一个评审两份清单）协作——见 architecture.md §13。

**价值**：极高。统计研究项目天然混合理论与实证；把它们放到同一套工具链里是产品级的差异化。当前所有单主干竞品（StatProver、EvoScientist、AI Scientist v2）都没有跨域错题本匹配，也没有双清单评审。

**复杂度**：高。约 10 周分 6 期（P0 文档 → P1 内核 domain-agnostic → P2 检索 → P3 NL 工作流 → P4 Lean 保险层 → P5 合作面）。新增一个 MCP server（`prove_mcp`）——v3.0 默认的"不开新 MCP server"为这次领域扩展明确放宽。

**约束条件**：
- 分层纪律（[ADR 0007](adr/0007-tools-skills-hooks-layering.md)）从 day 1 起即生效。新 proof 工具必须保持原子动词；StatProver 那 6 阶段流水线只活在 `prove-sop` skill 的 markdown 里，不进代码。
- 我们不会去匹敌 StatProver 的 40k 语料 / 80k 错误库规模。我们的差异化点是工作流整合，不是检索质量。
- Lean 保险层按命题逐个 opt-in；任何工作流都不会卡在 Lean 成功才放行。

**状态**：在做（v4.0 分期计划）。

---

## 优先级建议

如果要从今天开始执行，我建议的顺序是：

1. **方向 1（Thompson Sampling）** —— 收益高、成本低，几小时就能验证
2. **方向 4（脚本溯源）** —— 关闭已知的 provenance 漏洞
3. **方向 7（节奏面板）** —— 短平快，提升用户体验
4. **方向 6（语义化失败匹配）** —— 中期投入，长期复利
5. **方向 2（Meta-Calibration 闭环）** —— 在多模型场景成熟前不急
6. **方向 5（序贯分析）** —— 数学需要小心设计，但收益巨大
7. **方向 3（谱系传播）** —— 等研究树长起来再做最划算
8. **方向 8（并发控制）** —— 等真有多用户需求时再做
9. **方向 9（Git 考古）** —— 等核心稳定后再扩展冷启动
10. **方向 10（对比基准）** —— 等系统真正用过几个真实研究任务后再做

**方向 11（证明主干）单独处理**——它是已经在做的 v4.0 承诺，不在"是否值得做"的讨论范畴里，详见 ADR 0008 与分期计划。

## 几个不属于路线图的方向

为了避免误解，这里也列出几个**不**建议追加的方向：

- **重新加 Web UI**：v0.2 已经有充分理由删掉它，不要走回头路
- **替换 SQLite 为 Postgres**：单文件状态边界是项目的核心优势之一
- **支持多语言（除中英之外）**：目前没有需求，且 i18n 基础设施已具备，按需扩展即可
- ~~**接入 Lean 形式化证明**~~：**已被方向 11（v4.0）取代**——proof 主干把 Lean 作为保险层接入，主路径走 NL。原本"成本高、收益狭窄"的判断在单主干假设下是对的；两主干架构改变了成本结构——proof 工作流复用现有基础设施（BT、校准、provenance、replay、cockpit、错题本）的边际成本几乎为零。详见 [ADR 0008](adr/0008-two-trunk-domain-architecture.md)。

## 写在最后

ClaudeScientist 当前的核心价值是"让 AI 驱动的研究流程产出可信结果"。任何后续方向都应当围绕这个核心展开——能让数字更可信、能让流程更可控、能让记忆更耐久的方向，优先级就高；偏离这个核心的方向（即便单看技术上很有趣），都应当谨慎。
