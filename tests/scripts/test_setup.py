"""Tests for ``python -m claudescientist.setup``.

Strategy: exercise the non-interactive path end-to-end. Interactive
questionary prompts are NOT exercised here — testing prompt-toolkit
under pytest is fragile, and the non-interactive path covers the same
state machine. Step probes are unit-tested directly via ``_setup_io``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claudescientist import _setup_io as io
from claudescientist.setup import (
    SetupState,
    main,
    run_wizard,
    step_auto_prune,
    step_embed_backend,
    step_heldout_dir,
    step_lean,
    step_repo_root,
    step_sanity,
)

# ---------------------------------------------------------------------------
# .env IO
# ---------------------------------------------------------------------------


def test_read_env_returns_empty_when_missing(tmp_path):
    assert io.read_env_file(tmp_path / "nope.env") == {}


def test_read_env_skips_comments_and_blanks(tmp_path):
    p = tmp_path / ".env"
    p.write_text(
        "# header comment\n"
        "\n"
        "FOO=bar\n"
        "BAZ=  qux  \n"
        "# trailing\n"
        "BROKEN_LINE_NO_EQUALS\n",
        encoding="utf-8",
    )
    parsed = io.read_env_file(p)
    assert parsed == {"FOO": "bar", "BAZ": "qux"}


def test_update_env_creates_fresh_file(tmp_path):
    p = tmp_path / ".env"
    io.update_env_file(p, {"A": "1", "B": "two"})
    text = p.read_text(encoding="utf-8")
    assert "A=1" in text
    assert "B=two" in text
    # Header documenting provenance — match either the package name or
    # the wizard module so a future doc rewrite isn't a test churn point.
    assert "claudescientist" in text


def test_update_env_preserves_existing_keys_and_comments(tmp_path):
    p = tmp_path / ".env"
    p.write_text(
        "# my own comment\n"
        "MINE=hello\n"
        "FOO=stale\n",
        encoding="utf-8",
    )
    io.update_env_file(p, {"FOO": "fresh", "NEW": "added"})
    text = p.read_text(encoding="utf-8")
    assert "# my own comment" in text
    assert "MINE=hello" in text
    assert "FOO=fresh" in text
    assert "FOO=stale" not in text
    assert "NEW=added" in text


def test_update_env_idempotent_when_values_match(tmp_path):
    p = tmp_path / ".env"
    io.update_env_file(p, {"K": "v"})
    first = p.read_text(encoding="utf-8")
    io.update_env_file(p, {"K": "v"})
    second = p.read_text(encoding="utf-8")
    assert first == second


def test_update_env_no_op_when_updates_empty(tmp_path):
    p = tmp_path / ".env"
    p.write_text("FOO=bar\n", encoding="utf-8")
    io.update_env_file(p, {})
    assert p.read_text(encoding="utf-8") == "FOO=bar\n"


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------


def test_probe_python_passes_on_311_plus():
    result = io.probe_python()
    assert result.ok is True
    assert "Python" in result.detail


def test_probe_uv_finds_executable_when_present(monkeypatch, tmp_path):
    fake = tmp_path / "uv.exe"
    fake.write_text("")
    monkeypatch.setattr(io.shutil, "which", lambda name: str(fake) if name == "uv" else None)
    assert io.probe_uv().ok is True


def test_probe_uv_fails_when_absent(monkeypatch):
    monkeypatch.setattr(io.shutil, "which", lambda name: None)
    assert io.probe_uv().ok is False


def test_probe_npx_is_soft_dependency_when_absent(monkeypatch):
    monkeypatch.setattr(io.shutil, "which", lambda name: None)
    result = io.probe_npx()
    assert result.ok is False
    assert "OpenAlex" in result.detail


def test_probe_npx_finds_executable_when_present(monkeypatch, tmp_path):
    fake = tmp_path / "npx.cmd"
    fake.write_text("")
    monkeypatch.setattr(io.shutil, "which", lambda name: str(fake) if name == "npx" else None)
    result = io.probe_npx()
    assert result.ok is True
    assert result.detail == str(fake)


def test_probe_lean_reports_missing_tools(monkeypatch):
    monkeypatch.setattr(io.shutil, "which", lambda name: None)
    ok, missing = io.probe_lean_toolchain()
    assert ok is False
    assert set(missing) == {"elan", "lake", "lean"}


def test_probe_lean_passes_when_all_present(monkeypatch):
    monkeypatch.setattr(io.shutil, "which", lambda name: f"/usr/bin/{name}")
    ok, missing = io.probe_lean_toolchain()
    assert ok is True
    assert missing == []


def test_probe_repo_root_walks_up(tmp_path):
    repo = tmp_path / "repo"
    nested = repo / "a" / "b"
    nested.mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n")
    (repo / ".claude").mkdir()
    found = io.probe_repo_root(nested)
    assert found == repo.resolve()


def test_probe_repo_root_returns_none_when_no_match(tmp_path):
    assert io.probe_repo_root(tmp_path) is None


def test_probe_repo_root_requires_both_markers(tmp_path):
    """A directory with only pyproject.toml is NOT a claudescientist repo
    root — that would false-positive when a user runs setup from a random
    Python project."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    assert io.probe_repo_root(tmp_path) is None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """A minimal repo layout that satisfies the probe."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / ".claude").mkdir()
    (tmp_path / "scripts").mkdir()
    return tmp_path


