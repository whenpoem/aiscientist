# ADR 0008: Two-trunk domain architecture (empirical + proof) on a shared core

- **Status**: Accepted (v4.0)
- **Date**: 2026-05

## Context

ClaudeScientist v3.0 shipped as a single-domain tool: an augmentation layer
for ML-style empirical research, where the differentiation is reproducibility
machinery (preregistration, multi-seed verdicts, held-out budget,
provenance DAG, calibrated reviewer gate). That trunk works.

In April 2026 the StatAI Lab released **StatProver**, a closed-source
LLM-driven NL proof assistant for statistics, built on a 40k-problem corpus
(StatEval) and an 80k empirical fault repository. It demonstrated real
product surface for "automated statistical proof" and made it concrete that
ClaudeScientist's user base would soon want this capability — not as a
toy, but as a peer to the empirical workflow. Three options surfaced:

1. **Add proof as a feature on the existing trunk** — keep the v3.0 narrative;
   bolt proof tools onto verify_mcp.
2. **Pivot: proof becomes the main trunk, ML demoted** — restage as a
   StatProver competitor.
3. **Two trunks on a shared core** — empirical and proof coexist, sharing
   the parts of the architecture that are already domain-agnostic.

Option 1 leaves a proof user staring at `seed_perturb`, `query_heldout`,
`baseline_fairness`, and `leakage_check` — none of which apply. Option 2
discards the v3.0 reproducibility differentiation that StatProver does not
have, and enters a corpus-and-error-repo arms race we cannot win. The
existing core (`mem_nodes`, `mem_failures`, `mem_bt_ratings`, calibration,
replay, cockpit, basic hooks) is already domain-free in everything but
naming; only the verify-side ML primitives are truly empirical-specific.

A real statistical research project moves between trunks: simulation →
proposition → proof → empirical validation. Splitting that into two
products would force users to bridge by hand.

## Decision

Adopt option 3. ClaudeScientist v4.0 has **two trunks under one
domain-agnostic core**:

**Shared core** (no domain knowledge):
- `claudescientist.runtime` (state.db, migrations, event emission)
- `mem_nodes` / `mem_edges` — single hypothesis/proposition graph; `kind`
  CHECK constraint extended with `proposition`, `proof_skeleton`,
  `proof_snippet` so both trunks share the tree
- `mem_failures` — gains `domain TEXT NOT NULL DEFAULT 'empirical'`;
  `record_failure` and `match_signatures` accept an optional `domain`
  filter, with cross-domain match as the default
- `mem_bt_ratings` + tournament — kind check relaxed to allow
  `proof_skeleton` vs `proof_skeleton` comparisons; cross-kind comparison
  remains forbidden
- `meta_calibration`, `mem_replay_branches`, cockpit, event bus,
  destructive-bash and intervention-pump hooks

**Empirical trunk** (existing, unchanged in scope):
- `verify_mcp`: leakage, heldout, seed, baseline fairness, preregistration,
  provenance DAG, pin_metric, budget
- Hooks: `leakage_guard.py`, `provenance_log.py`
- Agents: engineer, verifier

**Proof trunk** (new in v4.0):
- `prove_mcp` — a third MCP server registered alongside `memory_mcp` and
  `verify_mcp`. Owns tables `prv_corpus_problems`, `prv_corpus_keywords`,
  `prv_diagnostic_manifests`, `prv_lean_attempts`. Tools cover corpus
  ingest, bidirectional max-matching retrieval, proof segmentation,
  snippet diagnosis (which queries `mem_failures` with `domain='proof'`),
  global correction, and Lean triage.
- Lean reinsurance via the third-party `lean-lsp-mcp` package, gated by a
  `triage_for_formalization` rule so only eligible propositions are
  attempted.
- Agents: prover (the v0.1 stub is activated), reviewer (gains a parallel
  proof checklist).

**Cooperation interfaces** between the two trunks — exactly four, no more:

1. **One tree.** Empirical hypotheses and proof propositions are siblings
   under the same question node.
2. **One failure ledger.** `mem_failures` is cross-domain; an off-by-one
   that surfaced in a script can flag the same off-by-one in a proof.
