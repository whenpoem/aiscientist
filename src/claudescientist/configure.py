"""Configure one ordinary research workspace for the public plugin."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from . import __version__
from .workspace_config import EMBED_BACKENDS, read_workspace_config, write_workspace_config

LOCAL_DEFAULT_MODEL = "Qwen/Qwen3-Embedding-0.6B"
OPENAI_DEFAULT_MODEL = "text-embedding-3-large"
DEFAULT_LEAN_PROJECT = Path(".research-agent") / "lean" / "claudescientist-proofs"
DEFAULT_HELDOUT_DIR = Path.home() / ".research-agent" / "heldout"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claudescientist configure",
        description="Configure ClaudeScientist for one research workspace.",
    )
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--embedding-backend", choices=EMBED_BACKENDS)
    parser.add_argument("--embedding-model")
    parser.add_argument("--embedding-base-url")
    parser.add_argument("--heldout-dir")
    parser.add_argument(
        "--auto-prune",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    parser.add_argument(
        "--lean",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    parser.add_argument("--lean-project")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _questionary():
    try:
        import questionary
    except ImportError as exc:  # pragma: no cover - declared base dependency
        raise SystemExit(
            "Interactive configuration needs questionary. "
            "Reinstall claudescientist or use --non-interactive."
        ) from exc
    return questionary


def _existing_settings(root: Path) -> dict[str, Any]:
    loaded = read_workspace_config(root)
    values = loaded.values
    return {
        "embedding": {
            "backend": values.get("RESEARCH_AGENT_EMBED_BACKEND", "local"),
            "model": values.get("RESEARCH_AGENT_EMBED_MODEL", ""),
            "base_url": values.get("RESEARCH_AGENT_EMBED_BASE_URL", ""),
        },
        "heldout": {
            "directory": values.get(
                "RESEARCH_AGENT_HELDOUT_DIR", str(DEFAULT_HELDOUT_DIR)
            )
        },
        "research": {
            "auto_prune": values.get("RESEARCH_AGENT_AUTO_PRUNE", "0") == "1"
        },
        "lean": {
            "enabled": values.get("RESEARCH_AGENT_LEAN_ENABLED", "0") == "1",
            "project_path": values.get("LEAN_PROJECT_PATH", str(DEFAULT_LEAN_PROJECT)),
        },
    }


def _ask_text(message: str, *, default: str = "") -> str:
    answer = _questionary().text(message, default=default).ask()
    if answer is None:
        raise KeyboardInterrupt
    return str(answer).strip()


def _ask_confirm(message: str, *, default: bool = False) -> bool:
    answer = _questionary().confirm(message, default=default).ask()
    if answer is None:
        raise KeyboardInterrupt
    return bool(answer)


def _ask_backend(default: str) -> str:
    answer = _questionary().select(
        "Embedding backend for proof-corpus retrieval:",
        choices=[
            "local - local sentence-transformers model",
            "openai - OpenAI-compatible embedding service",
            "mock - deterministic test backend",
        ],
        default={
            "local": "local - local sentence-transformers model",
            "openai": "openai - OpenAI-compatible embedding service",
            "mock": "mock - deterministic test backend",
        }[default],
    ).ask()
    if answer is None:
        raise KeyboardInterrupt
    return str(answer).split(" ", 1)[0]


def _resolve_settings(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    settings = _existing_settings(root)
    embedding = settings["embedding"]
    heldout = settings["heldout"]
    research = settings["research"]
    lean = settings["lean"]

    if args.non_interactive:
        backend = args.embedding_backend or embedding["backend"]
    else:
        backend = args.embedding_backend or _ask_backend(embedding["backend"])
    embedding["backend"] = backend

    default_model = embedding["model"]
    if not default_model:
        default_model = (
            LOCAL_DEFAULT_MODEL if backend == "local" else OPENAI_DEFAULT_MODEL
        )
    if backend == "mock":
        embedding["model"] = args.embedding_model or "mock"
        embedding["base_url"] = ""
    else:
        embedding["model"] = args.embedding_model or (
            default_model
            if args.non_interactive
            else _ask_text("Embedding model:", default=default_model)
        )
        if backend == "openai":
            embedding["base_url"] = (
                args.embedding_base_url
                if args.embedding_base_url is not None
                else (
                    embedding["base_url"]
                    if args.non_interactive
                    else _ask_text(
                        "OpenAI-compatible base URL (leave blank for OpenAI):",
                        default=embedding["base_url"],
                    )
                )
            )
        else:
            embedding["base_url"] = ""

    heldout_value = args.heldout_dir
    if heldout_value is None and not args.non_interactive:
        heldout_value = _ask_text(
            "Held-out dataset directory:", default=str(heldout["directory"])
        )
    heldout_path = Path(
        os.path.expandvars(os.path.expanduser(heldout_value or heldout["directory"]))
    )
    if not heldout_path.is_absolute():
        heldout_path = root / heldout_path
    heldout_path = heldout_path.resolve()
    heldout_path.mkdir(parents=True, exist_ok=True)
    heldout["directory"] = str(heldout_path)

    research["auto_prune"] = (
        args.auto_prune
        if args.auto_prune is not None
        else (
            research["auto_prune"]
            if args.non_interactive
            else _ask_confirm(
                "Allow automatic pausing of low-strength branches?",
                default=research["auto_prune"],
            )
        )
    )

    lean["enabled"] = (
        args.lean
        if args.lean is not None
        else (
            lean["enabled"]
            if args.non_interactive
            else _ask_confirm(
                "Use Lean machine verification in this workspace?",
                default=lean["enabled"],
            )
        )
    )
    lean_value = args.lean_project
    if lean["enabled"] and lean_value is None and not args.non_interactive:
        lean_value = _ask_text(
            "Lean mathlib project path:", default=str(lean["project_path"])
        )
    lean["project_path"] = lean_value or lean["project_path"] or str(DEFAULT_LEAN_PROJECT)
    return settings


def configure_workspace(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.workspace).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    settings = _resolve_settings(args, root)
    path = write_workspace_config(settings, root)

    lean_path = Path(str(settings["lean"]["project_path"]))
    if not lean_path.is_absolute():
        lean_path = root / lean_path
    lean_ready = (lean_path / "lakefile.lean").is_file()
    warnings: list[str] = []
    if settings["embedding"]["backend"] == "openai" and not os.environ.get(
        "OPENAI_API_KEY"
    ):
        warnings.append("Set OPENAI_API_KEY in your shell before using the proof MCP.")
    if settings["lean"]["enabled"] and not lean_ready:
        warnings.append(
            f"Lean is enabled but no lakefile.lean was found at {lean_path.resolve()}."
        )

    return {
        "ok": True,
        "workspace": str(root),
        "config": str(path),
        "settings": settings,
        "warnings": warnings,
        "next_steps": [
            "Start a new Codex task from this workspace so MCPs and hooks reload.",
            "Use Codex plugin settings to enable arxiv, openalex, or lean when needed.",
            f"Run `claudescientist doctor --workspace {root}` to check the setup.",
        ],
    }


def print_result(result: dict[str, Any]) -> None:
    print(f"Workspace configured: {result['workspace']}")
    print(f"Configuration file: {result['config']}")
    for warning in result["warnings"]:
        print(f"Warning: {warning}")
    print("Next steps:")
    for step in result["next_steps"]:
        print(f"- {step}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = configure_workspace(args)
    except KeyboardInterrupt:
        print("Configuration cancelled. No configuration file was written.")
        return 1
    if args.as_json:
        import json

        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_result(result)
    return 0


def proof_extra_install_command() -> str:
    return f'uv tool install --force "claudescientist[proof]=={__version__}"'


__all__ = [
    "build_parser",
    "configure_workspace",
    "main",
    "print_result",
    "proof_extra_install_command",
]


if __name__ == "__main__":
    raise SystemExit(main())
