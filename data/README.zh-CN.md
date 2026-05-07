# 冷启动数据

本目录提供证明主干（proof trunk）开箱即用所需的种子数据。如果没有这些数据，
`retrieve_skeletons` 会返回空，`diagnose_snippet` 也无法命中历史错误模式。

两份 JSONL 文件，每行一条记录：

| 文件 | 加载脚本 | 目标表 | 行数 |
|---|---|---|---|
| `proof_corpus_seed.jsonl` | `scripts/seed_proof_corpus.py` | `prv_corpus_problems` + `prv_corpus_keywords` | ≥80 |
| `proof_failure_seed.jsonl` | `scripts/seed_proof_failures.py` | `mem_failures`（domain=`'proof'`） | ≥60 |

两个加载脚本都是幂等的，重复运行不会重复插入。`proof_corpus_seed.jsonl`
按 `problem_id` upsert，`proof_failure_seed.jsonl` 按 `(trigger, root_cause)`
自然键去重。

## 运行方法

```powershell
# clone + uv sync --extra proof 之后：
uv run python scripts/seed_proof_corpus.py
uv run python scripts/seed_proof_failures.py
```

如果只想部分入库（比如冒烟测试）：

```powershell
uv run python scripts/seed_proof_corpus.py --limit 20
uv run python scripts/seed_proof_failures.py --limit 10
```

## Embedding 后端注意

`seed_proof_corpus.py` 内部调用 `prove_mcp.tools.corpus.ingest_proof_corpus`，
关键词向量化用的是 `RESEARCH_AGENT_EMBED_BACKEND` 选定的后端。新克隆默认是
`local`（`sentence-transformers/all-MiniLM-L6-v2`）；测试固定为 `mock`。
**切换后端后需要重新入库**，因为每行都记录了 embedding 维度，
`retrieve_skeletons` 不允许跨后端混合。

## Schema 参考

### `proof_corpus_seed.jsonl` 单行结构

```json
{
  "problem_id": "markov_inequality",
  "statement": "...",
  "reference_proof": "...",
  "lexical_keywords": ["Markov", "inequality"],
  "semantic_keywords": ["first moment bound", "tail bound from expectation"],
  "domain_tags": ["probability", "inequality"]
}
```

必填：`problem_id`、`statement`，以及 `lexical_keywords` / `semantic_keywords`
中至少一个。可选：`reference_proof`、`domain_tags`。

### `proof_failure_seed.jsonl` 单行结构

```json
{
  "trigger": "applied Cauchy-Schwarz to (E[XY])^2 <= E[X^2] E[Y^2]",
  "symptom": "step asserts the bound without verifying both second moments are finite",
  "root_cause": "Cauchy-Schwarz requires E[X^2], E[Y^2] < infinity",
  "resolution": "explicitly check the finite second moments before invoking the inequality"
}
```

必填：`trigger`、`symptom`。`(trigger, root_cause)` 是幂等去重的自然键。

## 扩展种子

欢迎手动追加。在任一 JSONL 后面追加新行后重跑加载脚本即可，不会动已有行。
**用你自己的话改写**，不要逐字搬运教科书或论文。

如果扩展来自公开数据集（StatEval、arXiv 证明等），建议加载时显式指定
`--source stateval` 或 `--source arxiv`，这样 `prv_corpus_problems.source`
能区分来源，方便后续审计。
