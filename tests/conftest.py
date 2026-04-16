from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return {
        name: importlib.reload(importlib.import_module(name))
        for name in [
            "memory_mcp.db",
            "memory_mcp.impl",
            "verify_mcp.db",
            "verify_mcp.impl",
            "cockpit.db",
            "cockpit.server",
        ]
    }
