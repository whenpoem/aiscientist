# 安装：Lean 形式化保险层（P4）

> 一次性配置，让证明主干的 `prover` 子代理能通过 `lean-lsp-mcp` 调用真正的
> Lean 4 工具链。如果你只想用 NL 证明流程（P2 + P3），跳过本文档即可——证明主干在没有 Lean 时也完全可用。

本指南**默认手动执行**。第三方 `lean-lsp-mcp`、Lean 工具链、mathlib4 总共
是 ~2-3 GB 安装、首次编译 ~15 分钟的重量级依赖。把它们塞进 `uv sync` 里
会让所有不想用 Lean 的贡献者都被拖累，所以保留为按需启用。

## 1. 安装 elan（Lean 版本管理器）

**Windows (PowerShell)**:

```powershell
curl -L "https://raw.githubusercontent.com/leanprover/elan/master/elan-init.ps1" -o elan-init.ps1
powershell -ExecutionPolicy Bypass -File elan-init.ps1 -y
# 重启 shell，让 PATH 加载 %USERPROFILE%\.elan\bin
```

**macOS / Linux**:

```bash
curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf | sh -s -- -y
```

验证：

```powershell
elan --version
lean --version   # 应输出 "Lean (version 4.x...)"
```

## 2. 安装 `lean-lsp-mcp`

MCP 包装器本身只有 ~5 MB，是 PyPI 上的 Python 包。

```powershell
uv tool install lean-lsp-mcp
```

验证：

```powershell
uv tool run lean-lsp-mcp --help
```

如果 `command not found`，确认 `%USERPROFILE%\.local\bin`（或系统对应路径）
在 PATH 里。

## 3. 引导 mathlib4 项目

`prover` 代理在一个依赖 mathlib4 的 lake 项目中运行 Lean。在
`.research-agent/lean/` 下建一个专用 checkout：

```powershell
# 在仓库根目录
mkdir -Force .research-agent\lean
cd .research-agent\lean
lake new claudescientist-proofs math
cd claudescientist-proofs
lake update
lake exe cache get   # 下载预编译 mathlib（~2 GB，首次约 10 分钟）
lake build
```

`cache get` 是漫长的一步，但只会做一次。

## 4. 启用 lean MCP 服务器

**不用改 settings.json**。`.claude/settings.json` 里已经登记了一个 `lean`
mcpServer，命令是 `scripts/lean_mcp_or_noop.py`。这个 wrapper 启动时检测
PATH 上是否有 `lake` 和 `lean`：

- 工具链已装 → wrapper 把 stdio 透传给真正的 `lean-lsp-mcp`
- 工具链未装 → wrapper 干净退出（exit 0）+ 一行 stderr 说明；
  prover agent 调时看到没有 `mcp__lean__*` 工具，按 prompt 自动终止

所以做完 1-3 节后**直接重启 Claude Code 就行**，lean MCP 自动上线。
不需要手改 JSON、不需要重命名。以后哪天卸了 elan / mathlib，wrapper
自动回退，不用做任何撤销。

## 4b. 预先放入 spike 模板

仓库在 `.research-agent/lean/spikes-template/` 下提供 5 个小型统计引理的
Lean 源码模板。把它们拷到你的 lake 项目里：

```powershell
# 在 .research-agent\lean\claudescientist-proofs 内：
mkdir ClaudescientistProofs\Spikes -Force
copy ..\spikes-template\*.lean ClaudescientistProofs\Spikes\
```

然后在 `ClaudescientistProofs.lean`（lake new 生成的库根文件）里加上 import：

```lean
import ClaudescientistProofs.Spikes.SampleMeanUnbiased
import ClaudescientistProofs.Spikes.MarkovInequality
import ClaudescientistProofs.Spikes.ChebyshevInequality
import ClaudescientistProofs.Spikes.CauchySchwarz
import ClaudescientistProofs.Spikes.BonferroniUnion
```

再跑 `lake build`。spike 文件里凡是需要 mathlib 具名引理的位置都留了
`sorry`——这正是要交给 prover 循环去修的地方。

## 4c. 给 Lean 尝试配置预算

`prover` 代理（见 `.claude/agents/prover.md` § Budget）规定：在
`res_budget_ledger` 里没有 wallclock 配额时，拒绝启动 Lean 尝试。一次性配置：

