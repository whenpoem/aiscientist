# Codex installation and use

> 中文版本：[setup-codex-plugin.zh-CN.md](setup-codex-plugin.zh-CN.md)

This guide is for ordinary users of the public Codex plugin. It applies to
Codex CLI and the Codex desktop app. Source contributors should also read
[Project setup wizard](#project-setup-wizard).

ClaudeScientist has two installed parts:

- The Python package provides the `claudescientist` command, four local MCP
  backends, Doctor, and Cockpit.
- The Codex plugin provides Skills, hooks, and MCP configuration. Its source is
  fixed to the Git tag that matches the Python package version.

Research data is not stored in either installation. Each research project uses
its own `.research-agent/state.db` file.

## 1. Prerequisites

Install `uv` and Codex before installing ClaudeScientist. Check them in
PowerShell:

```powershell
uv --version
codex --version
```

The four core MCPs do not require Node.js. OpenAlex is optional and requires
Node.js/npm. Lean is also optional and has a separate setup process.

## 2. Recommended installation

Run these commands once:

```powershell
uv tool install claudescientist==5.1.3
claudescientist setup --scope user
```

The first command permanently installs the `claudescientist` command for the
current Windows user. It also installs Cockpit, Doctor, and the local MCP
backend code.

The second command asks Codex to add the ClaudeScientist marketplace at the
GitHub `v5.1.3` tag and install `claudescientist@claudescientist`. It is not an
interactive project-configuration wizard.

Check the installed Python version:

```powershell
claudescientist --version
```

Expected output:

```text
claudescientist 5.1.3
```

### One-time execution without installing the CLI

This command also installs the plugin:

```powershell
uv tool run --from claudescientist==5.1.3 claudescientist setup --scope user
```

Use it only if you do not want the `claudescientist` command to remain
installed. Later Doctor and Cockpit commands must then use the longer
`uv tool run --from ...` form.

### Manual Codex plugin installation

These commands install only the Codex plugin:

```powershell
codex plugin marketplace add whenpoem/aiscientist --ref v5.1.3
codex plugin add claudescientist@claudescientist
```

This is useful for diagnosing plugin installation. It does not permanently
install the `claudescientist` CLI, so the recommended two-command installation
is simpler for most users.

## 3. First use in a research project

Open PowerShell in the project that Codex will work on. This can be an existing
project or an empty directory. It does not need to be the ClaudeScientist source
checkout.

```powershell
cd D:\path\to\your-research-project
claudescientist doctor --workspace .
```

Doctor reports the resolved workspace, database path, plugin state, MCP
imports, Cockpit monitoring, hook trust, and intervention delivery. A warning
about hook trust is normal before the first trusted Codex task.

Start Codex from this directory:

```powershell
codex -C .
```

For the desktop app, open the same folder as the task workspace. Start a new
task after installation so Codex reloads the plugin and MCP configuration.

When Codex asks whether to trust the plugin hooks, review and approve them if
you want lifecycle checks and Cockpit intervention delivery. Without hook
trust, MCP events can still be displayed, but interventions remain
`monitor-only` and cannot enter the next Codex turn.

Open a second PowerShell window in the same project:

```powershell
cd D:\path\to\your-research-project
claudescientist cockpit --workspace .
```

For Chinese labels:

```powershell
claudescientist cockpit --workspace . --lang zh
```

The Codex task and Cockpit must use the same workspace. They then read and
write the same `.research-agent/state.db` file. Cockpit does not start a web
server and does not upload research data.

In Codex, start the full research workflow with:

```text
$research-sop investigate whether the proposed method improves the baseline
```

You can also enter `/skills` and choose a specific Skill. Codex Skills use the
`$skill-name` form. The `/research-sop` form is for Claude Code.

## 4. Optional integrations

The public plugin starts four local MCPs by default:

| MCP | Default | Purpose |
|---|---|---|
| `memory` | enabled | Research graph, evidence, comparisons, failures, and literature records |
| `verify` | enabled | Provenance, seed checks, preregistration, held-out access, and budgets |
| `prove` | enabled | Natural-language proof workflow and proof records |
| `cockpit` | enabled | Events, monitoring, and user interventions |
| `arxiv` | disabled | Search and fetch arXiv papers |
| `openalex` | disabled | Search and fetch OpenAlex records |
| `lean` | not registered by the public plugin | Optional formal verification through `lean-lsp-mcp` |

### Enable arXiv

Open **Settings > MCP servers** in Codex, enable `arxiv`, and start a new task.
The first start downloads `arxiv-mcp-server==0.5.0` through `uv`.

Equivalent plugin configuration:

```toml
[plugins."claudescientist@claudescientist".mcp_servers.arxiv]
enabled = true
```

### Enable OpenAlex

Check that Node.js/npm is available:

```powershell
npx --version
```

Then enable `openalex` under **Settings > MCP servers** and start a new task.
The plugin launches `openalex-research-mcp@0.5.0` through `npx`.

Equivalent plugin configuration:

```toml
[plugins."claudescientist@claudescientist".mcp_servers.openalex]
enabled = true
```

Keep OpenAlex disabled when `npx` is unavailable.

### Enable Lean for an ordinary plugin installation

The natural-language proof workflow works without Lean. Enable Lean only when
you need machine-checked Lean 4 verification. The public plugin does not
register this third-party MCP automatically because Lean, mathlib, and the
project cache require a separate multi-gigabyte installation.

Complete these steps:

1. Install `elan`, Lean, `lake`, and a mathlib project by following
   [setup-lean.md](setup-lean.md).
2. Create the mathlib project inside each research workspace at
   `.research-agent/lean/claudescientist-proofs`.
3. From the research workspace root, register the Lean MCP:

```powershell
codex mcp add lean -- uv tool run lean-lsp-mcp --lean-project-path .research-agent/lean/claudescientist-proofs
```

4. Start a new Codex task from that workspace and confirm that `lean` appears
   in the MCP list.

Run the following command to check. A working entry should show `lean` as
`enabled`:

```powershell
codex mcp list
```

Then test it in a new task:

```text
$prove-sop Prove that addition of real numbers is commutative. Use Lean formal verification if the proposition is eligible.
```

The relative path is resolved from the active research workspace. If you keep
the Lean project elsewhere, replace it with the full path to the directory that
contains `lakefile.lean`.

Long Lean runs should have a wall-clock budget in the verification ledger. The
Lean guide shows the budget MCP call and a small verification test.

To stop using Lean, run `codex mcp remove lean` and start a new Codex task. This
does not delete the local mathlib project or existing proof records.

## 5. Project setup wizard

ClaudeScientist has two setup commands with different purposes:

| Command | Intended user | What it changes |
|---|---|---|
| `claudescientist setup --scope user` | Ordinary Codex plugin user | Installs the version-matched marketplace and public plugin in the user's Codex configuration |
| `claudescientist setup --scope project` | Source contributor or project-local Claude Code/Codex developer | Runs the older eight-step source-checkout wizard and writes local development files |

The project wizard checks for `pyproject.toml` and `.claude/`, so it is intended
to run from a ClaudeScientist source checkout. It can:

1. Check Python, `uv`, Claude Code, Codex, and `npx`.
2. Select Claude Code, Codex, or both as the development host.
3. Generate project-local `.codex/config.toml`, agent definitions, and Skills.
4. Choose an embedding backend and write the result to `.env`.
5. Install optional proof dependencies and seed the bundled proof corpus.
6. Set the held-out dataset directory.
7. Detect an existing Lean toolchain. It reports the result but does not install Lean.
8. Configure whether automatic branch pausing stays advisory or is enabled.

Run it only when developing this repository or when using the checked-in Claude
Code configuration:

```powershell
git clone https://github.com/whenpoem/aiscientist.git
cd aiscientist
uv sync
uv run python -m claudescientist.setup
```

Ordinary portable-plugin users should not run the project wizard in each
research project. It creates a second project-local Codex configuration and can
make it unclear whether Codex is using the plugin or the generated local files.

## 6. Check an installation

Run Doctor from the research workspace:

```powershell
claudescientist doctor --workspace .
```

Also check the Codex plugin and MCP lists when needed:

```powershell
codex plugin list --json
codex mcp list
```

Common results:

- `arxiv` or `openalex` disabled: normal until you enable that optional server.
- Cockpit `monitor-only`: hooks are not trusted in the current Codex task.
- Empty Cockpit: no events have been written in this workspace yet, or Codex
  and Cockpit were started with different workspace paths.
- Skill missing after installation: start a new Codex task so plugin discovery
  runs again.

## 7. Update

The marketplace is fixed to a release tag, so a normal marketplace refresh
stays on the same version. To move to a newer ClaudeScientist release, upgrade
the Python command, remove the old plugin source, and run user setup again:

```powershell
uv tool upgrade claudescientist
codex plugin remove claudescientist
codex plugin marketplace remove claudescientist
claudescientist setup --scope user
```

This does not delete research databases. Start a new Codex task and run Doctor
again after the update. User setup reads the newly installed Python version and
selects the matching Git tag.

## 8. Remove

```powershell
codex plugin remove claudescientist
uv tool uninstall claudescientist
```

Removing the program does not delete `.research-agent/state.db` or generated
reports from existing research projects.
