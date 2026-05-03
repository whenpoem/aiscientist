# 实操：写一篇论文

> English version: [writing-a-paper.md](writing-a-paper.md)
> 如何利用验证栈起草一份"每个数字都可追溯"的手稿。如果还没读过 [`first-research-task.zh-CN.md`](first-research-task.zh-CN.md)，请先读那份——本教程假设你已经做完实验、pin 好了指标。

`reviewer` 子智能体强制执行一条严格契约：任何最终写入 `.md` 文件的数值声明，都必须可以追溯到四个锚点。这份文档解释如何端到端满足这个契约。

## 四个锚点

下笔之前，先把 reviewer 会要的东西刻在脑子里。每个数字都要有：

1. **指标 pin** —— 必须存在一行 `ver_metric_pins`，其 `claim` 与你引用的数字对得上
2. **稳定的种子结论** —— 关联到该 pin 的 `ver_seed_runs.verdict='stable'`
3. **达成的预注册** —— 一行 `ver_preregistrations`，`status='met'`
4. **新鲜的 provenance** —— `refresh_claim` 报告 `status='fresh'`，没有漂移的输入文件

四项中只要有一项缺失或过期，reviewer 就会拒绝起草，并列出缺失的锚点。这是功能，不是阻碍。

## 第 0 步：先做一个快照

任何写作开始之前，先把状态冻结：

```
mcp__memory__snapshot label="paper-draft-v1"
```

这会把整张假说图与 BT 评分都保存下来。如果将来有人质疑某条声明，你可以重放写作时刻的精确状态。

## 第 1 步：列出所有声明

打开一份新 markdown 文件，把你打算写的每一个数值声明列出来：

```
- ViT-S/16 加 per-head dropout 0.3，在 CIFAR-10 上达到 87.3%
- 不加 dropout，baseline 达到 85.5%
- 提升幅度为 1.8 个百分点
- 在种子 [0,1,2] 上结果稳定（std=0.004）
- 在匹配的 epoch 预算下比较公平（proposed=20, baseline=18）
```

这就是**声明清单（claim manifest）**。每一行对应一次锚点检查。

## 第 2 步：调用 writeup SOP

运行：

```
/writeup-sop 起草一份关于 dropout 研究的一页报告
```

这会启动一个工作流，它会：

1. 遍历声明清单
2. 对每一个数值声明调用 `mcp__verify__check_provenance(claim)`
3. 如果状态是 `missing`，暂停并要求你重跑实验或者删掉这条声明
4. 如果状态是 `found`，再调用 `refresh_claim(claim)` 检测上游漂移
5. 全部通过后，起草周边文字

任何未通过验证的数字处，工作流都会明显地停下。这是正确行为。

## 第 3 步：处理缺失的锚点

针对 reviewer 报告的每个阻断项：

### "缺失 pin"

数字未被 pin。pin 一下：

```
mcp__verify__pin_metric claim="vit_dropout_test_accuracy" value=0.873 session_id=<auto> source_command="..."
```

### "缺失种子结论"

指标已经 pin，但还没跑过种子扰动。跑一次：

```
mcp__verify__seed_perturb script_path=<your_script>.py seeds=[0,1,2] metric_pin_id=<上一步的 pin 号>
```

### "缺失或未达成预注册"

数字是在没有预注册的情况下产生的。这里没有捷径——预注册必须**在实验之前**就存在。诚实的做法是：

1. 在手稿里如实承认这个结果是探索性的，而非确认性的
2. 现在补一个预注册，**用新种子重跑**实验
3. 引用重跑结果，而不是原结果

这正是项目要强制守住的"探索性分析 vs 确认性分析"的边界。

### "provenance 已过期"

`refresh_claim` 报告 `status='stale'`。一个或多个输入文件自实验跑过之后被改动了。要么：

1. 还原原始文件（如果漂移是无意的，这是最佳选项），要么
2. 在当前文件上重跑实验，并更新 pin

reviewer 不会接受 stale 的声明。

## 第 4 步：纳入审计痕迹

每条通过验证的声明，writeup 工作流会在它后面追加一段隐藏的 HTML 注释作为追溯：

```markdown
<!-- prov: pin_id=42 prereg_id=preg_8a3f seed_run_id=17 fresh=true snapshot=snap_2026-05-03 -->
The ViT-S/16 model with per-head dropout 0.3 reaches 87.3% on CIFAR-10.
```

这些注释在渲染后的 Markdown 中不可见，但充当审计痕迹。它们只在最终发布步骤、经过人工审阅之后才会被移除。

## 第 5 步：考虑矛盾

发布之前，跑一次：

```
mcp__memory__find_contradictions
```

这会浮现所有通过 `contradicts` 边相连的节点对。如果当前声明与之前的某个声明矛盾，手稿必须：

1. 在正文中显式解决这个矛盾，或者
2. 把先前的声明标记为 superseded，并重跑所有依赖于它的分析

## 第 6 步：处理 baseline

如果论文涉及"提出方法 vs baseline"的比较，包含公平性检查：

```
mcp__verify__baseline_fairness proposed_log=runs/proposed.log baseline_log=runs/baseline.log
```

如果 verdict 是 `unfair`，writeup 工作流会拒绝发布该比较，直到：

1. baseline 在匹配预算下重跑，或者
2. 不公平的轴在手稿中被显式披露

披露是可以接受的，但对顶级 venue 通常不够——还是把预算匹配上更好。

## 第 7 步：reviewer 终审

输入：

```
@reviewer 对 dropout writeup 做最终审计
```

reviewer 会读完整份草稿，给出两种结果之一：

- **`accept`** 并附上一份验证锚点的简短总结
- **`reject`** 并列出所有遗留的阻断项

收到 `reject` 时可以逐项处理后再跑一次。reviewer 故意挑剔；把它当作同行评审，而不是橡皮图章。

## 永远不要做的事

下面是系统刻意要让你做不了的反模式：

- **挑种子**。如果三个种子里只有种子 1 达到了目标，verdict 就是 `unstable`，声明无法通过。
- **看到结果之后改阈值**。预注册阈值不可变。允许提一个新预注册（用更宽松的阈值），但必须披露。
- **没 pin 就引用**。即便数字"显然没问题"，它也必须被 pin。
- **绕过 `query_heldout`**。永远不要直接读 held-out 测试集。leakage guard 会拦截；工作流不会绕开。
- **手工编辑 `.research-agent/state.db`**。所有状态都必须通过 MCP 工具走。手改会留下审计盲区。

## 关于行文风格

项目不对行文风格做任何主张，只强制可追溯性。一旦每个数字都通过了四锚点检查，你就可以用任何你喜欢的语气来写——除了数字之外，系统对其他一切保持沉默。
