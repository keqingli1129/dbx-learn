---
description: "Task list for Smart Claims — End-to-End Insurance Lakehouse"
---

# Tasks: Smart Claims — End-to-End Insurance Lakehouse

**Input**: Design documents from `docs/001-smart-claims/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/](./contracts/)

**Tests**: REQUIRED. Declared at specification time (spec.md FR-044, checklist notes). Test files
are part of the deliverable and are committed alongside implementation code, not discarded once
green.

**Organization**: grouped by user story. Each phase is an independently demonstrable increment.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: parallelizable — different files, no dependency on an incomplete task
- **[Story]**: `[US1]`…`[US7]`, mapping to spec.md user stories
- Every task names its exact file path

## Conventions

- Profile is always `DEFAULT`, passed explicitly as `--profile DEFAULT`. Never rely on the default.
- Pipeline code uses the **modern** API: `from pyspark import pipelines as dp`. `import dlt`,
  `@dlt.*`, `LIVE.`, `APPLY CHANGES` and `dlt.apply_changes` are all forbidden — `LIVE.` errors
  outright on current runtimes (research R5).
- Cleaning and decision logic lives in `src/smart_claims/lib/` as pure Python and is *imported*
  by pipeline code. Logic written inline inside a `@dp.table` body is a defect — it cannot be
  tested offline (research R10, plan Structure Decision).
- Catalog is `smart_claims_dev` throughout; never hardcode it in transformation code, read it
  from pipeline configuration.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: bundle skeleton and test harness. No business logic.

- [X] T001 Scaffold the bundle with `databricks bundle init default-python` (project_name `smart_claims`, serverless yes, pipeline yes, python yes, notebook no, catalog `smart_claims_dev`) into a temporary directory, then move its contents to the repository root — `bundle init` has no in-place mode (research R11). Delete the generated `CLAUDE.md`/`AGENTS.md` (they would override this project's instructions) and remove the `artifacts: uv build --wheel` block, the bundle's only uv dependency. Verify with `databricks bundle validate --strict -t dev --profile DEFAULT`
- [X] T002 Strip the generated NYC-taxi demo from the scaffold, and fix two stale uv references left by the template — the `uv run pytest` hint in `tests/conftest.py` and the uv setup instructions in `README.md`. Delete: delete `src/smart_claims/taxis.py`, `src/smart_claims/main.py`, `src/smart_claims_etl/` (whole tree, including `transformations/sample_*.py` and `explorations/`), `tests/sample_taxis_test.py`, `resources/sample_job.job.yml` and `resources/smart_claims_etl.pipeline.yml`. Keep `.vscode/`, `fixtures/`, `.gitignore`, `pyproject.toml` and `databricks.yml`. Re-run `bundle validate --strict` — it must still pass with zero resources
- [X] T003 Create the package layout under `src/smart_claims/`: subpackages `lib/`, `setup/`, `ingest/`, `transform/`, `ml/`, `genie/`, `app/`, each with an `__init__.py`. `lib/` is the Spark-free boundary Constitution II requires
- [X] T004 Add the project's own variables to `databricks.yml` alongside the generated `catalog` and `schema`: `speed_threshold` (default `45`) and `warehouse_id` (default `cdcb7003ae7dd5ab`, the Serverless Starter Warehouse). Leave the generated `artifacts`, `uuid` and `prod` target intact
- [ ] T005 Add dependencies to `pyproject.toml` (which already has `[build-system]` from the scaffold — verify it packages `src/smart_claims`): runtime `fastapi`, `uvicorn`, `python-multipart`, `databricks-sdk`; dev group `pytest`, `pytest-mock`. Do NOT add `pyspark` — it conflicts with `databricks-connect`. No uv: dependencies are installed with `pip install -e '.[dev]'` into a plain virtualenv. Note the scaffold's own warning that pipeline dependencies belong in each pipeline's `environment` block, not here (research R11)
- [ ] T006 [P] Configure pytest in `pyproject.toml`: `testpaths = ["tests"]`, and register the marker `workspace` for tests requiring a live profile, with `addopts = "-m 'not workspace'"` so `pytest` runs offline by default
- [ ] T007 [P] Create `tests/__init__.py`, `tests/unit/__init__.py`, `tests/integration/__init__.py`, and `tests/conftest.py` defining a `--profile` option that skips `workspace`-marked tests when absent

**Checkpoint**: `databricks bundle validate -t dev --profile DEFAULT` is clean and `uv run pytest` exits successfully with zero tests collected.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: the pure-Python library every later phase imports, and the catalog every later phase writes to.

**⚠️ CRITICAL**: no user story work can begin until this phase is complete.

### Tests (write first, watch them fail)

- [ ] T008 [P] Write `tests/unit/test_severity.py` asserting the severity domain is exactly `Trivial Damage`, `Minor Damage`, `Major Damage`, `Total Loss`; that the classifier's 3-class output maps onto it deterministically; that comparison is case- and whitespace-insensitive; and that an unknown label raises rather than silently returning a default
- [ ] T009 [P] Write `tests/unit/test_payload.py` asserting base64-encoded JSON decodes to a dict with keys `chassis_no`, `speed`, `latitude`, `longitude`, `event_timestamp`; that malformed base64 and malformed JSON each return a sentinel rather than raising (a single bad payload must not fail ingestion — spec edge case); and that all values arrive as strings
- [ ] T010 [P] Write `tests/unit/test_cleaning.py` covering: `"Ada Lovelace"` → `("Ada", "Lovelace")`; single-token and triple-token names; empty and null names; address whitespace and casing normalisation; and date coercion for all four formats present in the data (`MM/dd/yyyy`, `yyyy-MM-dd`, `dd-MM-yyyy`, `dd/MM/yyyy`) plus `yyyy-MM-dd HH:mm:ss`, with unparseable input returning `None` not raising
- [ ] T011 [P] Write `tests/unit/test_decision.py` covering the three-valued fold from contracts/rules-engine.md: all `pass` → `release_funds`; any `fail` → `requires_investigation`; **any `indeterminate` → `requires_investigation`**; empty rule set; and that `indeterminate` is never collapsed to `pass` or `fail`

### Implementation

- [ ] T012 [P] Implement `src/smart_claims/lib/severity.py` — the single `SEVERITY_DOMAIN` tuple, `normalize(label)`, and `MODEL_LABEL_MAP` mapping classifier classes onto the domain. No Spark import
- [ ] T013 [P] Implement `src/smart_claims/lib/payload.py` — `decode_telematics(data_b64) -> dict | None`. No Spark import
- [ ] T014 [P] Implement `src/smart_claims/lib/cleaning.py` — `split_name`, `normalize_address`, `parse_date(value, fmt)`. No Spark import and delete the `resources/.gitkeep` placeholder, which exists only so the directory is tracked before the first resource YAML
- [ ] T015 [P] Implement `src/smart_claims/lib/decision.py` — `CheckResult` (`pass`/`fail`/`indeterminate`) and `overall_outcome(results) -> str`. No Spark import
- [ ] T016 Create `resources/catalog.yml` declaring catalog `smart_claims_dev` and schemas `source`, `landing`, `bronze`, `silver`, `gold`, plus managed volumes `landing.telematics_raw`, `landing.claims`, `landing.training_images` (depends on T001)
- [ ] T017 Create `src/smart_claims/lib/config.py` reading `catalog`, `speed_threshold` and volume roots from pipeline/job configuration with no hardcoded catalog name
- [ ] T018 Deploy and verify: `databricks bundle deploy -t dev --profile DEFAULT`, then confirm all five schemas exist via `databricks schemas list smart_claims_dev --profile DEFAULT`

**Checkpoint**: `uv run pytest tests/unit` passes (T008–T011 now green); catalog and schemas exist in the workspace.

---

## Phase 3: User Story 1 - Governed Data Foundation (Priority: P1) 🎯 MVP

**Goal**: seeded operational source data and labelled training images, ready for every downstream story.

**Independent Test**: run the setup job; four schemas populated, source tables referentially consistent, training-image volume holding ≥3 labels with ≥20 images each.

- [ ] T019 [US1] Implement `src/smart_claims/setup/seed_source_data.py` generating ~1000 customers, ~1200 policies, ~1300 claims per the schemas in data-model.md, writing to `source.customer`, `source.policy`, `source.claim` with `delta.enableChangeDataFeed = true` AND `delta.enableRowTracking = true` on all three (row tracking is required for gold MVs to refresh incrementally rather than silently full-recompute — research R6, FR-023)
- [ ] T020 [US1] Extend `seed_source_data.py` to inject the **deliberate defects** the later phases prove they catch: some `claim.claim_no` NULL; some `claim.incident_hour` outside 0–23; some `policy.premium` negative; some `claim.total_claim_amount` zero or negative; `customer.name` always a combined `"First Last"`; `customer.address` with inconsistent whitespace and casing. Dates written as text in four distinct formats — `claim_date` as `yyyy-MM-dd HH:mm:ss`, `incident_date` as `MM/dd/yyyy`, `driver_license_issue_date` as `dd/MM/yyyy`, `policy.pol_issue_date` as `dd-MM-yyyy`, `pol_eff_date`/`pol_expiry_date` as `yyyy-MM-dd`
- [ ] T021 [US1] Ensure referential consistency in `seed_source_data.py`: every `claim.policy_no` resolves to a policy and every `policy.customer_id` to a customer, EXCEPT a small deliberate set of orphan claims to exercise the missing-policy edge case. Assign `policy.chassis_no` values that the telematics producer will later emit for
- [ ] T022 [US1] Implement `src/smart_claims/setup/fetch_training_images.py` with an **explicit egress check first** (FR-004) — attempt an HTTPS request and fail with an actionable message naming the fallback if it fails. Egress was confirmed working during planning (research R1), so a failure here is a change in conditions, not a design error
- [ ] T023 [US1] Extend `fetch_training_images.py` to download a public labelled car-damage-severity dataset and write images into `/Volumes/smart_claims_dev/landing/training_images/<severity_label>/<file>.jpg` so the label is recoverable from the path, normalising each label through `lib.severity.normalize`
- [ ] T024 [US1] Implement `src/smart_claims/setup/seed_claim_images.py` populating `/Volumes/smart_claims_dev/landing/claims/images/` with accident photos, `/Volumes/smart_claims_dev/landing/claims/metadata/` with the `image_id,claim_no,image_path,uploaded_at` CSV linking images to seeded claims, and an empty `/Volumes/smart_claims_dev/landing/claims/archive/` directory
- [ ] T025 [US1] Create `resources/setup.job.yml` declaring a serverless job with tasks `seed_source_data` → `fetch_training_images` → `seed_claim_images`, with an environment declaring the `faker` dependency (absent from the base image — research R1)
- [ ] T026 [US1] Deploy and run: `databricks bundle deploy -t dev --profile DEFAULT && databricks bundle run setup_job -t dev --profile DEFAULT`. Verify SC-001 — query row counts on all three source tables and list the training-image volume to confirm ≥3 labels with ≥20 images each

**Checkpoint**: US1 complete. Source data and images exist; nothing downstream built yet.

---

## Phase 4: User Story 2 - Telematics Event Ingestion (Priority: P2)

**Goal**: telematics events decoded from encoded payloads into typed bronze columns, incrementally.

**Independent Test**: emit a known batch, ingest, confirm exact typed rows; emit more, re-ingest, confirm only new rows added.

- [ ] T027 [US2] Implement `src/smart_claims/setup/telematics_producer.py` writing newline-delimited JSON files into `/Volumes/smart_claims_dev/landing/telematics_raw/`, each line `{"partition_key","sequence_number","approximate_arrival_timestamp","data"}` where `data` is base64 of `{"chassis_no","speed","latitude","longitude","event_timestamp"}` with **all values as strings** (data-model.md). Emit for the `chassis_no` values seeded in T021, including at least one vehicle with speeds above the 45 threshold and at least one policy's vehicle with **no** readings at all, to exercise the indeterminate speed check
- [ ] T028 [US2] Create `resources/telematics_producer.job.yml` declaring a serverless job wrapping T027, parameterised by record count and batch count
- [ ] T029 [US2] Implement `src/smart_claims_etl/transformations/bronze/telematics.py` — a streaming table `bronze.telematics` reading with Auto Loader (`cloudFiles`, format `json`) from the landing volume, then decoding: base64 → `cast(string)` → `from_json` against an all-string map schema → projection into `stream_metadata STRUCT<partition_key, sequence_number, arrival_ts>` plus typed `chassis_no`, `speed`, `latitude`, `longitude`, `event_timestamp`, plus `_ingested_at`. Decoding calls `lib.payload` via a UDF — do not reimplement the decode inline
- [ ] T030 [US2] Create `resources/ingest.pipeline.yml` declaring the ingest pipeline with default catalog `smart_claims_dev`, default schema `bronze`, serverless, `continuous: false`, and `root_path: ../src/smart_claims_etl` and `libraries.glob.include: ../src/smart_claims_etl/transformations/bronze/**` so only bronze dataset files are evaluated, plus configuration keys `catalog`, `landing_volume_root`, `schema_evolution_mode`, `clean_source_retention`, `archive_path` (contracts/pipeline-datasets.md). Do NOT hardcode these in pipeline code. Declare `environment.dependencies: ["--editable ${workspace.file_path}"]` so the pipeline can `import smart_claims.lib` from the deployed files (research R11) **Unresolved from the scaffold**: `databricks.yml` declares a single `schema` variable (assigned `dev`/`prod`), which does not fit this design — the medallion schemas are fixed (`bronze`, `silver`, `gold`) and differ per pipeline, not per environment. Decide here whether to set the pipeline's schema literally and drop the variable, or repurpose it.
- [ ] T031 [US2] Deploy, run the producer, then run the ingest pipeline. Verify typed columns are populated and NOT base64 text
- [ ] T032 [US2] Verify incrementality (SC-003): record the row count, re-run ingest with no new files, confirm the count is unchanged; then run the producer again, re-run ingest, confirm only the new events were added
- [ ] T033 [US2] Verify continuous mode (US2 scenario 3): flip `continuous: true`, redeploy, start the pipeline, run the producer while it runs, confirm rows appear without re-triggering. **Stop the pipeline afterwards** — a continuous pipeline consumes serverless quota indefinitely
- [ ] T034 [US2] Restore `continuous: false` and redeploy, leaving triggered mode as the committed default
- [ ] T035 [P] [US2] Write `tests/integration/test_telematics_ingestion.py` (marked `workspace`) asserting decoded column types and that no row retains an un-decoded payload

**Checkpoint**: US2 complete. Telematics flows into bronze in both modes.

---

## Phase 5: User Story 3 - Operational Database Change Capture (Priority: P3)

**Goal**: inserts, updates and deletes at the source converge into bronze.

**Independent Test**: one insert, one update, one delete at source; after one ingest run each is correctly reflected.

- [ ] T036 [US3] Implement one file per CDC target — `src/smart_claims_etl/transformations/bronze/customer.py`, `src/smart_claims_etl/transformations/bronze/policy.py`, `src/smart_claims_etl/transformations/bronze/claim.py` — each creating its explicit streaming table via `dp.create_streaming_table`, each fed by `dp.create_auto_cdc_flow` reading the corresponding source table's change feed as a stream (`spark.readStream.option("readChangeFeed","true").table(...)`)
- [ ] T037 [US3] Configure each Auto CDC flow in `cdc.py`: `keys` on the natural key (`customer_id`, `policy_no`, `claim_no`), `sequence_by="_commit_version"`, `apply_as_deletes=expr("_change_type = 'delete'")`, `stored_as_scd_type="1"`, and `except_column_list` excluding the change-feed metadata columns. Use `dp.create_auto_cdc_flow` — NOT the legacy `apply_changes`
- [ ] T038 [US3] Add the CDC source datasets to `resources/ingest.pipeline.yml` so the three `src/smart_claims_etl/transformations/bronze/` CDC files are included in the same pipeline (contracts/pipeline-datasets.md — the ingest pipeline owns all bronze tables)
- [ ] T039 [US3] Implement `src/smart_claims/setup/cdc_mutations.py` performing exactly one INSERT into `source.policy`, one UPDATE of a `source.claim` row's `incident_severity`, and one DELETE from `source.customer` — printing the affected keys so the verification queries are reproducible
- [ ] T040 [US3] Extend `cdc_mutations.py` with the three verification queries from quickstart.md §3, run **before and after** ingestion, printing both results so the propagation is visible rather than asserted
- [ ] T041 [US3] Create `resources/cdc_mutation.job.yml` declaring a serverless job wrapping T039–T040
- [ ] T042 [US3] Deploy and run the initial CDC ingestion; verify bronze customer/policy/claim row counts match their source tables
- [ ] T043 [US3] Run the mutation job, re-run ingest, and verify SC-002: the inserted policy present; the updated claim showing the **new** severity and appearing **exactly once** (a duplicate row with the old value means the key or sequence column is wrong); the deleted customer returning zero rows
- [ ] T044 [P] [US3] Write `tests/integration/test_cdc_propagation.py` (marked `workspace`) asserting all three propagations, including explicitly that the updated row count is 1, not 2

**Checkpoint**: US3 complete. Bronze converges on source state.

---

## Phase 6: User Story 4 - Accident Image and Metadata Ingestion (Priority: P4)

**Goal**: images and metadata ingested incrementally, with schema drift handled both ways and processed files archived.

**Independent Test**: ingest, add a drifted file under each mode, confirm the configured behaviour; confirm processed images relocate to archive.

- [ ] T045 [US4] Implement `bronze.training_images` in `src/smart_claims_etl/transformations/bronze/training_images.py` — Auto Loader with `cloudFiles.format = binaryFile` over `/Volumes/smart_claims_dev/landing/training_images/`, retaining `path`, `modificationTime`, `length`, `content`, plus `label` derived from the path via `_metadata.file_path` (NOT the deprecated `input_file_name()`) and normalised through `lib.severity`
- [ ] T046 [US4] Implement `bronze.claim_images_meta` in `src/smart_claims_etl/transformations/bronze/claim_images_meta.py` — Auto Loader with `cloudFiles.format = csv` over the metadata folder, with `cloudFiles.schemaEvolutionMode` read from the pipeline's `schema_evolution_mode` configuration key so both modes are selectable without a code change, and a `_rescued_data` column
- [ ] T047 [US4] Implement `bronze.claim_images` in `src/smart_claims_etl/transformations/bronze/claim_images.py` — Auto Loader with `binaryFile`, plus `cloudFiles.cleanSource = MOVE`, `cloudFiles.cleanSource.retentionDuration` from the `clean_source_retention` config key, and `cloudFiles.cleanSource.moveDestination` set to the `archive_path` config key
- [ ] T048 [US4] Deploy and run ingest; verify `bronze.training_images` holds ≥3 distinct labels with ≥20 images each, and that `bronze.claim_images_meta` and `bronze.claim_images` are populated
- [ ] T049 [US4] Verify drift mode `addNewColumns` (SC-004 part 1): with the config set to `addNewColumns`, upload a metadata CSV carrying one extra column to the landing volume, re-run ingest, and confirm the new column exists on the table, NULL for all prior rows and populated for the new one
- [ ] T050 [US4] Verify drift mode `rescue` (SC-004 part 2): set the config to `rescue`, redeploy, upload a metadata CSV carrying a *further* new column, re-run ingest, and confirm the table's columns are **unchanged** and the new field's value appears inside `_rescued_data`
- [ ] T051 [US4] Verify archiving (SC-005): after `clean_source_retention` elapses, re-run ingest and list `dbfs:/Volumes/smart_claims_dev/landing/claims/archive` — processed files present there and absent from `images/`. If nothing moved, the retention window has not elapsed; re-run rather than treating it as a failure (spec edge case)
- [ ] T052 [US4] **Risk contingency**: if `cleanSource` proves unsupported on managed volumes, replace it with an explicit post-ingest file-move task in `objectstore.py`, and record the substitution in `research.md` under a new decision heading. Do not silently drop the archiving requirement
- [ ] T053 [P] [US4] Write `tests/integration/test_schema_drift.py` (marked `workspace`) asserting the two drift modes produce their distinct documented outcomes
- [ ] T054 [US4] Set the committed default for `schema_evolution_mode` back to `rescue` and redeploy — quarantining drift is the safer production default

**Checkpoint**: US4 complete. All three file-ingestion behaviours demonstrated.

---

## Phase 7: User Story 5 - Cleansing, Business Views and Scheduled Orchestration (Priority: P5)

**Goal**: quality-enforced silver, joined gold views, and an hourly orchestrated graph.

**Independent Test**: injected invalid records excluded from silver and reported; gold joins neither lose nor duplicate claims; scheduled job runs in dependency order.

- [ ] T055 [US5] Implement `silver.claim` in `src/smart_claims_etl/transformations/silver/claim.py` with `@dp.expect_all_or_drop` carrying exactly three constraints — `valid_claim_number: claim_no IS NOT NULL`, `valid_incident_hour: incident_hour BETWEEN 0 AND 23` and `positive_claim_amount: total_claim_amount > 0` (FR-015) — coercing all four date columns using their respective formats via `lib.cleaning.parse_date`, and dropping `_rescued_data`
- [ ] T056 [P] [US5] Implement `silver.policy` in `src/smart_claims_etl/transformations/silver/policy.py` with `expect_all_or_drop` on `valid_policy_number: policy_no IS NOT NULL`, `premium → abs(premium)` (FR-019), and the three date columns coerced with their distinct formats
- [ ] T057 [P] [US5] Implement `silver.customer` in `src/smart_claims_etl/transformations/silver/customer.py` with `expect_all_or_drop` on `valid_customer_id: customer_id IS NOT NULL`, `name` split into `first_name`/`last_name` via `lib.cleaning.split_name`, `address` normalised via `lib.cleaning.normalize_address`, and `date_of_birth` coerced
- [ ] T058 [P] [US5] Implement `silver.telematics` in `src/smart_claims_etl/transformations/silver/telematics.py` with `expect_all_or_drop` on `chassis_no IS NOT NULL` and `speed >= 0`, casting speed/latitude/longitude to DOUBLE and `event_timestamp` to TIMESTAMP
- [ ] T059 [P] [US5] Implement `src/smart_claims_etl/transformations/silver/training_images.py` and `src/smart_claims_etl/transformations/silver/claim_images.py`; the latter joins `bronze.claim_images` to `bronze.claim_images_meta` to attach `claim_no`, with `expect_all_or_drop` on `claim_no IS NOT NULL`
- [ ] T060 [US5] Implement `gold.telematics_agg` in `src/smart_claims_etl/transformations/gold/telematics_agg.py` as a **Materialized View** (`@dp.materialized_view`) — NOT a streaming table — grouped by `chassis_no` **and `event_date`** (the date part of `event_timestamp`) producing `max_speed`, `avg_speed`, `avg_latitude`, `avg_longitude`, `reading_count`. The date grain is required (FR-021): grouping by vehicle alone would judge a claim against a speed recorded on an unrelated day. A streaming table is append-only and will not recompute aggregates when source rows change (research R6)
- [ ] T061 [US5] Implement `gold.customer_claim_policy` in `src/smart_claims_etl/transformations/gold/customer_claim_policy.py` as a materialized view joining `silver.claim ⋈ silver.policy ⋈ silver.customer`, producing exactly one row per claim
- [ ] T062 [US5] Implement `gold.customer_claim_policy_telematics` in `src/smart_claims_etl/transformations/gold/customer_claim_policy_telematics.py` as a materialized view **left**-joining T061's output to `gold.telematics_agg` on `chassis_no` **AND `event_date = incident_date`** (FR-022). The left join is required, not stylistic — a vehicle with no readings must still yield a claim row so its speed check can be recorded indeterminate rather than the claim disappearing (data-model.md)
- [ ] T063 [US5] Create `resources/transform.pipeline.yml` with default catalog `smart_claims_dev`, default schema `silver`, serverless, `root_path: ../src/smart_claims_etl` and two glob includes (`transformations/silver/**`, `transformations/gold/**`), gold datasets written by fully-qualified name, and `environment.dependencies: ["--editable ${workspace.file_path}"]` so the pipeline can import `smart_claims.lib.cleaning` (research R11). Declare no `torch` dependency here — this pipeline does not need it **Unresolved from the scaffold**: `databricks.yml` declares a single `schema` variable (assigned `dev`/`prod`), which does not fit this design — the medallion schemas are fixed (`bronze`, `silver`, `gold`) and differ per pipeline, not per environment. Decide here whether to set the pipeline's schema literally and drop the variable, or repurpose it.
- [ ] T064 [US5] Deploy and run the transform pipeline; verify SC-006 by inspecting the expectations panel — non-zero drops for `valid_claim_number` and `valid_incident_hour` are **expected**, because T020 seeded those defects. Zero drops means the expectations are not firing, not that the data is clean
- [ ] T065 [US5] Verify SC-007: `silver.claim` count, `gold.customer_claim_policy_telematics` count, and its distinct `claim_no` count must all be equal. `gold_rows > distinct_claims` means a join fanned out — most likely telematics joined before aggregating
- [ ] T066 [US5] Verify FR-023 is actually met, not silently degraded: confirm the gold MVs refresh incrementally, which requires serverless **and** `delta.enableRowTracking = true` on the sources set in T019. If they full-recompute, row tracking is missing
- [ ] T067 [US5] Enforce the source schema contract (FR-045) across the `src/smart_claims_etl/transformations/silver/` files — declare the columns each silver dataset depends on and fail the update with an error naming the missing column if one is absent, rather than emitting null-filled rows. Verify SC-007b by dropping a depended-upon column from a source table and confirming the failure message names it
- [ ] T068 [US5] Create `resources/orchestration.job.yml` declaring job `smart_claims_hourly` with `ingest_pipeline` → `transform_pipeline`, the second depending on the first's success (FR-024), on an hourly schedule **paused** until Phase 10
- [ ] T069 [US5] Deploy and run `smart_claims_hourly`; confirm transform starts only after ingest succeeds, and that a deliberately failed ingest prevents transform from running

**Checkpoint**: US5 complete. Trustworthy gold data, orchestrated.

---

## Phase 8: User Story 6 - Damage Classification and Automated Triage (Priority: P6)

**Goal**: a tracked, governed classifier and a data-driven rules engine producing per-check triage outcomes.

**Independent Test**: model registered with `@prod` alias and a confusion matrix; one claim per violated rule flagged for exactly that reason; a compliant claim approved.

**⚠️ Modifies prior-phase code**: T080 extends `src/smart_claims/lib/decision.py` created in Phase 2 (T015). Its existing test `tests/unit/test_decision.py` (T011) must be **updated in place**, not duplicated — watch the new assertion go red, then green, then re-run the *full* file before committing.

### Spike (run first)

- [ ] T070 [US6] **Spike S1** — attempt to create a minimal custom model serving endpoint on this workspace and record the outcome in `research.md` under R9/S1. The workspace currently exposes only Foundation Model endpoints. If it succeeds, real-time inference becomes an enhancement in Phase 9; if it fails, record the exact error and proceed with batch scoring. **Nothing downstream may block on this** — no acceptance scenario depends on an endpoint existing

### Implementation

- [ ] T071 [US6] Implement `src/smart_claims/ml/resize_images.py` producing `gold.training_images_resized` — images resized to 224×224 via a `PIL`-based UDF (`PIL` 10.3.0 is present on serverless, research R1), preserving `path`, `label` and resized `content`
- [ ] T072 [US6] Implement `src/smart_claims/ml/train_classifier.py` — load `gold.training_images_resized`, split train/test, normalise tensors, fine-tune `torchvision` ResNet-18 on CPU for a small number of epochs. Use ResNet-18 rather than a larger variant because no GPU is available (research R8)
- [ ] T073 [US6] Extend `train_classifier.py` with MLflow tracking against a named experiment, logging hyperparameters, per-epoch metrics and the model artifact, wrapped as a PyFunc taking binary image content and returning a severity label plus confidence, with labels drawn from `lib.severity.MODEL_LABEL_MAP`
- [ ] T074 [US6] Extend `train_classifier.py` to set `mlflow.set_registry_uri("databricks-uc")` and register the model as `smart_claims_dev.gold.claims_damage_level` with alias `@prod` (FR-027)
- [ ] T075 [US6] Extend `train_classifier.py` to compute and log a per-class confusion matrix on the held-out split (FR-029, SC-009). Accuracy is **recorded, not thresholded** — a mediocre matrix is acceptable, an empty one is not
- [ ] T076 [US6] Implement `src/smart_claims/ml/batch_score.py` producing `gold.claim_images_predicted` — load the model with `mlflow.pyfunc.spark_udf` at alias `@prod` and score `silver.claim_images`, writing `predicted_severity` and `prediction_confidence` alongside `claim_no`
- [ ] T077 [US6] Create `resources/ml.job.yml` declaring a serverless job with tasks `resize_images` → `train_classifier` → `batch_score`, its environment declaring `torch`, `torchvision` and a pinned `mlflow>=3` (all absent or outdated on the base image — research R1). Keep training a **separate task** from scoring so scoring can re-run without retraining
- [ ] T078 [US6] Implement `src/smart_claims/ml/seed_rules.py` creating `gold.claims_rules` per data-model.md and inserting the four seeded rules, with `check_expr` written so operands that are missing yield SQL `NULL` — do **not** wrap operands in `coalesce`, which would destroy the indeterminate signal (contracts/rules-engine.md)
- [ ] T079 [US6] Implement `src/smart_claims/ml/evaluate_rules.py` — the generic evaluator reading all enabled rules and applying each to `gold.customer_claim_policy_telematics` left-joined to `gold.claim_images_predicted`, mapping each `check_expr` result `true → pass`, `false → fail`, `NULL → indeterminate`
- [ ] T080 [US6] Extend `src/smart_claims/lib/decision.py` (from T015) with any composition logic the evaluator needs, and **update `tests/unit/test_decision.py` in place** with assertions for the new behaviour. Re-run the full file, not only the new test, before committing
- [ ] T081 [US6] Complete `evaluate_rules.py` to write `gold.claim_insights` — one row per claim carrying every column of the joined input, `predicted_severity`, one result column per rule name, `overall_outcome` and `evaluated_at`. `release_funds` only when every check is `pass` (FR-033)
- [ ] T082 [US6] Add `seed_rules` and `evaluate_rules` tasks to `resources/ml.job.yml`, and add a `score_and_triage` task (batch score + evaluate, no training) to `resources/orchestration.job.yml` downstream of transform
- [ ] T083 [US6] Deploy and run the ML job; verify SC-008 — an MLflow run with logged parameters and metrics, and the model registered with a `@prod` alias traceable to that run
- [ ] T084 [P] [US6] Write `tests/integration/test_rules_engine.py` (marked `workspace`) constructing one fixture claim per violated rule and asserting SC-010: each is `requires_investigation` with **exactly** that check `fail`; plus SC-011: a compliant claim is `release_funds`; plus a claim with no telematics is `requires_investigation` with the speed check `indeterminate`
- [ ] T085 [US6] Verify SC-012: insert a fifth rule into `gold.claims_rules`, re-run the evaluator, and confirm all existing claims are re-scored and a new result column appears — **with no code change**
- [ ] T086 [US6] Verify the spec's missing-data edge cases end to end: an orphan claim (seeded in T021) yields indeterminate coverage and policy-date checks and is routed to investigation, never silently approved

**Checkpoint**: US6 complete. Governed model and extensible triage.

---

## Phase 9: User Story 7 - Business Consumption Surfaces (Priority: P7)

**Goal**: dashboard, natural-language interface, and a claims portal with customer and admin modes.

**Independent Test**: dashboard reconciles against direct queries; Genie answers a known question; a claim submitted through the portal returns the same decision the rules engine produces.

**⚠️ Consumes prior-phase output**: the app reads `gold.claim_insights` from Phase 8 and MUST render its `indeterminate` results correctly — treating them as pass or fail is a defect.

### Spike (run first)

- [ ] T087 [US7] **Spike S2** — attempt to create one small Lakebase database instance and record the outcome in `research.md` under R9/S2. The workspace has the managed-Postgres plumbing but zero instances. If it fails, the app uses the warehouse-backed repository and SC-015's two-second target is relaxed per the spec's assumptions

### Dashboard and Genie

- [ ] T088 [P] [US7] Author `src/dashboards/claims_investigation.lvdash.json` with datasets over `gold.claim_insights`, parameterised by a start/end date range, and visuals for total claim volume, severity breakdown, and outcome split. **Test every SQL query via the CLI before deploying** — untested dashboard SQL is the most common cause of a broken deploy
- [ ] T089 [US7] Create `resources/dashboard.yml` declaring the dashboard resource; deploy and verify SC-013 by reconciling the headline count against `SELECT count(*) FROM smart_claims_dev.gold.claim_insights`, and confirming every visual responds to the date filter
- [ ] T090 [US7] Implement `src/smart_claims/genie/create_space.py` — an idempotent script creating a Genie space over the gold tables, reading the same configuration values the bundle uses so there is no second source of truth. Genie has **no bundle resource type** (research R2), so this script is the only way to satisfy FR-043 for it
- [ ] T091 [US7] Run the Genie script and verify US7 scenario 3: ask "how many claims fall into each severity category", confirm the counts match a direct query and the generated SQL is visible

### Serving copy

- [ ] T092 [US7] If S2 succeeded, add `database_instances` and a `synced_database_tables` entry for `gold.customer_claim_policy_telematics` keyed on `claim_no` to `resources/`; if S2 failed, skip and record the substitution in `plan.md`'s risk table

### Application

- [ ] T093 [P] [US7] Implement `src/smart_claims/app/repository.py` — the `ClaimsRepository` interface covering every read and write in contracts/app-api.md. No handler may issue SQL directly; this interface is what lets S2's outcome change nothing above it
- [ ] T094 [P] [US7] Implement `src/smart_claims/app/repository_warehouse.py` backing the interface via the SQL warehouse (`psycopg2` is present, but this path uses the SDK's SQL execution)
- [ ] T095 [P] [US7] Implement `src/smart_claims/app/repository_lakebase.py` backing the interface via Lakebase Postgres, only if S2 succeeded
- [ ] T096 [US7] Implement `src/smart_claims/app/main.py` — FastAPI app with startup-time repository selection, and `GET /health` returning `{"status","data_source"}` where `data_source` reports which repository resolved, making S2's outcome observable at runtime
- [ ] T097 [US7] Implement `POST /api/claims/classify` in `main.py` per contracts/app-api.md — multipart image, returns predicted severity and confidence; **415** for non-image uploads (FR-041) and **413** for oversize. If S1 succeeded, call the endpoint; otherwise load the registered model in-process
- [ ] T098 [US7] Implement `POST /api/claims` in `main.py` — validates all eight fields, records the claim, evaluates all four checks, and returns **201** with `claim_no`, `overall_outcome` and a `checks` array whose `result` values are `pass`/`fail`/`indeterminate`. Unknown `policy_no` returns the claim as `requires_investigation` with indeterminate coverage and policy-date checks, **not** a hard error. Duplicate submission returns **409** with the existing `claim_no` (spec edge case)
- [ ] T099 [P] [US7] Implement `GET /api/admin/overview` and `GET /api/admin/claims/{claim_no}` in `main.py` per the contract, with `telematics: null` when a vehicle has no readings so the client renders the speed check as indeterminate rather than absent
- [ ] T100 [P] [US7] Implement `GET /api/claims/{claim_no}/image` in `main.py` returning the stored photograph
- [ ] T101 [US7] Implement the frontend in `src/smart_claims/app/static/` — customer mode (upload with pre-submission severity preview, the eight-field form, and a decision panel listing all four check results) and admin mode (overview with totals, severity breakdown and severity filter; analysis tab with per-claim checks, claim details, customer details and the image)
- [ ] T102 [US7] Create `resources/app.yml` declaring the app with its SQL warehouse resource, plus the database resource if S2 succeeded and the serving endpoint if S1 succeeded
- [ ] T103 [US7] Deploy and verify SC-014: upload a photo, see the predicted severity before submitting, complete the form, submit, and confirm the decision arrives within two minutes showing all four check results and matching what `evaluate_rules.py` independently produces for the same inputs. Confirm a non-image upload is rejected clearly
- [ ] T104 [US7] Verify SC-015 and the admin flows: overview totals and severity filter work; opening a claim populates its detail view including the image in under two seconds. If S2 failed and this misses, record the measured latency rather than silently accepting it
- [ ] T105 [P] [US7] Write `tests/unit/test_app_validation.py` covering request validation and the check-result serialisation, with no workspace dependency

**Checkpoint**: US7 complete. All seven stories delivered.

---

## Phase 10: Polish & Cross-Cutting Concerns

- [ ] T106 Enable the hourly schedule on `smart_claims_hourly` in `resources/orchestration.job.yml` (paused since T068) and confirm one unattended run completes end to end
- [ ] T107 [P] Verify SC-016 from a clean checkout — `uv sync && uv run pytest tests/unit` passes with no workspace connection and no profile configured
- [ ] T108 Verify SC-017 — deploy the bundle to an empty state and confirm a working system with no undocumented manual steps; correct `quickstart.md` wherever reality diverged from it
- [ ] T109 [P] Write `README.md` at repo root covering purpose, the Free Edition substitutions from spec.md's table, deployment, and how the spikes resolved
- [ ] T110 Reconcile `research.md` — record the actual outcomes of spikes S1 and S2 and any contingency taken in T052, so the document reflects what was built rather than what was planned
- [ ] T111 Verify teardown safety: `databricks bundle destroy -t dev --profile DEFAULT` removes only this feature's assets and leaves the unrelated catalogs (`test`, `my_files`, `bridge_monitoring`, `claudecatalog`) and the pre-existing `agent-langgraph-agent-one` app untouched
- [ ] T112 [P] Verify Constitution III (one writer per table): enumerate every table written by each pipeline and job and confirm no table has two producers, cross-checking against the ownership table in `contracts/pipeline-datasets.md`. Record the enumeration so a reviewer can re-check it without re-deriving it
- [ ] T113 [P] Verify Constitution V (no real personal data — NON-NEGOTIABLE): confirm every row in `source.customer`, `source.policy`, `source.claim`, the telematics feed and both image sets originates from the setup job's generators; confirm no real dataset was substituted; and confirm the deployed app URL is not shared beyond the workspace owner. Record the result in `README.md`
- [ ] T114 [P] Add a repository lint enforcing Constitution VI and the explicit-profile constraint — fail on any occurrence of `import dlt`, `@dlt.`, `LIVE.`, `APPLY CHANGES` or `dlt.apply_changes` under `src/`, and on any `databricks` CLI invocation in `src/`, `resources/` or the docs that omits `--profile`. Wire it into the unit test run so it executes offline with no workspace
- [ ] T115 Run `superpowers:requesting-code-review` across the whole branch, then `superpowers:finishing-a-development-branch`

---

## Dependencies & Execution Order

### Phase dependencies

- **Phase 1 (Setup)**: no dependencies
- **Phase 2 (Foundational)**: depends on Phase 1 — **blocks every user story**
- **Phase 3 (US1)**: depends on Phase 2. Blocks US2–US7 in practice, because every downstream story reads the data it seeds
- **Phase 4 (US2)**, **Phase 5 (US3)**, **Phase 6 (US4)**: each depends on Phase 3. **Mutually independent** — the three ingestion paths touch different files and different bronze tables
- **Phase 7 (US5)**: depends on Phases 4, 5 and 6 — silver reads all bronze tables
- **Phase 8 (US6)**: depends on Phase 7 — triage reads the gold joined view
- **Phase 9 (US7)**: depends on Phase 8 — every surface reads `gold.claim_insights`
- **Phase 10**: depends on all of the above

This story graph is more sequential than the template's default. That is inherent to a medallion
architecture, not a planning failure — silver cannot be built before bronze exists. The genuine
parallelism is the three ingestion paths in Phases 4–6.

### Within each story

- Tests are written first and must fail before implementation
- `lib/` pure functions before the pipeline code that imports them
- Bronze before silver before gold
- Spikes before any work that would depend on their outcome

### Parallel opportunities

- **T006, T007** in Setup
- **T008–T011** (all four unit test files) then **T012–T015** (all four lib modules) in Foundational — eight tasks across eight files
- **Phases 4, 5 and 6 in their entirety** — three ingestion paths, three separate files, three separate bronze table sets
- **T056–T059** — four silver tables in the same file but independent dataset definitions; parallelise only if the implementer can avoid edit conflicts, otherwise treat as sequential
- **T093–T095**, then **T099, T100** in the app
- **T107, T109** in polish

---

## Parallel Example: Phase 2 Foundational

```bash
# Write all four unit test files together (they must fail first):
Task: "Write tests/unit/test_severity.py"
Task: "Write tests/unit/test_payload.py"
Task: "Write tests/unit/test_cleaning.py"
Task: "Write tests/unit/test_decision.py"

# Then implement all four pure modules together:
Task: "Implement src/smart_claims/lib/severity.py"
Task: "Implement src/smart_claims/lib/payload.py"
Task: "Implement src/smart_claims/lib/cleaning.py"
Task: "Implement src/smart_claims/lib/decision.py"
```

## Parallel Example: Phases 4–6 Ingestion

```bash
# Three independent ingestion paths after US1 completes:
Task: "Phase 4 (T027-T035): telematics producer and Auto Loader decode"
Task: "Phase 5 (T036-T044): Auto CDC from Delta change feed"
Task: "Phase 6 (T045-T054): binaryFile, CSV drift, cleanSource archive"
```

---

## Implementation Strategy

### MVP

Phases 1–3 (T001–T026). Delivers a governed catalog with seeded, referentially consistent source
data and labelled images — the foundation every other story reads. **Stop and validate** against
SC-001 before continuing.

### Incremental delivery

Each of Phases 4 through 9 is independently demonstrable and can be stopped at:

1. **+US2** — telematics decoded into typed bronze columns, both modes
2. **+US3** — insert/update/delete converging into bronze
3. **+US4** — images ingested, drift handled both ways, files archived
4. **+US5** — quality-enforced silver and joined gold, orchestrated hourly
5. **+US6** — governed classifier and extensible triage
6. **+US7** — dashboard, Genie, and the claims portal

### Dispatch grouping (per the project's subagent workflow)

- **Phases 1 + 2**: one lightweight dispatch, no separate reviewer gate — prerequisite plumbing
- **Phase 3 onward**: group by deliverable. Sequential tasks building one deliverable bundle into
  one dispatch; `[P]` tasks on separate files get their own. Each group: implementer → reviewer
  (spec compliance + code quality) → fix loop until clean
- **Reviewer context**: source Global Constraints from spec.md's FRs and success criteria,
  plan.md's Technical Context, **and `.specify/memory/constitution.md` v1.0.0**, which is ratified
  and binding. Reviewers MUST gate on all 7 principles. Principles I (Test Discipline) and V (No
  Real Personal Data) are NON-NEGOTIABLE — a violation of either fails the review outright and
  MUST NOT be waived to unblock a task
- **Test compliance**: tests are required for this feature. Reviewers verify the test files are
  present **in the diff** — not merely quoted in the implementer's report — and that RED/GREEN
  evidence is included

### Ledger format

```
Phase 3 (T019-T026) [US1]: complete (commits <base7>..<head7>, review clean)
Phase 8 group C (T078-T081) [US6]: complete — extends lib/decision.py from Phase 2 (T015),
  tests/unit/test_decision.py updated in place, full file re-run, review clean
```

---

## Notes

- `[P]` means different files and no dependency on an incomplete task
- Commit after each task or logical group; test files are committed **with** their implementation
- Verify tests fail before implementing — a test that passes before the code exists is testing nothing
- Stop at any checkpoint to validate a story independently
- Keep continuous pipelines stopped except during their demonstration (T033/T034) — Free Edition
  serverless quota is finite and a forgotten continuous pipeline will consume it
