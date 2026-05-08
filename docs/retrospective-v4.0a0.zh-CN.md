# 复盘 — v4.0.0a0

> English version: [retrospective-v4.0a0.md](retrospective-v4.0a0.md)
>
> 写于 Plan v2 收尾、v4.0 alpha 落地之后。覆盖三件事：
> 这次到底交付了什么、对系统自动判断逻辑做的全面审计（哪些已修、哪些
> 留作后续）、以及按"收益÷成本"排序的下一步建议。

## 落地内容

Plan v1（P0–P5，~10 周）和 Plan v2（这一轮）合起来交付了：

**架构**
- 两主干架构（ADR 0008）：原 empirical 主干 + 新 proof 主干，
  共享一个内核（图、错题、BT、校准、cockpit），合作面**有且仅有**
  四条。
- Tools/Skills/Hooks 三层纪律（ADR 0007）防止证明主干退化成
  硬编码流水线。

**代码面**
- 新 MCP server：`prove_mcp`（18 个工具，覆盖语料、检索、证明节点、
  切片、诊断、修正、Lean 形式化保险层）。
- Embedding 适配层三种后端（mock / local / openai）。测试用 mock，
  实战默认 local，OpenAI 按需开启。
- Memory MCP 扩展：`mem_failures.domain`（跨域错题本）、
  `mem_nodes.kind` 扩展支持证明 kind、BT 比较原语接受
  `hypothesis` 与 `proof_skeleton` 同 kind 互比。
- Lean MCP wrapper（`scripts/lean_mcp_or_noop.py`）自动分流：
  工具链在 → 透传给真 `lean-lsp-mcp`；不在 → 干净 exit-0
  noop。**不再需要手动改 `_lean → lean`**。

**冷启动数据**
- `data/proof_corpus_seed.jsonl` —— 85 条手工整理的统计证明问题，
  覆盖 8 大类。端到端验证过：用真 `local` embedding 后端查
  Markov 不等式，top-1 命中 sim=0.889。
- `data/proof_failure_seed.jsonl` —— 84 条改写过的证明错误模式，
  9 个类别。
- `scripts/seed_proof_corpus.py` 和 `scripts/seed_proof_failures.py`
  幂等加载。

**Reviewer + cockpit**
- Reviewer agent 增加证明 checklist（JSON 输出含
  `numeric_claims` 和 `theorem_claims` 两列，硬规则并行）。
- Cockpit i18n 标签覆盖所有证明事件；树面板按 kind 显示不同前缀和
  颜色。

**运维集成**
- Snapshot 覆盖证明子树（proposition 前线 + 最近 draft + manifest +
  Lean attempt + corpus 计数）。v3.0 老库通过
  `sqlite3.OperationalError` 包裹优雅降级。
- `stop_flush` digest 每个回合统计证明 manifest / Lean 尝试 /
  wallclock 总和。
- Prover agent prompt 要求 ≥ 5 分钟的 Lean 尝试**必须先经过 budgeter**。

**测试数**：239 绿（Plan v2 之前 203 + 新增 36 跨种子脚本、
snapshot proof 覆盖、stop_flush proof 覆盖、triage 回归、BT pause
建议覆盖、Lean wrapper）。

## 系统自动判断逻辑审计

Plan v2 故意把"系统每一处自动决策"过了一遍——白名单/黑名单、
阈值切割、子串匹配、状态枚举校验、防御性读。下面是发现 + 处理。

### 这次已修

