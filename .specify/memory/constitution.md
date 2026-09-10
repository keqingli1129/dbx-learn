# Smart Claims Constitution

## Core Principles

### I. Test Discipline (NON-NEGOTIABLE)

Automated tests are REQUIRED. This was declared at specification time (spec.md FR-044) and is not
reopenable during implementation.

- `tests/unit/` MUST run offline: no Spark session, no workspace connection, no configured profile.
- `tests/integration/` MUST carry the `workspace` marker and MUST skip cleanly when no profile is
  available.
- Tests MUST be written before the implementation they cover, and MUST be observed failing before
  that implementation exists. A test that passes before its subject is written tests nothing.
- Test files are part of the deliverable. They MUST be committed alongside implementation code and
  MUST NOT be discarded once green.
- Declarative pipeline expectations enforce data quality at runtime. They are NOT a substitute for
  the test suite, and their presence MUST NOT be offered as a reason to omit tests.

**Rationale**: a data platform fails silently. Wrong dates, a fanned-out join, or a rule that scores
missing data as passing all produce plausible-looking tables. Offline tests are the only check that
runs before anything reaches the workspace.

### II. Testable Logic Boundary

Transformation, decoding, cleaning and decision logic MUST live in `src/smart_claims/lib/` as pure
Python with no Spark import, and MUST be imported by pipeline code rather than duplicated in it.

Logic written inline inside a `@dp.table` body is a defect and MUST be rejected in review, however
short it is.

**Rationale**: `databricks-connect` is a dependency of this repository and cannot coexist with a
local `pyspark` install (research R10), so no offline Spark session is available. Separating pure
logic from its Spark wrappers is therefore not a style preference — it is the only mechanism by
which Principle I can be satisfied at all.

### III. One Writer Per Table

Every Unity Catalog table MUST have exactly one owning pipeline or job, as recorded in
`contracts/pipeline-datasets.md`.

A table written by two producers is a defect, not a configuration choice.

**Rationale**: two writers produce non-deterministic refresh ordering, make lineage meaningless, and
turn an incremental refresh into a race. The failure is intermittent and therefore expensive to
diagnose later.

### IV. Reproducible From The Repository

Every workspace asset MUST be declared in version-controlled bundle configuration and MUST deploy
from a clean checkout. Manual console configuration is NOT permitted.

Where no bundle resource type exists — Genie spaces being the known case (research R2) — an
idempotent script driven by the same configuration values the bundle uses is REQUIRED. A documented
click-path is not an acceptable substitute.

**Rationale**: the source transcript builds everything through the user interface. That teaches the
concepts well and reproduces nothing. A second source of truth for configuration is how deployments
drift.

### V. No Real Personal Data (NON-NEGOTIABLE)

All customer, policy, claim, telematics and image data MUST be synthetic.

The claims portal has no authentication by design. It MUST NOT be exposed to real claimants, and
real personal data MUST NOT be loaded into any part of this system.

**Rationale**: this is a learning artifact modelling an insurance workflow — a domain whose real data
is sensitive by definition. The absent authentication is an accepted trade-off *only* under the
condition that nothing real is ever present.

### VI. Modern Pipeline API Only

Pipeline code MUST use `from pyspark import pipelines as dp`.

The legacy surface is FORBIDDEN: `import dlt`, `@dlt.*` decorators, the `LIVE.` prefix,
`APPLY CHANGES`, and `dlt.apply_changes`. Use `dp.create_auto_cdc_flow`,
`spark.readStream.table(...)`, `CREATE OR REFRESH STREAMING TABLE` and `AUTO CDC INTO` instead.

**Rationale**: the source transcript predates the rename, so transcribing its code literally
produces something that does not run — `LIVE.` errors outright on current runtimes. Writing the
modern API from the start avoids a migration that would otherwise touch every pipeline file.

### VII. Honest Degradation

Where a Free Edition capability proves unavailable, the substitution and its measured consequence
MUST be recorded in `research.md`.

- Requirements MUST NOT be silently dropped.
- Success criteria MUST NOT be silently relaxed; a relaxation MUST be stated, with the measured
  value that replaced the target.
- Known open items MUST be resolved by an early spike with a predetermined fallback, so that no
  dependent work is built atop an unverified assumption.

**Rationale**: the two open capability questions at planning time — custom model serving and
Lakebase — each have a fallback that changes what the system can claim. A fallback taken quietly
becomes a false claim in the documentation.

## Platform Constraints

- **Serverless compute only.** No classic clusters, no GPU, no instance pools.
- **Explicit profile always.** Every CLI invocation MUST pass `--profile DEFAULT`. Relying on the
  configured default profile is NOT permitted, in code, in documentation, or in examples.
- **Workspace isolation.** This project MUST NOT modify or remove the workspace's unrelated
  catalogs — `test`, `my_files`, `bridge_monitoring`, `claudecatalog` — or the pre-existing
  `agent-langgraph-agent-one` app. Teardown MUST be verified against this.
- **Quota discipline.** Continuous pipelines MUST be stopped after their demonstration. A forgotten
  continuous pipeline will exhaust the tier's serverless quota.
- **No external services.** No external object storage, database, streaming service, or cloud IAM
  role is available. Designs requiring one MUST be substituted and recorded under Principle VII.

## Development Workflow

Execution is subagent-driven: for each dispatch group, an implementer subagent produces the work, a
reviewer subagent gates it, and a fix loop runs until the review is clean.

**Reviewer obligations**:

- Source Global Constraints from `spec.md` functional requirements and success criteria,
  `plan.md` Technical Context, and this constitution.
- Verify test files are present **in the diff** — not merely quoted in the implementer's report —
  and that RED/GREEN evidence is included (Principle I).
- Verify no logic was written inline in a pipeline decorator (Principle II).
- Verify no table gained a second writer (Principle III).
- When a group modifies code an earlier phase built, cross-reference the *original* story's
  requirements in `spec.md`, not only the current story's — the change MUST NOT break what the
  earlier story already guaranteed.

**Implementer obligations**:

- When modifying a file an earlier phase created, read its current state and its existing test file
  first; update that test in place rather than adding a parallel one.
- Re-run the full test suite for a modified file, not only the new assertion, before committing.

## Governance

This constitution supersedes other practices for this project. Where it conflicts with a habit, a
template default, or a convenience, this document governs.

**Amendment procedure**: amendments are made by updating this file with a version bump and a
recorded rationale. An amendment that removes or weakens a NON-NEGOTIABLE principle requires an
explicit, recorded decision by the project owner — it MUST NOT be made to unblock a failing task.

**Versioning policy**: semantic versioning.

- **MAJOR** — a principle is removed or redefined in a backward-incompatible way.
- **MINOR** — a principle or section is added, or guidance materially expanded.
- **PATCH** — clarification, wording, or non-semantic refinement.

**Compliance review**: every reviewer gate checks compliance with the principles above. Complexity
that appears to violate a principle MUST be justified in `plan.md`'s Complexity Tracking table, with
the simpler alternative named and the reason for rejecting it stated. An unjustified violation is a
review failure, not a judgement call.

**Runtime guidance**: `docs/001-smart-claims/plan.md` and `docs/001-smart-claims/tasks.md` carry the
operational detail. This constitution carries only what must not be traded away.

**Version**: 1.0.0 | **Ratified**: 2026-09-09 | **Last Amended**: 2026-09-09
