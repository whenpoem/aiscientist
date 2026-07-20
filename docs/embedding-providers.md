# Embedding providers

> 中文版本：[embedding-providers.zh-CN.md](embedding-providers.zh-CN.md)

ClaudeScientist's `openai` embedding backend talks to any provider that
exposes the OpenAI `/v1/embeddings` shape. This page lists the
providers the project has actually tested, plus the configuration each
one needs.

The wire protocol contract is the `openai` Python SDK. Providers that
diverge from it (custom auth headers, non-standard error envelopes) are
out of scope — they may work, but the project does not patch around
them.

## Setting a provider

The backend reads three environment variables:

| Variable | Meaning |
|---|---|
| `RESEARCH_AGENT_EMBED_BACKEND` | Set to `openai` |
| `RESEARCH_AGENT_EMBED_BASE_URL` | The provider's endpoint; leave unset to use OpenAI's default |
| `RESEARCH_AGENT_EMBED_MODEL` | The model identifier the provider expects |
| `OPENAI_API_KEY` | The provider's API key (every compatible provider accepts it through this variable) |

Ordinary plugin users set the first three values with:

```powershell
claudescientist configure --workspace . --embedding-backend openai
```

The command writes non-secret values to `.research-agent/config.toml` and
leaves `OPENAI_API_KEY` in the environment. Source contributors can still use
`claudescientist dev-setup`, which writes the checkout's `.env`.

After changing the provider or model, reindex any existing proof corpus before
using retrieval results from the new backend. Source contributors can run
`uv run python scripts/reindex_proof_corpus.py`.

## Tested presets

### OpenAI

The SDK default. Leave `RESEARCH_AGENT_EMBED_BASE_URL` unset.

```bash
RESEARCH_AGENT_EMBED_BACKEND=openai
RESEARCH_AGENT_EMBED_MODEL=text-embedding-3-large
OPENAI_API_KEY=sk-...
```

Vector dimension: 3072. Per-call cost is the smallest among current
OpenAI embedding models, but you pay it on every retrieval, so
extensive iteration may push you toward a self-hosted backend.

### Aliyun DashScope

China-resident users, no GFW issues.

```bash
RESEARCH_AGENT_EMBED_BACKEND=openai
RESEARCH_AGENT_EMBED_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
RESEARCH_AGENT_EMBED_MODEL=text-embedding-v3
OPENAI_API_KEY=sk-...   # DashScope API key
```

Vector dimension: 1024. The DashScope key is issued in the Aliyun
console; the `compatible-mode/v1` suffix on the URL is the part that
makes it speak the OpenAI shape.

### Jina

Multilingual, retrieval-oriented.

```bash
RESEARCH_AGENT_EMBED_BACKEND=openai
RESEARCH_AGENT_EMBED_BASE_URL=https://api.jina.ai/v1
RESEARCH_AGENT_EMBED_MODEL=jina-embeddings-v3
OPENAI_API_KEY=jina_...
```

Vector dimension: 1024. Jina's free tier is sufficient to seed and
exercise the proof corpus end-to-end.

### Voyage

Retrieval-tuned, English-strong.

```bash
RESEARCH_AGENT_EMBED_BACKEND=openai
RESEARCH_AGENT_EMBED_BASE_URL=https://api.voyageai.com/v1
RESEARCH_AGENT_EMBED_MODEL=voyage-3
OPENAI_API_KEY=pa-...
```

Vector dimension: 1024.

### GLM (Zhipu)

China-resident users, high dimension.

```bash
RESEARCH_AGENT_EMBED_BACKEND=openai
RESEARCH_AGENT_EMBED_BASE_URL=https://open.bigmodel.cn/api/paas/v4
RESEARCH_AGENT_EMBED_MODEL=embedding-3
OPENAI_API_KEY=...
```

Vector dimension: 2048.

## Using a provider not in this list

The wizard's "Other" option asks for an arbitrary `base_url` and a
model name. If the provider passes the smoke check (one successful
`embed(["probe"])` call returning a unit vector), retrieval will work
the same way it does for the tested presets.

When a brand-new provider misbehaves, the first thing to check is
whether the `openai` SDK alone can call it — the project does not add
any logic between the SDK and the network.

## Switching back to a local model

Self-hosted embedding remains the default for a reason: no network
round-trip, no per-call cost, no rate limit. The local backend's
default model is `Qwen/Qwen3-Embedding-0.6B` (~600 MB, multilingual);
the legacy English-only option is `all-MiniLM-L6-v2` (~80 MB).

```bash
RESEARCH_AGENT_EMBED_BACKEND=local
RESEARCH_AGENT_EMBED_MODEL=Qwen/Qwen3-Embedding-0.6B
```

The first ingest call downloads the model from Hugging Face. Slow or
restricted networks should set `HF_ENDPOINT=https://hf-mirror.com`
before the first launch so the download routes through a mirror.
After switching, run `uv run python scripts/reindex_proof_corpus.py`
to re-encode any previously ingested corpus.