```text
mcp__verify__budget_consume(
  scope='session',
  resource='wallclock_sec',
  amount=0,
  limit_value=3600,           # 每个 session 1 小时上限，按需调整
  window='daily'
)
```

（这是在 Claude Code 内调 MCP，不是 shell 命令。）每次 Lean 尝试 prover
会先 `budget_check`，结束后 `budget_consume` 实际 `duration_sec`。

## 5. 冒烟测试

打开 Claude Code，让 prover 验证最简单的 spike 引理：

```
@prover prove that for any two real numbers a, b: a + b = b + a (use Lean's add_comm)
```

期望流程：

1. Triage 返回 `eligible=True`（短文本、不在黑名单里）。
2. `mcp__lean__lean_verify` 接受 `theorem ex_addcomm (a b : ℝ) : a + b = b + a := add_comm a b`。
3. Prover 调 `record_lean_attempt(status='verified', ...)` + `attach_evidence(polarity='supports', ...)`。
4. cockpit 事件流出现 `lean_proof_succeeded`。

任何一步报路径或版本错误 → 看 Troubleshooting。

## 6. Spike 引理清单（P4 退出准则）

P4 阶段目标：在 30 分钟 prover 预算内验证下面 5 条至少 3 条。它们都在
mathlib 已有覆盖之内：

1. `theorem sample_mean_linearity (n : ℕ) (X : Fin n → ℝ) : (1/n : ℝ) * ∑ i, X i = ∑ i, (1/n : ℝ) * X i`
2. `theorem chebyshev_inequality {Ω : Type*} [MeasurableSpace Ω] (μ : Measure Ω) ...`（用 `MeasureTheory.meas_ge_le_variance_div`）
3. `theorem cauchy_schwarz_finite_l2 ...`（用 `inner_mul_le_norm_mul_norm`）
4. `theorem bonferroni_upper_bound (n : ℕ) (p : ℝ) : 1 - (1-p)^n ≤ n * p`
5. `theorem markov_inequality (X : ℝ → ℝ) ...`（用 `MeasureTheory.meas_ge_le_integral_div`）

具体名称取决于 mathlib 版本。起草时用 `mcp__lean__lean_leansearch` 找
当前的规范名。

### 批量验证脚本

完成 1-4c 后可以一次性走完 5 个 spike 模板，并把结果写入
`prv_lean_attempts`：

```powershell
uv run python scripts/run_spikes.py
```

行为：
- `lake` 不在 PATH 或 lake 项目未 bootstrap 时清晰报错并跳过。
- 自动把 spike 模板拷到 `ClaudescientistProofs/Spikes/`（如尚未拷贝）。
- 每个 spike `lake build` 30 分钟超时。
- 通过 `prove_mcp.tools.lean_bridge.record_lean_attempt` 记录每次尝试。
- 至少 3/5 verified 时 exit code 0（P4 退出准则）。

幂等：重跑只追加新 attempt 行，不删旧记录。

## Troubleshooting

- **"lake: command not found"** —— elan 没把自己加进 PATH。重启 shell 或手动加 `%USERPROFILE%\.elan\bin`。
- **`lake exe cache get` 慢** —— 首次正常（约 10 分钟），后续走本地缓存。
- **`lean-lsp-mcp` 启动失败** —— 检查 `LEAN_PROJECT_PATH` 指向含 `lakefile.lean` 的目录，不是它的父目录。
- **Mathlib import 报错** —— prover 调用前先跑一次 `lake build`，让 Lean 把首次依赖编译完。
- **Windows 路径含空格** —— 强烈建议用 `D:\` 下无空格的路径。mathlib 构建工具历史上对路径空格敏感。

## 为什么是 opt-in

ADR 0008 写得很清楚：Lean 是**保险层**，不是证明主干的主路。NL 工作流
（语料检索、起草、切片、诊断、修正）完全不依赖 Lean。仓库即使没装
lean-lsp-mcp，也能通过 `uv run pytest`，并能产出 reviewer 可接受的证明
manuscript（命题的 `formal_proof_status` 标 `unverified` 即可）。
Lean 是最强证据天花板，不是地板。