| ID | 严重度 | 位置 | 描述 |
|---|---|---|---|
| **A** | 中 | `prove_mcp/tools/lean_bridge.py` | Triage 白名单太窄——85 条种子语料里有 ~10 条会被误判为"不在 mathlib 覆盖范围"（Borel-Cantelli、Hoeffding、Rao-Blackwell、sub-Gaussian、KL、Pinsker、Glivenko-Cantelli、Wald/score test、Lehmann-Scheffé）。白名单从 30 个关键词扩到 ~90 个，覆盖全部 8 个语料类别。 |
| **B** | 低 | 同 | 黑名单过激：`lebesgue integral`、`ergodic`、`measure-preserving` 在 mathlib 里都有完整覆盖却被拒绝。已移除。只保留真正薄弱的领域（Itô、SDE、Banach/Hilbert/Sobolev 抽象、无限维）。 |
| **C** | 低 | 同 | 子串匹配没加词边界——`ols` 命中 `controls`、`tools`。新增 `_WORD_BOUNDARY_REQUIRED = {ols, mle, rao, ump, blue, ito}` 用 `\b…\b` 正则约束。 |
| **D** | 表述 | 同 | 被拒绝的命题会标上 `difficulty='high'`（有误导性："high" 暗示"合格但难"）。改成 `'n/a'`。配套 schema_version 4 迁移把 `prv_lean_attempts.triage_difficulty` CHECK 约束放宽。 |
| **M** | 中 | `memory_mcp/tools/bt.py` | `suggest_pause_low_strength` 硬编码 `WHERE n.kind = 'hypothesis'`，证明 BT 锦标赛根本无法被 auto-prune。改成默认遍历 `BT_RANKABLE_KINDS` 全部；同时接受 `kind=` 过滤参数。 |

### 留作 v4.x（这轮没改）

| ID | 严重度 | 位置 | 留作的理由 |
|---|---|---|---|
| **E** | 中 | `.claude/hooks/leakage_guard.py:171` | Markdown 验证按目录名（`reports`、`writeup`）触发。`paper/`、`submission/`、`manuscript/`、`final/` 等命名下的 manuscript 完全绕过数字声明 provenance 检查。**修法**：改为基于内容的检测——发现 `\\begin{theorem}`、`\\section`、密集数字 token 都触发，目录名只作为辅助信号。本轮"不加新逻辑"原则下未改。 |
| **F** | 中 | `runtime.py:204`（METRIC_RE） | 标签清单（`acc, f1, auc, loss, precision, recall, mse, rmse, mae, bleu, rouge, score, metric`）偏向经典 ML benchmark。统计学常用标签缺失：`p-value`、`coverage`、`power`、`effect_size`、`cohen_d`、`chi2`、`t-stat`、`iou`、`ndcg`、`map`、`top-1/5`。**修法**：扩并集 + 每个新标签写单元测试。 |
| **G** | 中低 | 同 METRIC_RE | 数值模式 `[-+]?\d+(?:\.\d+)?%?` 拒绝科学计数法。`p < 1.2e-3` 不会触发 markdown 检查。**修法**：扩成 `(?:[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?%?)`。 |
| **J** | 中低 | `.claude/hooks/destructive_bash_guard.py:11` | 模式 `\brm\s+-rf\b` 抓不住分开的标志（`rm -r -f`、`rm --recursive --force`）。 |
| **K** | 中 | 同 | 没匹配 shell 重定向清空（`> important.txt`）、`rmdir /s /q`、`git branch -D`、`git stash drop`。 |
| **L** | 低 | `bt.py:327`（`update_bt_rating`） | 不更新 `mem_nodes.elo_score`，只 `record_judgement` 双写。仅影响显示（BT strength 是真实数据源）。**修法**：要么去掉 `record_judgement` 的双写、要么这边补上以保持一致。 |
| **N** | 低（当下）/ 中（规模上来后） | `prove_mcp/tools/retrieval.py` | 没有 SQL `LIKE` 预筛——每次查询对全语料做密集向量重排。≤2k 条没问题，5k+ 开始变慢。**修法**：`len(corpus) > 2000` 时加 LIKE 预筛。 |
| **O** | 中 | `verify_mcp/tools/verification.py:71` | `seed_perturb` 默认 `stability_tol=0.01` 是绝对值；对不在 [0,1] 的指标无意义。**修法**：`stability_tol` 改成 `(absolute, relative)` 元组取大值。 |
| **P** | 低 | 同 | 1 个 seed 时 `std_value=0.0` → 自动判 "stable" 但没有任何证据。**修法**：`len(seeds) < 2` 时返回 `verdict="insufficient_seeds"`。 |
| **Q** | 表述 | `prove_mcp/tools/diagnosis.py` | Manifest `status='open'` 语义重载：finalize 之前（还在诊断）和 finalize 之后有 flaw（等待修正）外观一样。**修法**：拆成 `open` / `awaiting_correction`，或加 `finalized_at` 时间戳区分。 |