3. **One BT leaderboard.** Proof skeletons compete in the same
   tournament structure; cross-kind comparison stays disallowed to keep
   semantics clean.
4. **One reviewer, two checklists.** `reviewer.md` switches checklist by
   manuscript content: empirical claims keep the existing four gates
   (pin / seed verdict / met preregistration / fresh provenance);
   theorem claims add an empty diagnostic manifest plus either a Lean
   verification or an explicit `unverified` flag.

The new MCP server is justified despite the v3.0 default of "no new MCP
server" (see archive plan-v3.0): a domain expansion at this size is the
exception that example was always meant to allow. The core/trunk split is
documented in [`docs/architecture.md`](../architecture.md) §13.

## Consequences

### Positive

- v3.0 reproducibility differentiation is preserved; ML users see no
  regression. A v3.x deployment continues to work with `RESEARCH_AGENT_DB`
  files unmodified.
- Proof workflows inherit BT, calibration, provenance, replay,
  preregistration ("preregister this lemma's empirical companion test"),
  and the cockpit for free.
- Cross-domain failure matching is a real differentiator: a single
  `match_signatures` call can surface analogous mistakes from either
  trunk, which neither single-trunk product offers.
- Reviewer's existing JSON contract extends additively; `numeric_claims`
  stays exactly as ADR 0006 fixed it, and `theorem_claims` is the only
  new top-level key.

### Negative

- Two trunks = more documents, more tests, more onboarding load. The
  module maps in `memory_mcp/__init__.py` and `verify_mcp/__init__.py`
  carry per-tool `[core]` / `[empirical]` tags so contributors do not
  have to guess.
- Some `verify_mcp` tools become "empirical-only" but still appear in
  the global tool catalog. We accept the catalog clutter rather than
  fragment users by mode.
- Cross-domain `match_signatures` recall depends on signature semantics
  staying compatible across domains. For now both domains store
  natural-language `(trigger, symptom, root_cause, resolution)`; if
  domain-specific structured fields ever diverge, the cross-domain match
  will silently weaken.
- We cannot out-corpus StatProver. The product wedge is workflow
  integration (proof + empirical + reviewer + cockpit + reproducibility),
  not raw retrieval quality.

### Alternatives considered

- **Proof as a feature on the existing trunk** — lost because empirical
  verify primitives become noise in proof workflows, and the reviewer
  contract grows confusingly.
- **Pivot to proof-only; demote ML** — lost because we gain no advantage
  StatProver does not already have, while discarding the v3.0
  reproducibility differentiation that is genuinely ours.
- **Two independent products sharing nothing** — lost because the shared
  failure ledger, the cross-trunk BT, and the dual-checklist reviewer are
  the actual moat; without them the two halves do not compound.
- **Stay single-trunk and decline the proof direction** — lost because
  the user has explicitly chosen to enter the statistical-proof space
  and matching StatProver's product surface is the stated goal.

## References

- Originating discussion: plan file
  `C:\Users\whenpoem\.claude\plans\snazzy-twirling-donut.md`.
- Reverses: [`docs/roadmap.md`](../roadmap.md) "Wire in Lean formal
  proofs" was on the explicit do-not-do list; this ADR moves it under the
  Proof Trunk direction.
- StatProver inspiration (not adoption): StatAI Lab, "StatProver
  Technical Report" (April 2026).
- Implementation phasing: P0 (this ADR + ADR 0007 + architecture §13),
  P1 core domain-agnostic refactor, P2-P4 proof trunk build, P5
  cooperation surface.
- Sister ADR: [`0007-tools-skills-hooks-layering.md`](0007-tools-skills-hooks-layering.md)
  pins the discipline that keeps the proof trunk from collapsing into a
  pipeline.
- Code that depends on this decision (post-P5): `src/prove_mcp/*`,
  `src/memory_mcp/tools/failures.py`, `src/memory_mcp/tools/bt.py`,
  `.claude/agents/reviewer.md`, `.claude/agents/prover.md`,
  `.claude/skills/prove-sop/`.
