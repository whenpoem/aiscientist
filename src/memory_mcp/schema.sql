PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS mem_nodes (
  node_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK(kind IN ('question', 'hypothesis', 'experiment', 'evidence', 'conclusion')),
  text TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'active' CHECK(state IN ('active', 'refuted', 'superseded', 'archived')),
  elo_score REAL NOT NULL DEFAULT 1500.0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_by TEXT NOT NULL DEFAULT 'claude',
  parent_id TEXT REFERENCES mem_nodes(node_id)
);

CREATE TABLE IF NOT EXISTS mem_edges (
  edge_id INTEGER PRIMARY KEY AUTOINCREMENT,
  src TEXT NOT NULL REFERENCES mem_nodes(node_id),
  dst TEXT NOT NULL REFERENCES mem_nodes(node_id),
  relation TEXT NOT NULL CHECK(relation IN ('parent_of', 'refines', 'contradicts', 'supports', 'refutes', 'supersedes', 'blocks')),
  rationale TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_mem_edges_src ON mem_edges(src);
CREATE INDEX IF NOT EXISTS idx_mem_edges_dst ON mem_edges(dst);

CREATE TABLE IF NOT EXISTS mem_judgements (
  judgement_id INTEGER PRIMARY KEY AUTOINCREMENT,
  a_node_id TEXT NOT NULL REFERENCES mem_nodes(node_id),
  b_node_id TEXT NOT NULL REFERENCES mem_nodes(node_id),
  winner_node_id TEXT NOT NULL REFERENCES mem_nodes(node_id),
  reason TEXT DEFAULT '',
  k_factor REAL NOT NULL DEFAULT 32.0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_mem_judgements_a_node_id ON mem_judgements(a_node_id);
CREATE INDEX IF NOT EXISTS idx_mem_judgements_b_node_id ON mem_judgements(b_node_id);
CREATE INDEX IF NOT EXISTS idx_mem_judgements_winner_node_id ON mem_judgements(winner_node_id);

CREATE TABLE IF NOT EXISTS mem_snapshots (
  snapshot_id TEXT PRIMARY KEY,
  label TEXT NOT NULL DEFAULT '',
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_mem_snapshots_created_at ON mem_snapshots(created_at DESC);

CREATE TABLE IF NOT EXISTS mem_failures (
  failure_id INTEGER PRIMARY KEY AUTOINCREMENT,
  trigger TEXT NOT NULL,
  symptom TEXT NOT NULL,
  root_cause TEXT DEFAULT '',
  resolution TEXT DEFAULT '',
  signature TEXT,
  seen_count INTEGER NOT NULL DEFAULT 1,
  first_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE VIRTUAL TABLE IF NOT EXISTS mem_failures_fts USING fts5(
  trigger,
  symptom,
  root_cause,
  resolution,
  content='mem_failures',
  content_rowid='failure_id'
);

CREATE TRIGGER IF NOT EXISTS mem_failures_ai AFTER INSERT ON mem_failures BEGIN
  INSERT INTO mem_failures_fts(rowid, trigger, symptom, root_cause, resolution)
  VALUES (new.failure_id, new.trigger, new.symptom, coalesce(new.root_cause, ''), coalesce(new.resolution, ''));
END;

CREATE TRIGGER IF NOT EXISTS mem_failures_ad AFTER DELETE ON mem_failures BEGIN
  INSERT INTO mem_failures_fts(mem_failures_fts, rowid, trigger, symptom, root_cause, resolution)
  VALUES ('delete', old.failure_id, old.trigger, old.symptom, coalesce(old.root_cause, ''), coalesce(old.resolution, ''));
END;

CREATE TRIGGER IF NOT EXISTS mem_failures_au AFTER UPDATE ON mem_failures BEGIN
  INSERT INTO mem_failures_fts(mem_failures_fts, rowid, trigger, symptom, root_cause, resolution)
  VALUES ('delete', old.failure_id, old.trigger, old.symptom, coalesce(old.root_cause, ''), coalesce(old.resolution, ''));
  INSERT INTO mem_failures_fts(rowid, trigger, symptom, root_cause, resolution)
  VALUES (new.failure_id, new.trigger, new.symptom, coalesce(new.root_cause, ''), coalesce(new.resolution, ''));
END;

CREATE TABLE IF NOT EXISTS mem_lit_compressed (
  paper_id TEXT PRIMARY KEY,
  source TEXT NOT NULL CHECK(source IN ('arxiv', 'openalex', 'manual')),
  title TEXT,
  authors TEXT,
  year INTEGER,
  venue TEXT,
  problem TEXT,
  method TEXT,
  claimed_results TEXT,
  assumptions TEXT,
  limitations TEXT,
  trust_level REAL NOT NULL DEFAULT 0.5,
  relates_to TEXT DEFAULT '{}',
  raw_abstract TEXT,
  ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE VIRTUAL TABLE IF NOT EXISTS mem_lit_fts USING fts5(
  title,
  problem,
  method,
  claimed_results,
  content='mem_lit_compressed',
  content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS mem_lit_compressed_ai AFTER INSERT ON mem_lit_compressed BEGIN
  INSERT INTO mem_lit_fts(rowid, title, problem, method, claimed_results)
  VALUES (new.rowid, coalesce(new.title, ''), coalesce(new.problem, ''), coalesce(new.method, ''), coalesce(new.claimed_results, ''));
END;

CREATE TRIGGER IF NOT EXISTS mem_lit_compressed_ad AFTER DELETE ON mem_lit_compressed BEGIN
  INSERT INTO mem_lit_fts(mem_lit_fts, rowid, title, problem, method, claimed_results)
  VALUES ('delete', old.rowid, coalesce(old.title, ''), coalesce(old.problem, ''), coalesce(old.method, ''), coalesce(old.claimed_results, ''));
END;

CREATE TRIGGER IF NOT EXISTS mem_lit_compressed_au AFTER UPDATE ON mem_lit_compressed BEGIN
  INSERT INTO mem_lit_fts(mem_lit_fts, rowid, title, problem, method, claimed_results)
  VALUES ('delete', old.rowid, coalesce(old.title, ''), coalesce(old.problem, ''), coalesce(old.method, ''), coalesce(old.claimed_results, ''));
  INSERT INTO mem_lit_fts(rowid, title, problem, method, claimed_results)
  VALUES (new.rowid, coalesce(new.title, ''), coalesce(new.problem, ''), coalesce(new.method, ''), coalesce(new.claimed_results, ''));
END;
