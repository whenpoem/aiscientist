# 历史归档

> English version: [README.md](README.md)

这个目录保存了 ClaudeScientist 从空仓库走到今天所经历的全部规划文档。这里的每一份计划都已经交付完成；系统当前的真实形态以 `docs/` 上一级目录里的文档为准，不在这里。

我们仍然保留这些文件，是因为它们记录了**为什么这样设计**，而不仅仅是做了什么。当后来的贡献者疑惑"为什么 cockpit 是 TUI 而不是浏览器应用"时，答案在 `plan-v0.2.md` 里；当他们疑惑"为什么用 Bradley-Terry 替换了 Elo"时，答案在 `plan-v3.0.md` 里。删掉这些文件等于抹去了决策的来龙去脉。

## 阅读顺序

如果你想了解完整的时间线，建议按以下顺序阅读：

1. **[`original-ideas.zh-CN.md`](original-ideas.zh-CN.md)** —— 项目的两行原始 brainstorm。这里提出的两个改进想法最终都在 v3.0 中落地。
2. **[`plan-v0.1.md`](plan-v0.1.md)** / [`plan-v0.1.zh-CN.md`](plan-v0.1.zh-CN.md) —— 第一份详细计划。包含最初的架构决策（单一 SQLite 文件、模块按表前缀隔离、统一使用 `uv`），以及一个已经被废弃的、基于 FastAPI + React + Vite 的浏览器 cockpit。浏览器前端在 v0.2 中被删除，但 v0.1 的其他设计基本保留至今。
3. **[`plan-v0.2.md`](plan-v0.2.md)** / [`plan-v0.2.zh-CN.md`](plan-v0.2.zh-CN.md) —— 务实重构。删掉了整套 Web UI，改用 Textual TUI，同时补齐三项验证能力：`seed_perturb`（多种子稳定性检查）、基于 Elo 的假说筛选、以及 held-out 预算控制。
4. **[`plan-v3.0.md`](plan-v3.0.md)** —— 统计严谨性升级。把 Elo 换成 Bradley-Terry，引入带 BH/Bonferroni 校正的预注册机制，增加可刷新的溯源 DAG，并把自动剪枝改为需要显式开启的环境变量。这是当前正在交付的版本。

## 归档之外是什么

`docs/` 目录下任何**不**在 `archive/` 里的文档，描述的都是系统当前的样子：

- `docs/overview.md` —— 五分钟建立心智模型
- `docs/architecture.md` —— 跨模块契约与不变量
- `docs/tool-reference.md` —— v3.0 全部 MCP 工具的完整参考
- `docs/workflows/` —— 按场景组织的实操教程

如果你发现归档中的某份计划与当前文档存在矛盾，**以当前文档为准**。欢迎提 issue 让归档加上注释说明，但请不要"修正"归档——这些文件属于不可变历史。

每个核心决策的精炼理由（每份一页，比长计划更易扫读），见 [`../adr/`](../adr/)。
