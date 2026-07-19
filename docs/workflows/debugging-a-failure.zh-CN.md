# 实操：排查一个失败

> English version: [debugging-a-failure.md](debugging-a-failure.md)
> 一份精简的实操教程，讲解事情出错时如何使用失败记忆和回放工具。如果还没读过 [`first-research-task.zh-CN.md`](first-research-task.zh-CN.md)，请先读那份。

当一次实验失败或产出意外结果时，项目提供了三件工具——它们组合起来能避免你重复解决同一个问题：`match_signatures`、`record_failure`、`replay_counterfactual`。本教程讲清楚每件工具的使用时机。

## 原则

每一次失败都是一次"在记忆里写下一行"的机会。坚持下来，整个项目就会变成一个记得你所有错误的私人专家系统。

## 第 1 步：失败发生时，先搜索

开始 debug 之前，先问失败记忆：

```
mcp__memory__match_signatures situation="ViT 训练时 cuda out of memory" k=5
```

这会在 `(trigger, symptom, root_cause, resolution)` 上做 BM25 排名，返回最相关的 5 条历史失败。如果有相似的失败，**在打开任何 debugger 之前先读一下它的 resolution**。这能省你几个小时。

如果什么都没匹配上，进入第 2 步。

## 第 2 步：最小复现

把失败缩到尽可能小的脚本里复现出来。这本身是好的工程实践，与项目无关；但越小的复现，最终的 record_failure 条目就越能被复用。

一个有用的经验：如果复现超过 50 行，继续砍。

## 第 3 步：二分

标准二分。destructive bash guard 会阻止你二分到一半时不小心跑出 `git reset --hard`，所以可以放心地激进使用 git。

找到出问题的 commit 时：

- 找出 **trigger（触发动作）**：什么动作导致了失败
- 找出 **symptom（症状）**：用户/系统观察到的现象
- 找出 **root cause（根因）**：底层原因
- 找出 **resolution（解决方案）**：是什么让它消失的

如果四样都说不清楚，继续挖。

## 第 4 步：记录失败

```
mcp__memory__record_failure \
  trigger="ViT 训练 batch_size=128 在 24GB GPU 上" \
  symptom="第一次 forward pass 之后 CUDA out of memory" \
  root_cause="ViT-B/16 的激活内存约为同 batch ResNet-50 的 2 倍" \
  resolution="把 batch_size 降到 64，或启用 gradient checkpointing"
```

系统会算一个确定性签名。如果你（或别人）日后记录了一条相同的失败，`seen_count` 会累加，而不是创建重复行。全文搜索索引会自动更新。

## 第 5 步：失败是概念性的而非机械性的

有时"失败"指的是某个假说被证据推翻，而不是脚本崩溃。这种情况下，正确的工具不是 `record_failure`，而是图本身：

```
mcp__memory__attach_evidence node_id=<假说_id> evidence_text="..." polarity=refutes
mcp__memory__mark_refuted node_id=<假说_id> reason="..." evidence_ids=[<新证据>]
```

这会通过 BT 层传播（`update_bt_rating` 带 `source=metric_diff`），cockpit 的树形面板里这个假说会显示为划线状态。

## 第 6 步：反事实场景

假设你一周前剪掉了一个假说分支，新的证据让你怀疑当时是不是剪错了。你想问"如果当时保留了那个分支会怎样"，但又不想动到当前状态。

这就是回放工具的用武之地：

```
# 先列出可用的快照
mcp__memory__list_replay_branches

# 然后在选中的快照上创建一个反事实分支
mcp__memory__replay_counterfactual \
  snapshot_id=snap_2026-04-21 \
  counterfactual="保留 hyp_8a3f 而不是 hyp_2b1e"
```

这会向 `mem_replay_branches` 写入一行，并发出 `replay_branch_created`。主图 `mem_nodes` 与 `mem_bt_ratings` 不受影响。你可以无风险地手动或自动探索这个反事实。

回放结束后，直接忽略它就好——除非你显式地通过新的 `propose_hypothesis` 把它"提升"，否则 replay 分支不会反向影响主图。

## 第 7 步：失败是泄漏检测报警

如果 `leakage_check` 标记了你的脚本、hook 拒绝了一次 `Write`，**这是设计如此**。正确做法**不是**绕过 hook，而是：

1. 读 finding 的 `message` 字段——它会指出确切的行号和规则
2. 重构脚本：只在训练数据上 fit 模型，然后用拟合好的 scaler 变换测试数据
3. 在新脚本上重跑 `leakage_check`
4. 干净之后，重试 `Write`

如果你确信泄漏检测错了（假阳性），把它记成一条失败，`root_cause="leakage_check 规则 X 在 pattern Y 上假阳性"`。这能为日后改进规则积累证据。

## 第 8 步：失败是预算溢出

`budget_consume` 返回了 `{"ok": False, "error": "budget_exceeded"}`。budgeter agent 本应提前发现；如果它没有，那它的 prompt 可能需要更新。

当下的正确反应是：

- **暂停当前操作**并重新评估计划
- **检查 `res_budget_ledger`** 看哪条轴爆了
- **要么经用户显式批准，提高预算上限**，要么**放弃该操作**

不要悄悄抬高上限继续跑。预算的存在就是为了让超支可见。

## 第 9 步：记录结果并验证

失败修好之后，还要做：

```
mcp__memory__attach_evidence node_id=<原假说> \
  evidence_text="commit abc123 修复了 bug，结果现在能复现" \
  polarity=supports
```

这能让假说图诚实地反映"今天我们知道什么"与"昨天我们知道什么"的差别。

## 反模式

- **debug 之前不调用 `match_signatures`**。可能在别人已经解决过的问题上浪费几个小时。
- **修好之后不记录失败**。下一个人（三个月后的你）会撞到同一面墙。
- **记录的失败模糊不清**。`trigger="错误"`、`symptom="坏了"` 毫无价值。四个字段的存在是有道理的。
- **为了"假设"什么而修改主图**。那是 `replay_counterfactual` 的职责。主图应当始终反映实际发生过的事情。

## 收尾的话

失败记录可以减少以后排查相似问题所需的时间。记录问题特征、原因和解决方法通常只
需要很短时间，但可能避免再次进行相同的排查。
