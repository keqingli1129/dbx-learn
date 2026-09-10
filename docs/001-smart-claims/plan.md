# Implementation Plan: Smart Claims — End-to-End Insurance Lakehouse

**Branch**: `001-smart-claims` | **Date**: 2026-09-09 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `docs/001-smart-claims/spec.md`

## Summary

Reproduce the seven-part Databricks project from `transcript.txt` as a bundle-deployed,
version-controlled implementation on a Free Edition workspace: a `smart_claims_dev` catalog with
five schemas, three ingestion paths, a quality-enforced medallion transformation, a governed
image classifier, a data-driven triage rules engine, and three consumption surfaces including a
FastAPI claims portal.

The technical approach follows from three findings established during Phase 0 research rather
than assumed. First, serverless has **working outbound internet** but ships **no deep-learning
stack** — so the public image dataset is fetched at setup and `torch`/`torchvision` are declared
as environment dependencies. Second, **Asset Bundles cover every resource type this feature needs
except Genie spaces** — so everything is declared in `databricks.yml` and the single exception is
a scripted post-deploy step, not a manual click. Third, **`databricks-connect` in this repo
precludes a local Spark session** — so transformation logic is written as pure functions in an
importable library with thin Spark wrappers, which is what makes the required offline test suite
possible at all.

The external AWS dependencies are replaced without loss of the underlying lessons: Delta change
data feed stands in for SQL Server CDC (a genuine transaction-log feed, so the insert/update/
delete verification is real rather than circular), and base64-encoded JSON files stand in for the
Kinesis byte payload (preserving the decode-to-typed-columns step exactly).

## Technical Context

**Language/Version**: Python 3.11 on serverless (Spark 4.2.0); Python 3.12 locally

**Primary Dependencies**: `pyspark.pipelines` (Lakeflow Declarative Pipelines, modern API — not
`dlt`), Auto Loader, Auto CDC, MLflow (pinned ≥ 3.x in the training environment; base image ships
2.11.4), `torch` + `torchvision` (declared, absent from base), FastAPI, `psycopg2` (present),
Databricks Asset Bundles via CLI v1.15.0

**Storage**: Unity Catalog — `smart_claims_dev` with `source`, `landing`, `bronze`, `silver`,
`gold`. Managed volumes only; no external location available. Optional Lakebase Postgres serving
copy, conditional on spike S2.

**Testing**: `pytest`. `tests/unit/` runs offline with no Spark and no workspace;
`tests/integration/` is marked `workspace` and uses `databricks-connect~=18.0.0` (already a dev
dependency; Java 21 present locally).

**Target Platform**: Databricks Free Edition, `DEFAULT` profile,
`https://dbc-b5c9918e-c2d2.cloud.databricks.com`. Serverless compute exclusively.

**Project Type**: Data and ML platform with a web application — a bundle-deployed lakehouse plus a
FastAPI Databricks App.

**Performance Goals**: Claim detail view populated < 2 s (SC-015). Claim submission through to
decision < 2 min (SC-014). Hourly end-to-end refresh. Model accuracy is measured and recorded,
not thresholded (SC-009) — CPU-only training makes any target arbitrary.

**Constraints**: No GPU. No classic compute. No external object storage, database, streaming
service or cloud IAM. Custom model serving and Lakebase instance creation both **unverified** and
carried as spikes with predetermined fallbacks. Must not disturb the workspace's five unrelated
catalogs or its pre-existing app.

**Scale/Scope**: ~1,000 customers, ~1,200 policies, ~1,300 claims, a few hundred labelled images,
telematics in the low tens of thousands of rows. Seven user stories; roughly 25 tables, three
pipelines, three jobs, one dashboard, one Genie space, one app.

## Constitution Check

*GATE: must pass before Phase 0. Re-checked after Phase 1.*

**Status: VACUOUS — no ratified principles.**

`.specify/memory/constitution.md` exists but is the unmodified spec-kit template: every principle
is still a `[PRINCIPLE_N_NAME]` placeholder and the version is `[CONSTITUTION_VERSION]`. There are
no gates to evaluate, so this check cannot fail and cannot provide assurance either.

This is reported rather than quietly passed because it has a concrete downstream consequence: the
project workflow sources reviewer context partly from the Constitution Check, and reviewers will
have nothing to check against beyond `spec.md` and this plan. Two options:

- Run `/speckit-constitution` before execution begins and ratify a small set of principles
  (test discipline, one-writer-per-table, no manual console steps, no real personal data). This
  is the recommendation — the fourth in particular is a genuine safety property of this feature.
