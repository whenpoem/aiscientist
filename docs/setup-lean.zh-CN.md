# 开启 Lean 形式化验证

> English version: [setup-lean.md](setup-lean.md)

ClaudeScientist 的自然语言证明流程不依赖 Lean。只有需要 Lean 4 检查形式化证明时，
才需要完成本文步骤。

普通公开插件用户可以按下面的情况操作：

- 只需要证明起草、检查和修改：不需要安装 Lean，直接使用 `$prove-sop`。
- 需要 Lean 机器验证：完成第 1–4 节，然后按第 7 节测试。
- 暂时不再使用 Lean：运行 `codex mcp remove lean`，再新建 Codex 任务。

`claudescientist setup --scope user` 不会安装或注册 Lean。旧的
`claudescientist setup --scope project` 也只检查 Lean 是否存在，不会代替本文的
工具链和 mathlib 安装步骤。

Lean 支持由三个独立部分组成：

1. `elan`、`lean` 和 `lake` 提供 Lean 工具链。
2. 本地 mathlib 项目提供 Lean 使用的定义和定理。
3. `lean-lsp-mcp` 让 Codex 或 Claude Code 通过 MCP 调用 Lean。

第一次安装通常占用 2–3 GB，并需要 10–20 分钟。ClaudeScientist 的普通安装不会
自动安装这些依赖。

## 1. 安装 Lean 工具链

### Windows

在 PowerShell 中运行：

```powershell
curl -L "https://raw.githubusercontent.com/leanprover/elan/master/elan-init.ps1" -o elan-init.ps1
powershell -ExecutionPolicy Bypass -File elan-init.ps1 -y
```

关闭并重新打开 PowerShell，让 `%USERPROFILE%\.elan\bin` 加入 `PATH`。

### macOS 或 Linux

```bash
curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf | sh -s -- -y
```

检查安装：

```powershell
elan --version
lean --version
lake --version
```

三个命令都能正常运行后再继续。

## 2. 安装 Lean MCP 服务器

```powershell
uv tool install lean-lsp-mcp
uv tool run lean-lsp-mcp --help
```

第二条命令应当显示 `lean-lsp-mcp` 的参数。此时还没有把服务器注册到 Codex。

## 3. 在研究项目中创建 mathlib 项目

进入准备使用 Codex 的研究项目：

```powershell
cd D:\你的研究项目
New-Item -ItemType Directory -Force .research-agent\lean
cd .research-agent\lean
lake new claudescientist-proofs math
cd claudescientist-proofs
lake update
lake exe cache get
lake build
```

`lake exe cache get` 会下载预编译 mathlib 缓存，通常是耗时最长的一步。完成后，
`.research-agent/lean/claudescientist-proofs` 中应当存在 `lakefile.lean`。

每个需要 Lean 的研究项目可以分别建立一个 mathlib 项目。也可以共用一个 mathlib
项目，但注册 MCP 时必须使用它的完整路径。

## 4. 普通 Codex 插件用户注册 Lean

公开 ClaudeScientist 插件不会自动注册 Lean。从研究项目根目录运行：

```powershell
codex mcp add lean -- uv tool run lean-lsp-mcp --lean-project-path .research-agent/lean/claudescientist-proofs
```

检查结果：

```powershell
codex mcp list
```

列表中应当出现状态为 `enabled` 的 `lean`。然后从同一研究项目新建 Codex 任务；
已经打开的任务不会自动重新读取 MCP 配置。

注册后，从同一个研究项目新建 Codex 任务。相对路径
`--lean-project-path` 以当前研究项目为起点。如果 mathlib 项目放在其他位置，请改成
包含 `lakefile.lean` 的目录的完整路径。

这个 MCP 条目保存在用户级 Codex 配置中。如果另一个研究项目没有对应的相对路径，
请先移除 `lean` 条目，或者改成一个所有项目都能访问的完整路径。

如果已经存在路径错误的 `lean` MCP，可以删除后重新添加：

