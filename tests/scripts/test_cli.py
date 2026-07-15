from __future__ import annotations

import json
import subprocess
from pathlib import Path

from claudescientist import cli, doctor, plugin_setup


def test_cockpit_cli_targets_explicit_external_workspace(tmp_path, capsys, monkeypatch):
    workspace = tmp_path / "research-project"
    workspace.mkdir()
    monkeypatch.delenv("RESEARCH_AGENT_DB_PATH", raising=False)
    monkeypatch.delenv("RESEARCH_AGENT_STATE_DIR", raising=False)

    assert cli.main(["cockpit", "--workspace", str(workspace), "--once", "--lang", "zh"]) == 0
    output = capsys.readouterr().out
    assert output.strip()
    assert (workspace / ".research-agent" / "state.db").is_file()


def test_doctor_reports_monitor_and_intervention_separately(tmp_path, monkeypatch):
    workspace = tmp_path / "research-project"
    config = workspace / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "[features]\nhooks=true\n# intervention_pump\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        doctor,
        "_codex_plugin_status",
        lambda: {"available": True, "installed": True, "enabled": True},
    )
    monkeypatch.setattr(doctor, "_trusted_claudescientist_hooks", lambda: True)

    result = doctor.run_doctor(workspace)
    assert result["checks"]["cockpit_monitoring"]["status"] == "ok"
    assert result["checks"]["hook_delivery"]["status"] == "ok"


def test_doctor_reports_monitor_only_when_hooks_are_untrusted(tmp_path, monkeypatch):
    workspace = tmp_path / "research-project"
    workspace.mkdir()
    monkeypatch.setattr(
        doctor,
        "_codex_plugin_status",
        lambda: {"available": True, "installed": True, "enabled": True},
    )
    monkeypatch.setattr(doctor, "_trusted_claudescientist_hooks", lambda: False)

    result = doctor.run_doctor(workspace)
    assert result["overall"] == "degraded"
    assert result["checks"]["cockpit_monitoring"]["status"] == "ok"
    delivery = result["checks"]["hook_delivery"]
    assert delivery["status"] == "degraded"
    assert "monitor-only" in delivery["detail"]


