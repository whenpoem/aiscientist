# 嵌入向量服务商

> English version: [embedding-providers.md](embedding-providers.md)

ClaudeScientist 的 `openai` 嵌入后端可以对接任何提供 OpenAI
`/v1/embeddings` 兼容接口的服务商。本页列出项目实际测试过的几家，并
给出各自需要的配置。

兼容性边界就是 `openai` Python SDK 本身。如果某家服务商的接口有偏差
（比如自定义的鉴权头、非标准的错误响应格式），项目不会专门适配——可
能能跑通，但出了问题不保证修。

## 配置方法

后端通过以下环境变量读取配置：

| 变量 | 含义 |
|---|---|
| `RESEARCH_AGENT_EMBED_BACKEND` | 设为 `openai` |
| `RESEARCH_AGENT_EMBED_BASE_URL` | 服务商的 API 端点；留空则使用 OpenAI 默认地址 |
| `RESEARCH_AGENT_EMBED_MODEL` | 服务商要求的模型名 |
| `OPENAI_API_KEY` | 服务商的 API key（兼容服务商都通过这个变量接收 key）|

普通插件用户通过下面的命令设置前三项：

```powershell
claudescientist configure --workspace . --embedding-backend openai
```

命令会把非敏感设置写入 `.research-agent/config.toml`，`OPENAI_API_KEY` 仍由环境变量
提供。源码贡献者可以继续使用 `claudescientist dev-setup`，它会写入源码仓库的
`.env`。

更换服务商或模型后，应当先用新后端重新索引已有证明语料。源码贡献者可以运行
`uv run python scripts/reindex_proof_corpus.py`。

## 已测试的预设方案

### OpenAI

SDK 默认值。`RESEARCH_AGENT_EMBED_BASE_URL` 留空即可。

```bash
RESEARCH_AGENT_EMBED_BACKEND=openai
RESEARCH_AGENT_EMBED_MODEL=text-embedding-3-large
OPENAI_API_KEY=sk-...
```

向量维度：3072。在 OpenAI 当前几款嵌入模型里单次调用成本最低，但每次
检索都要付费，迭代频繁的话费用会推着你转向本地模型。

### 阿里云 DashScope

中国境内用户首选，没有网络访问问题。

```bash
RESEARCH_AGENT_EMBED_BACKEND=openai
RESEARCH_AGENT_EMBED_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
RESEARCH_AGENT_EMBED_MODEL=text-embedding-v3
OPENAI_API_KEY=sk-...   # DashScope key
```

向量维度：1024。DashScope key 在阿里云控制台申请；URL 末尾的
`compatible-mode/v1` 是让它走 OpenAI 兼容接口的关键。

### Jina

多语言，面向检索场景。

```bash
RESEARCH_AGENT_EMBED_BACKEND=openai
RESEARCH_AGENT_EMBED_BASE_URL=https://api.jina.ai/v1
RESEARCH_AGENT_EMBED_MODEL=jina-embeddings-v3
OPENAI_API_KEY=jina_...
```

向量维度：1024。Jina 的免费额度够把证明语料完整灌入并跑一遍检索验证。

### Voyage

针对检索优化，英文表现较强。

```bash
RESEARCH_AGENT_EMBED_BACKEND=openai
RESEARCH_AGENT_EMBED_BASE_URL=https://api.voyageai.com/v1
RESEARCH_AGENT_EMBED_MODEL=voyage-3
OPENAI_API_KEY=pa-...
```

向量维度：1024。

### 智谱 GLM

中国境内用户，高维度方案。

```bash
RESEARCH_AGENT_EMBED_BACKEND=openai
RESEARCH_AGENT_EMBED_BASE_URL=https://open.bigmodel.cn/api/paas/v4
RESEARCH_AGENT_EMBED_MODEL=embedding-3
OPENAI_API_KEY=...
```

向量维度：2048。

## 使用不在列表里的服务商

设置向导里的"其他"选项会让你填一个自定义的 `base_url` 和模型名。只
要能通过冒烟测试（调一次 `embed(["probe"])` 返回正常的向量），检索效
果就和上面列出的预设方案一样。

新接入的服务商如果行为异常，第一步先确认 `openai` SDK 单独能不能正常
调通——项目在 SDK 和网络之间没有加任何中间层。

## 切回本地模型

本地嵌入一直是默认选项，理由很简单：不需要网络、不按次计费、没有速率
限制。本地后端的默认模型是 `Qwen/Qwen3-Embedding-0.6B`（约 600 MB，
支持多语言）；旧版的英文专用模型是 `all-MiniLM-L6-v2`（约 80 MB）。

```bash
RESEARCH_AGENT_EMBED_BACKEND=local
RESEARCH_AGENT_EMBED_MODEL=Qwen/Qwen3-Embedding-0.6B
```

首次灌入语料时模型会从 Hugging Face 下载。如果网络较慢或受限，可以在
首次启动前设一下 `HF_ENDPOINT=https://hf-mirror.com`，下载会走镜像站。
切完模型后跑一遍 `uv run python scripts/reindex_proof_corpus.py` 把
已有语料重新编码。
