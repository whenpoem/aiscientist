"""Helpers for the ``python -m claudescientist.setup`` wizard.

Four concerns, kept narrow:

1. **Probes** — read-only "is this tool / file / package available?" checks
   that drive step decisions. Probes never raise; they return ``(ok, info)``
   so the caller can render a one-line status.
2. **.env file IO** — load/merge/save so we don't trample the user's
   existing keys. We preserve comments and key order; new keys are
   appended in a clearly-marked block.
3. **subprocess wrappers** — for ``uv sync --extra proof`` and the seed
   scripts. Streams output in real time (so the user sees progress) and
   returns a status code.
4. **Provider presets and "open with default app"** (v4.2.0a0) — small
   tables and helpers shared by the embedding-backend step and the
   end-of-wizard quickstart prompt.

The questionary-based prompts live in ``setup.py`` itself; this module
is import-safe in CI / non-interactive paths.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Provider presets for the OpenAI-compatible embedding backend (ADR 0010).
#
# The tested set; users with another OpenAI-compatible provider can pick
# "Other" in the wizard and supply a base_url + model manually. The
# wizard never enforces the model name — providers add and retire
# models faster than this table can chase.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderPreset:
    """One row in the OpenAI-compatible provider menu."""

    key: str
    label: str
    base_url: str | None  # None = SDK default (api.openai.com)
    default_model: str
    notes: str


PROVIDER_PRESETS: tuple[ProviderPreset, ...] = (
    ProviderPreset(
        key="openai",
        label="OpenAI (api.openai.com)",
        base_url=None,
        default_model="text-embedding-3-large",
        notes="default; 3072-dim",
    ),
    ProviderPreset(
        key="dashscope",
        label="Aliyun DashScope",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_model="text-embedding-v3",
        notes="1024-dim; China-friendly",
    ),
    ProviderPreset(
        key="jina",
        label="Jina",
        base_url="https://api.jina.ai/v1",
        default_model="jina-embeddings-v3",
        notes="1024-dim; multilingual",
    ),
    ProviderPreset(
        key="voyage",
        label="Voyage",
        base_url="https://api.voyageai.com/v1",
        default_model="voyage-3",
        notes="1024-dim; retrieval-tuned",
    ),
    ProviderPreset(
        key="glm",
        label="GLM (Zhipu)",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        default_model="embedding-3",
        notes="2048-dim; China-friendly",
    ),
    ProviderPreset(
        key="other",
        label="Other (custom base_url)",
        base_url="",  # caller asks the user
        default_model="",
        notes="bring your own endpoint",
    ),
)


def provider_preset(key: str) -> ProviderPreset | None:
    """Look up a preset by its short key; returns None when unknown."""
    for preset in PROVIDER_PRESETS:
        if preset.key == key:
            return preset
    return None

# ---------------------------------------------------------------------------
# Probes (read-only environment inspection)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProbeResult:
    """One-line status for a probe.

    ``ok`` drives whether setup proceeds; ``detail`` is the human label
    we render next to the check (e.g. ``"Python 3.11.5"``).
    """

    ok: bool
    detail: str


def probe_python() -> ProbeResult:
    major, minor = sys.version_info.major, sys.version_info.minor
    label = f"Python {major}.{minor}.{sys.version_info.micro}"
    return ProbeResult(ok=(major, minor) >= (3, 11), detail=label)


def probe_uv() -> ProbeResult:
    path = shutil.which("uv")
    if path:
        return ProbeResult(ok=True, detail=path)
    return ProbeResult(ok=False, detail="uv not on PATH")


def probe_claude() -> ProbeResult:
    """Soft probe — claude CLI is recommended but not required for setup."""
    path = shutil.which("claude")
    if path:
        return ProbeResult(ok=True, detail=path)
    return ProbeResult(ok=False, detail="claude not on PATH (install Claude Code)")


def probe_npx() -> ProbeResult:
    """Soft probe for the OpenAlex literature MCP."""
    path = shutil.which("npx")
    if path:
        return ProbeResult(ok=True, detail=path)
    return ProbeResult(ok=False, detail="npx not on PATH (OpenAlex MCP disabled)")


def probe_lean_toolchain() -> tuple[bool, list[str]]:
    """Returns ``(all_present, missing)`` for elan + lake + lean."""
    needed = ("elan", "lake", "lean")
    missing = [t for t in needed if shutil.which(t) is None]
    return (not missing, missing)


def probe_sentence_transformers() -> bool:
    """Cheap import probe for the local embedding backend.

    Avoids actually constructing a model — just verifies the package is
    installed in the active interpreter so step 3 knows whether
    ``uv sync --extra proof`` already happened.
    """
    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        return False
    return True


def probe_repo_root(start: Path) -> Path | None:
    """Walk up from ``start`` looking for the claudescientist repo root.

    A directory qualifies if it contains BOTH ``pyproject.toml`` AND a
    ``.claude`` folder. We require both so a random project's pyproject
    doesn't false-positive when the user runs setup from the wrong dir.
    Returns ``None`` if no ancestor matches.
    """
    cur = start.resolve()
    for candidate in (cur, *cur.parents):
        if (candidate / "pyproject.toml").exists() and (candidate / ".claude").is_dir():
            return candidate
    return None


# ---------------------------------------------------------------------------
# .env file IO
# ---------------------------------------------------------------------------


def read_env_file(path: Path) -> dict[str, str]:
    """Parse ``.env`` into a dict, ignoring comments and blank lines.

    Best-effort parse — quoting and escapes are NOT honored. We assume
    setup-managed values are simple identifiers / paths / 0-or-1 flags.
    Anything fancier the user pre-edits and we leave alone (see
    ``update_env_file`` for the merge strategy).
    """
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def update_env_file(path: Path, updates: dict[str, str]) -> None:
    """Apply ``updates`` to the .env at ``path`` non-destructively.

    - Existing keys are rewritten in place (preserving line position so
      diffs stay small in dotfile repos).
    - New keys are appended in a clearly-marked block at the end.
    - Comments and blank lines elsewhere are preserved verbatim.
    - When the file does not exist, a fresh one is created with a
      header explaining provenance.

    Callers should NOT pass values containing newlines or unbalanced
    quotes; setup only writes simple paths and ``0``/``1`` flags.
    """
    if not updates:
        return
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# claudescientist environment configuration",
            "# Generated by `python -m claudescientist.setup`. Edit freely;",
            "# re-running setup will preserve any keys it does not own.",
            "",
        ]
        for k, v in updates.items():
            lines.append(f"{k}={v}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return

    existing = path.read_text(encoding="utf-8").splitlines()
    output: list[str] = []
    seen: set[str] = set()
    for line in existing:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates and key not in seen:
                output.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        output.append(line)

    new_keys = [k for k in updates if k not in seen]
    if new_keys:
        # Trailing-blank discipline: leave exactly one blank line before
        # our appended block so the diff is readable.
        if output and output[-1].strip() != "":
            output.append("")
        output.append("# Appended by claudescientist setup")
        for k in new_keys:
            output.append(f"{k}={updates[k]}")

    path.write_text("\n".join(output) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Subprocess wrappers
# ---------------------------------------------------------------------------


def run_streaming(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> int:
    """Run ``cmd`` and stream its stdout/stderr to the parent terminal.

    Returns the child's exit code. Used for ``uv sync --extra proof``
    and the corpus-seed scripts so the user sees real-time progress on
    long-running operations rather than a frozen splash.

    On Windows, we explicitly pass ``shell=False`` and a list[str] to
    avoid shell-quoting surprises with paths containing spaces.
    """
    if env is None:
        env = os.environ.copy()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd is not None else None,
            env=env,
            shell=False,
            check=False,
        )
    except FileNotFoundError as e:
        print(f"  ! command not found: {cmd[0]} ({e})")
        return 127
    return proc.returncode


def probe_hf_mirror() -> str | None:
    """Return the value of ``HF_ENDPOINT`` if the user has set one.

    ``HF_ENDPOINT`` is the standard way to point Hugging Face's
    transformers / sentence-transformers downloaders at a mirror —
    typically ``https://hf-mirror.com`` for China-resident users. The
    wizard reads this to decide whether to suggest setting it before
    pulling Qwen3-Embedding-0.6B (a ~600 MB download from
    huggingface.co).
    """
    value = os.environ.get("HF_ENDPOINT", "").strip()
    return value or None


def open_file_with_default_app(path: Path) -> bool:
    """Open ``path`` with the user's default registered application.

    Routes to ``os.startfile`` on Windows, ``open`` on macOS, and
    ``xdg-open`` on Linux. Returns True when the launch call
    apparently succeeded; False on FileNotFoundError (no handler
    installed) or OSError (path inaccessible). The wizard uses this to
    open the first-task walkthrough at the end of setup; the cockpit
    uses it to open generated report files.

    This helper does not block on the spawned process — markdown
    viewers and browsers run independently of the terminal session
    that asked for them.
    """
    sysname = platform.system()
    try:
        if sysname == "Windows":
            os.startfile(str(path))  # noqa: S606 - Windows-specific by design
            return True
        if sysname == "Darwin":
            result = subprocess.run(
                ["open", str(path)],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return result.returncode == 0
        # Linux and anything else POSIX-shaped.
        result = subprocess.run(
            ["xdg-open", str(path)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return result.returncode == 0
    except (OSError, FileNotFoundError):
        return False


__all__ = [
    "ProbeResult",
    "ProviderPreset",
    "PROVIDER_PRESETS",
    "open_file_with_default_app",
    "probe_python",
    "probe_uv",
    "probe_claude",
    "probe_npx",
    "probe_hf_mirror",
    "probe_lean_toolchain",
    "probe_sentence_transformers",
    "probe_repo_root",
    "provider_preset",
    "read_env_file",
    "update_env_file",
    "run_streaming",
]
