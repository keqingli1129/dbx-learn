# Quickstart: Validating Smart Claims

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

How to deploy the feature and prove each user story works. Every section maps to specific
success criteria. Run them in order — later sections depend on earlier data.

## Prerequisites

- Databricks CLI ≥ v1.15.0, authenticated on the `DEFAULT` profile (`databricks auth profiles`
  must show `Valid: YES`).
- Python 3.12 and Java 21 locally, for the test suites. No uv — a plain virtualenv is used.
- Authority to create catalogs, pipelines, jobs, dashboards and apps in the workspace.

**Working directory**: the repository root — the bundle is the repository.
**No uv**: use a plain virtualenv (`python -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]'`);
commands below are written as bare `pytest`.

## 0. Offline tests — no workspace needed

```bash
python -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]'
./run-tests.sh tests/unit -v
# run-tests.sh clears PYTHONPATH, which pytest cannot do for itself (research R10).
# pytest defaults to -m 'not workspace', so integration runs need an explicit -m workspace.
```

**Expect**: all pass. This is SC-016. It must pass before anything is deployed — it covers
payload decoding, name and address normalisation, date coercion and decision composition.

## 1. Deploy

```bash
./bootstrap.sh dev DEFAULT          # creates the catalog -- see below
databricks bundle validate -t dev --profile DEFAULT
databricks bundle deploy -t dev --profile DEFAULT
```

**Why `bootstrap.sh` comes first**: this account has Unity Catalog Default Storage enabled, and
catalog creation through the REST API is refused — which is the path both `bundle deploy` and
`databricks catalogs create` use. The same statement succeeds through SQL, so `bootstrap.sh` runs
`CREATE CATALOG IF NOT EXISTS` with the name taken from the bundle's own resolved variable
(research R14). It is idempotent; run it as often as you like.

**Expect**: validation clean; deploy creates the catalog, five schemas, volumes, three pipelines,
two jobs, the dashboard and the app.

```bash
databricks bundle run setup_job -t dev --profile DEFAULT
```

**Expect**: source tables seeded, training images downloaded into the landing volume. This is
SC-001 and SC-017.

```bash
databricks catalogs list --profile DEFAULT | grep smart_claims_dev
databricks schemas list smart_claims_dev --profile DEFAULT
```

**If the image download fails**: the task reports egress failure explicitly and stops (FR-004).
Network egress was confirmed working during planning (research R1); a failure here means
something changed, not that the design was wrong.

## 2. Telematics ingestion — US2

```bash
databricks bundle run telematics_producer -t dev --profile DEFAULT
databricks bundle run ingest_pipeline -t dev --profile DEFAULT
databricks experimental aitools tools query \
  "SELECT chassis_no, speed, latitude, longitude, event_timestamp FROM smart_claims_dev.bronze.telematics LIMIT 5" \
  --profile DEFAULT
```

**Expect**: five rows with populated typed columns — not an opaque blob. If you see base64 text,
the decode step is wrong.

**Incrementality (SC-003)**: note the row count, re-run `ingest_pipeline` with no new events,
confirm the count is unchanged. Then run the producer again and re-run ingest; only the new
events should be added.

**Continuous mode**: set the pipeline's `continuous` flag, start it, run the producer while it
runs, and watch rows appear without re-triggering. Stop it afterwards — a continuous pipeline
keeps consuming compute.

## 3. Change capture — US3

```bash
databricks experimental aitools tools query \
  "SELECT count(*) FROM smart_claims_dev.bronze.customer" --profile DEFAULT
databricks bundle run cdc_mutation_job -t dev --profile DEFAULT   # one insert, one update, one delete
databricks bundle run ingest_pipeline -t dev --profile DEFAULT
```

**Expect** (SC-002), verified by the three queries the mutation job prints:
- the inserted policy is present,
- the updated claim shows its **new** severity and appears exactly once — a second row with the
  old value means Auto CDC is misconfigured, most likely a wrong key or sequence column,
- the deleted customer returns zero rows.

## 4. File ingestion and drift — US4

```bash
databricks experimental aitools tools query \
  "SELECT count(*), count(DISTINCT label) FROM smart_claims_dev.bronze.training_images" --profile DEFAULT
```

**Expect**: ≥ 3 distinct labels, ≥ 20 images each.

**Schema drift (SC-004)** — run both modes:

1. With `schema_evolution_mode = addNewColumns`, upload a metadata file carrying one extra
   column and re-run ingest. **Expect**: the new column exists on the table, `NULL` for all
   prior rows, populated for the new one.
2. Switch to `rescue`, upload a file carrying a *further* new column, re-run.
   **Expect**: table columns unchanged; the new field's value appears inside `_rescued_data`.

**Archiving (SC-005)**: after the retention period elapses, re-run ingest and list the volume.

```bash
databricks fs ls dbfs:/Volumes/smart_claims_dev/landing/claims/archive --profile DEFAULT
```

