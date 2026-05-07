"""Tests for scripts/lean_mcp_or_noop.py.

The wrapper auto-dispatches the lean MCP based on whether the local Lean
toolchain (elan-installed lake + lean) is discoverable. We can't exercise
the spawn path safely in unit tests (it would launch the real
lean-lsp-mcp), so we cover:

- noop path: missing toolchain -> exit 0 + clear stderr.
- detection: ``_have_lean_toolchain`` returns True iff both lake and lean
  resolve.

The actual subprocess call is mocked.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest import mock

import pytest


@pytest.fixture
def wrapper_module():
    repo_root = Path(__file__).resolve().parents[2]
    scripts_dir = repo_root / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    if "lean_mcp_or_noop" in sys.modules:
        del sys.modules["lean_mcp_or_noop"]
    return importlib.import_module("lean_mcp_or_noop")


def test_noop_when_toolchain_missing(wrapper_module, capsys):
    """If neither lake nor lean is on PATH, exit 0 with a clear message."""
    with mock.patch.object(wrapper_module.shutil, "which", return_value=None):
        rc = wrapper_module.main([])
    captured = capsys.readouterr()
    assert rc == 0
    assert "lean MCP unavailable" in captured.err
    assert "docs/setup-lean.md" in captured.err


def test_have_lean_toolchain_requires_both(wrapper_module):
    """Both lake AND lean must resolve; presence of just one is not enough."""
    # both missing
    with mock.patch.object(wrapper_module.shutil, "which", return_value=None):
        assert not wrapper_module._have_lean_toolchain()

    # only lake present
    def only_lake(name):
        return "/usr/bin/lake" if name == "lake" else None

    with mock.patch.object(wrapper_module.shutil, "which", side_effect=only_lake):
        assert not wrapper_module._have_lean_toolchain()

    # only lean present
    def only_lean(name):
        return "/usr/bin/lean" if name == "lean" else None

    with mock.patch.object(wrapper_module.shutil, "which", side_effect=only_lean):
        assert not wrapper_module._have_lean_toolchain()

    # both present
    with mock.patch.object(
        wrapper_module.shutil, "which", side_effect=lambda name: f"/usr/bin/{name}"
    ):
        assert wrapper_module._have_lean_toolchain()


def test_spawn_path_invokes_subprocess_call_on_windows(wrapper_module):
    """When toolchain is present and we're on Windows, _spawn_real_mcp uses
    subprocess.call (Windows lacks a clean exec). On POSIX it would
    os.execvp instead; we don't test that path because execvp replaces
    the test process."""
    with mock.patch.object(wrapper_module.os, "name", "nt"), mock.patch.object(
        wrapper_module.subprocess, "call", return_value=0
    ) as call_mock:
        rc = wrapper_module._spawn_real_mcp(["--foo"])
    assert rc == 0
    args = call_mock.call_args[0][0]
    assert args[:4] == ["uv", "tool", "run", "lean-lsp-mcp"]
    assert args[-1] == "--foo"


def test_main_with_explicit_argv_isolates_sys_argv(wrapper_module):
    """Passing argv explicitly should not depend on sys.argv contents."""
    sentinel_args = ["--unused-flag"]
    with mock.patch.object(wrapper_module.shutil, "which", return_value=None):
        rc = wrapper_module.main(sentinel_args)
    assert rc == 0
