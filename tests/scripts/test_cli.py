from __future__ import annotations

import json
import subprocess

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
                "version": "5.1.0",
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
    assert result["versions"] == ["5.1.0"]


def test_doctor_hook_trust_honours_codex_home(tmp_path, monkeypatch):
    codex_home = tmp_path / "isolated-codex"
    codex_home.mkdir()
    (codex_home / "config.toml").write_text(
        '[hooks.state."claudescientist@personal"]\ntrusted_hash = "sha256:test"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    assert doctor._trusted_claudescientist_hooks() is True  # noqa: SLF001


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
    assert result["ref"] == "v5.1.0"
    assert commands == [
        [
            "codex.cmd",
            "plugin",
            "marketplace",
            "add",
            "whenpoem/aiscientist",
            "--ref",
            "v5.1.0",
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
    assert result["requested_ref"] == "v5.1.0"


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
