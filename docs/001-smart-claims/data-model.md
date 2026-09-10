# Data Model: Smart Claims

**Date**: 2026-09-09 | **Feature**: [spec.md](./spec.md) | **Research**: [research.md](./research.md)

Catalog: `smart_claims_dev`. Five schemas. Every table below is fully qualified as
`smart_claims_dev.<schema>.<table>`.

## Layer map

```
source/  (simulated operational database, Delta CDF enabled)
  customer, policy, claim
        │  change feed  ──────────────────► Auto CDC
landing/ (volumes only, no tables)
  telematics_raw/        JSON event files      ──► Auto Loader
  claims/images/         accident photos       ──► Auto Loader (cleanSource=MOVE)
  claims/archive/        processed photos
  claims/metadata/       image↔claim CSV       ──► Auto Loader (schema evolution)
  training_images/       labelled photos       ──► Auto Loader (binaryFile)
        │
bronze/  raw, typed as-ingested
  telematics, customer, policy, claim,
  training_images, claim_images, claim_images_meta
        │  expectations + cleaning
silver/  cleaned, quality-enforced
  telematics, customer, policy, claim,
  training_images, claim_images
        │  aggregate + join
gold/    business-ready
  telematics_agg (MV), customer_claim_policy (MV),
  customer_claim_policy_telematics (MV),
  training_images_resized, claim_images_predicted,
  claims_rules, claim_insights,
  claims_damage_level (registered model)
```

## Source layer

All three carry `delta.enableChangeDataFeed = true` and `delta.enableRowTracking = true` (the
latter is required for downstream materialized views to refresh incrementally rather than
recompute — see research R6).

### `source.customer`
| Column | Type | Notes |
|---|---|---|
| `customer_id` | STRING | natural key |
| `name` | STRING | combined "First Last" — deliberately un-split, as in the transcript |
| `date_of_birth` | STRING | text date, format `MM/dd/yyyy` |
| `address` | STRING | inconsistent whitespace and casing, deliberately |
| `email`, `phone` | STRING | |
| `city`, `state`, `zip` | STRING | |

### `source.policy`
| Column | Type | Notes |
|---|---|---|
| `policy_no` | STRING | natural key |
| `customer_id` | STRING | → `customer.customer_id` |
| `chassis_no` | STRING | insured vehicle; joins to telematics |
| `sum_insured` | DECIMAL(12,2) | coverage ceiling — the amount claims are checked against |
| `premium` | DECIMAL(10,2) | **some values deliberately negative**, to exercise FR-019 |
| `pol_eff_date`, `pol_expiry_date` | STRING | text dates, format `yyyy-MM-dd` |
| `pol_issue_date` | STRING | text date, **format `dd-MM-yyyy`** — deliberately different from the two above, to exercise FR-017 |
| `model`, `make`, `model_year` | STRING / INT | vehicle |

### `source.claim`
| Column | Type | Notes |
|---|---|---|
| `claim_no` | STRING | natural key. **Some rows deliberately null**, to exercise FR-015 |
| `policy_no` | STRING | → `policy.policy_no` |
| `claim_date` | STRING | text date, `yyyy-MM-dd HH:mm:ss` |
| `incident_date` | STRING | text date, `MM/dd/yyyy` — a third distinct format |
| `incident_hour` | INT | 0–23. **Some rows deliberately out of range**, to exercise FR-015 |
| `incident_type`, `collision_type` | STRING | |
| `incident_severity` | STRING | customer's self-assessment. Domain below |
| `incident_city`, `incident_state` | STRING | |
| `total_claim_amount` | DECIMAL(12,2) | the amount claimed. **Some rows deliberately zero or negative**, to exercise FR-015 |
| `num_vehicles_involved` | INT | |
| `driver_license_issue_date` | STRING | text date, `dd/MM/yyyy` — a fourth format |

**Severity domain** (single vocabulary shared by customer self-assessment, model prediction and
ground-truth labels — a mismatch here would break the severity check silently):
`Trivial Damage` · `Minor Damage` · `Major Damage` · `Total Loss`

The classifier's three-class output maps onto this domain; the mapping is defined once, in
`smart_claims.lib.severity`, and used by training, scoring and rule evaluation alike.

## Landing layer

Volumes only — no tables. Managed volumes under `smart_claims_dev.landing`.

### Telematics event file format
One JSON object per line, written by the producer job:

```json
{"partition_key": "<chassis_no>", "sequence_number": "000000000000001",
 "approximate_arrival_timestamp": "2026-09-09T12:00:00Z",
 "data": "<base64 of the payload below>"}
```

Decoded `data` payload — every field a string, matching the transcript's all-string map schema:

```json
{"chassis_no": "...", "speed": "68.4", "latitude": "48.13", "longitude": "11.58",
 "event_timestamp": "2026-09-09T11:59:58Z"}
```

### Image metadata CSV
`image_id,claim_no,image_path,uploaded_at` — plus, in the two drift-test files added later, one
and then two extra columns, to exercise FR-013's two modes.

### Training image layout
`training_images/<severity_label>/<file>.jpg` — the label is recoverable from the path, exactly
as the transcript relies on.

## Bronze layer

Ingested as-is, no cleaning. All streaming tables.

- **`bronze.telematics`** — `stream_metadata STRUCT<partition_key, sequence_number, arrival_ts>`,
  then `chassis_no`, `speed`, `latitude`, `longitude`, `event_timestamp`, all STRING, plus
  `_ingested_at`. Produced by decode → `from_json` → column projection.
