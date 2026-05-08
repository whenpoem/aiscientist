"""Interactive setup wizard for a fresh claudescientist clone.

Walks the user through 7 install-time decisions that the README otherwise
scatters across multiple sections:

    1. Sanity checks (python ≥ 3.11, ``uv`` on PATH, ``claude`` on PATH)
    2. Repo root detection (the wizard must be in the right tree)
    3. Embedding backend choice (mock | local | openai)
    4. Proof corpus seeding (calls ``scripts/seed_proof_*.py``)
    5. Held-out dataset directory (writes ``RESEARCH_AGENT_HELDOUT_DIR``)
    6. Lean toolchain detection (probes elan / lake / lean; never auto-installs)
    7. Auto-prune flag (``RESEARCH_AGENT_AUTO_PRUNE``)

Output is a project-local ``.env`` file. The wizard does NOT modify
``.claude/settings.json``, the user's shell rc, or any global config —
``.env`` is the single artifact written so a re-run can see what setup
already decided.

Usage:
    uv run python -m claudescientist.setup
    uv run python -m claudescientist.setup --non-interactive
    uv run python -m claudescientist.setup --reset

Non-interactive mode reads answers from these env vars:
    CLAUDESCIENTIST_SETUP_BACKEND       mock | local | openai (default: local)
    CLAUDESCIENTIST_SETUP_HELDOUT_DIR   absolute path        (default: $HOME)
    CLAUDESCIENTIST_SETUP_AUTO_PRUNE    0 | 1                (default: 0)
    CLAUDESCIENTIST_SETUP_OPENAI_KEY    only used if BACKEND=openai
    CLAUDESCIENTIST_SETUP_SEED_CORPUS   0 | 1                (default: 1)
    CLAUDESCIENTIST_SETUP_INSTALL_PROOF 0 | 1                (default: 1)

The wizard is idempotent: each step probes current state and either
short-circuits (already done) or asks before overwriting. ``--reset``
disables short-circuits so every prompt fires again.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import _setup_io as io


def _can_render_unicode() -> bool:
    """Whether stdout's encoding can carry the box-drawing / check glyphs.

    Windows ``cmd.exe`` and PowerShell sessions on Chinese-locale machines
    default to GBK, where ``"✓"`` (✓) raises UnicodeEncodeError. We
    detect that early and fall back to ASCII glyphs so setup never crashes
    on first run. Users on Windows Terminal with ``chcp 65001`` get the
    pretty output automatically.
    """
    enc = (sys.stdout.encoding or "").lower()
    if "utf" in enc:
        return True
    try:
        "✓".encode(sys.stdout.encoding or "ascii")
    except (UnicodeEncodeError, LookupError, TypeError):
        return False
    return True


_UNICODE_OK = _can_render_unicode()
_GLYPH_OK = "✓" if _UNICODE_OK else "+"
_GLYPH_FAIL = "✗" if _UNICODE_OK else "x"
_BOX_STYLE = box.ROUNDED if _UNICODE_OK else box.ASCII

# ---------------------------------------------------------------------------
# UI: questionary is loaded lazily so --non-interactive paths don't even
# touch prompt_toolkit (helps when stdout is piped, when running in
# non-tty CI, etc.).
# ---------------------------------------------------------------------------


def _q():
    """Lazy import for questionary. Raises a friendly error if missing."""
    try:
        import questionary
    except ImportError as e:  # pragma: no cover - questionary is a hard dep
        raise SystemExit(
            "questionary is required for interactive setup. "
            "Run `uv sync` to install it, or pass --non-interactive."
        ) from e
    return questionary


_console = Console()


# ---------------------------------------------------------------------------
# Wizard state
# ---------------------------------------------------------------------------


@dataclass
class SetupState:
    """Mutable state passed through every step.

    ``env_updates`` accumulates over the run and is flushed to the
    project's ``.env`` once at the end of step 7. Writing per-step would
    leave the user with a half-applied .env if they Ctrl+C mid-wizard.
    """

    repo_root: Path
    non_interactive: bool
    reset: bool
    skip_deps: bool
    env_updates: dict[str, str] = field(default_factory=dict)
    aborted: bool = False

    @property
    def env_path(self) -> Path:
        return self.repo_root / ".env"


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m claudescientist.setup",
        description="Interactive setup wizard for a claudescientist clone.",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="answer all prompts from CLAUDESCIENTIST_SETUP_* env vars",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="re-run every step even if its outcome is already in place",
    )
    parser.add_argument(
        "--skip-deps",
        action="store_true",
        help="never invoke `uv sync` even if a step would install something",
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help="override the repo root probe (useful for tests)",
    )
    return parser


# ---------------------------------------------------------------------------
# Banner + final cheat sheet
# ---------------------------------------------------------------------------


def _print_banner() -> None:
    _console.print()
    _console.print(
        Panel.fit(
            Text.assemble(
                ("claudescientist setup\n", "bold"),
                "Configure embed backend, held-out paths, proof corpus, and Lean reinsurance.\n",
                ("Output: ", "dim"),
                (".env at the repo root.", "dim italic"),
            ),
            border_style="cyan",
            box=_BOX_STYLE,
        )
    )
    _console.print()


def _print_cheatsheet(state: SetupState) -> None:
    _console.print()
    _console.print(
        Panel.fit(
            Text.assemble(
                ("Setup complete.\n\n", "bold green"),
                ("Wrote: ", "dim"),
                (f"{state.env_path}\n\n", ""),
                ("Two ways to activate the .env:\n", "bold"),
                "  1. Restart Claude Code; uv run will pick the values up.\n",
                "  2. ",
                ("uv run --env-file .env python -m cockpit.tui", "cyan"),
                "\n  3. ",
                ("set -a; source .env; set +a", "cyan"),
                ("  (bash/zsh, current shell)\n\n", "dim"),
                ("Two terminals to start a session:\n", "bold"),
                "  Terminal A: ",
                ("claude", "cyan"),
                "\n",
                "  Terminal B: ",
                ("uv run python -m cockpit.tui", "cyan"),
                "\n",
            ),
            border_style="green",
            box=_BOX_STYLE,
        )
    )
    _console.print()


# ---------------------------------------------------------------------------
# Helpers shared across steps
# ---------------------------------------------------------------------------


def _heading(n: int, total: int, title: str) -> None:
    sep = "·" if _UNICODE_OK else "-"
    _console.print()
    _console.print(f"[bold]Step {n}/{total}[/bold] {sep} {title}")


def _check_table(rows: list[tuple[bool, str, str]]) -> None:
    """Render a small status table.

    Glyph choice degrades to ASCII on terminals that can't render the
    Unicode check / cross (Windows GBK, cmd.exe with default codepage).
    See ``_can_render_unicode`` at module top.
    """
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("status", width=2)
    table.add_column("label")
    table.add_column("detail", style="dim")
    for ok, label, detail in rows:
        if ok:
            glyph = f"[green]{_GLYPH_OK}[/green]"
        else:
            glyph = f"[red]{_GLYPH_FAIL}[/red]"
        table.add_row(glyph, label, detail)
    _console.print(table)


def _ask_select(state: SetupState, message: str, choices: list[str], default: str) -> str:
    if state.non_interactive:
        return default
    try:
        result = _q().select(message, choices=choices, default=default).ask()
    except KeyboardInterrupt:
        return _abort(state)
    if result is None:
        return _abort(state)
    return str(result)


def _ask_text(
    state: SetupState,
    message: str,
    *,
    default: str = "",
    secret: bool = False,
) -> str:
    if state.non_interactive:
        return default
    try:
        if secret:
            result = _q().password(message).ask()
        else:
            result = _q().text(message, default=default).ask()
    except KeyboardInterrupt:
        return _abort(state)
    if result is None:
        return _abort(state)
    return str(result)


def _ask_confirm(state: SetupState, message: str, default: bool = True) -> bool:
    if state.non_interactive:
        return default
    try:
        result = _q().confirm(message, default=default).ask()
    except KeyboardInterrupt:
        _abort(state)
        return False
    if result is None:
        _abort(state)
        return False
    return bool(result)


def _abort(state: SetupState) -> str:
    state.aborted = True
    _console.print("[yellow]aborted by user[/yellow]")
    return ""


def _env_flag(name: str, default: str) -> str:
    """Read a CLAUDESCIENTIST_SETUP_* env var, returning ``default`` if unset."""
    return os.environ.get(name, default)


# ---------------------------------------------------------------------------
# Step 1 — sanity checks
# ---------------------------------------------------------------------------


def step_sanity(state: SetupState) -> bool:
    _heading(1, 7, "Sanity checks")
    py = io.probe_python()
    uv = io.probe_uv()
    claude = io.probe_claude()
    _check_table(
        [
            (py.ok, ("python " + (">=" if not _UNICODE_OK else "≥") + " 3.11"), py.detail),
            (uv.ok, "uv on PATH", uv.detail),
            (claude.ok, "claude on PATH (recommended)", claude.detail),
        ]
    )
    if not py.ok:
        _console.print("[red]python 3.11+ is required.[/red]")
        return False
    if not uv.ok:
        _console.print("[red]uv is required. Install: https://docs.astral.sh/uv/[/red]")
        return False
    if not claude.ok:
        _console.print(
            "[yellow]claude not found — the cockpit and MCP servers run "
            "without it, but you'll need it to drive a research session.[/yellow]"
        )
    return True


# ---------------------------------------------------------------------------
# Step 2 — repo root
# ---------------------------------------------------------------------------


def step_repo_root(state: SetupState) -> bool:
    _heading(2, 7, "Repo root")
    _console.print(f"  using {state.repo_root}")
    pyproject = state.repo_root / "pyproject.toml"
    claude_dir = state.repo_root / ".claude"
    _check_table(
        [
            (pyproject.exists(), "pyproject.toml", str(pyproject)),
            (claude_dir.is_dir(), ".claude/", str(claude_dir)),
        ]
    )
    return pyproject.exists() and claude_dir.is_dir()


# ---------------------------------------------------------------------------
# Step 3 — embedding backend
# ---------------------------------------------------------------------------


_BACKEND_CHOICES = ("local", "mock", "openai")


def step_embed_backend(state: SetupState) -> bool:
    _heading(3, 7, "Embedding backend (proof trunk)")
    current = io.read_env_file(state.env_path).get(
        "RESEARCH_AGENT_EMBED_BACKEND", "local"
    )
    if state.non_interactive:
        backend = _env_flag("CLAUDESCIENTIST_SETUP_BACKEND", "local")
    else:
        _console.print(
            "  mock: deterministic, no model download — used for tests.\n"
            "  local: sentence-transformers/all-MiniLM-L6-v2 (~80 MB).\n"
            "  openai: requires OPENAI_API_KEY — billed per call."
        )
        backend = _ask_select(
            state,
            "which embedding backend?",
            list(_BACKEND_CHOICES),
            default=current if current in _BACKEND_CHOICES else "local",
        )
        if state.aborted:
            return False
    if backend not in _BACKEND_CHOICES:
        _console.print(f"[red]unknown backend {backend!r}; defaulting to local[/red]")
        backend = "local"
    state.env_updates["RESEARCH_AGENT_EMBED_BACKEND"] = backend

    if backend == "local":
        st_present = io.probe_sentence_transformers()
        if st_present:
            _console.print("  [green]sentence-transformers already installed.[/green]")
        else:
            _console.print(
                "  sentence-transformers is NOT installed in the active venv."
            )
            do_install = (
                _env_flag("CLAUDESCIENTIST_SETUP_INSTALL_PROOF", "1") == "1"
                if state.non_interactive
                else _ask_confirm(
                    state, "run `uv sync --extra proof` now?", default=True
                )
            )
            if state.aborted:
                return False
            if do_install and not state.skip_deps:
                rc = io.run_streaming(
                    ["uv", "sync", "--extra", "proof"], cwd=state.repo_root
                )
                if rc != 0:
                    _console.print(
                        f"[red]uv sync failed (exit {rc}); skipping seed step.[/red]"
                    )
                    state.env_updates["RESEARCH_AGENT_EMBED_BACKEND"] = "mock"
                    return True
            elif state.skip_deps:
                _console.print(
                    "[yellow]--skip-deps set; not installing. Run `uv sync "
                    "--extra proof` manually before using the proof trunk.[/yellow]"
                )

    if backend == "openai":
        key = (
            _env_flag("CLAUDESCIENTIST_SETUP_OPENAI_KEY", "")
            if state.non_interactive
            else _ask_text(state, "OPENAI_API_KEY:", secret=True)
        )
        if state.aborted:
            return False
        if key:
            state.env_updates["OPENAI_API_KEY"] = key
        else:
            _console.print(
                "[yellow]no key provided — set OPENAI_API_KEY before launch.[/yellow]"
            )
    return True


# ---------------------------------------------------------------------------
# Step 4 — proof corpus seed
# ---------------------------------------------------------------------------


def step_seed_corpus(state: SetupState) -> bool:
    _heading(4, 7, "Proof corpus seed")
    backend = state.env_updates.get(
        "RESEARCH_AGENT_EMBED_BACKEND",
        io.read_env_file(state.env_path).get("RESEARCH_AGENT_EMBED_BACKEND", "local"),
    )
    if backend == "mock":
        _console.print("  backend=mock; skipping seed (mock is for tests).")
        return True

    seed_corpus = state.repo_root / "scripts" / "seed_proof_corpus.py"
    seed_failures = state.repo_root / "scripts" / "seed_proof_failures.py"
    if not seed_corpus.exists():
        _console.print(
            f"[yellow]missing {seed_corpus}; skipping seed (older repo layout?).[/yellow]"
        )
        return True

    do_seed = (
        _env_flag("CLAUDESCIENTIST_SETUP_SEED_CORPUS", "1") == "1"
        if state.non_interactive
        else _ask_confirm(state, "seed the proof corpus now?", default=True)
    )
    if state.aborted:
        return False
    if not do_seed:
        _console.print(
            "  skipping seed. Run later: "
            "[cyan]uv run python scripts/seed_proof_corpus.py[/cyan]"
        )
        return True

    rc = io.run_streaming(
        ["uv", "run", "python", str(seed_corpus)], cwd=state.repo_root
    )
    if rc != 0:
        _console.print(
            f"[red]seed_proof_corpus.py failed (exit {rc}). Continuing.[/red]"
        )
        return True
    if seed_failures.exists():
        rc2 = io.run_streaming(
            ["uv", "run", "python", str(seed_failures)], cwd=state.repo_root
        )
        if rc2 != 0:
            _console.print(
                f"[red]seed_proof_failures.py failed (exit {rc2}).[/red]"
            )
    return True


# ---------------------------------------------------------------------------
# Step 5 — held-out dir
# ---------------------------------------------------------------------------


def step_heldout_dir(state: SetupState) -> bool:
    _heading(5, 7, "Held-out dataset directory")
    home = str(Path.home())
    current = io.read_env_file(state.env_path).get(
        "RESEARCH_AGENT_HELDOUT_DIR", home
    )
    default_dir = (
        _env_flag("CLAUDESCIENTIST_SETUP_HELDOUT_DIR", current)
        if state.non_interactive
        else current
    )

    if state.non_interactive:
        chosen = default_dir
    else:
        _console.print(
            "  default: your home directory. Pick another path if you want\n"
            "  held-out registrations to live elsewhere (e.g. an external SSD)."
        )
        chosen = _ask_text(state, "held-out directory:", default=default_dir)
        if state.aborted:
            return False
    chosen = chosen.strip()
    if not chosen:
        chosen = home

    expanded = Path(os.path.expandvars(os.path.expanduser(chosen))).resolve()
    if not expanded.exists():
        if not state.non_interactive and not _ask_confirm(
            state, f"{expanded} does not exist — create it?", default=True
        ):
            _console.print("[yellow]not creating; held-out dir will be unset.[/yellow]")
            return True
        try:
            expanded.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            _console.print(f"[red]could not create {expanded}: {e}[/red]")
            return True

    state.env_updates["RESEARCH_AGENT_HELDOUT_DIR"] = str(expanded)
    _console.print(f"  using [cyan]{expanded}[/cyan]")
    return True


# ---------------------------------------------------------------------------
# Step 6 — Lean detection
# ---------------------------------------------------------------------------


def step_lean(state: SetupState) -> bool:
    _heading(6, 7, "Lean reinsurance (optional)")
    ok, missing = io.probe_lean_toolchain()
    if ok:
        _console.print(
            "  [green]elan + lake + lean detected.[/green] "
            "Lean MCP will activate automatically."
        )
        return True
    _console.print(
        f"  Lean toolchain incomplete (missing: {', '.join(missing)}).\n"
        "  Lean reinsurance stays in noop mode until installed.\n"
        "  Setup guide: [cyan]docs/setup-lean.md[/cyan]"
    )
    return True


# ---------------------------------------------------------------------------
# Step 7 — auto-prune
# ---------------------------------------------------------------------------


def step_auto_prune(state: SetupState) -> bool:
    _heading(7, 7, "Auto-prune (suggest_pause_low_strength)")
    _console.print(
        "  By default, low-strength branches are SUGGESTED for pause but\n"
        "  not actually paused. Set RESEARCH_AGENT_AUTO_PRUNE=1 to let the\n"
        "  system act on its own suggestions."
    )
    if state.non_interactive:
        enable = _env_flag("CLAUDESCIENTIST_SETUP_AUTO_PRUNE", "0") == "1"
    else:
        enable = _ask_confirm(state, "enable auto-prune?", default=False)
        if state.aborted:
            return False
    if enable:
        state.env_updates["RESEARCH_AGENT_AUTO_PRUNE"] = "1"
        _console.print("  auto-prune ENABLED.")
    else:
        _console.print("  keeping the dry-run default.")
    return True


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_wizard(state: SetupState) -> int:
    """Drive every step in order. Returns a process exit code."""
    _print_banner()
    steps = [
        step_sanity,
        step_repo_root,
        step_embed_backend,
        step_seed_corpus,
        step_heldout_dir,
        step_lean,
        step_auto_prune,
    ]
    for step in steps:
        ok = step(state)
        if state.aborted:
            return 1
        if not ok:
            _console.print(
                "[red]step failed; aborting before writing .env.[/red]"
            )
            return 1
    if state.env_updates:
        io.update_env_file(state.env_path, state.env_updates)
    _print_cheatsheet(state)
    return 0


def _resolve_repo_root(override: str | None) -> Path | None:
    if override:
        path = Path(override).resolve()
        return path if (path / "pyproject.toml").exists() else None
    return io.probe_repo_root(Path.cwd())


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = _resolve_repo_root(args.repo_root)
    if repo_root is None:
        _console.print(
            "[red]Could not locate the claudescientist repo root.[/red]\n"
            "  Run setup from inside a clone, or pass --repo-root <path>.\n"
            "  A valid repo root contains both pyproject.toml and .claude/."
        )
        return 1
    state = SetupState(
        repo_root=repo_root,
        non_interactive=bool(args.non_interactive),
        reset=bool(args.reset),
        skip_deps=bool(args.skip_deps),
    )
    return run_wizard(state)


if __name__ == "__main__":
    sys.exit(main())
