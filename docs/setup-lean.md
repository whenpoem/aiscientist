# Enable Lean formal verification

> 中文版本：[setup-lean.zh-CN.md](setup-lean.zh-CN.md)

ClaudeScientist's natural-language proof workflow works without Lean. Complete
this guide only when you need Lean 4 to check a formal proof.

Ordinary public-plugin users can use this rule:

- For proof drafting, checking, and correction only, use `$prove-sop` without
  installing Lean.
- For machine-checked Lean verification, complete sections 1–4 and then run the
  test in section 7.
- To stop using Lean in one workspace, run its configuration again with
  `--no-lean` and start a new Codex task.

`claudescientist setup --scope user` installs a disabled Lean MCP definition,
but it does not install the Lean toolchain, `lean-lsp-mcp`, or mathlib.

Lean support has three independent parts:

1. `elan`, `lean`, and `lake` provide the Lean toolchain.
2. A local mathlib project provides the definitions and theorems used by Lean.
3. `lean-lsp-mcp` lets Codex or Claude Code call Lean through MCP.

The first installation normally uses 2–3 GB and may take 10–20 minutes. None of
these dependencies is installed by the normal ClaudeScientist setup.

## 1. Install the Lean toolchain

### Windows

Run in PowerShell:

```powershell
curl -L "https://raw.githubusercontent.com/leanprover/elan/master/elan-init.ps1" -o elan-init.ps1
powershell -ExecutionPolicy Bypass -File elan-init.ps1 -y
```

Close and reopen PowerShell so `%USERPROFILE%\.elan\bin` is added to `PATH`.

### macOS or Linux

```bash
curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf | sh -s -- -y
```

Check the installation:

```powershell
elan --version
lean --version
lake --version
```

Do not continue until all three commands work.

## 2. Install the Lean MCP server

```powershell
uv tool install lean-lsp-mcp
uv tool run lean-lsp-mcp --help
```

The second command should print the `lean-lsp-mcp` options. This does not yet
register the server with Codex.

## 3. Create a mathlib project in the research workspace

Open PowerShell in the project where you will use Codex:

```powershell
cd D:\path\to\your-research-project
New-Item -ItemType Directory -Force .research-agent\lean
cd .research-agent\lean
lake new claudescientist-proofs math
cd claudescientist-proofs
lake update
lake exe cache get
lake build
```

`lake exe cache get` downloads the precompiled mathlib cache and is usually the
longest step. The directory
`.research-agent/lean/claudescientist-proofs` should contain `lakefile.lean`
when setup finishes.

Create one mathlib project in each research workspace that needs Lean, or use a
full path to one shared mathlib project when registering the MCP.

## 4. Configure Lean for an ordinary Codex plugin installation

Return to the research workspace root and save its Lean project path:

```powershell
claudescientist configure --workspace . --lean `
  --lean-project .research-agent\lean\claudescientist-proofs
```

Next, open Codex settings, find the ClaudeScientist plugin MCPs, and enable
`lean`. Start a new Codex task from this workspace. An already-open task does
not reload MCP configuration automatically.

The plugin starts `claudescientist mcp lean`. That command reads the current
workspace's `.research-agent/config.toml` and passes its mathlib path to
`lean-lsp-mcp`. Each workspace can therefore use a different Lean project.

Check the complete setup:

```powershell
claudescientist doctor --workspace .
codex mcp list
```

To stop using Lean in this workspace, run:

```powershell
claudescientist configure --workspace . --no-lean
```

You can also disable `lean` in the plugin MCP settings to stop it for all
workspaces. Neither action deletes the mathlib project or proof records.

## 5. Source-checkout and Claude Code configuration

This section is only for users developing the ClaudeScientist repository.

For Claude Code, `.claude/settings.json` already starts
`scripts/lean_mcp_or_noop.py`. The script checks whether `lake` and `lean` are
available:

- If they are available, it starts `lean-lsp-mcp`.
- If the toolchain is absent, it exits without making the Claude Code session
  fail.

After installing the toolchain and creating the mathlib project, restart Claude
Code from the repository root.

The `claudescientist dev-setup` wizard generates a disabled
`[mcp_servers.lean]` entry in
`.codex/config.toml` for project-local Codex development. After completing
sections 1–3, change its `enabled` value to `true` and restart Codex. The wizard
only detects the Lean toolchain; it does not install Lean or mathlib.

## 6. Configure a time budget

Long Lean attempts should have a wall-clock budget in the verification ledger.
Ask Codex to make this MCP call before the first long attempt:

```text
mcp__verify__budget_consume(
  scope='session',
  resource='wallclock_sec',
  amount=0,
  limit_value=3600,
  window='daily'
)
```

This example sets a one-hour daily limit for the session scope. Adjust the limit
to match the task. The prover checks the budget before a longer Lean run and
records the actual duration afterward.

## 7. Test Lean from Codex

Start a new Codex task in the research workspace and enter:

```text
$prove-sop Prove that addition of real numbers is commutative. Use Lean formal verification if the proposition is eligible.
```

For a successful formal verification, the expected result includes:

1. `triage_for_formalization` reports that the proposition is eligible.
2. A `mcp__lean__*` verification tool runs inside the configured mathlib project.
3. `record_lean_attempt` records the result.
4. Cockpit displays the Lean attempt event.

If the Lean MCP is unavailable, the natural-language proof workflow can still
finish, but the result must be marked as not formally verified.

## 8. Source-checkout proof examples

The repository contains five Lean example files under
`.research-agent/lean/spikes-template/`. These files and
`scripts/run_spikes.py` are contributor validation materials; they are not
included in the public Python package.

Source contributors can copy the examples into the mathlib project and run:

```powershell
uv run python scripts/run_spikes.py
```

The script builds each example and records the results in `prv_lean_attempts`.
Ordinary plugin users do not need this step.

## Troubleshooting

- **`elan`, `lean`, or `lake` is not found:** close and reopen the terminal, or
  add `%USERPROFILE%\.elan\bin` to `PATH`.
- **`lake exe cache get` is slow:** the first mathlib cache download is large.
  Later runs reuse the local cache.
- **`lean-lsp-mcp` cannot find the project:** check that
  `--lean-project-path` names the directory containing `lakefile.lean`.
- **Mathlib import errors:** run `lake update`, `lake exe cache get`, and
  `lake build` inside the mathlib project.
- **Codex does not show Lean tools:** run `codex mcp list`, then start a new
  task from the research workspace root.
- **The project path contains spaces:** try a short path without spaces if the
  Lean build reports path-related errors.

## Why Lean is optional

Corpus retrieval, proof drafting, segmentation, diagnosis, and correction do
not require Lean. Lean adds machine-checked verification for propositions that
can be expressed with the installed mathlib version. Leaving Lean disabled does
not disable the rest of the proof workflow.