- **`bronze.customer` / `bronze.policy` / `bronze.claim`** — Auto CDC targets. Same columns as
  their source tables. Keyed on the natural key, sequenced by `_commit_version`, SCD Type 1.
- **`bronze.training_images`** — `path`, `modificationTime`, `length`, `content BINARY`, plus
  `label` derived from `path`.
- **`bronze.claim_images`** — same shape, without `label`. Source files archived after ingestion.
- **`bronze.claim_images_meta`** — CSV columns plus `_rescued_data STRING`.

## Silver layer

Cleaned and quality-enforced. Expectations are `expect_all_or_drop`.

| Table | Expectations | Transformations |
|---|---|---|
| `silver.claim` | `claim_no IS NOT NULL`; `incident_hour BETWEEN 0 AND 23`; `total_claim_amount > 0` | four date columns → DATE / TIMESTAMP, each with its own format; drop `_rescued_data` |
| `silver.policy` | `policy_no IS NOT NULL` | `premium → abs(premium)`; three date columns → DATE |
| `silver.customer` | `customer_id IS NOT NULL` | `name` → `first_name` + `last_name`; `date_of_birth` → DATE; `address` normalised |
| `silver.telematics` | `chassis_no IS NOT NULL`; `speed >= 0` | strings → DOUBLE / TIMESTAMP |
| `silver.training_images` | `label IS NOT NULL` | label normalised to the severity domain |
| `silver.claim_images` | `claim_no IS NOT NULL` | joined to metadata to attach `claim_no` |

## Gold layer

- **`gold.telematics_agg`** (MV) — grouped by **`chassis_no` and `event_date`** (the date part of
  `event_timestamp`): `max_speed`, `avg_speed`, `avg_latitude`, `avg_longitude`, `reading_count`.
  `max_speed` is what the speed rule tests.

  The date grain is required, not an optimisation. Grouping by `chassis_no` alone gives a vehicle
  one speed figure across its whole history, so a claim would be judged against a speed recorded
  on some unrelated day — the spec's "two accidents for the same vehicle" edge case.
- **`gold.customer_claim_policy`** (MV) — `claim ⋈ policy ⋈ customer`. One row per claim.
- **`gold.customer_claim_policy_telematics`** (MV) — the above, left-joined to `telematics_agg` on
  **`chassis_no` AND `telematics_agg.event_date = claim.incident_date`**. **Left** join
  deliberately: a vehicle with no readings for that date must still produce a claim row, with the
  speed check recorded indeterminate rather than the claim vanishing.

  Because `telematics_agg` holds at most one row per (vehicle, date), this join cannot fan out —
  the claim count is preserved exactly, which is what SC-007 verifies.
- **`gold.training_images_resized`** — 224×224 normalised training images.
- **`gold.claim_images_predicted`** — accident images with `predicted_severity` and
  `prediction_confidence`.
- **`gold.claims_rules`** — the rules engine's rule store. See the contract.
- **`gold.claim_insights`** — the triage output. See the contract.

## Triage rule store — `gold.claims_rules`

| Column | Type | Notes |
|---|---|---|
| `rule_id` | STRING | stable identifier |
| `rule_name` | STRING | the check whose result it produces, e.g. `valid_amount` |
| `description` | STRING | human-readable |
| `check_expr` | STRING | a SQL boolean expression over `gold.customer_claim_policy_telematics` joined to predictions |
| `pass_label`, `fail_label` | STRING | text written into the result column |
| `enabled` | BOOLEAN | |
| `created_at` | TIMESTAMP | |

Rules are data, not code (FR-030) — adding a rule is an insert, and re-evaluating all claims
(FR-034) is a re-run of the same generic evaluator.

### Seeded rules

| `rule_name` | Condition for pass |
|---|---|
| `valid_amount` | `total_claim_amount <= sum_insured` |
| `valid_severity` | `predicted_severity = incident_severity` |
| `valid_policy_date` | `incident_date BETWEEN pol_eff_date AND pol_expiry_date` |
| `valid_speed` | `max_speed <= <configured threshold>` |

## Triage output — `gold.claim_insights`

One row per claim: every column of `gold.customer_claim_policy_telematics`, plus
`predicted_severity`, plus one result column per rule (`valid_amount`, `valid_severity`,
`valid_policy_date`, `valid_speed`), plus:

| Column | Type | Notes |
|---|---|---|
| `overall_outcome` | STRING | `release_funds` \| `requires_investigation` |
| `evaluated_at` | TIMESTAMP | |

**Three-valued result, not boolean.** Each check is `pass`, `fail` or `indeterminate`. A check is
indeterminate when its inputs are absent — no telematics readings, no image, or a missing policy
or customer. `overall_outcome` is `release_funds` only when **every** check is `pass`; `fail` and
`indeterminate` both yield `requires_investigation` (FR-033). This is what makes the spec's edge
cases behave correctly instead of silently approving claims on missing data — a two-valued
result would force absent inputs to be scored as either pass or fail, and both are wrong.

## Registered model

`smart_claims_dev.gold.claims_damage_level`, alias `@prod`, MLflow PyFunc wrapping the fine-tuned
ResNet-18. Signature: binary image content in, severity label plus confidence out.

## Serving copy (conditional on spike S2)

`gold.customer_claim_policy_telematics` synced to a Lakebase Postgres table keyed on `claim_no`,
for the application's interactive reads. If unavailable, the app reads the same view through the
SQL warehouse behind an unchanged interface.
