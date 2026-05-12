# ADR 0010：通过可配置 base_url 支持多家嵌入服务商

- **状态**：Accepted (v4.2)
- **日期**：2026-05

## 背景

`prove_mcp` 提供三种嵌入后端：`mock`（确定性输出，测试用）、`local`
（sentence-transformers，跑在本地）和 `openai`（调 API）。v4.1 阶段，
`openai` 后端把 SDK 默认端点和 `text-embedding-3-large` 模型写死了，
`local` 后端则把 `all-MiniLM-L6-v2` 写死了。这两个选择都开始带来问题：

1. 项目的主要用户日常使用中文。`all-MiniLM-L6-v2` 只针对英文优化，在
   种子语料的中文聚类上效果明显不行；而从国内网络稳定访问
   `api.openai.com` 也不该被当作理所当然的前提。
2. 好几家嵌入服务商（阿里云 DashScope、Jina、Voyage、智谱 GLM、
   DeepSeek 等）都提供与 OpenAI 兼容的 HTTP 接口。官方 `openai`
   Python SDK 的构造函数本来就有一个 `base_url` 参数，就是为了让调
   用方把请求重定向到这些服务商。要支持它们，成本只是多一个 `base_url`
   配置项；好处是用户可以自由选择服务商。
3. 证明语料在存储每条关键词的向量时，附带了 `(embed_backend, embed_dim)`
   两个字段来标识来源。但在 v4.1 下，同一个后端、两个不同模型产生的
   行可以静默共存。检索时要么全部被过滤掉（比如用
   `text-embedding-3-large` 查询去匹配 `text-embedding-v3` 的行），
   要么——如果维度恰好一样——返回语义完全无关的向量。

## 决策

v4.2.0a0 引入三个配套改动：

1. **`OpenAIEmbedder` 接受可配置的 `base_url`**，通过构造函数参数或
   `RESEARCH_AGENT_EMBED_BASE_URL` 环境变量传入。向量维度不再写死，
   首次调 `embed` 时从响应里读出来。用户通过设定 `base_url` + 模型名
   来选择服务商；项目不维护服务商列表。
2. **`prv_corpus_keywords` 新增 `embedding_model TEXT` 列**
   （schema_version 5）。`ingest_proof_corpus` 会把当前后端的模型名
   写进去；`retrieve_skeletons` 按完整的
   `(embed_backend, embedding_model, embed_dim)` 三元组来过滤，不再
   只看 `(backend, dim)` 两项。三元组对不上时会抛出明确的
   `RuntimeError`，列出存储里有哪些三元组、当前用的是哪个。v4.1 遗留
   的旧行数据保留，模型标识记为 `'unknown'`；运行
   `scripts/reindex_proof_corpus.py` 就能在当前配置下重新编码。
3. **本地默认模型改为 `Qwen/Qwen3-Embedding-0.6B`**（多语言，首次使用
   下载约 600 MB）。想用更小的英文模型的用户可以通过
   `RESEARCH_AGENT_EMBED_MODEL` 把 `all-MiniLM-L6-v2` 指定回去。设置
   向导会解释这个取舍，并在用户访问 huggingface.co 比较慢时建议设
   `HF_ENDPOINT=https://hf-mirror.com`。

兼容性边界就是 OpenAI Python SDK 本身。如果某家服务商偏离了这个接口
（比如用自定义的鉴权方式、返回非标准的错误结构），那就不在项目的支持
范围里：用户当然可以试，但出了问题项目不会专门打补丁。
`docs/embedding-providers.md` 列出了五家测试过的预设方案；设置向导在
用户选服务商时也会展示这些预设，另外提供一个"其他"选项允许填写自定义
的 `base_url`。

## 后果

### 正面

- 一个后端就能覆盖 OpenAI 加所有 OpenAI 兼容的服务商。用户改个配置就
  能切换，不需要动代码。
- 中文用户默认就有多语言检索能力；证明语料种子里的中文聚类现在能拿到
  合理的匹配分数。
- 存储里携带的元数据足以在查询时识别出混用了不同模型的语料。维度碰巧
  相同但语义不同的向量不会被悄悄混在一起。
- 新增一个服务商只需要改文档。预设方案表可以扩展，`embedding.py` 不
  用动。

### 负面

- 网络受限的用户首次下载 Qwen3 模型时可能会慢。向导会提示
  `HF_ENDPOINT` 镜像选项，但不会替用户设——那样会悄悄覆盖用户已有的
  全局 HuggingFace 配置。
- OpenAI 后端首次读取维度时多一次网络请求，因为维度是通过一次真实的
  嵌入调用探测出来的。探测结果会缓存到进程结束。
- `(backend, model, dim)` 三元组校验很严格，换一次模型就要重建一次
  索引。`scripts/reindex_proof_corpus.py` 是标准做法；cockpit 检测到
  不匹配时会弹一次提示引导用户去跑。
- 服务商之间的差异由用户自己负责。文档覆盖了五家服务商；其他的不进
  CI。

### 备选方案

- **单独建一个 `openai_compatible` 后端类**。否决——九成代码都是
  `OpenAIEmbedder` 的重复。SDK 的接口已经够用了，差的只是把
  `base_url` 暴露出来。
- **保留 `text-embedding-3-large` 当通用默认，只在 README 里说明
  `base_url` 怎么覆盖**。否决——设置向导是新用户最先接触到的界面，
  把预设方案放在向导里能省下用户去逐个搜索每家服务商的配置方法。
- **首次启动时自动把已有语料迁移到新模型**。否决——后台自动重新编码
  会让 cockpit 卡在一个用户没主动要求的长时间操作上。手动跑
  `reindex_proof_corpus.py` 多一步操作，但更安全。
- **接一个第三方路由层（比如 LiteLLM）**。否决——给本来就兼容 OpenAI
  接口的服务商再加一层依赖，净效果是负的。

## 引用

- 计划文件：`C:\Users\whenpoem\.claude\plans\iridescent-snuggling-matsumoto.md`
- 相关 ADR：[`0009-reports-as-files-monitoring-as-tui.md`](0009-reports-as-files-monitoring-as-tui.md)
- 服务商预设表：[`../embedding-providers.zh-CN.md`](../embedding-providers.zh-CN.md)
- 实现位置：`src/prove_mcp/embedding.py`、
  `src/prove_mcp/tools/corpus.py`、
  `src/prove_mcp/tools/retrieval.py`、
  `scripts/reindex_proof_corpus.py`、
  `src/claudescientist/setup.py`。
