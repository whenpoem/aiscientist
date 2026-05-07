from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RESEARCH_AGENT_STATE_DIR", str(tmp_path / ".research-agent"))
    # Pin the cockpit user-settings file inside tmp_path so test runs cannot
    # write to (or read from) the developer's real ~/.config dir.
    monkeypatch.setenv(
        "RESEARCH_AGENT_COCKPIT_CONFIG", str(tmp_path / "cockpit.toml")
    )
    # Tests run under the deterministic mock embedding backend so they need
    # neither sentence-transformers nor an OPENAI_API_KEY. The live MCP server
    # defaults to the 'local' backend (sentence-transformers); install via
    # `uv sync --extra proof`. See ADR 0008 + prove_mcp/embedding.py for the
    # available backends.
    monkeypatch.setenv("RESEARCH_AGENT_EMBED_BACKEND", "mock")
    module_names = [
        "memory_mcp.db",
        "memory_mcp.tools._common",
        "memory_mcp.tools.bt",
        "memory_mcp.tools.calibration",
        "memory_mcp.tools.failures",
        "memory_mcp.tools.graph",
        "memory_mcp.tools.literature",
        "memory_mcp.tools.replay",
        "memory_mcp.impl",
        "verify_mcp.db",
        # Reload pure claudescientist helpers before verify-side modules
        # that bind their functions at import time.
        "claudescientist.heldout",
        "verify_mcp.heldout",
        "verify_mcp.heldout_cli",
        "verify_mcp.tools._common",
        "verify_mcp.tools.budget",
        "verify_mcp.tools.heldout",
        "verify_mcp.tools.leakage",
        "verify_mcp.tools.prereg",
        "verify_mcp.tools.provenance",
        "verify_mcp.tools.verification",
        "verify_mcp.impl",
        "prove_mcp.db",
        "prove_mcp.embedding",
        "prove_mcp.tools._common",
        "prove_mcp.tools.corpus",
        "prove_mcp.tools.retrieval",
        "prove_mcp.tools.nodes",
        "prove_mcp.tools.segmentation",
        "prove_mcp.tools.diagnosis",
        "prove_mcp.tools.correction",
        "prove_mcp.tools.lean_bridge",
        "prove_mcp.impl",
        "cockpit.db",
    ]
    optional_modules = [
        "cockpit.data",
        "cockpit.app",
        "cockpit.mcp_server",
    ]

    loaded = {
        name: importlib.reload(importlib.import_module(name))
        for name in module_names
    }
    for name in optional_modules:
        try:
            loaded[name] = importlib.reload(importlib.import_module(name))
        except ModuleNotFoundError:
            continue
    loaded["cockpit.db"].ensure()
    return loaded