### 已知设计选择（不是 bug）

下面这些看起来像 bug，其实是有意为之：

- **Reviewer 是软门**：只有 `leakage_guard` 是硬规则 hook。Reviewer 子代理需要主动 spawn。这在 ADR 0007（Tools/Skills/Hooks 分层）里有明文。如果用户跳过 reviewer，theorem 类断言就不会被检查。
- **`destructive_bash_guard` 是减速带**：不追求完备。`.claude/hooks/README.md` 已写明。约定是除已列出的之外，破坏性命令必须显式带 `# CONFIRM_DESTRUCTIVE`。
- **`source` 是固定枚举**：`ingest_proof_corpus` 只接受 `{stateval, manual, arxiv}`。要加第四个必须同时改 `VALID_SOURCES` + schema CHECK + 写迁移。这是有意为之的摩擦——遥测一致性优先于用户自由度。
- **Auto-prune 默认 dry-run**：必须设 `RESEARCH_AGENT_AUTO_PRUNE=1` 才真正翻成 `paused`。保守默认，用户主动启用。
- **Triage 是启发式不是 oracle**：基于关键词的 eligibility 判断**故意做得粗糙**（ADR 0007）。agent 可以用户授权后覆盖（见 `prover.md`）。长期更优的路径是改成"先调一次 `lean leansearch` 探查再下判定"，但这是 v4.x 的事。

## v4.0a0 → v4.0a1 后续建议

按 收益÷成本 排序。**只优化现有功能、不加新东西**。

### Tier 1（先做——高收益、低成本）

1. **Bug F + G**：扩 `METRIC_RE`，覆盖统计学专用标签 + 科学计数法。
   `runtime.py` 改 ~10 行 + 在 `tests/test_runtime.py` 加 2-3 个单测。
   **成本**：1 小时。**收益**：堵上 leakage hook 在非 ML manuscript
   上的最大缺口。

2. **Bug E**：`_should_verify_markdown` 改成基于内容检测。任何
   `.md` 文件命中 `\\begin{theorem}`、`\\section`、或 N 个以上
   数字 token 都触发。**成本**：2 小时。**收益**：leakage hook 不
   再依赖目录命名。

3. **Bug J + K**：扩 `destructive_bash_guard` 模式。**成本**：
   30 分钟。**收益**：边际，但减速带更紧。

### Tier 2（用得着时做）

4. **Bug O + P**：`seed_perturb` 尺度感知 + 1-seed 处理。**成本**：
   2 小时。**收益**：仅在真有项目用 seed_perturb 跑非 accuracy 指标
   时才显出价值。

5. **Bug Q**：拆 manifest `open` 状态。**成本**：4 小时
   （动 schema + diagnosis.py + correction.py + tests + docs）。
   **收益**：审计清晰度。当下只是表述问题。

6. **Bug L**：决定 `update_bt_rating` ↔ `mem_nodes.elo_score`
   双写不对称。**成本**：30 分钟。**收益**：很小，仅影响显示。

### Tier 3（规模上来后再做）

7. **Bug N**：`retrieve_skeletons` 加 SQL `LIKE` 预筛。语料过 ~2000
   条之前都不必做。当前 85 条，有 20× 余量。

