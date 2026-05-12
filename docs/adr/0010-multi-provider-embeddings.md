# ADR 0010: Multi-provider embeddings via configurable base_url

- **Status**: Accepted (v4.2)
- **Date**: 2026-05

## Context

`prove_mcp` ships three embedding backends: `mock` (deterministic, for
tests), `local` (sentence-transformers), and `openai`. Through v4.1 the
`openai` backend hardcoded the SDK's default endpoint and the
`text-embedding-3-large` model, and the `local` backend hardcoded
`all-MiniLM-L6-v2`. Both choices became friction surfaces:

1. The project's main user works primarily in Chinese. The
   English-biased `all-MiniLM-L6-v2` underperforms on Chinese clusters
   in the seed corpus, and reaching `api.openai.com` reliably from
   networks behind the GFW is not something the project should assume.
2. Several embedding providers (Aliyun DashScope, Jina, Voyage, GLM,
   DeepSeek, …) ship an OpenAI-compatible HTTP shape. The official
   `openai` Python SDK exposes `base_url` as a constructor argument
   exactly so callers can redirect to those providers without
   abandoning the SDK. The cost of supporting them is a single
   `base_url` parameter; the benefit is full provider choice.
3. The proof corpus stores per-keyword embeddings along with the
   `(embed_backend, embed_dim)` pair that produced them. Through v4.1
   the same backend with two different models would silently coexist
   in storage. Retrieval would then either filter out everything
   (`text-embedding-3-large` query against `text-embedding-v3` rows)
   or — worse, in the unlikely case of dimension match — return
   nonsense vectors.

## Decision

Three coordinated changes, taking effect in v4.2.0a0:

1. **`OpenAIEmbedder` accepts a configurable `base_url`** through the
   constructor argument or the `RESEARCH_AGENT_EMBED_BASE_URL`
   environment variable. The vector dimension is no longer hardcoded;
   it is discovered on the first `embed` call by reading the response
   length. Users select a provider by setting `base_url` + the model
   name; the project does not maintain an enum of providers.
2. **`prv_corpus_keywords` gains an `embedding_model TEXT` column**
   (schema_version 5). `ingest_proof_corpus` writes the active
   backend's `model_name` into it; `retrieve_skeletons` filters by
   the full `(embed_backend, embedding_model, embed_dim)` triple
   instead of just `(backend, dim)`. Mismatches surface as a clear
   `RuntimeError` listing the triples present in storage and the
   active triple. Legacy rows ingested under v4.1 keep their data
   but carry `'unknown'` as the model identifier; running
   `scripts/reindex_proof_corpus.py` re-encodes them under the
   active configuration.
3. **The default `local` model becomes `Qwen/Qwen3-Embedding-0.6B`**
   (multilingual, ~600 MB download on first use). Users who want the
   smaller English-only model can pin `all-MiniLM-L6-v2` via
   `RESEARCH_AGENT_EMBED_MODEL`. The setup wizard explains the
   trade-off and suggests setting `HF_ENDPOINT=https://hf-mirror.com`
   when the user is behind a slow link to huggingface.co.

The wire protocol contract is the OpenAI Python SDK itself. A
provider that diverges from that shape (different auth scheme,
non-standard error envelopes) is out of scope: the user can still
try it, but if it breaks we will not patch around it. Five providers
are listed as tested presets in `docs/embedding-providers.md`; the
wizard surfaces them and an "Other" option that accepts an arbitrary
`base_url`.

## Consequences

### Positive

- One backend covers OpenAI plus every OpenAI-compatible provider.
  The user picks via configuration, not code.
- Chinese-locale users get multilingual retrieval by default; the
  proof corpus seed already exercises Chinese clusters and now scores
  reasonably on them.
- Storage carries enough metadata to refuse mixed-model corpora at
  query time, instead of silently mixing vectors that look the right
  dimension but mean different things.
- Adding a new provider is a documentation change. The wizard's
  preset table can grow without touching `embedding.py`.

### Negative

- Users behind restrictive networks may still see slow Qwen3
  downloads on first use. The wizard hints at `HF_ENDPOINT` but does
  not set it for the user; that would silently shadow their existing
  global config.
- The OpenAI backend now takes one extra network round-trip the first
  time `.dim` is read, because the dimension is probed by a real
  embed call. The probe is cached for the rest of the process.
- The `(backend, model, dim)` triple is strict enough that any model
  upgrade triggers a re-index. `scripts/reindex_proof_corpus.py` is
  the canonical path; the cockpit surfaces a one-time toast nudging
  users toward it when it sees a mismatch.
- Provider variance is the user's problem. We test five providers in
  documentation; others are not covered by CI.

### Alternatives considered

- **A separate `openai_compatible` backend class.** Lost because
  ninety percent of the code would be a copy of `OpenAIEmbedder`.
  The SDK already has the right shape; the missing piece was just
  routing `base_url`.
- **Keep `text-embedding-3-large` as the universal default and
  document base_url overrides only in the README.** Lost because the
  wizard is the new-user contact point — surfacing presets there
  saves the user one Google search per provider.
- **Migrate the existing corpus on first launch under a new model.**
  Lost because automatic re-embedding on startup can block the
  cockpit on a long-running operation the user did not ask for. A
  manual `reindex_proof_corpus.py` step is louder but safer.
- **Embed a third-party provider router (e.g. LiteLLM).** Lost
  because adding a dependency to route to providers that themselves
  speak the OpenAI shape would be a net loss.

## References

- Plan file: `C:\Users\whenpoem\.claude\plans\iridescent-snuggling-matsumoto.md`
- Sibling ADR: [`0009-reports-as-files-monitoring-as-tui.md`](0009-reports-as-files-monitoring-as-tui.md)
- Provider preset table: [`../embedding-providers.md`](../embedding-providers.md)
- Implementation: `src/prove_mcp/embedding.py`,
  `src/prove_mcp/tools/corpus.py`,
  `src/prove_mcp/tools/retrieval.py`,
  `scripts/reindex_proof_corpus.py`,
  `src/claudescientist/setup.py`.