```powershell
codex mcp remove lean
codex mcp add lean -- uv tool run lean-lsp-mcp --lean-project-path D:\完整路径\claudescientist-proofs
```

如果暂时不再使用 Lean，只运行下面的命令即可：

```powershell
codex mcp remove lean
```

这只删除 Codex 中的 Lean MCP 配置，不会删除本地 mathlib 项目或已有证明记录。

## 5. 源码仓库和 Claude Code 配置

本节只适用于开发 ClaudeScientist 源码仓库的用户。

Claude Code 的 `.claude/settings.json` 已经配置
`scripts/lean_mcp_or_noop.py`。这个脚本会检查 `lake` 和 `lean`：

- 已安装时，启动 `lean-lsp-mcp`。
- 缺失时，正常退出，不让 Claude Code 任务启动失败。

安装工具链并创建 mathlib 项目后，从源码仓库根目录重新启动 Claude Code 即可。

旧的项目级设置向导会在 `.codex/config.toml` 中生成默认关闭的
`[mcp_servers.lean]`。完成第 1–3 节后，把 `enabled` 改成 `true`，再重新启动 Codex。
向导只检查 Lean 是否存在，不会安装 Lean 或 mathlib。

## 6. 设置运行时间预算

较长的 Lean 尝试应当先在验证记录中设置运行时间额度。第一次长时间运行前，请让
Codex 调用：

```text
mcp__verify__budget_consume(
  scope='session',
  resource='wallclock_sec',
  amount=0,
  limit_value=3600,
  window='daily'
)
```

这个示例为 session 范围设置每日一小时上限，可以根据任务调整。Prover 会在较长的
Lean 运行前检查预算，结束后记录实际耗时。

## 7. 在 Codex 中测试 Lean

在研究项目中新建 Codex 任务，然后输入：

```text
$prove-sop 证明实数加法满足交换律。如果命题符合条件，请使用 Lean 形式化验证。
```

形式化验证成功时，应当看到：

1. `triage_for_formalization` 判断该命题可以形式化。
2. `mcp__lean__*` 验证工具在配置的 mathlib 项目中运行。
3. `record_lean_attempt` 记录结果。
4. Cockpit 显示 Lean 尝试事件。

如果 Lean MCP 不可用，自然语言证明流程仍然可以完成，但结果必须标明尚未经过
形式化验证。

## 8. 源码仓库中的证明示例

源码仓库在 `.research-agent/lean/spikes-template/` 中提供五个 Lean 示例文件，并
提供 `scripts/run_spikes.py`。这些内容用于贡献者验证，不包含在公开 Python 包中。

源码贡献者可以把示例复制到 mathlib 项目后运行：

```powershell
uv run python scripts/run_spikes.py
```

脚本会构建各个示例，并把结果写入 `prv_lean_attempts`。普通插件用户不需要执行。

## 常见问题

- **找不到 `elan`、`lean` 或 `lake`：**关闭并重新打开终端，或者把
  `%USERPROFILE%\.elan\bin` 加入 `PATH`。
- **`lake exe cache get` 很慢：**第一次需要下载较大的 mathlib 缓存，后续会使用
  本地缓存。
- **`lean-lsp-mcp` 找不到项目：**检查 `--lean-project-path` 是否指向包含
  `lakefile.lean` 的目录。
- **Mathlib import 报错：**在 mathlib 项目中依次运行 `lake update`、
  `lake exe cache get` 和 `lake build`。
- **Codex 看不到 Lean 工具：**运行 `codex mcp list`，然后从研究项目根目录新建任务。
- **项目路径包含空格：**如果 Lean 构建报告路径错误，可以改用不含空格的短路径。

## 为什么默认不启用 Lean

语料检索、证明起草、片段划分、诊断和修正都不依赖 Lean。Lean 只为能够使用当前
mathlib 版本表达的命题增加机器验证。不开启 Lean 不影响其他证明功能。
