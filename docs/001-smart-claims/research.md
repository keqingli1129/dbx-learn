# Phase 0 Research: Smart Claims

**Date**: 2026-09-09 | **Feature**: [spec.md](./spec.md) | **Profile**: `DEFAULT`

All findings below were established empirically against the target workspace
(`https://dbc-b5c9918e-c2d2.cloud.databricks.com`) on 2026-09-09, not assumed. Two items could
not be settled without creating resources; they are carried into the plan as explicit spikes with
predetermined fallbacks.

## R1. Serverless runtime capabilities

**Method**: submitted a one-off serverless notebook job that introspected the runtime and
attempted outbound HTTP. Run terminated `SUCCESS`. Probe artifacts have been deleted from the
workspace.

| Property | Observed |
|---|---|
| Spark | 4.2.0 |
| Python | 3.11.10 |
| Outbound HTTPS to huggingface.co / pypi.org / github.com | **200 OK on all three** |
| `PIL` | 10.3.0 |
| `mlflow` | 2.11.4 |
| `scikit-learn` / `matplotlib` / `pandas` / `numpy` | 1.3.0 / 3.7.2 / 1.5.3 / 1.23.5 |
| `psycopg2` | 2.9.3 |
| `torch`, `torchvision`, `transformers`, `datasets`, `huggingface_hub` | **absent** |
| `faker` | absent |

**Decision**: fetch the labelled image dataset over the network at setup time; declare
`torch`, `torchvision`, `faker` and a modern `mlflow` as serverless environment dependencies.

**Rationale**: egress is confirmed working, which removes the largest risk to US1 and makes the
"download a public dataset" choice safe. The absent deep-learning stack is expected on serverless
and is exactly the situation the transcript hits when its gold pipeline fails for a missing
library — the fix is the same, declaring the dependency on the environment rather than
`%pip install` inside the pipeline.

**Consequence for MLflow**: the base image ships MLflow **2.11.4**, which predates MLflow 3. Unity
Catalog model registration and aliases work on 2.x via `mlflow.set_registry_uri("databricks-uc")`,
so nothing in this feature is blocked. A newer `mlflow` is pinned in the training environment
anyway, so behaviour does not drift with the base image.

**Alternatives considered**: bundling images into the repository (rejected — bloats git, and
egress works); `%pip install` inside pipeline code (rejected — the environment declaration is the
supported serverless mechanism and is reproducible from the bundle).

## R2. Deployment mechanism — what Asset Bundles can declare

**Method**: inspected `databricks bundle schema` from CLI v1.15.0.

| Resource type | In bundle schema |
|---|---|
| `catalogs`, `schemas`, `volumes` | yes |
| `pipelines`, `jobs`, `apps`, `dashboards` | yes |
| `experiments`, `registered_models`, `model_serving_endpoints` | yes |
| `database_instances`, `synced_database_tables` | yes |
| `sql_warehouses`, `alerts`, `quality_monitors`, `secret_scopes` | yes |
| **`genie`** | **no** |

**Decision**: define every asset in the bundle except the Genie space, which has no bundle
resource type and is created by a small idempotent script invoked as a post-deploy step, driven by
the same configuration values as the bundle.

**Rationale**: FR-043 requires deployment from a clean checkout with no manual console steps. A
scripted creation satisfies that; a console click does not. Isolating the one exception keeps it
visible rather than buried.