- Proceed without one, accepting that reviewers gate on `spec.md`'s functional requirements and
  this plan's Technical Context alone.

**Post-Phase-1 re-check**: unchanged — still vacuous. Nothing in the Phase 1 design introduces a
constitutional violation, because there is no constitution to violate.

## Project Structure

### Documentation (this feature)

```text
docs/001-smart-claims/
├── spec.md               # PRD — 7 user stories, 44 FRs, 17 SCs
├── plan.md               # This file
├── research.md           # Phase 0 — empirical workspace findings, 10 decisions
├── data-model.md         # Phase 1 — catalog layout, table schemas, severity domain
├── quickstart.md         # Phase 1 — deploy and validation walkthrough
├── contracts/
│   ├── app-api.md        # Claims portal HTTP API
│   ├── rules-engine.md   # Rule store and three-valued evaluation
│   └── pipeline-datasets.md  # Pipeline ownership boundaries
├── checklists/
│   └── requirements.md   # Spec quality validation
└── tasks.md              # Phase 2 — /speckit-tasks output, NOT created by this command
```

### Source Code (repository root)

```text
databricks.yml                      # bundle root, target: dev
resources/
├── catalog.yml                     # catalog, 5 schemas, 4 volumes
├── setup.job.yml                   # bootstrap: seed source data, fetch images
├── ingest.pipeline.yml             # bronze; continuous flag + config keys
├── transform.pipeline.yml          # silver + gold MVs
├── ml.job.yml                      # resize, train, score, seed rules, triage
├── orchestration.job.yml           # hourly: ingest -> transform -> triage
├── cdc_mutation.job.yml            # insert/update/delete verification (US3)
├── telematics_producer.job.yml     # writes JSON event files (US2)
├── dashboard.yml                   # AI/BI dashboard resource
└── app.yml                         # FastAPI app + resources

src/smart_claims/
├── lib/                            # PURE PYTHON — no Spark import, offline-testable
│   ├── severity.py                 # the one severity domain + label mapping
│   ├── payload.py                  # base64 -> JSON -> typed dict
│   ├── cleaning.py                 # name split, address normalise, date coercion
│   └── decision.py                 # fold check results -> overall outcome
├── setup/
│   ├── seed_source_data.py         # synthetic customers/policies/claims (with deliberate defects)
│   └── fetch_training_images.py    # egress check, download, write to volume
├── ingest/
│   ├── telematics.py               # Auto Loader + decode
│   ├── cdc.py                      # Auto CDC from Delta change feed
│   └── objectstore.py              # binaryFile, CSV drift, cleanSource archive
├── transform/
│   ├── bronze_to_silver.py         # expectations + calls into lib.cleaning
│   └── silver_to_gold.py           # aggregation MV + join MVs
├── ml/
│   ├── resize_images.py
│   ├── train_classifier.py         # ResNet-18, MLflow, UC register + @prod
│   ├── batch_score.py              # spark_udf
│   ├── seed_rules.py               # populate gold.claims_rules
│   └── evaluate_rules.py           # generic three-valued evaluator
├── genie/
│   └── create_space.py             # scripted — no bundle resource type exists
└── app/
    ├── main.py                     # FastAPI
    ├── repository.py               # ClaimsRepository interface
    ├── repository_lakebase.py      # \
    ├── repository_warehouse.py     #  > selected at startup; spike S2 decides
    └── static/                     # simple frontend, customer + admin modes

dashboards/
└── claims_investigation.lvdash.json

tests/
├── unit/                           # offline, always runs (SC-016)
│   ├── test_payload.py
│   ├── test_cleaning.py
│   ├── test_severity.py
│   └── test_decision.py
└── integration/                    # marked `workspace`, needs a profile
    ├── test_rules_engine.py
    └── test_cdc_propagation.py
```

**Structure Decision**: a single Python package `src/smart_claims/` mirrored by `tests/`, with
bundle resources in `resources/`. The repository is already a `uv`-managed Python project, so this
extends what exists rather than introducing a second layout.

The division that matters is `lib/` versus everything else. `lib/` contains no Spark import, so
it is importable and testable without a session — which research R10 established is the *only*
way to satisfy SC-016 given `databricks-connect` blocks a local `pyspark`. Pipeline modules import
from `lib/` and wrap its functions; they never reimplement logic inline. A reviewer finding a date
format or a name-splitting rule written directly inside a `@dp.table` body should treat it as a
defect — it is untestable there.

Test location follows a mirrored tree, matching the greenfield default in the project workflow.