def test_doctor_cli_json_output(tmp_path, capsys, monkeypatch):
    workspace = tmp_path / "research-project"
    workspace.mkdir()
    monkeypatch.setattr(
        doctor,
        "_codex_plugin_status",
        lambda: {"available": True, "installed": False, "enabled": False},
    )
    monkeypatch.setattr(doctor, "_trusted_claudescientist_hooks", lambda: False)

    assert cli.main(["doctor", "--workspace", str(workspace), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["checks"]["state_database"]["path"].startswith(str(workspace))


def test_doctor_parses_real_codex_plugin_json(monkeypatch):
    payload = {
        "installed": [
            {
                "pluginId": "claudescientist@personal",
                "name": "claudescientist",
                "version": "5.1.1",
                "installed": True,
                "enabled": True,
            }
        ],
        "available": [],
    }

    def fake_run(command, **kwargs):
        assert command[-3:] == ["plugin", "list", "--json"]
        assert kwargs["capture_output"] is True
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(doctor, "codex_command_prefix", lambda: ["codex.cmd"])
    monkeypatch.setattr(doctor.subprocess, "run", fake_run)

    result = doctor._codex_plugin_status()  # noqa: SLF001
    assert result["installed"] is True
    assert result["enabled"] is True
    assert result["versions"] == ["5.1.1"]


def test_doctor_hook_trust_honours_codex_home(tmp_path, monkeypatch):
    codex_home = tmp_path / "isolated-codex"
    codex_home.mkdir()
    (codex_home / "config.toml").write_text(
        '[hooks.state."claudescientist@personal"]\ntrusted_hash = "sha256:test"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    assert doctor._trusted_claudescientist_hooks() is True  # noqa: SLF001


def test_doctor_reports_optional_runtime_readiness(tmp_path, monkeypatch):
    workspace = tmp_path / "research-project"
    config = workspace / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(
        """
[mcp_servers.arxiv]
enabled = true
[mcp_servers.openalex]
enabled = true
[mcp_servers.lean]
enabled = true
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: None)
    real_find_spec = doctor.importlib.util.find_spec
    monkeypatch.setattr(
        doctor.importlib.util,
        "find_spec",
        lambda name: None if name == "sentence_transformers" else real_find_spec(name),
    )
    monkeypatch.setattr(
        doctor,
        "_codex_plugin_status",
        lambda: {"available": True, "installed": True, "enabled": True},
    )
    monkeypatch.setattr(doctor, "_trusted_claudescientist_hooks", lambda: True)

    checks = doctor.run_doctor(workspace)["checks"]
    assert checks["node_runtime"]["status"] == "optional"
    assert checks["literature_arxiv"]["status"] == "degraded"
    assert checks["literature_openalex"]["status"] == "degraded"
    assert checks["lean_reinsurance"]["status"] == "degraded"
    assert checks["embedding_backend"]["status"] == "degraded"


def test_doctor_optional_tools_do_not_degrade_when_disabled(tmp_path, monkeypatch):
    workspace = tmp_path / "research-project"
    workspace.mkdir()
    monkeypatch.setenv("RESEARCH_AGENT_EMBED_BACKEND", "mock")
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        doctor,
        "_codex_plugin_status",
        lambda: {"available": True, "installed": True, "enabled": True},
    )
    monkeypatch.setattr(doctor, "_trusted_claudescientist_hooks", lambda: True)

    checks = doctor.run_doctor(workspace)["checks"]
    assert checks["literature_arxiv"]["status"] == "ok"
    assert checks["literature_openalex"]["status"] == "ok"
    assert checks["lean_reinsurance"]["status"] == "ok"
    assert checks["embedding_backend"]["status"] == "ok"


def test_doctor_rejects_state_database_inside_separate_installation(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "research-project"
    installation = tmp_path / "installed-package"
    workspace.mkdir()
    installation.mkdir()
    misplaced = installation / ".research-agent" / "state.db"
    monkeypatch.setenv("RESEARCH_AGENT_DB_PATH", str(misplaced))
    monkeypatch.setenv("RESEARCH_AGENT_EMBED_BACKEND", "mock")
    monkeypatch.setattr(doctor, "installation_root", lambda: installation)
    monkeypatch.setattr(
        doctor,
        "_codex_plugin_status",
        lambda: {"available": True, "installed": True, "enabled": True},
    )
    monkeypatch.setattr(doctor, "_trusted_claudescientist_hooks", lambda: True)

    result = doctor.run_doctor(workspace)
    database = result["checks"]["state_database"]
    assert result["overall"] == "error"
    assert database["misplaced"] is True
    assert database["inside_installation_root"] is True


def test_user_setup_installs_version_matched_marketplace_and_plugin(monkeypatch):
    commands: list[list[str]] = []

    def fake_runner(command, **kwargs):
        commands.append(command)
        assert kwargs["check"] is False
        assert kwargs["capture_output"] is True
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    monkeypatch.setattr(plugin_setup, "codex_command_prefix", lambda: ["codex.cmd"])
    result = plugin_setup.install_user_plugin(runner=fake_runner)

    assert result["ok"] is True
    assert result["ref"] == "v5.1.1"
    assert commands == [
        [
            "codex.cmd",
            "plugin",
            "marketplace",
            "add",
            "whenpoem/aiscientist",
            "--ref",
            "v5.1.1",
            "--json",
        ],
        [
            "codex.cmd",
            "plugin",
            "add",
            "claudescientist@claudescientist",
            "--json",
        ],
    ]


def test_user_setup_stops_after_marketplace_failure(monkeypatch):
    commands: list[list[str]] = []

    def fake_runner(command, **_kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 2, stdout="", stderr="bad ref")

    monkeypatch.setattr(plugin_setup, "codex_command_prefix", lambda: ["codex.cmd"])
    result = plugin_setup.install_user_plugin(runner=fake_runner)

    assert result["ok"] is False
    assert result["error"] == "codex_plugin_install_failed"
    assert len(commands) == 1


def test_user_setup_rejects_incomplete_installed_plugin_assets(tmp_path, monkeypatch):
    installed = tmp_path / "stale-plugin"
    (installed / ".codex-plugin").mkdir(parents=True)
    (installed / ".codex-plugin" / "plugin.json").write_text(
        '{"name":"claudescientist"}', encoding="utf-8"
    )

    def fake_runner(command, **_kwargs):
        payload = (
            {"marketplaceName": "claudescientist"}
            if "marketplace" in command
            else {"installedPath": str(installed)}
        )
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps(payload), stderr=""
        )

    monkeypatch.setattr(plugin_setup, "codex_command_prefix", lambda: ["codex.cmd"])
    result = plugin_setup.install_user_plugin(runner=fake_runner)

    assert result["ok"] is False
    assert result["error"] == "codex_plugin_assets_missing"
    assert set(result["missing_assets"]) == {
        ".mcp.json",
        str(Path("hooks") / "hooks.json"),
        "skills",
    }


def test_user_setup_accepts_complete_installed_plugin_assets(tmp_path, monkeypatch):
    installed = tmp_path / "complete-plugin"
    (installed / ".codex-plugin").mkdir(parents=True)
    (installed / ".codex-plugin" / "plugin.json").write_text(
        '{"name":"claudescientist"}', encoding="utf-8"
    )
    (installed / ".mcp.json").write_text('{"mcpServers":{}}', encoding="utf-8")
    (installed / "hooks").mkdir()
    (installed / "hooks" / "hooks.json").write_text(
        '{"hooks":{}}', encoding="utf-8"
    )
    (installed / "skills").mkdir()

    def fake_runner(command, **_kwargs):
        payload = (
            {"marketplaceName": "claudescientist"}
            if "marketplace" in command
            else {"installedPath": str(installed)}
        )
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps(payload), stderr=""
        )

    monkeypatch.setattr(plugin_setup, "codex_command_prefix", lambda: ["codex.cmd"])
    result = plugin_setup.install_user_plugin(runner=fake_runner)

    assert result["ok"] is True
    assert result["installed_path"] == str(installed)


def test_user_setup_omits_git_ref_for_local_marketplace(tmp_path, monkeypatch):
    commands: list[list[str]] = []

    def fake_runner(command, **_kwargs):
        commands.append(command)
        stdout = (
            json.dumps({"marketplaceName": "local-research-tools"})
            if "marketplace" in command
            else "{}"
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(plugin_setup, "codex_command_prefix", lambda: ["codex.cmd"])
    result = plugin_setup.install_user_plugin(source=str(tmp_path), runner=fake_runner)

    assert result["ok"] is True
    assert "--ref" not in commands[0]
    assert commands[1][-2] == "claudescientist@local-research-tools"
    assert result["ref"] is None
    assert result["requested_ref"] == "v5.1.1"


def test_project_setup_cli_forwards_wizard_flags(tmp_path, monkeypatch):
    captured: list[str] = []

    def fake_setup_main(argv):
        captured.extend(argv)
        return 0

    import claudescientist.setup as setup_module

    monkeypatch.setattr(setup_module, "main", fake_setup_main)
    assert (
        cli.main(
            [
                "setup",
                "--scope",
                "project",
                "--non-interactive",
                "--skip-deps",
                "--repo-root",
                str(tmp_path),
            ]
        )
        == 0
    )
    assert captured == [
        "--non-interactive",
        "--skip-deps",
        "--repo-root",
        str(tmp_path),
    ]
