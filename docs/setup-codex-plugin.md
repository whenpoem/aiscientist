# Codex installation and use

> Chinese version: [setup-codex-plugin.zh-CN.md](setup-codex-plugin.zh-CN.md)

This guide is for ordinary users of the public Codex plugin. Source
contributors should use the separate development command described near the
end of this page.

ClaudeScientist has two installed parts:

- The Python package provides the `claudescientist` command, MCP backends,
  Doctor, Cockpit, and the workspace configuration command.
- The Codex plugin provides Skills, hooks, and MCP launch definitions.

Each research project stores its own configuration and state under
`.research-agent/`. The installed package and plugin do not own research data.

## 1. Install the package and plugin

Install [uv](https://docs.astral.sh/uv/) and Codex first. Check both commands:

```powershell
uv --version
codex --version
```

Then run:

```powershell
uv tool install claudescientist==5.1.4
claudescientist setup --scope user
```

The first command installs the CLI for the current operating-system user. The
second command installs the public Codex plugin from the matching Git tag. Run
these two commands once per computer, not once per research project.

Check the installed version:

```powershell
claudescientist --version
```

Expected output:

```text
claudescientist 5.1.4
```

Manual plugin installation is also possible:

```powershell
codex plugin marketplace add whenpoem/aiscientist --ref v5.1.4
codex plugin add claudescientist@claudescientist
```

Manual plugin installation does not install the `claudescientist` CLI. The
two-command installation above is therefore the normal path.

## 2. Configure each research project

Open a terminal in the research project and run:

```powershell
cd D:\path\to\your-research-project
claudescientist configure --workspace .
```

This command creates:

```text
.research-agent/config.toml
```

The interactive configuration covers:

1. Embedding backend and model for proof-corpus retrieval.
2. Held-out dataset directory.
3. Whether low-strength branches may be paused automatically.
4. Whether this workspace uses optional Lean verification and, if so, the
   mathlib project path.

The file contains only non-secret settings. Do not put API keys in it. For an
OpenAI-compatible embedding service, set `OPENAI_API_KEY` in the shell or the
operating system's credential environment before starting Codex.

The command can be run again safely. Existing answers are used as defaults.
For automation, use explicit non-interactive options, for example:

```powershell
claudescientist configure --workspace . --non-interactive `
  --embedding-backend mock `
  --heldout-dir D:\research-heldout `
  --no-auto-prune `
  --no-lean
```

Explicit environment variables still take priority over the project file.
This allows a temporary override without editing `config.toml`.

## 3. Start Codex, Doctor, and Cockpit

After installation or configuration, start a new Codex task from the research
project so Codex reloads the plugin, MCP definitions, and hooks:

```powershell
codex -C .
```

In the desktop app, open the same project folder as the task workspace.

When Codex asks whether to trust the plugin hooks, review the request and
approve it if you want lifecycle checks and Cockpit intervention delivery.
Without hook trust, MCP monitoring still works, but Cockpit interventions stay
in monitor-only mode.

Check the setup from the project directory:

```powershell
claudescientist doctor --workspace .
```

Doctor reports the selected workspace, project configuration, database path,
plugin state, hook trust, optional MCP state, embedding backend, and Lean
readiness.

Open Cockpit in a second terminal:

```powershell
claudescientist cockpit --workspace .
```

For Chinese labels:

```powershell
claudescientist cockpit --workspace . --lang zh
```

Codex and Cockpit must use the same workspace. They then share
`.research-agent/state.db`. Cockpit is a local terminal application and does
not upload the database.

Start the full workflow in Codex with:

```text
$research-sop investigate whether the proposed method improves the baseline
```

You can also enter `/skills` and select a specific Skill.

## 4. What is configured where

| Setting | Where it is configured | Scope |
|---|---|---|
| Plugin installation | `claudescientist setup --scope user` | One operating-system user |
| Embedding, held-out directory, auto-prune, Lean project | `claudescientist configure --workspace .` | One research project |
| arXiv, OpenAlex, and Lean MCP enabled state | Codex plugin/MCP settings | Codex user |
| API keys | Shell or operating-system environment | Current process or user |
| Research records | `.research-agent/state.db` | One research project |
| Cockpit language/theme | Cockpit command options | Current launch |

The project configuration is loaded automatically before ClaudeScientist
starts a core MCP, a hook, Doctor, or Cockpit. You do not need to load a `.env`
file manually.

## 5. Optional MCPs

The public plugin enables four local MCPs by default and includes three
optional MCPs in the disabled state:

| MCP | Default | Purpose |
|---|---|---|
| `memory` | enabled | Research graph, evidence, comparisons, failures, and literature records |
| `verify` | enabled | Provenance, seed checks, preregistration, held-out access, and budgets |
| `prove` | enabled | Natural-language proof workflow and proof records |
| `cockpit` | enabled | Events, monitoring, and user interventions |
| `arxiv` | disabled | Search and fetch arXiv papers |
| `openalex` | disabled | Search and fetch OpenAlex records |
| `lean` | disabled | Optional machine-checked Lean verification |

### arXiv

Open Codex settings, find the ClaudeScientist plugin MCPs, enable `arxiv`, and
start a new task. The first launch downloads
`arxiv-mcp-server==0.5.0` through `uv`.

Equivalent user configuration:

```toml
[plugins."claudescientist@claudescientist".mcp_servers.arxiv]
enabled = true
```

### OpenAlex

OpenAlex needs Node.js and npm. Check `npx` first:

```powershell
npx --version
```

Enable `openalex` in the ClaudeScientist plugin MCP settings and start a new
task. Leave it disabled if `npx` is unavailable.

Equivalent user configuration:

```toml
[plugins."claudescientist@claudescientist".mcp_servers.openalex]
enabled = true
```

### Lean

Natural-language proof drafting and checking do not require Lean. To add
machine verification:

1. Install `elan`, Lean, `lake`, `lean-lsp-mcp`, and create a mathlib project
   by following [setup-lean.md](setup-lean.md).
2. Run the workspace configuration again:

   ```powershell
   claudescientist configure --workspace . --lean `
     --lean-project .research-agent\lean\claudescientist-proofs
   ```

3. Enable `lean` in the ClaudeScientist plugin MCP settings.
4. Start a new Codex task and run `claudescientist doctor --workspace .`.

The plugin starts Lean through the ClaudeScientist CLI, which reads the mathlib
path from the current workspace configuration. Different research projects can
therefore use different Lean projects without repeatedly replacing one global
MCP command.

To stop using Lean in one project, run the configuration command again with
`--no-lean`. You may also disable the Lean MCP globally in Codex settings.

## 6. Held-out data

The configuration command selects the directory in which sequestered datasets
are kept. Register a dataset with:

```powershell
uv tool run --from claudescientist==5.1.4 python -m claudescientist.heldout `
  register <name> <path>
```

Registration moves the source data into the held-out directory; it does not
make a second copy. Back up important data before registering it. After
registration, agents should use the `query_heldout` verification tool instead
of reading the files directly.

## 7. Source contributors

The old project setup wizard is now exposed as:

```powershell
git clone https://github.com/whenpoem/aiscientist.git
cd aiscientist
uv sync
uv run claudescientist dev-setup
```

It is only for developing this source checkout. It checks development tools,
generates project-local Claude Code/Codex adapter files, writes the checkout's
`.env`, installs optional proof dependencies, and can seed the bundled proof
corpus.

`claudescientist setup --scope project` remains as a temporary compatibility
alias. It prints a deprecation warning and runs `dev-setup`. Ordinary plugin
users should not use either command in their research projects.

## 8. Update or uninstall

Upgrade the Python package, replace the pinned plugin marketplace, and install
the matching plugin again:

```powershell
uv tool upgrade claudescientist
codex plugin remove claudescientist
codex plugin marketplace remove claudescientist
claudescientist setup --scope user
```

Existing `.research-agent/config.toml` and `.research-agent/state.db` files are
not removed.

To uninstall the program and plugin:

```powershell
codex plugin remove claudescientist
uv tool uninstall claudescientist
```

This also leaves existing research-project data in place.

## 9. Common checks

- `workspace_configuration: degraded`: run
  `claudescientist configure --workspace .` in the research project.
- `monitor-only`: trust the plugin hooks, then start a new Codex task.
- arXiv or OpenAlex is disabled: normal until that source is needed.
- Lean is degraded: check the toolchain, `lakefile.lean`, workspace setting,
  and plugin MCP enabled state.
- Cockpit is empty: check that Codex and Cockpit use the same workspace.
- Skills are missing after installation: start a new Codex task so plugin
  discovery runs again.
