# 实操：第一次研究任务

> English version: [first-research-task.md](first-research-task.md)
> 完整端到端走一遍 ClaudeScientist 上的一次研究任务。如果还没读过 [`../overview.zh-CN.md`](../overview.zh-CN.md)，请先读那份。

本教程假设你已经跑过 `uv sync`，仓库已经配置好。我们会跑一个小但真实的任务：研究 per-head dropout 是否有助于 Vision Transformer 的扩展。具体研究主题不重要——重要的是工作流的形状。

## 0. 准备两个终端

从仓库根目录打开两个终端。

```powershell
# 终端 A：Claude Code REPL（在仓库根目录）
claude

# 终端 B：cockpit TUI（在仓库根目录）
uv run python -m cockpit.tui
```

此时你应该在右侧看到一棵空的假说树。下面所有操作都在终端 A 进行，除非另有说明。

## 1. 启动 research SOP

在终端 A 输入：

```
/research-sop 研究 per-head dropout 是否有助于 ViT 扩展
```

这会触发 `research-sop` skill，由它负责调度整个流程。几秒之后，终端 B 应当出现以下变化：

- cockpit 的"问题"节点出现在树根
- 三到五个假说节点在它下面长出
- 事件流刷出若干 `graph_delta` 行

幕后发生了什么：

1. Claude 在失败记忆里查了一遍 `match_signatures("per-head dropout ViT scaling")`
2. Claude 调用了 `query_literature(...)` 看看是否已经收录了相关论文
3. （如果文献稀疏）Claude 派出了 `librarian` 子智能体，通过 `arxiv` 与 `openalex` 拉论文，然后对每篇调用 `ingest_paper`
4. Claude 派出了 `researcher` 子智能体，它生成候选假说，对每个调用 `propose_hypothesis`

## 2. 跑一轮 Bradley-Terry 锦标赛

由于至少有三个假说，`bt-tournament` skill 会自动触发。如果没有，手动触发：

```
/bt-tournament
```

对每一对假说，Claude 会：

1. 调用 `judge_hypotheses(a_id, b_id)` 拉取标准比较 prompt
2. 在线决出胜者（Claude 读 prompt、套入判定标准、做选择）
3. 调用 `record_judgement(a_id, b_id, winner_id, reason)`

在终端 B，每次比较都会发出一个 `bt_rating_updated` 事件。假说树尾列从 `bt n/a` 更新为 `bt +0.42 ±0.13 n=3` 这样的读数。

锦标赛结束后，请求一份排行榜：

```
mcp__memory__get_bt_leaderboard top_k=5
```

你会看到类似这样的输出：

```
1. hyp_8a3f...   strength=+1.84   lcb=+0.97  ucb=+2.71   n=4
2. hyp_2b1e...   strength=+0.31   lcb=-0.55  ucb=+1.18   n=3
3. hyp_c92d...   strength=-0.62   lcb=-1.48  ucb=+0.25   n=3
...
```

榜首假说与亚军的置信区间不重叠时，它就是要推进的候选。

## 3. 为确认性实验预注册

如果下一次运行要支撑主结论，先锁定目标；如果还在探索，可以先跑，但必须把结果标成探索性，不能直接当成最终确认性结论。

```
/preregister hyp_8a3f... metric=test_accuracy direction=higher_better threshold=0.85
```

`preregister` 工具会写一行 `ver_preregistrations`，状态为 `open`，并发出 `prereg_locked` 事件。cockpit 的 "Claims" 标签现在显示一条待处理记录。

## 4. 实现实验

把任务交给 engineer 子智能体：

```
@engineer 把 dropout 干预实现为一个小的 MNIST-proxy 训练脚本，带 --seed 参数
```

engineer 会写脚本。在它写的过程中，几个 hook 会自动触发：

- **写文件之前**：`leakage_guard.py` 扫描文件中已知的泄漏 pattern。如果 engineer 不小心写了 `model.fit(pd.concat([train, test]))`，写入会被直接拒绝。
- **跑 Bash 之前**：`destructive_bash_guard.py` 检查诸如 `rm -rf` 的命令。除非命令以 `# CONFIRM_DESTRUCTIVE` 结尾，否则会被拦截。

接下来 engineer 会跑这个脚本。运行时：

- `provenance_log.py`（PostToolUse）从 stdout 中抠出每个 `accuracy: 0.91` 这样的数字，写入 `ver_provenance`