### Lean 形式化保险层后续（独立轨道）

8. **Spike 模板要跟 mathlib 版本绑定**。5 个 spike `.lean` 文件用了
   `Mathlib.Algebra.BigOperators.Basic`，这个路径在 mathlib v4.13+
   被搬走了。要么 lakefile 里 pin 死特定 mathlib commit，要么让
   prover agent 学会自动发现新路径。**成本**：发现路径 1-2 天，
   pin 路径 30 分钟。pin 路径脆（mathlib 改得快），发现路径才是
   长期正确答案。

9. **`scripts/run_spikes.py` 现在会全部记成 failed**：因为 spike
   imports 过期。每跑一次就往 `prv_lean_attempts` 写 5 条 failed
   行噪音。建议加 `--dry-run` 或第一个 import error 时自动 skip。
   **成本**：1 小时。

## 反思

### 做得好

- **四接口设计扛住了考验**。Plan v1 + v2 + 这次审计走完，empirical
  和 proof 主干之间始终保持精确四条合作面（一棵树、一本错题、
  一张排行榜、一个评审两份清单）。没有暗中冒出第五条耦合。

- **`mem_failures.domain` 是对的原语**。加一个字符串列、默认
  `'empirical'`，跨域错题本就跑通了。没新表、没迁移痛苦。这正是
  ADR 0007 倡导的"扩展不替换"模式。

- **mock embedding 让测试零成本保持确定性**。239 个测试 ~70 秒跑完，
  因为没有任何测试加载 sentence-transformers。真后端只在手工跑
  端到端时验证一次。

- **ADR 0007 的"原子动词"规则防住了流水线化**。每个新 prove_mcp
  工具都是单一动词。`prove-sop` skill 是建议态 markdown，不是
  强制顺序。"写一个 `run_full_proof_workflow()` 把它们打包"的
  诱惑确实出现过，被正确抵抗。

### 做得不好

- **白名单启发式会僵化**。Triage 白名单 v0.1 时拍脑袋写的，随着语料
  变大越来越错。这次审计才发现 ~12% 种子问题被错杀。给 mathlib
  时鲜覆盖做白名单注定漂移；改成"先调一次 leansearch 探查"是架构
  正确解，但属于 v4.x。

- **Schema CHECK 约束迁移很重**。Bug D 把 rejected 命题的标签从
  `'high'` 改成 `'n/a'`，要走完整的 SQLite 表重建（CHECK 不能在原
  地修改）。这是 SQLite 已知的痛点。今后如有新枚举字段，建议用
  独立"valid values"表或运行时校验，别把枚举烧进 schema。

- **Lean spike 模板对 mathlib 稳定性过于乐观**。写在
  `Mathlib.Algebra.BigOperators.Basic` 上，结果 v4.13 就搬了路径。
  "spike 是 prover loop 起点"的定位能 cover 这一点，但 lakefile
  里 pin 一个已知能跑的 mathlib commit 会更干净。

- **冷启动语料的有效范围要靠手用才能发现**。我们按"覆盖广度"出了
  85 + 84 条（8 类 × ~10 条），但真正问题是"用户的真实查询能否检
  索出有用候选"。Plan v2 没跑真实研究项目验证这点。下一轮迭代的
  自然循环：发布 → 使用 → 把用户碰到的真错误 ingest 进去 → 语料增长。

## 收尾

v4.0.0a0 是个**自洽的 alpha**。架构（两主干、四接口）正确。代码
风格一致（原子动词、reviewer 契约、snapshot 范围、budgeter 集成）。
冷启动数据小但真实（典型查询的实测检索 sim=0.889）。审计找出 12 处
值得修的；5 处当场修了，7 处带明确严重度和成本估计归档到 v4.x。

剩下的都是**迭代精调，不是重新设计**。

---

*复盘版本：1.0 · 2026-05-07 · tag：`v4.0.0a0`*
