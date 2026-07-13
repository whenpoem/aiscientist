# Codex plugin setup

The public plugin is the portable installation path for Codex CLI and the Codex
desktop app. It bundles ClaudeScientist's four local MCP servers, seven Skills,
hooks, and Cockpit integration. Research state stays in the active project.

## Install

```powershell
uv tool run --from claudescientist==5.1.0 claudescientist setup --scope user
```

Equivalent manual commands:

```powershell
codex plugin marketplace add whenpoem/aiscientist --ref v5.1.0
codex plugin add claudescientist@claudescientist
```

The public installation has two matching release artifacts: the
`claudescientist==5.1.0` Python package that runs the local MCPs and hooks, and
the `v5.1.0` Git tag that distributes the plugin. Both must exist before a new
user can install this release. During source development, pass a local
marketplace path with `--marketplace-source`; the setup command deliberately
omits Git-only `--ref` handling for local paths.

Start a new Codex task so plugin discovery and MCP startup run from a clean
session. When Codex presents the plugin-hook trust prompt, review and approve it
to enable Cockpit intervention delivery and lifecycle protections.

## Verify from any project

```powershell
uv tool run --from claudescientist==5.1.0 claudescientist doctor --workspace .
```

Doctor reports plugin state, core imports, the workspace and database path,
Cockpit monitoring, hook trust, and intervention delivery separately. An
untrusted hook state is a deliberate **monitor-only** degradation: MCP tools can
still write events and Cockpit can display them, but queued interventions cannot
enter the next Codex turn until the hooks are trusted.

## Open Cockpit

```powershell
uv tool run --from claudescientist==5.1.0 claudescientist cockpit --workspace .
uv tool run --from claudescientist==5.1.0 claudescientist cockpit --workspace . --lang zh
```

The plugin and Cockpit resolve the same workspace database. Installing the
plugin publicly does not publish research state or start a web service.

## Optional integrations

The public plugin enables only `memory`, `verify`, `prove`, and `cockpit`.

```powershell
codex mcp add arxiv -- uv tool run arxiv-mcp-server==0.5.0
codex mcp add openalex -- npx -y openalex-research-mcp@0.5.0
```

Lean requires the steps in [setup-lean.md](setup-lean.md). External MCPs are
version-pinned so a ClaudeScientist release does not silently change behavior.

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
