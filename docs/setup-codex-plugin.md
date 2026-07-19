# Codex plugin setup

The public plugin is the portable installation path for Codex CLI and the Codex
desktop app. v5.1.2 bundles four
enabled local MCP servers, two disabled literature MCP definitions, seven
Skills, hooks, and Cockpit integration. Research state stays in the active
project.

## Install

```powershell
uv tool run --from claudescientist==5.1.2 claudescientist setup --scope user
```

Equivalent manual commands:

```powershell
codex plugin marketplace add whenpoem/aiscientist --ref v5.1.2
codex plugin add claudescientist@claudescientist
```

The public installation has two matching release artifacts: the
`claudescientist==5.1.2` Python package that runs the local MCPs and hooks, and
the `v5.1.2` Git tag that distributes the plugin. Both must exist before a new
user can install this release. During source development, pass a local
marketplace path with `--marketplace-source`; the setup command deliberately
omits Git-only `--ref` handling for local paths.

Start a new Codex task so plugin discovery and MCP startup run from a clean
session. When Codex presents the plugin-hook trust prompt, review and approve it
to enable Cockpit intervention delivery and lifecycle protections.

## Verify from any project

```powershell
uv tool run --from claudescientist==5.1.2 claudescientist doctor --workspace .
```

Doctor reports plugin state, core imports, the workspace and database path,
Cockpit monitoring, hook trust, and intervention delivery separately. An
untrusted hook state is a deliberate **monitor-only** degradation: MCP tools can
still write events and Cockpit can display them, but queued interventions cannot
enter the next Codex turn until the hooks are trusted.

## Open Cockpit

```powershell
uv tool run --from claudescientist==5.1.2 claudescientist cockpit --workspace .
uv tool run --from claudescientist==5.1.2 claudescientist cockpit --workspace . --lang zh
```

The plugin and Cockpit resolve the same workspace database. Installing the
plugin publicly does not publish research state or start a web service.

## Optional literature integrations

The plugin enables only `memory`, `verify`, `prove`, and `cockpit` by default.
v5.1.2 also provides `arxiv` and `openalex` as disabled, version-pinned MCP
servers. Enable either server from **Settings > MCP servers**, then start a new
Codex task. The equivalent user configuration in `~/.codex/config.toml` is:

```toml
[plugins."claudescientist@claudescientist".mcp_servers.arxiv]
enabled = true

[plugins."claudescientist@claudescientist".mcp_servers.openalex]
enabled = true
```

arXiv needs `uv` and downloads `arxiv-mcp-server==0.5.0` on first use.
OpenAlex needs Node.js/npm and launches
`openalex-research-mcp@0.5.0` through `npx`. Keep a server disabled if its
launcher is unavailable. Doctor reads both project-local MCPs and these plugin
overrides when reporting readiness.

Lean requires the separate steps in [setup-lean.md](setup-lean.md). External
MCPs are version-pinned so a ClaudeScientist release does not silently change
behavior.

## Project-local compatibility mode

Contributors can still run `uv run python -m claudescientist.setup` inside this
checkout. It generates `.codex/config.toml`, `.codex/agents/`, and
`.agents/skills/` for repository development. Do not copy these files into every
research repository; use the plugin for portable use.

## Update or remove

```powershell
codex plugin marketplace upgrade claudescientist
codex plugin remove claudescientist
```

After an update, start a new Codex task and rerun doctor. Removing the plugin
does not delete any project's `.research-agent/state.db`.