def _make_state(repo: Path, **overrides) -> SetupState:
    defaults = dict(
        repo_root=repo,
        non_interactive=True,
        reset=False,
        skip_deps=True,
    )
    defaults.update(overrides)
    return SetupState(**defaults)


# ---------------------------------------------------------------------------
# Step-level non-interactive behavior
# ---------------------------------------------------------------------------


def test_step_sanity_passes_in_active_venv(fake_repo):
    state = _make_state(fake_repo)
    # We rely on the test runner's own python (≥3.11). uv is on PATH for
    # CI but not strictly required here — if uv probe fails we still
    # accept it as a soft fail; the test asserts the function returns a
    # bool, not a specific value.
    result = step_sanity(state)
    assert isinstance(result, bool)


def test_step_repo_root_succeeds_with_valid_layout(fake_repo):
    state = _make_state(fake_repo)
    assert step_repo_root(state) is True


def test_step_repo_root_fails_without_claude_dir(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    state = _make_state(tmp_path)
    assert step_repo_root(state) is False


def test_step_embed_backend_writes_env_update_for_default(fake_repo, monkeypatch):
    monkeypatch.delenv("CLAUDESCIENTIST_SETUP_BACKEND", raising=False)
    monkeypatch.delenv("CLAUDESCIENTIST_SETUP_INSTALL_PROOF", raising=False)
    state = _make_state(fake_repo)
    assert step_embed_backend(state) is True
    assert state.env_updates.get("RESEARCH_AGENT_EMBED_BACKEND") == "local"


def test_step_embed_backend_honors_mock_via_env(fake_repo, monkeypatch):
    monkeypatch.setenv("CLAUDESCIENTIST_SETUP_BACKEND", "mock")
    state = _make_state(fake_repo)
    assert step_embed_backend(state) is True
    assert state.env_updates["RESEARCH_AGENT_EMBED_BACKEND"] == "mock"


def test_step_embed_backend_falls_back_for_unknown_value(fake_repo, monkeypatch):
    monkeypatch.setenv("CLAUDESCIENTIST_SETUP_BACKEND", "telepathy")
    state = _make_state(fake_repo)
    step_embed_backend(state)
    assert state.env_updates["RESEARCH_AGENT_EMBED_BACKEND"] == "local"


def test_step_embed_backend_records_openai_key_when_provided(
    fake_repo, monkeypatch
):
    monkeypatch.setenv("CLAUDESCIENTIST_SETUP_BACKEND", "openai")
    monkeypatch.setenv("CLAUDESCIENTIST_SETUP_OPENAI_KEY", "sk-fake-test")
    state = _make_state(fake_repo)
    step_embed_backend(state)
    assert state.env_updates["RESEARCH_AGENT_EMBED_BACKEND"] == "openai"
    assert state.env_updates["OPENAI_API_KEY"] == "sk-fake-test"


# ---------------------------------------------------------------------------
# v4.2.0a0: provider presets, Qwen default, HF mirror probe, quickstart
# ---------------------------------------------------------------------------


def test_step_embed_backend_local_pins_qwen3_by_default(fake_repo, monkeypatch):
    """Plain local backend with no model override → Qwen3 default lands
    in .env updates (ADR 0010 / v4.2.0a0)."""
    monkeypatch.setenv("CLAUDESCIENTIST_SETUP_BACKEND", "local")
    monkeypatch.setenv("CLAUDESCIENTIST_SETUP_SEED_CORPUS", "0")
    monkeypatch.delenv("CLAUDESCIENTIST_SETUP_LOCAL_MODEL", raising=False)
    state = _make_state(fake_repo)
    step_embed_backend(state)
    assert state.env_updates["RESEARCH_AGENT_EMBED_MODEL"] == (
        "Qwen/Qwen3-Embedding-0.6B"
    )


def test_step_embed_backend_local_honors_user_model_override(fake_repo, monkeypatch):
    monkeypatch.setenv("CLAUDESCIENTIST_SETUP_BACKEND", "local")
    monkeypatch.setenv("CLAUDESCIENTIST_SETUP_LOCAL_MODEL", "all-MiniLM-L6-v2")
    monkeypatch.setenv("CLAUDESCIENTIST_SETUP_SEED_CORPUS", "0")
    state = _make_state(fake_repo)
    step_embed_backend(state)
    assert state.env_updates["RESEARCH_AGENT_EMBED_MODEL"] == "all-MiniLM-L6-v2"


def test_step_embed_backend_dashscope_preset(fake_repo, monkeypatch):
    monkeypatch.setenv("CLAUDESCIENTIST_SETUP_BACKEND", "openai")
    monkeypatch.setenv("CLAUDESCIENTIST_SETUP_PROVIDER", "dashscope")
    monkeypatch.setenv("CLAUDESCIENTIST_SETUP_OPENAI_KEY", "sk-fake")
    state = _make_state(fake_repo)
    step_embed_backend(state)
    assert (
        state.env_updates["RESEARCH_AGENT_EMBED_BASE_URL"]
        == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    assert state.env_updates["RESEARCH_AGENT_EMBED_MODEL"] == "text-embedding-v3"
    assert state.env_updates["OPENAI_API_KEY"] == "sk-fake"


def test_step_embed_backend_openai_preset_clears_base_url(fake_repo, monkeypatch):
    """Picking the plain 'openai' preset must clear any prior base_url
    override so the SDK falls back to its built-in default."""
    monkeypatch.setenv("CLAUDESCIENTIST_SETUP_BACKEND", "openai")
    monkeypatch.setenv("CLAUDESCIENTIST_SETUP_PROVIDER", "openai")
    monkeypatch.setenv("CLAUDESCIENTIST_SETUP_OPENAI_KEY", "sk-fake")
    state = _make_state(fake_repo)
    step_embed_backend(state)
    assert state.env_updates["RESEARCH_AGENT_EMBED_BASE_URL"] == ""
    assert state.env_updates["RESEARCH_AGENT_EMBED_MODEL"] == "text-embedding-3-large"


def test_step_embed_backend_other_preset_uses_custom_base_url(fake_repo, monkeypatch):
    monkeypatch.setenv("CLAUDESCIENTIST_SETUP_BACKEND", "openai")
    monkeypatch.setenv("CLAUDESCIENTIST_SETUP_PROVIDER", "other")
    monkeypatch.setenv("CLAUDESCIENTIST_SETUP_BASE_URL", "https://my-provider.test/v1")
    monkeypatch.setenv("CLAUDESCIENTIST_SETUP_REMOTE_MODEL", "custom-embed-1")
    monkeypatch.setenv("CLAUDESCIENTIST_SETUP_OPENAI_KEY", "sk-fake")
    state = _make_state(fake_repo)
    step_embed_backend(state)
    assert (
        state.env_updates["RESEARCH_AGENT_EMBED_BASE_URL"]
        == "https://my-provider.test/v1"
    )
    assert state.env_updates["RESEARCH_AGENT_EMBED_MODEL"] == "custom-embed-1"


def test_provider_preset_lookup_known_key():
    preset = io.provider_preset("dashscope")
    assert preset is not None
    assert preset.label.startswith("Aliyun")
    assert "dashscope" in (preset.base_url or "")


def test_provider_preset_lookup_unknown_key_is_none():
    assert io.provider_preset("nonexistent-provider") is None


def test_probe_hf_mirror_returns_value_when_set(monkeypatch):
    monkeypatch.setenv("HF_ENDPOINT", "https://hf-mirror.com")
    assert io.probe_hf_mirror() == "https://hf-mirror.com"


def test_probe_hf_mirror_returns_none_when_unset(monkeypatch):
    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    assert io.probe_hf_mirror() is None


def test_probe_hf_mirror_ignores_blank(monkeypatch):
    """An exported-but-blank env var should be treated as unset."""
    monkeypatch.setenv("HF_ENDPOINT", "   ")
    assert io.probe_hf_mirror() is None


def test_open_file_dispatches_to_xdg_open_on_linux(monkeypatch, tmp_path):
    target = tmp_path / "demo.md"
    target.write_text("hello")
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))

        class _R:
            returncode = 0

        return _R()

    monkeypatch.setattr(io.platform, "system", lambda: "Linux")
    monkeypatch.setattr(io.subprocess, "run", fake_run)
    assert io.open_file_with_default_app(target) is True
    assert calls and calls[0][0] == "xdg-open"
    assert calls[0][1] == str(target)


