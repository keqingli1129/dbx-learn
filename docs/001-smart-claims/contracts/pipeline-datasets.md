# Contract: Pipeline Dataset Boundaries

Three Lakeflow Declarative Pipelines plus one orchestrating job. The contract between them is the
set of tables each owns; no pipeline writes a table another owns.

## `ingest` pipeline — default target `smart_claims_dev.bronze`

**Reads**: `landing` volumes; the change feed of `source.customer` / `policy` / `claim`.
**Owns**: `bronze.telematics`, `bronze.customer`, `bronze.policy`, `bronze.claim`,
`bronze.training_images`, `bronze.claim_images`, `bronze.claim_images_meta`.

| Dataset | Type | Mechanism |
|---|---|---|
| `bronze.telematics` | Streaming Table | Auto Loader (JSON) → base64 decode → `from_json` → typed columns |
| `bronze.customer`/`policy`/`claim` | Streaming Table (explicit) + Auto CDC flow | change-feed stream, keyed on natural key, `sequence_by="_commit_version"`, `apply_as_deletes` on `_change_type = 'delete'`, SCD Type 1 |
| `bronze.training_images` | Streaming Table | Auto Loader, `cloudFiles.format=binaryFile` |
| `bronze.claim_images_meta` | Streaming Table | Auto Loader, `cloudFiles.format=csv`, schema-evolution mode from pipeline configuration |
| `bronze.claim_images` | Streaming Table | Auto Loader, `binaryFile`, `cloudFiles.cleanSource=MOVE` |

**Configuration keys** (pipeline settings, not hardcoded — the transcript hardcodes these and
notes it should not):
`catalog`, `landing_volume_root`, `schema_evolution_mode`, `clean_source_retention`,
`archive_path`.

**Modes**: `continuous: false` by default; the same pipeline definition runs continuously when
the flag flips (FR-008). No code change.

## `transform` pipeline — default target `smart_claims_dev.silver`

**Reads**: `bronze.*`. **Owns**: all `silver.*`, and the three gold materialized views
`gold.telematics_agg`, `gold.customer_claim_policy`, `gold.customer_claim_policy_telematics`
(written by fully-qualified name).

Silver datasets are streaming tables carrying `expect_all_or_drop` expectations. Gold datasets are
materialized views — required, not stylistic, because they aggregate and join over sources whose
rows change (research R6).

Cleaning logic is **imported from `smart_claims.lib.cleaning`**, not written inline in the
decorators, so it is unit-testable offline (research R10).

**File layout**: one dataset per file, named after the dataset, under
`src/smart_claims_etl/transformations/{bronze,silver,gold}/` (research R12). Each pipeline's
`libraries.glob` targets only the layers it owns, which is what keeps the one-writer-per-table
invariant below mechanically enforceable rather than merely documented.

## `ml` job — not a pipeline

**Reads**: `silver.training_images`, `silver.claim_images`, `gold.customer_claim_policy_telematics`.
**Owns**: `gold.training_images_resized`, `gold.claim_images_predicted`, `gold.claims_rules`,
`gold.claim_insights`, and the registered model.

Tasks: resize → train + register → batch score → seed rules → evaluate rules.
Training is a separate task from scoring so scoring can re-run without retraining.

## `smart_claims_hourly` job — orchestration

```
ingest_pipeline ──► transform_pipeline ──► score_and_triage
```

`transform` runs only on `ingest` success; `score_and_triage` only on `transform` success
(FR-024). Training is **not** in the hourly job — it runs on demand. Scheduled hourly.

## Ownership invariant

Each table has exactly one writer. A table written by two pipelines is a defect, not a
configuration choice — it produces non-deterministic refresh ordering and makes lineage
meaningless.
