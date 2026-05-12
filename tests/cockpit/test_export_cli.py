"""CLI tests for python -m cockpit.export."""

from __future__ import annotations

import pytest


def test_list_kinds_lists_every_known_kind(workspace, capsys):
    from cockpit.export.cli import main

    rc = main(["--list-kinds"])
    assert rc == 0
    captured = capsys.readouterr()
    out = captured.out.split()
    assert set(out) == {"closure", "draft", "diagnostic", "portfolio", "cascade"}


def test_missing_kind_or_node_id_yields_error(workspace):
    from cockpit.export.cli import main

    with pytest.raises(SystemExit) as exc:
        main([])
    # argparse exits 2 on usage errors.
    assert exc.value.code == 2


def test_unknown_kind_yields_exit_2(workspace, capsys):
    from cockpit.export.cli import main

    rc = main(["nonsense", "prop_x"])
    assert rc == 2
    captured = capsys.readouterr()
    assert "unknown kind" in captured.err


def test_unknown_format_yields_systemexit(workspace, capsys):
    from cockpit.export.cli import main

    with pytest.raises(SystemExit) as exc:
        main(["closure", "prop_x", "--format", "pdf"])
    msg = str(exc.value).lower()
    assert "unknown format" in msg or "pdf" in msg


def test_happy_path_writes_file_and_prints_path(
    workspace, monkeypatch, tmp_path, capsys
):
    from cockpit.export.cli import main

    monkeypatch.setenv("RESEARCH_AGENT_REPORTS_DIR", str(tmp_path / "out"))
    prove_impl = workspace["prove_mcp.impl"]
    prop = prove_impl.propose_proposition("CLI happy-path proposition")

    rc = main(["closure", prop["node_id"], "--format", "md"])
    assert rc == 0
    captured = capsys.readouterr()
    printed = captured.out.strip()
    assert printed
    # Each printed line is a path; verify the file actually exists.
    from pathlib import Path

    paths = [Path(line) for line in printed.splitlines() if line]
    assert paths
    for path in paths:
        assert path.exists()
        assert path.suffix == ".md"


def test_happy_path_with_both_formats_writes_two_files(
    workspace, monkeypatch, tmp_path, capsys
):
    from cockpit.export.cli import main

    monkeypatch.setenv("RESEARCH_AGENT_REPORTS_DIR", str(tmp_path / "out"))
    prove_impl = workspace["prove_mcp.impl"]
    prop = prove_impl.propose_proposition("CLI both-format proposition")

    rc = main(["closure", prop["node_id"], "--format", "md,html"])
    assert rc == 0
    captured = capsys.readouterr()
    lines = [line for line in captured.out.splitlines() if line]
    assert len(lines) == 2
    suffixes = {line.rsplit(".", 1)[-1] for line in lines}
    assert suffixes == {"md", "html"}
