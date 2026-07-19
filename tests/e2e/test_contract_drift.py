from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

MCP_RE = re.compile(r"\bmcp__([A-Za-z_][A-Za-z0-9_]*)__([A-Za-z_][A-Za-z0-9_]*)\b")
LOCAL_MCP_SERVERS = {"memory", "verify", "prove"}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _tool_sets(workspace) -> dict[str, set[str]]:
    return {
        "memory": set(workspace["memory_mcp.impl"].TOOL_NAMES),
        "verify": set(workspace["verify_mcp.impl"].TOOL_NAMES),
        "prove": set(workspace["prove_mcp.impl"].TOOL_NAMES),
    }


def test_project_version_metadata_stays_in_lockstep():
    repo = _repo_root()
    pyproject = tomllib.loads((repo / "pyproject.toml").read_text(encoding="utf-8"))
    expected = pyproject["project"]["version"]

    from claudescientist import __version__

    assert __version__ == expected
    assert f"v{expected}" in (repo / "README.md").read_text(encoding="utf-8")
    assert f"v{expected}" in (repo / "README.zh-CN.md").read_text(encoding="utf-8")
    assert f"v{expected}" in (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert f"v{expected}" in (repo / "AGENTS.zh-CN.md").read_text(encoding="utf-8")
    assert f"v{expected}" in (repo / "docs" / "tool-reference.md").read_text(
        encoding="utf-8"
    )
    assert f"v{expected}" in (repo / "docs" / "tool-reference.zh-CN.md").read_text(
        encoding="utf-8"
    )


def test_agent_and_skill_mcp_tool_mentions_resolve_to_live_tools(workspace):
    repo = _repo_root()
    known = _tool_sets(workspace)
    checked_files = [
        *sorted((repo / ".claude" / "agents").glob("*.md")),
        *sorted((repo / ".claude" / "skills").glob("*/SKILL.md")),
    ]

    unknown: list[str] = []
    for path in checked_files:
        text = path.read_text(encoding="utf-8")
        for server, tool_name in MCP_RE.findall(text):
            if server not in LOCAL_MCP_SERVERS:
                continue
            if tool_name not in known[server]:
                unknown.append(f"{path.relative_to(repo)}: mcp__{server}__{tool_name}")

    assert unknown == []


def test_agent_and_skill_mcp_server_mentions_are_registered():
    repo = _repo_root()
    settings = json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))
    registered = set(settings["mcpServers"])
    checked_files = [
        *sorted((repo / ".claude" / "agents").glob("*.md")),
        *sorted((repo / ".claude" / "skills").glob("*/SKILL.md")),
    ]

    missing: list[str] = []
    for path in checked_files:
        text = path.read_text(encoding="utf-8")
        for server, tool_name in MCP_RE.findall(text):
            if server not in registered:
                missing.append(f"{path.relative_to(repo)}: mcp__{server}__{tool_name}")

    assert missing == []


def test_external_mcp_optional_edges_are_documented():
    repo = _repo_root()
    setup_lean = (repo / "docs" / "setup-lean.md").read_text(encoding="utf-8")
    readme = (repo / "README.md").read_text(encoding="utf-8")
    settings = json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))

    assert settings["mcpServers"]["lean"]["args"] == [
        "run",
        "python",
        "scripts/lean_mcp_or_noop.py",
    ]
    assert settings["mcpServers"]["arxiv"]["args"][-1] == "arxiv-mcp-server==0.5.0"
    assert settings["mcpServers"]["openalex"]["args"][-1] == (
        "openalex-research-mcp@0.5.0"
    )
    assert "toolchain is absent" in setup_lean
    assert "npx" in readme
    assert "arxiv-mcp-server" in readme


def test_fastmcp_stdio_entrypoints_keep_startup_output_quiet():
    repo = _repo_root()
    entrypoints = [
        "src/memory_mcp/dev_server.py",
        "src/memory_mcp/server.py",
        "src/verify_mcp/dev_server.py",
        "src/verify_mcp/server.py",
        "src/prove_mcp/dev_server.py",
        "src/prove_mcp/server.py",
    ]

    for rel_path in entrypoints:
        text = (repo / rel_path).read_text(encoding="utf-8")
        assert 'mcp.run(show_banner=False, log_level="ERROR")' in text


def test_reports_directory_is_gitignored_by_default():
    repo = _repo_root()
    gitignore = (repo / ".gitignore").read_text(encoding="utf-8")

    assert "reports/" in gitignore


def test_tool_reference_lists_every_local_mcp_tool(workspace):
    repo = _repo_root()
    known = _tool_sets(workspace)
    docs = {
        "en": (repo / "docs" / "tool-reference.md").read_text(encoding="utf-8"),
        "zh": (repo / "docs" / "tool-reference.zh-CN.md").read_text(encoding="utf-8"),
    }

    missing: list[str] = []
    for lang, text in docs.items():
        for server, tool_names in known.items():
            for tool_name in sorted(tool_names):
                if tool_name not in text:
                    missing.append(f"{lang}: {server}.{tool_name}")

    assert missing == []
