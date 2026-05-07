# Cold-start data

This directory bundles the seed material that the proof trunk needs to be
useful out of the box. Without it, `retrieve_skeletons` returns empty results
and `diagnose_snippet` cannot match historical failure modes.

Two JSONL files, each one row per record:

| File | Loader | Target table | Rows |
|---|---|---|---|
| `proof_corpus_seed.jsonl` | `scripts/seed_proof_corpus.py` | `prv_corpus_problems` + `prv_corpus_keywords` | ≥80 |
| `proof_failure_seed.jsonl` | `scripts/seed_proof_failures.py` | `mem_failures` (domain=`'proof'`) | ≥60 |

Both loaders are idempotent: re-running them does not duplicate rows.
`proof_corpus_seed.jsonl` is upserted by `problem_id`; `proof_failure_seed.jsonl`
is deduplicated on the `(trigger, root_cause)` natural key.

## How to run

```powershell
# After cloning + uv sync --extra proof:
uv run python scripts/seed_proof_corpus.py
uv run python scripts/seed_proof_failures.py
```

To partially seed (e.g. for a smoke test):

```powershell
uv run python scripts/seed_proof_corpus.py --limit 20
uv run python scripts/seed_proof_failures.py --limit 10
```

## Embedding backend caveat

`seed_proof_corpus.py` calls `prove_mcp.tools.corpus.ingest_proof_corpus`,
which embeds keywords through whichever backend `RESEARCH_AGENT_EMBED_BACKEND`
selects. The default in a fresh checkout is `local`
(`sentence-transformers/all-MiniLM-L6-v2`). Tests pin `mock`. Switching
backend after seeding requires re-ingesting, because the embedding
dimension is recorded per row and `retrieve_skeletons` rejects mixed
backends.

## Schema reference

### `proof_corpus_seed.jsonl` row

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

Required: `problem_id`, `statement`, and at least one of
`lexical_keywords` / `semantic_keywords`.
Optional: `reference_proof`, `domain_tags`.

### `proof_failure_seed.jsonl` row

```json
{
  "trigger": "applied Cauchy-Schwarz to (E[XY])^2 <= E[X^2] E[Y^2]",
  "symptom": "step asserts the bound without verifying both second moments are finite",
  "root_cause": "Cauchy-Schwarz requires E[X^2], E[Y^2] < infinity",
  "resolution": "explicitly check the finite second moments before invoking the inequality"
}
```

Required: `trigger`, `symptom`. The `(trigger, root_cause)` pair acts as
the natural key for idempotency.

## Extending the seed

Hand-curated extensions are welcome. Append rows to either JSONL file and
re-run the loader; existing rows are not touched. Keep the wording original
(paraphrased from your own understanding) — do **not** copy verbatim from
textbooks or papers.

If your extension comes from a public dataset (e.g. StatEval, arXiv proofs),
prefer using `--source stateval` or `--source arxiv` so telemetry can
distinguish the lineage in `prv_corpus_problems.source`.
