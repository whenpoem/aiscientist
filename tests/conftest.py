from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RESEARCH_AGENT_STATE_DIR", str(tmp_path / ".research-agent"))
    module_names = [
        "memory_mcp.db",
        "memory_mcp.impl",
        "verify_mcp.db",
        # heldout reload order (v3.1): db -> heldout -> heldout_cli -> impl,
        # then claudescientist.heldout last so its lazy wrapper sees fresh
        # verify_mcp.heldout_cli on its next call.
        "verify_mcp.heldout",
        "verify_mcp.heldout_cli",
        "verify_mcp.impl",
        "claudescientist.heldout",
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