## 5. 用多个种子验证

跑种子扰动检查：

```
mcp__verify__seed_perturb script_path=mnist_proxy.py seeds=[0,1,2]
```

这会用不同的 `--seed` 把脚本重跑三次，计算 test accuracy 的均值和标准差，写入 `ver_seed_runs`。默认稳定性检查会自动选择合适容差：小型有界指标近似按绝对容差，大尺度指标按相对容差。cockpit 的 "Claims" 标签现在会在指标旁显示 ✓ 或 ✗。

## 6. pin 指标并解锁预注册

pin 住结果：

```
mcp__verify__pin_metric claim="vit_dropout_test_accuracy" value=0.873 session_id=<auto> source_command="uv run python mnist_proxy.py --seed 0"
```

这会创建一行 `ver_metric_pins`，并关联到种子运行。然后解锁预注册：

```
mcp__verify__resolve_preregistration prereg_id=preg_... observed_value=0.873
```

如果观测值在锁定方向上达到了阈值，状态翻为 `met`。如果你还传了 `observed_p_value`，系统会把配置的多重比较校正应用到所有当前打开的预注册上。当前 v3.0 兼容实现中，`bh` 和 `bonferroni` 共用同一套 Bonferroni-style 计算。

## 7. 抽查 provenance DAG

如果实验依赖输入数据文件，刷新一下声明：

```
mcp__verify__refresh_claim claim="vit_dropout_test_accuracy"
```

这会重新计算该声明 DAG 中每个输入文件的哈希。如果有任何文件相比当初 `record_provenance` 时发生了漂移，声明会被标记为 `stale`，并触发 `prov_dag_stale` 事件。stale provenance 会阻断发布级核心声明；没有 DAG 的记录会作为 unchecked 审计信息暴露出来。

## 8. 总结并暂停弱分支

再看一次排行榜：

```
mcp__memory__get_bt_leaderboard
```

找出 UCB 明显低于 0 的假说。建议暂停它们：

```
mcp__memory__suggest_pause_low_strength ucb_threshold=-0.5
```

默认情况下，这**只会发出建议**——并不真正暂停任何东西。如果设置了 `RESEARCH_AGENT_AUTO_PRUNE=1`，被建议的分支会立即暂停。无论哪种情况，都可以用 `resume_branch(node_id, reason)` 反转。

## 9. 交给 writeup

现在可以让 Claude 起草一份简短的总结：

```
@reviewer 准备一份 dropout 研究的一页总结
```

reviewer agent 会对发布级核心声明执行 writeup 契约：中心 confirmatory 指标需要 metric pin、stable 的种子结论、met 的预注册、以及未漂移的 provenance。探索性结果和上下文数字要如实标注，而不是一律通过所有硬门。

## 10. 结束 session

在终端 A 退出 Claude Code，然后在终端 B 退出 TUI（按 `q`）。重启二者。你应当看到整张图、所有 BT 评分、所有预注册、所有 metric pin 都和你离开时一模一样——SQLite 文件是唯一的状态来源。

## 你刚才完成了什么

- 生成并持久化了一张假说图
- 用 Bradley-Terry 锦标赛排出了候选
- 在跑任何代码之前锁定了证伪目标
- 在泄漏与破坏性命令双重 guard 下实现了实验
- 用三个随机种子验证了结果
- 记录了带文件指纹的溯源
- 应用多重比较校正解锁了预注册
- 用 dry-run 方式剪掉了弱分支
- 起草了一份强制满足以上全部条件的 writeup

这就是完整的 v3.0 闭环。其他工作流（[写一篇论文](writing-a-paper.zh-CN.md)、[排查一个失败](debugging-a-failure.zh-CN.md)）覆盖了同一套机制的更窄切面。

## 常见的"咦怎么这样"

- **cockpit 滞后最多 1 秒** —— 这是轮询周期，不是 bug。
- **在 cockpit 按 `n` 不会打断当前正在执行的工具** —— 干预会被排队，到下一个 `UserPromptSubmit` 或 `Stop` 事件时才送达。这是有意为之。
- **首次运行会创建 `.research-agent/state.db`** —— 删掉这个目录就能从头开始，但所有记忆都会被抹掉。
- **修改了代码必须重启 MCP 服务器才能生效** —— Claude Code 在 session 启动时拉起这些服务器并一直保持。重启 Claude Code 才会重新加载。
