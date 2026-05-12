PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- Proof-trunk tables (prv_*). Owned by prove_mcp; see ADR 0008 +
-- architecture.md §13. Cross-trunk signalling goes through cockpit_events
-- and through the shared core tables (mem_nodes, mem_failures).

CREATE TABLE IF NOT EXISTS prv_corpus_problems (
  problem_id TEXT PRIMARY KEY,
  source TEXT NOT NULL CHECK(source IN ('stateval', 'manual', 'arxiv')),
  statement TEXT NOT NULL,
  reference_proof TEXT NOT NULL DEFAULT '',
  domain_tags TEXT NOT NULL DEFAULT '[]',
  ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_prv_corpus_problems_source
  ON prv_corpus_problems(source);

CREATE TABLE IF NOT EXISTS prv_corpus_keywords (
  problem_id TEXT NOT NULL REFERENCES prv_corpus_problems(problem_id) ON DELETE CASCADE,
  keyword TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('lexical', 'semantic')),
  embedding BLOB NOT NULL,
  embed_backend TEXT NOT NULL,
  embed_dim INTEGER NOT NULL,
  -- Added in schema_version=5 (v4.2.0a0 / ADR 0010): the specific model
  -- identifier that produced the vector, so multiple models under the
  -- same backend (e.g. several OpenAI-compatible providers) stay
  -- distinguishable and retrieval can refuse mismatches at the
  -- (backend, model, dim) triple. Default 'unknown' on legacy rows
  -- so a v4.1 corpus migrates cleanly; the retrieval tool surfaces a
  -- clear hint when it encounters such rows.
  embedding_model TEXT NOT NULL DEFAULT 'unknown',
  PRIMARY KEY (problem_id, keyword, kind)
);

CREATE INDEX IF NOT EXISTS idx_prv_corpus_keywords_kw
  ON prv_corpus_keywords(keyword);

CREATE INDEX IF NOT EXISTS idx_prv_corpus_keywords_backend
  ON prv_corpus_keywords(embed_backend, embed_dim);

-- The (backend, model, dim) triple index lives in
-- db._migrate_add_embedding_model_column rather than here. A legacy
-- v4 corpus table predates the embedding_model column, so trying to
-- declare this index inside the executescript pass would fail before
-- the migration helper has a chance to add the column. The helper
-- runs after the schema pass and uses CREATE INDEX IF NOT EXISTS, so
-- fresh databases still get the index — just one step later.

-- P3: snippet-level diagnostic manifest. One row per draft (a
-- proof_skeleton mem_node holding full draft text). status transitions:
--   open      -- segmented but diagnosis unfinished or flawed entries pending correction
--   empty     -- diagnosis complete, no flaws -> reviewer can let theorem through
--   applied   -- a correction has been applied; manifest is closed-out history

CREATE TABLE IF NOT EXISTS prv_diagnostic_manifests (
  manifest_id INTEGER PRIMARY KEY AUTOINCREMENT,
  draft_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'empty', 'applied')),
  items_json TEXT NOT NULL DEFAULT '{"entries": []}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finalized_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_prv_diagnostic_manifests_draft
  ON prv_diagnostic_manifests(draft_id);

CREATE INDEX IF NOT EXISTS idx_prv_diagnostic_manifests_status
  ON prv_diagnostic_manifests(status);

-- P4: Lean reinsurance attempts. One row per attempted Lean
-- formalisation, success or failure; the prover agent orchestrates
-- the actual lean-lsp-mcp calls and writes results here. Failures feed
-- back into the cross-domain failure ledger (mem_failures.domain='proof')
-- via memory_mcp.record_failure -- this table is the proof-trunk-local
-- audit trail.
CREATE TABLE IF NOT EXISTS prv_lean_attempts (
  attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
  proposition_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('queued', 'running', 'verified', 'failed', 'timeout')),
  lean_source TEXT NOT NULL DEFAULT '',
  stderr TEXT NOT NULL DEFAULT '',
  duration_sec REAL,
  triage_eligible INTEGER NOT NULL DEFAULT 0 CHECK(triage_eligible IN (0, 1)),
  triage_reasons TEXT NOT NULL DEFAULT '[]',
  -- 'n/a' added in schema_version=4 (Plan v2 / Bug D fix): rejected propositions
  -- get 'n/a' instead of an over-strong 'high' label so audit consumers can
  -- distinguish "rejected by triage" from "eligible but expected to be hard".
  triage_difficulty TEXT NOT NULL DEFAULT 'unknown'
    CHECK(triage_difficulty IN ('low', 'med', 'high', 'n/a', 'unknown')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_prv_lean_attempts_proposition
  ON prv_lean_attempts(proposition_id);

CREATE INDEX IF NOT EXISTS idx_prv_lean_attempts_status
  ON prv_lean_attempts(status);
