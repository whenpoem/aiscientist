# Setup: Lean reinsurance layer (P4)

> One-time setup so the proof trunk's `prover` subagent can call into a real Lean 4 toolchain via `lean-lsp-mcp`. Skip this guide if you only want the NL proof workflow (P2 + P3); the proof trunk is fully usable without Lean.

This guide is **manual** by design. The third-party `lean-lsp-mcp`, the Lean toolchain, and mathlib4 are all heavyweight installs (~2-3 GB total, ~15 minutes of compile time on first import). Automating their install inside `uv sync` would punish every contributor who never wants Lean. Run this once when you want reinsurance.

## 1. Install elan (the Lean version manager)

**Windows (PowerShell)**:

```powershell
# Verify you have curl + tar from Windows. Most Win11 builds do.
curl -L "https://raw.githubusercontent.com/leanprover/elan/master/elan-init.ps1" -o elan-init.ps1
powershell -ExecutionPolicy Bypass -File elan-init.ps1 -y
# Restart your shell so $env:PATH picks up %USERPROFILE%\.elan\bin
```

**macOS / Linux**:

```bash
curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf | sh -s -- -y
```

Verify:

```powershell
elan --version
lean --version   # should print "Lean (version 4.x...)"
```

## 2. Install `lean-lsp-mcp`

The MCP wrapper itself is a Python package on PyPI; it is small (~5 MB).

```powershell
uv tool install lean-lsp-mcp
```

Verify:

```powershell
uv tool run lean-lsp-mcp --help
```

If you get `command not found`, ensure `%USERPROFILE%\.local\bin` (or your platform equivalent) is on PATH.

## 3. Bootstrap a mathlib4 project for the prover

The `prover` agent runs Lean inside a project that depends on mathlib4. Create a dedicated checkout under `.research-agent/lean/`:

```powershell
cd D:\aiscientist\claudescientist
mkdir -Force .research-agent\lean
cd .research-agent\lean
lake new claudescientist-proofs math
cd claudescientist-proofs
lake update
lake exe cache get   # downloads precompiled mathlib (~2 GB, ~10 minutes first time)
lake build
```

The cache fetch is the long step. It only happens once per Lean toolchain version.

## 4. Activate the lean MCP server

`.claude/settings.json` registers a `lean` mcpServer block but **leaves it commented-out by default** so contributors who skipped this guide do not see startup errors. To activate, edit the file and remove the leading underscore on the key:

```json
{
  "mcpServers": {
    "lean": {
      "command": "uv",
      "args": ["tool", "run", "lean-lsp-mcp"],
      "env": {
        "LEAN_PROJECT_PATH": "D:/aiscientist/claudescientist/.research-agent/lean/claudescientist-proofs"
      }
    }
  }
}
```

Restart the Claude Code session after editing settings.json.

## 5. Smoke test

Open Claude Code in the project. Ask the prover agent to verify the smallest possible spike lemma:

```
@prover prove that for any two real numbers a, b: a + b = b + a (use Lean's add_comm)
```

Expected behaviour:

1. Triage returns `eligible=True` (short text, "real numbers" not blacklisted).
2. `mcp__lean__lean_verify` accepts a one-liner like `theorem ex_addcomm (a b : ℝ) : a + b = b + a := add_comm a b`.
3. Prover calls `record_lean_attempt(status='verified', ...)` and `attach_evidence(polarity='supports', ...)`.
4. The cockpit Event Stream shows a `lean_proof_succeeded` event.

If any step fails with a path or version error, see Troubleshooting below.

## 6. Spike lemma list (P4 exit criterion)

The P4 phasing-plan goal is to verify at least 3 of the following 5 lemmas inside a 30-minute prover budget per lemma. These are deliberately chosen to be inside mathlib's coverage:

1. `theorem sample_mean_linearity (n : ℕ) (X : Fin n → ℝ) : (1/n : ℝ) * ∑ i, X i = ∑ i, (1/n : ℝ) * X i`
2. `theorem chebyshev_inequality {Ω : Type*} [MeasurableSpace Ω] (μ : Measure Ω) ...` (use `MeasureTheory.meas_ge_le_variance_div`)
3. `theorem cauchy_schwarz_finite_l2 ...` (use `inner_mul_le_norm_mul_norm` from `Mathlib.Analysis.InnerProductSpace.Basic`)
4. `theorem bonferroni_upper_bound (n : ℕ) (p : ℝ) : 1 - (1-p)^n ≤ n * p`
5. `theorem markov_inequality (X : ℝ → ℝ) ...` (use `MeasureTheory.meas_ge_le_integral_div`)

The exact statement choice depends on mathlib version. Use `mcp__lean__lean_leansearch` to discover the canonical name when drafting.

## Troubleshooting

- **"lake: command not found"** -- elan didn't add itself to PATH. Re-source your shell or add `%USERPROFILE%\.elan\bin` manually.
- **`lake exe cache get` is slow** -- expected first time (~10 min). Subsequent runs use the local cache.
- **`lean-lsp-mcp` fails to start** -- check `LEAN_PROJECT_PATH` points at the directory containing `lakefile.lean`, not its parent.
- **Mathlib import errors** -- run `lake build` once before invoking the prover; Lean's first-touch import builds proof obligations.
- **Windows path with spaces** -- prefer a path under `D:\` with no spaces. The mathlib build tooling has historically been sensitive to spaces.

## Why this is opt-in

ADR 0008 spells out: Lean is *reinsurance*, not the proof trunk's main path. The NL workflow (corpus retrieval, draft, segment, diagnose, correction) does not require any Lean machinery. A repo without lean-lsp-mcp installed should still pass `uv run pytest` and produce reviewer-acceptable proof manuscripts (with the proposition's `formal_proof_status` marked `unverified`). Lean is the strongest-possible-evidence ceiling, not the floor.
