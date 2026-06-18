"""Interactive setup wizard for a fresh claudescientist clone.

Walks the user through 8 install-time decisions that the README otherwise
scatters across multiple sections:

    1. Sanity checks (python ≥ 3.11, ``uv`` on PATH, ``claude`` on PATH)
    2. Repo root detection (the wizard must be in the right tree)
    3. Agent host choice (claude | codex | both)
    4. Embedding backend choice (mock | local | openai)
    5. Proof corpus seeding (calls ``scripts/seed_proof_*.py``)
    6. Held-out dataset directory (writes ``RESEARCH_AGENT_HELDOUT_DIR``)
    7. Lean toolchain detection (probes elan / lake / lean; never auto-installs)
    8. Auto-prune flag (``RESEARCH_AGENT_AUTO_PRUNE``)

Output is a project-local ``.env`` file plus optional project-local Codex
adapter files when the selected host is ``codex`` or ``both``. The wizard does
NOT modify ``.claude/settings.json``, the user's shell rc, or any global config.

Usage:
    uv run python -m claudescientist.setup
    uv run python -m claudescientist.setup --non-interactive
    uv run python -m claudescientist.setup --reset

Non-interactive mode reads answers from these env vars:
    CLAUDESCIENTIST_SETUP_AGENT_HOST    claude | codex | both (default: claude)
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
from . import agent_hosts


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
                "Configure agent host, embed backend, held-out paths, proof corpus, and Lean.\n",
                ("Output: ", "dim"),
                (".env plus optional Codex adapter files.", "dim italic"),
            ),
            border_style="cyan",
            box=_BOX_STYLE,
        )
    )
    _console.print()


_QUICKSTART_DOC = Path("docs/workflows/first-research-task.md")
_DEFAULT_HELDOUT_DIR = Path.home() / ".research-agent" / "heldout"


def _print_cheatsheet(state: SetupState) -> None:
    host = agent_hosts.normalize_agent_host(
        state.env_updates.get(
            "CLAUDESCIENTIST_AGENT_HOST",
            io.read_env_file(state.env_path).get("CLAUDESCIENTIST_AGENT_HOST"),
        )
    )
    if host == agent_hosts.HOST_CODEX:
        restart_line = "  1. Restart Codex; uv run will pick the values up.\n"
        terminal_a = "codex"
    elif host == agent_hosts.HOST_BOTH:
        restart_line = "  1. Restart Claude Code / Codex; uv run will pick the values up.\n"
        terminal_a = "claude  (or: codex)"
    else:
        restart_line = "  1. Restart Claude Code; uv run will pick the values up.\n"
        terminal_a = "claude"
    _console.print()
    _console.print(
        Panel.fit(
            Text.assemble(
                ("Setup complete.\n\n", "bold green"),
                ("Wrote: ", "dim"),
                (f"{state.env_path}\n\n", ""),
                ("Two ways to activate the .env:\n", "bold"),
                restart_line,
                "  2. ",
                ("uv run --env-file .env python -m cockpit.tui", "cyan"),
                "\n  3. ",
                ("set -a; source .env; set +a", "cyan"),
                ("  (bash/zsh, current shell)\n\n", "dim"),
                ("Two terminals to start a session:\n", "bold"),
                "  Terminal A: ",
                (terminal_a, "cyan"),
                "\n",
                "  Terminal B: ",
                ("uv run python -m cockpit.tui", "cyan"),
                "\n\n",
                ("First time? Read: ", "bold"),
                (str(_QUICKSTART_DOC), "cyan"),
                ("\n  (15-minute walkthrough of your first session)\n", "dim"),
            ),
            border_style="green",
            box=_BOX_STYLE,
        )
    )
    _console.print()


def _maybe_open_quickstart(state: SetupState) -> None:
    """Offer to open the first-task walkthrough in the user's default app.

    Skipped in --non-interactive mode (the cheatsheet still mentions the
    path). Skipped when the file is not present (older clones). Failure
    to open is reported as a tip rather than an error.
    """
    if state.non_interactive:
        return
    path = (state.repo_root / _QUICKSTART_DOC).resolve()
    if not path.exists():
        return
    try:
        proceed = _ask_confirm(
            state, "open the first-task walkthrough now?", default=True
        )
    except (KeyboardInterrupt, EOFError):  # pragma: no cover - defensive
        return
    if state.aborted or not proceed:
        return
    if not io.open_file_with_default_app(path):
        _console.print(
            "[yellow]could not launch the default markdown handler; "
            f"open {path} manually when you're ready.[/yellow]"
        )


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
    _heading(1, 8, "Sanity checks")
    py = io.probe_python()
    uv = io.probe_uv()
    claude = io.probe_claude()
    codex = io.probe_codex()
    npx = io.probe_npx()
    _check_table(
        [
            (py.ok, ("python " + (">=" if not _UNICODE_OK else "≥") + " 3.11"), py.detail),
            (uv.ok, "uv on PATH", uv.detail),
            (claude.ok, "claude on PATH (Claude Code host)", claude.detail),
            (codex.ok, "codex on PATH (Codex host)", codex.detail),
            (npx.ok, "npx on PATH (OpenAlex MCP)", npx.detail),
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
            "[yellow]claude not found; choose Codex or install Claude Code "
            "before driving a Claude-hosted research session.[/yellow]"
        )
    if not codex.ok:
        _console.print(
            "[yellow]codex not found; choose Claude Code or install Codex "
            "before driving a Codex-hosted research session.[/yellow]"
        )
    if not npx.ok:
        _console.print(
            "[yellow]npx not found — OpenAlex literature search will be "
            "unavailable until Node.js/npm is installed. arXiv search still "
            "uses `uv tool run arxiv-mcp-server`.[/yellow]"
        )
    return True


# ---------------------------------------------------------------------------
# Step 2 — repo root
# ---------------------------------------------------------------------------


def step_repo_root(state: SetupState) -> bool:
    _heading(2, 8, "Repo root")
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
# Step 3 - agent host
# ---------------------------------------------------------------------------


def step_agent_host(state: SetupState) -> bool:
    _heading(3, 8, "Agent host")
    existing = io.read_env_file(state.env_path).get("CLAUDESCIENTIST_AGENT_HOST", "claude")
    if state.non_interactive:
        host = _env_flag("CLAUDESCIENTIST_SETUP_AGENT_HOST", existing)
    else:
        _console.print(
            "  claude: use the checked-in .claude settings.\n"
            "  codex: generate project-local .codex config, agents, and skills.\n"
            "  both: keep Claude Code support and add the Codex adapter."
        )
        host = _ask_select(
            state,
            "which agent host should drive ClaudeScientist?",
            list(agent_hosts.HOST_CHOICES),
            default=(
                existing
                if existing in agent_hosts.HOST_CHOICES
                else agent_hosts.HOST_CLAUDE
            ),
        )
        if state.aborted:
            return False
    normalized = agent_hosts.normalize_agent_host(host)
    if normalized != host:
        _console.print(f"  normalized agent host {host!r} -> {normalized!r}.")
    state.env_updates["CLAUDESCIENTIST_AGENT_HOST"] = normalized

    if normalized in {agent_hosts.HOST_CLAUDE, agent_hosts.HOST_BOTH}:
        result = agent_hosts.check_claude_support(state.repo_root)
        missing = [path for path in result.checked if not path.exists()]
        if missing:
            _console.print(
                "[yellow]Claude Code support files missing: "
                + ", ".join(str(path) for path in missing)
                + "[/yellow]"
            )
        else:
            _console.print("  Claude Code support files present.")

    if normalized in {agent_hosts.HOST_CODEX, agent_hosts.HOST_BOTH}:
        result = agent_hosts.ensure_codex_support(state.repo_root)
        if result.written:
            changed = "\n  - ".join(
                str(path.relative_to(state.repo_root)) for path in result.written
            )
            _console.print("  wrote Codex adapter files:\n  - " + changed)
        else:
            _console.print("  Codex adapter files already up to date.")
    return True


# ---------------------------------------------------------------------------
# Step 4 - embedding backend
# ---------------------------------------------------------------------------


_BACKEND_CHOICES = ("local", "mock", "openai")
_LOCAL_DEFAULT_MODEL = "Qwen/Qwen3-Embedding-0.6B"
_LOCAL_LEGACY_MODEL = "all-MiniLM-L6-v2"


def step_embed_backend(state: SetupState) -> bool:
    _heading(4, 8, "Embedding backend (proof trunk)")
    current = io.read_env_file(state.env_path).get(
        "RESEARCH_AGENT_EMBED_BACKEND", "local"
    )
    if state.non_interactive:
        backend = _env_flag("CLAUDESCIENTIST_SETUP_BACKEND", "local")
    else:
        _console.print(
            "  mock:   deterministic, no model download — used for tests.\n"
            "  local:  sentence-transformers, default Qwen3-Embedding-0.6B\n"
            "          (~600 MB multilingual); legacy users can pin "
            "all-MiniLM-L6-v2.\n"
            "  openai: any OpenAI-compatible endpoint (OpenAI, DashScope,\n"
            "          Jina, Voyage, GLM, …). Requires an API key."
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
        return _configure_local_backend(state)
    if backend == "openai":
        return _configure_openai_backend(state)
    return True


def _configure_local_backend(state: SetupState) -> bool:
    """Install the optional dep, pick a model, and hint about HF mirror."""
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

    # Model choice. Default is Qwen3-Embedding-0.6B (multilingual, ~600 MB).
    # Existing v4.1 users get asked once; their previous RESEARCH_AGENT_EMBED_MODEL
    # (if any) carries through as the default.
    existing_model = io.read_env_file(state.env_path).get(
        "RESEARCH_AGENT_EMBED_MODEL", ""
    )
    if state.non_interactive:
        chosen_model = (
            _env_flag("CLAUDESCIENTIST_SETUP_LOCAL_MODEL", existing_model)
            or _LOCAL_DEFAULT_MODEL
        )
    else:
        _console.print(
            f"\n  Default model: [cyan]{_LOCAL_DEFAULT_MODEL}[/cyan] "
            "(~600 MB, multilingual).\n"
            f"  Legacy option: [cyan]{_LOCAL_LEGACY_MODEL}[/cyan] "
            "(~80 MB, English-only).\n"
            "  Anything else accepted by sentence-transformers also works."
        )
        prompt_default = existing_model or _LOCAL_DEFAULT_MODEL
        chosen_model = _ask_text(
            state, "model name:", default=prompt_default
        ).strip() or prompt_default
        if state.aborted:
            return False

    state.env_updates["RESEARCH_AGENT_EMBED_MODEL"] = chosen_model

    # HF mirror hint when the chosen model lives on Hugging Face and the
    # user hasn't pointed HF_ENDPOINT at a mirror. We only print a hint;
    # we never set HF_ENDPOINT for the user, because that would silently
    # override an existing global override.
    if _looks_like_hf_model(chosen_model) and io.probe_hf_mirror() is None:
        _console.print(
            "\n  [dim]Note:[/dim] this model downloads from huggingface.co on "
            "first use.\n"
            "  Users on slow or restricted networks may want to set\n"
            "    [cyan]HF_ENDPOINT=https://hf-mirror.com[/cyan]\n"
            "  in their shell rc before the first cockpit launch."
        )

    if chosen_model != _LOCAL_LEGACY_MODEL:
        _console.print(
            "\n  [dim]The model downloads on first ingest call; subsequent "
            "runs use the cached weights.[/dim]"
        )
    return True


def _configure_openai_backend(state: SetupState) -> bool:
    """Pick a provider preset, set base_url + model, capture the API key."""
    existing_env = io.read_env_file(state.env_path)
    current_url = existing_env.get("RESEARCH_AGENT_EMBED_BASE_URL", "")
    current_model = existing_env.get("RESEARCH_AGENT_EMBED_MODEL", "")

    if state.non_interactive:
        preset_key = _env_flag("CLAUDESCIENTIST_SETUP_PROVIDER", "openai").lower()
    else:
        _console.print(
            "\n  Pick the OpenAI-compatible provider. The default 'openai' "
            "option targets api.openai.com; the others redirect via base_url."
        )
        preset_key = _ask_select(
            state,
            "provider:",
            [p.label for p in io.PROVIDER_PRESETS],
            default=io.PROVIDER_PRESETS[0].label,
        )
        if state.aborted:
            return False
        # Map label back to key.
        preset_key = next(
            (p.key for p in io.PROVIDER_PRESETS if p.label == preset_key),
            "openai",
        )

    preset = io.provider_preset(preset_key) or io.PROVIDER_PRESETS[0]

    # Resolve base_url:
    # - preset with explicit URL → use it
    # - preset "openai" (base_url=None) → clear any prior override
    # - preset "other" → ask the user; keep prior value as default
    if preset.key == "other":
        if state.non_interactive:
            chosen_url = _env_flag("CLAUDESCIENTIST_SETUP_BASE_URL", current_url)
        else:
            chosen_url = _ask_text(
                state, "base_url:", default=current_url
            ).strip()
            if state.aborted:
                return False
        if chosen_url:
            state.env_updates["RESEARCH_AGENT_EMBED_BASE_URL"] = chosen_url
    elif preset.base_url:
        state.env_updates["RESEARCH_AGENT_EMBED_BASE_URL"] = preset.base_url
    else:
        # OpenAI default — clear any prior override so the SDK uses its built-in.
        state.env_updates["RESEARCH_AGENT_EMBED_BASE_URL"] = ""

    # Resolve model name.
    if preset.key == "other":
        if state.non_interactive:
            chosen_model = _env_flag("CLAUDESCIENTIST_SETUP_REMOTE_MODEL", current_model)
        else:
            chosen_model = _ask_text(
                state, "model name:", default=current_model
            ).strip() or current_model
            if state.aborted:
                return False
    else:
        if state.non_interactive:
            chosen_model = _env_flag(
                "CLAUDESCIENTIST_SETUP_REMOTE_MODEL", preset.default_model
            )
        else:
            chosen_model = _ask_text(
                state, "model name:", default=preset.default_model
            ).strip() or preset.default_model
            if state.aborted:
                return False
    if chosen_model:
        state.env_updates["RESEARCH_AGENT_EMBED_MODEL"] = chosen_model

    # API key. All compatible providers accept a key through OPENAI_API_KEY
    # — that's the SDK's contract.
    key = (
        _env_flag("CLAUDESCIENTIST_SETUP_OPENAI_KEY", "")
        if state.non_interactive
        else _ask_text(state, "API key (OPENAI_API_KEY):", secret=True)
    )
    if state.aborted:
        return False
    if key:
        state.env_updates["OPENAI_API_KEY"] = key
    else:
        _console.print(
            "[yellow]no key provided — set OPENAI_API_KEY before launch.[/yellow]"
        )

    if preset.key != "openai":
        _console.print(
            f"\n  Provider [cyan]{preset.label}[/cyan] configured "
            f"({preset.notes}). The vector dimension is discovered on the "
            "first embedding call."
        )
    return True


def _looks_like_hf_model(model_name: str) -> bool:
    """Cheap heuristic: model identifiers that contain a slash usually map
    to a Hugging Face repo path (e.g. ``Qwen/Qwen3-Embedding-0.6B``,
    ``BAAI/bge-small-zh-v1.5``). Single-token names like
    ``all-MiniLM-L6-v2`` are also HF-hosted but ship with sentence-
    transformers' built-in registry, so the mirror warning is less
    urgent for them."""
    return "/" in (model_name or "")


# ---------------------------------------------------------------------------
# Step 5 - proof corpus seed
# ---------------------------------------------------------------------------


def step_seed_corpus(state: SetupState) -> bool:
    _heading(5, 8, "Proof corpus seed")
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
# Step 6 - held-out dir
# ---------------------------------------------------------------------------


def step_heldout_dir(state: SetupState) -> bool:
    _heading(6, 8, "Held-out dataset directory")
    home = str(Path.home())
    current = io.read_env_file(state.env_path).get(
        "RESEARCH_AGENT_HELDOUT_DIR", str(_DEFAULT_HELDOUT_DIR)
    )
    # Older setup builds used the whole home directory as the held-out root.
    # That makes the leakage guard treat normal user files as sequestered data.
    # Heal that legacy value on the next setup run.
    if Path(os.path.expandvars(os.path.expanduser(current))).resolve() == Path(home).resolve():
        current = str(_DEFAULT_HELDOUT_DIR)
    default_dir = (
        _env_flag("CLAUDESCIENTIST_SETUP_HELDOUT_DIR", current)
        if state.non_interactive
        else current
    )

    if state.non_interactive:
        chosen = default_dir
    else:
        _console.print(
            "  default: ~/.research-agent/heldout. Pick another path if you want\n"
            "  held-out registrations to live elsewhere (e.g. an external SSD)."
        )
        chosen = _ask_text(state, "held-out directory:", default=default_dir)
        if state.aborted:
            return False
    chosen = chosen.strip()
    if not chosen:
        chosen = str(_DEFAULT_HELDOUT_DIR)

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
# Step 7 - Lean detection
# ---------------------------------------------------------------------------


def step_lean(state: SetupState) -> bool:
    _heading(7, 8, "Lean reinsurance (optional)")
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
# Step 8 - auto-prune
# ---------------------------------------------------------------------------


def step_auto_prune(state: SetupState) -> bool:
    _heading(8, 8, "Auto-prune (suggest_pause_low_strength)")
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
        step_agent_host,
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
    _maybe_open_quickstart(state)
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