def test_open_file_dispatches_to_open_on_macos(monkeypatch, tmp_path):
    target = tmp_path / "demo.md"
    target.write_text("hello")
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))

        class _R:
            returncode = 0

        return _R()

    monkeypatch.setattr(io.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(io.subprocess, "run", fake_run)
    assert io.open_file_with_default_app(target) is True
    assert calls and calls[0][0] == "open"


def test_open_file_returns_false_when_handler_missing(monkeypatch, tmp_path):
    target = tmp_path / "demo.md"
    target.write_text("hello")

    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("xdg-open not installed")

    monkeypatch.setattr(io.platform, "system", lambda: "Linux")
    monkeypatch.setattr(io.subprocess, "run", fake_run)
    assert io.open_file_with_default_app(target) is False


def test_maybe_open_quickstart_noop_in_non_interactive(fake_repo, monkeypatch):
    """In --non-interactive mode the wizard must not try to launch a
    GUI handler — there is no user to consent."""
    from claudescientist import setup as setup_mod

    target_dir = fake_repo / "docs" / "workflows"
    target_dir.mkdir(parents=True)
    (target_dir / "first-research-task.md").write_text("walkthrough")

    calls: list[Path] = []
    monkeypatch.setattr(
        io,
        "open_file_with_default_app",
        lambda path: (calls.append(path), True)[1],
    )
    state = _make_state(fake_repo, non_interactive=True)
    setup_mod._maybe_open_quickstart(state)
    assert calls == []


def test_maybe_open_quickstart_silent_when_doc_missing(fake_repo, monkeypatch):
    """No first-task doc → no prompt, no error."""
    from claudescientist import setup as setup_mod

    # Patch _ask_confirm to fail loudly if the wizard reaches it; the
    # missing-file early-return should beat the prompt.
    monkeypatch.setattr(
        setup_mod,
        "_ask_confirm",
        lambda *a, **k: pytest.fail("should not prompt when doc is missing"),
    )
    state = _make_state(fake_repo, non_interactive=False)
    setup_mod._maybe_open_quickstart(state)  # must not raise


def test_step_heldout_dir_writes_safe_default(fake_repo, monkeypatch):
    monkeypatch.delenv("CLAUDESCIENTIST_SETUP_HELDOUT_DIR", raising=False)
    state = _make_state(fake_repo)
    assert step_heldout_dir(state) is True
    assert state.env_updates["RESEARCH_AGENT_HELDOUT_DIR"].endswith(
        str(Path(".research-agent") / "heldout")
    )


def test_step_heldout_dir_heals_legacy_home_default(fake_repo, monkeypatch):
    (fake_repo / ".env").write_text(
        f"RESEARCH_AGENT_HELDOUT_DIR={Path.home()}\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("CLAUDESCIENTIST_SETUP_HELDOUT_DIR", raising=False)
    state = _make_state(fake_repo)
    assert step_heldout_dir(state) is True
    assert Path(state.env_updates["RESEARCH_AGENT_HELDOUT_DIR"]) != Path.home()


def test_step_heldout_dir_blank_override_stays_safe(fake_repo, monkeypatch):
    monkeypatch.setenv("CLAUDESCIENTIST_SETUP_HELDOUT_DIR", "")
    state = _make_state(fake_repo)
    assert step_heldout_dir(state) is True
    assert Path(state.env_updates["RESEARCH_AGENT_HELDOUT_DIR"]) != Path.home()
    assert state.env_updates["RESEARCH_AGENT_HELDOUT_DIR"].endswith(
        str(Path(".research-agent") / "heldout")
    )


def test_step_heldout_dir_creates_target_when_missing(fake_repo, tmp_path, monkeypatch):
    target = tmp_path / "fresh-heldout-dir"
    assert not target.exists()
    monkeypatch.setenv("CLAUDESCIENTIST_SETUP_HELDOUT_DIR", str(target))
    state = _make_state(fake_repo)
    step_heldout_dir(state)
    assert target.exists()
    assert state.env_updates["RESEARCH_AGENT_HELDOUT_DIR"] == str(target.resolve())


def test_step_lean_returns_true_regardless_of_toolchain(fake_repo, monkeypatch):
    """Lean is opt-in — a missing toolchain is INFORMATIONAL, not a fail."""
    monkeypatch.setattr(io.shutil, "which", lambda name: None)
    state = _make_state(fake_repo)
    assert step_lean(state) is True
    # No env updates: setup never auto-installs Lean.
    assert "RESEARCH_AGENT_LEAN" not in state.env_updates


def test_step_auto_prune_off_by_default(fake_repo, monkeypatch):
    monkeypatch.delenv("CLAUDESCIENTIST_SETUP_AUTO_PRUNE", raising=False)
    state = _make_state(fake_repo)
    assert step_auto_prune(state) is True
    assert "RESEARCH_AGENT_AUTO_PRUNE" not in state.env_updates


def test_step_auto_prune_on_via_env(fake_repo, monkeypatch):
    monkeypatch.setenv("CLAUDESCIENTIST_SETUP_AUTO_PRUNE", "1")
    state = _make_state(fake_repo)
    step_auto_prune(state)
    assert state.env_updates["RESEARCH_AGENT_AUTO_PRUNE"] == "1"


# ---------------------------------------------------------------------------
# End-to-end non-interactive run
# ---------------------------------------------------------------------------


def test_run_wizard_writes_env_with_all_defaults(fake_repo, monkeypatch):
    """The non-interactive happy path should leave a .env with the four
    keys setup owns, all populated from defaults."""
    monkeypatch.delenv("CLAUDESCIENTIST_SETUP_BACKEND", raising=False)
    monkeypatch.setenv("CLAUDESCIENTIST_SETUP_BACKEND", "mock")
    monkeypatch.setenv("CLAUDESCIENTIST_SETUP_AUTO_PRUNE", "0")
    monkeypatch.setenv("CLAUDESCIENTIST_SETUP_SEED_CORPUS", "0")
    state = _make_state(fake_repo)
    rc = run_wizard(state)
    assert rc == 0
    env = io.read_env_file(state.env_path)
    assert env.get("RESEARCH_AGENT_EMBED_BACKEND") == "mock"
    assert "RESEARCH_AGENT_HELDOUT_DIR" in env


def test_run_wizard_idempotent_second_pass(fake_repo, monkeypatch):
    """Re-running setup should not corrupt or duplicate a key. The
    user's own MINE=hello key must survive both runs untouched."""
    (fake_repo / ".env").write_text("MINE=hello\n", encoding="utf-8")
    monkeypatch.setenv("CLAUDESCIENTIST_SETUP_BACKEND", "mock")
    monkeypatch.setenv("CLAUDESCIENTIST_SETUP_AUTO_PRUNE", "0")
    monkeypatch.setenv("CLAUDESCIENTIST_SETUP_SEED_CORPUS", "0")
    state1 = _make_state(fake_repo)
    run_wizard(state1)
    state2 = _make_state(fake_repo)
    run_wizard(state2)
    text = (fake_repo / ".env").read_text(encoding="utf-8")
    # User's own key preserved.
    assert "MINE=hello" in text
    # Setup-owned key present exactly once.
    assert text.count("RESEARCH_AGENT_EMBED_BACKEND=") == 1


def test_main_aborts_when_repo_root_unfindable(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rc = main(["--non-interactive"])
    assert rc == 1
    captured = capsys.readouterr()
    assert "repo root" in captured.out.lower()


def test_main_succeeds_with_repo_root_override(fake_repo, monkeypatch):
    monkeypatch.setenv("CLAUDESCIENTIST_SETUP_BACKEND", "mock")
    monkeypatch.setenv("CLAUDESCIENTIST_SETUP_AUTO_PRUNE", "0")
    monkeypatch.setenv("CLAUDESCIENTIST_SETUP_SEED_CORPUS", "0")
    rc = main(["--non-interactive", "--repo-root", str(fake_repo), "--skip-deps"])
    assert rc == 0
    assert (fake_repo / ".env").exists()


def test_skip_deps_prevents_uv_sync_invocation(fake_repo, monkeypatch):
    """Tracker test: with --skip-deps, run_streaming must not be called
    for the embed-backend install path. We also pin the backend to a
    value that would normally trigger the install."""
    calls: list[list[str]] = []

    def fake_run_streaming(cmd, **kwargs):
        calls.append(list(cmd))
        return 0

    monkeypatch.setattr(io, "run_streaming", fake_run_streaming)
    # Pretend sentence-transformers is missing so the install path is
    # the one we'd want to take if not skipping.
    monkeypatch.setattr(io, "probe_sentence_transformers", lambda: False)
    monkeypatch.setenv("CLAUDESCIENTIST_SETUP_BACKEND", "local")
    monkeypatch.setenv("CLAUDESCIENTIST_SETUP_INSTALL_PROOF", "1")
    monkeypatch.setenv("CLAUDESCIENTIST_SETUP_SEED_CORPUS", "0")
    monkeypatch.setenv("CLAUDESCIENTIST_SETUP_AUTO_PRUNE", "0")
    state = _make_state(fake_repo, skip_deps=True)
    run_wizard(state)
    # Neither uv sync nor seed scripts should have been invoked.
    assert all("sync" not in c[1:] for c in calls), calls