**Alternatives considered**: creating the Genie space by hand and documenting it (rejected — fails
FR-043); skipping Genie (rejected — it is an explicit acceptance scenario, US7 #3).

## R3. Telematics transport substitute

**Decision**: a producer job writes newline-delimited JSON records into
`landing.telematics_raw`, each record carrying a base64-encoded payload alongside envelope
metadata. A streaming table ingests them with Auto Loader and decodes
`base64 → cast to string → from_json → typed columns`.

**Rationale**: the transcript's genuine lesson is not "Kinesis" — it is that a stream delivers an
opaque encoded payload which must be decoded into a typed schema, and that the pipeline framework
hides checkpointing so re-runs process only new data. Encoding the payload preserves the decode
step exactly. Auto Loader gives the same exactly-once incremental guarantee the transcript
attributes to the declarative framework, and the pipeline's `continuous` flag reproduces the
triggered-versus-continuous switch verbatim.

**Alternatives considered**: Kafka against an external broker (rejected — no external service);
Zerobus gRPC ingest (rejected — availability on this tier unverified, and it would bypass the
decode lesson); Spark rate source (rejected — skips ingestion entirely, losing Auto Loader,
checkpointing and decoding all at once).

**Lost relative to the transcript**: configuring a Unity Catalog service credential against a
cloud IAM role. Documented in the spec's substitution table; not recoverable on this tier.

## R4. Change-capture substitute

**Decision**: seed `source.customer`, `source.policy` and `source.claim` as Delta tables with
`delta.enableChangeDataFeed = true`. A mutation script performs ordinary inserts, updates and
deletes against them. The ingestion pipeline reads each table's change feed as a stream and
applies it with Auto CDC — `dp.create_auto_cdc_flow(...)` in Python, or `AUTO CDC INTO` in SQL —
keyed on the natural key, sequenced by `_commit_version`, treating `_change_type = 'delete'` as a
delete.

**Rationale**: this is materially better than a hand-rolled change-log table. Delta's change feed
*is* a real transaction-log-derived CDC feed, so the source-side mutations are genuine database
operations rather than manually appended change records. The convergence semantics FR-010 demands
— updates replacing rather than duplicating, deletes removing — are exactly Auto CDC's SCD Type 1
behaviour, which is what the transcript's managed ingestion pipeline performs. The insert/update/
delete verification of FR-011 and SC-002 becomes a genuine end-to-end test.

**Alternatives considered**: an append-only change-log table written by the mutation script
(rejected — the script would be fabricating the change records it later verifies, making the test
circular); `create_auto_cdc_from_snapshot_flow` comparing full snapshots (rejected — it detects
changes by diffing rather than replaying them, so it would not exercise delete propagation the
same way); Lakehouse Federation to an external database (rejected — no external database).

**Lost relative to the transcript**: the managed ingestion gateway and its staging volume, which
require classic compute and a reachable external database; and source-side CDC enablement on SQL
Server. Documented in the spec.

## R5. Auto CDC API surface — modern versus legacy

**Decision**: use the modern API exclusively. `from pyspark import pipelines as dp`;
`@dp.table` / `@dp.materialized_view` / `@dp.temporary_view`; `dp.create_auto_cdc_flow`;
`dp.create_streaming_table`; `spark.readStream.table(...)`. In SQL, `CREATE OR REFRESH STREAMING
TABLE` / `MATERIALIZED VIEW` and `AUTO CDC INTO`.

**Rationale**: the transcript predates the rename and shows `dlt.*` / `APPLY CHANGES` / the `LIVE.`
prefix. `LIVE.` now errors outright in modern pipelines, so transcribing the transcript's code
literally would not run. Writing the modern API from the start avoids a migration later.

## R6. Dataset type per layer

**Decision**:

| Layer | Type | Why |
|---|---|---|
| Bronze telematics, images, image metadata | Streaming Table + Auto Loader | file sources, append-only, incremental |
| Bronze customer / policy / claim | Streaming Table populated by an Auto CDC flow | upserts and deletes, not appends |
| All silver tables | Streaming Table with expectations | append-only reads from bronze; expectations attach here |
| Gold aggregated telematics | Materialized View | `GROUP BY` over a streaming source must be an MV — a streaming table is append-only and will not recompute aggregates when rows change |
| Gold joined views | Materialized View | full-scan joins; refresh incrementally on serverless |

**Rationale**: the aggregation case is the trap worth calling out. The transcript aggregates
telematics; expressing that as a streaming table would silently produce wrong results as source
rows change. Incremental MV refresh additionally requires serverless plus row tracking on the
source — both hold here, but the source tables must set `delta.enableRowTracking = true` for
FR-023 to be satisfied rather than silently falling back to full recompute.

## R7. Silver expectations

**Decision**: `@dp.expect_all_or_drop` (Python) / `ON VIOLATION DROP ROW` (SQL), matching the
transcript's stated choice of drop over warn or fail.

**Rationale**: FR-015 requires rejection, not warning. Expectation pass/fail counts are recorded
per run by the framework, satisfying FR-016 without extra code.

## R8. Model training and consumption

**Decision**: fine-tune `torchvision` ResNet-18 on CPU serverless, log to a named MLflow
experiment, register to `smart_claims_dev.gold.claims_damage_level` with a `@prod` alias via
`mlflow.set_registry_uri("databricks-uc")`, and score in bulk with `mlflow.pyfunc.spark_udf`.
Real-time serving is a spike, not a dependency.

**Rationale**: ResNet-18 rather than the transcript's larger ResNet, because training is CPU-only.
The MLflow lifecycle — track, register, alias, score — is identical regardless of model size, and
that lifecycle, not accuracy, is the learning objective. `spark_udf` is the correct scoring path
for a plain logged model; the feature-store variant does not apply as no feature tables are used.

**Alternatives considered**: a vision foundation model via `ai_query` (rejected during scoping —
drops the MLflow training lifecycle entirely, which is the point of US6); training a classical
classifier on extracted features (rejected — further from the transcript with no benefit).

## R9. Open items carried as spikes

Both must be resolved by an early task, and both have a predetermined fallback so neither can
block the critical path.

### S1 — Custom model serving availability

**Status**: unresolved. The workspace exposes 11 serving endpoints, **all** Foundation Model APIs;
zero custom endpoints exist. Whether Free Edition permits creating one cannot be determined
without attempting creation, which was deliberately not done during planning.

**Resolution**: attempt to create a minimal custom endpoint. If it succeeds, wire the app to it
and keep batch scoring as the bulk path. If it fails, record the error and proceed with batch
scoring only.

**Fallback**: batch scoring into a gold table; the app reads precomputed predictions and, for a
freshly uploaded image, scores it in-process by loading the registered model. No acceptance
scenario depends on an endpoint existing.

### S2 — Lakebase instance availability

**Status**: unresolved. A `MANAGED_POSTGRESQL` connection and a `MANAGED_ONLINE_CATALOG`
(`lakebase_catalog`) already exist in the workspace, but `list-database-instances` returns empty.
The bundle schema supports `database_instances` and `synced_database_tables`, so if the tier
permits it, declaring it in the bundle will work. `psycopg2` is present on serverless, so
connectivity from compute is available.

**Resolution**: attempt to create one small instance and one synced table from the gold joined
view.

**Fallback**: FR-037 is satisfied by the SQL warehouse instead; SC-015's two-second target is
relaxed and the substitution recorded in the plan. The app's data access is written behind a
single interface so the backing store can be swapped without touching the UI.

## R10. Test strategy

**Decision**: two suites.

- `tests/unit/` — pure Python, no Spark, no workspace. Covers payload decoding, name and address
  normalisation, date-format coercion, and the decision-composition logic that folds individual
  check outcomes into an overall verdict including the indeterminate cases. Always runs; this is
  the suite SC-016 refers to.
- `tests/integration/` — marked `workspace`, skipped unless a profile is configured. Covers the
  SQL rules evaluated against fixture tables, and the CDC insert/update/delete propagation.

**Rationale**: the repository already carries `databricks-connect~=18.0.0` as a dev dependency, and
`databricks-connect` cannot coexist with a local `pyspark` install — so an offline Spark session is
not available. Rather than fight that, the transformation logic is written as pure functions over
scalar values with thin Spark UDF or expression wrappers around them. The logic is then testable
offline and the wrappers are trivial enough not to need unit tests. Java 21 is present locally,
so `databricks-connect` works for the integration suite when a profile is available.

**Consequence for design**: this is a real constraint on how the transformation code is
structured, not just a testing detail. Cleaning logic must not be written inline inside pipeline
decorators; it belongs in an importable module the pipelines call into.

## R11. Why the bundle was hand-written rather than `databricks bundle init`

**Method**: ran `databricks bundle init default-python` into a scratch directory and read the
generated `databricks.yml`, pipeline resource, `pyproject.toml` and `tests/conftest.py`.

**Decision**: hand-write `databricks.yml` and the resource files, but **adopt three patterns**
the template revealed.

**Rationale for not scaffolding**: `bundle init` creates a *new* project from a template. This
repository already exists and already has a layout the plan prescribes — `pyproject.toml` managed
by `databricks environments setup-local`, `docs/001-smart-claims/`, `.specify/`, and the
`src/smart_claims/lib/` boundary that Constitution II requires. The template generates its own
competing structure (`src/<project>_etl/transformations/`, sample taxi jobs, a `fixtures/`
directory) that would then have to be deleted and reworked. Scaffolding over an existing,
specified layout costs more than it saves.

**Patterns adopted from the template**:

1. **`bundle.uuid`** — a stable identifier for the bundle. Added to `databricks.yml`.
2. **Editable install for pipeline code** — the template's pipeline resource declares
   `environment.dependencies: ["--editable ${workspace.file_path}"]`. This is how a pipeline
   imports the project's own Python package from the deployed files. It is the mechanism that
   makes Constitution II workable in practice: without it, `src/smart_claims/ingest/*.py` cannot
   `import smart_claims.lib`. Applies to T028 (ingest pipeline), T061 (transform pipeline).
   Requires a `[build-system]` in `pyproject.toml` — ours currently has none. Folded into T003.
3. **Pipeline dependency caching caveat** — the template's `pyproject.toml` warns: *"for
   pipelines, dependencies are cached during development; add dependencies to the 'environment'
   section of your pipeline.yml file instead"*. This confirms the plan's approach of declaring
   `torch`/`torchvision`/`mlflow` on the job and pipeline environments (T023, T074) rather than
   in `[project].dependencies`.

**Also noted, not adopted**: the template's `tests/conftest.py` initialises Databricks Connect for
*every* test and falls back to serverless. That contradicts Constitution I, which requires
`tests/unit/` to run with no workspace at all. Our `conftest.py` (T005) splits the two suites
instead — Spark only for `workspace`-marked tests.

**Also noted**: `${workspace.current_user.short_name}` resolves to the deploying user's short
name, the template's mechanism for per-developer dev schemas. Not applicable here — our schema
names (`bronze`, `silver`, `gold`) are fixed by the medallion design — but useful to know.