## Execution Phasing

Phases map one-to-one onto the spec's user stories, which map onto the transcript's parts. Each
delivers an independently demonstrable slice.

| Phase | Story | Delivers | Gate |
|---|---|---|---|
| 1 — Setup | — | `databricks.yml`, package skeleton, pytest config, CI-less test run | `bundle validate` clean, `pytest tests/unit` runs (vacuously) |
| 2 — Foundational | — | `lib/` pure modules + their unit tests; catalog/schema/volume resources | unit suite passes; catalog deployed |
| 3 | US1 | seed data with deliberate defects, image fetch with egress check | SC-001 |
| 4 | US2 | producer job, telematics ingestion, both modes | SC-003 + US2 scenarios |
| 5 | US3 | CDC ingestion + mutation verification job | SC-002 |
| 6 | US4 | binaryFile, CSV drift both modes, cleanSource archive | SC-004, SC-005 |
| 7 | US5 | silver expectations, gold MVs, hourly orchestration | SC-006, SC-007 |
| 8 | US6 | spike S1, resize, train, register, score, rules engine | SC-008 – SC-012 |
| 9 | US7 | spike S2, dashboard, Genie script, Lakebase, FastAPI app | SC-013 – SC-015 |
| 10 | — | whole-branch review, teardown verification | SC-016, SC-017 |

**Spikes run early inside their phases**, not at the end: S1 is the first task of phase 8 and S2
the first of phase 9, so the fallback is chosen before dependent work is built on an assumption.

**Cross-phase touches** — phases 7, 8 and 9 all modify code earlier phases created. Implementers
must be told which file and which existing test, and must re-run the full suite for that file:

- Phase 7 modifies the ingest pipeline's outputs' consumers, not the pipeline itself.
- Phase 8 adds `gold.claim_images_predicted` consumed by phase 9, and extends
  `lib/decision.py` written in phase 2 — `tests/unit/test_decision.py` is updated in place, not
  duplicated.
- Phase 9's app consumes `gold.claim_insights` from phase 8 and must handle its `indeterminate`
  results, which the phase 8 contract already defines.

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Custom serving unavailable (S1) | Real-time inference path drops | Fallback defined; no acceptance scenario depends on it; app loads the registered model in-process for fresh uploads |
| Lakebase unavailable (S2) | SC-015's 2 s target at risk | `ClaimsRepository` interface lets the warehouse back the app unchanged; SC-015 explicitly relaxable |
| `cleanSource` on managed volumes unverified | US4 archiving fails | Isolated to one table; if it fails, archive via an explicit post-ingest file move and record the substitution |
| CPU training too slow for the free tier's task limits | Phase 8 stalls | ResNet-18, small images, few epochs; reduce the image set before reducing the lifecycle — the lifecycle is the deliverable |
| Free Edition serverless quota exhaustion | Any phase stalls | Keep continuous pipelines stopped except during their demonstration; hourly schedule paused until phase 10 |
| MV falls back to full recompute | FR-023 unmet, silently | `delta.enableRowTracking = true` on source tables is a required setting, not an optimisation — verify it, don't assume it |
| Genie space script drifts from the bundle | FR-043 partially unmet | Script reads the same configuration values the bundle uses; no second source of truth |

## Complexity Tracking

No constitution gates exist to violate, so this section records deliberate complexity that a
reviewer might otherwise flag as unnecessary.

| Choice | Why needed | Simpler alternative rejected because |
|---|---|---|
| Three-valued check results rather than boolean | The spec's missing-data edge cases require distinguishing "failed" from "could not be evaluated" | Boolean forces absent telematics to score as pass (approves unverified claims) or fail (reports a driver as speeding on no evidence) — both wrong |
| `lib/` split from pipeline code | The only route to an offline test suite, given `databricks-connect` blocks local `pyspark` | Inline logic in pipeline decorators is untestable without a workspace, failing SC-016 |
| `ClaimsRepository` behind two implementations | Spike S2's outcome is unknown at design time | Committing to Lakebase risks rewriting the app if unavailable; committing to the warehouse forfeits SC-015 if it is available |
| Delta change feed rather than a hand-written change log | Makes the CDC verification genuine | A script that writes the change records it later verifies tests nothing |
| Rules as table rows rather than code | FR-030 and FR-034 require adding rules without code changes | Hardcoded rules cannot satisfy SC-012 |

## Next Command

`/speckit-tasks` — generates `tasks.md` with `T00x` identifiers, `[P]` parallel markers and
`[USn]` story labels, from this plan and the artifacts above.