**Expect**: processed files present in `archive/`, absent from `images/`. If nothing moved, the
retention period has not yet elapsed — re-run rather than treating it as a failure.

## 5. Quality and gold — US5

```bash
databricks bundle run transform_pipeline -t dev --profile DEFAULT
```

**Expect (SC-006)**: the pipeline's expectations panel shows non-zero drops for
`valid_claim_number` and `valid_incident_hour` — the seed data deliberately contains violations,
so **zero drops means the expectations are not firing**, not that the data is clean.

```bash
databricks experimental aitools tools query \
  "SELECT count(*) AS bad FROM smart_claims_dev.silver.claim
   WHERE claim_no IS NULL OR incident_hour NOT BETWEEN 0 AND 23" --profile DEFAULT
```

**Expect**: `bad = 0`.

**Joins (SC-007)** — no claims lost or duplicated:

```bash
databricks experimental aitools tools query \
  "SELECT (SELECT count(*) FROM smart_claims_dev.silver.claim) AS silver_claims,
          (SELECT count(*) FROM smart_claims_dev.gold.customer_claim_policy_telematics) AS gold_rows,
          (SELECT count(DISTINCT claim_no) FROM smart_claims_dev.gold.customer_claim_policy_telematics) AS distinct_claims" \
  --profile DEFAULT
```

**Expect**: all three equal. `gold_rows > distinct_claims` means a join fanned out — most likely
telematics joined without aggregating first.

**Amount rule (SC-007a)**: confirm no `silver.claim` row has `total_claim_amount <= 0`, and that
the quality report attributes the drops to `positive_claim_amount`.

**Schema contract (SC-007b)**: drop a depended-upon column from a source table, re-run transform,
and confirm it **fails with an error naming that column** rather than emitting null-filled rows.
Restore the column afterwards.

**Two accidents, one vehicle (SC-007)**: pick a chassis with readings on two dates and confirm
each claim gets the `max_speed` from its own incident date, not a shared figure.

**Cleaning spot checks**: `silver.customer` has populated `first_name` and `last_name`;
`silver.policy` has no negative `premium`; date columns are `DATE`/`TIMESTAMP`, not `STRING`.

**Orchestration**: run `smart_claims_hourly` and confirm transform starts only after ingest
succeeds.

## 6. Model and triage — US6

```bash
databricks bundle run ml_training_job -t dev --profile DEFAULT
```

Slow — CPU-only training. **Expect (SC-008)**: an MLflow run under the named experiment with
parameters and metrics logged, and `smart_claims_dev.gold.claims_damage_level` registered with a
`@prod` alias.

```bash
databricks experimental aitools tools query \
  "SELECT label, predicted_severity, count(*) FROM smart_claims_dev.gold.training_images_resized
   GROUP BY 1,2 ORDER BY 1,2" --profile DEFAULT
```

**Expect (SC-009)**: a populated confusion matrix. Accuracy is recorded, not thresholded — a
mediocre matrix is an acceptable outcome; an empty one is not.

**Rules (SC-010, SC-011)** — the triage test fixtures construct one claim per violated rule:

```bash
./run-tests.sh tests/integration/test_rules_engine.py -v -m workspace --profile DEFAULT
```

**Expect**: for each of the four checks, the claim violating only that check is
`requires_investigation` with exactly that check `fail`; the compliant claim is `release_funds`;
the claim with no telematics is `requires_investigation` with the speed check `indeterminate`.

**Extensibility (SC-012)**: insert a fifth rule, re-run the evaluator, confirm existing claims
are re-scored and a new result column appears — with no code change.

## 7. Consumption — US7

**Dashboard (SC-013)**: open it and reconcile the headline claim count against
`SELECT count(*) FROM smart_claims_dev.gold.claim_insights`. Narrow the date filter and confirm
every visual responds.

**Genie**: ask *"how many claims fall into each severity category"*. **Expect**: counts matching a
direct query, and the generated SQL visible.

**App (SC-014, SC-015)**:

```bash
databricks apps list --profile DEFAULT
```

Open the app URL. In customer mode, upload an accident photo — the predicted severity appears
before submission. Complete the form and submit. **Expect**: a decision within two minutes
showing all four individual check results, and matching what the rules engine independently
produces for the same inputs. Upload a non-image file and confirm a clear rejection (FR-041).

In admin mode: the overview shows totals and a severity breakdown, filtering works, and opening
a claim populates its detail view — including the uploaded image — in under two seconds.

```bash
curl -s "$APP_URL/health"
```

**Expect**: `data_source` reports `lakebase` or `sql_warehouse`, recording how spike S2 resolved.

## 8. Full teardown

```bash
databricks bundle destroy -t dev --profile DEFAULT
```

Removes everything this feature created. It must not touch the workspace's unrelated catalogs
(`test`, `my_files`, `bridge_monitoring`, `claudecatalog`) or the pre-existing
`agent-langgraph-agent-one` app — verify that after destroying.
