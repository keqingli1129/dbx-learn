# Contract: Claims Portal HTTP API

FastAPI backend for the Databricks App. Serves both customer and admin modes.
All responses `application/json` unless noted. No authentication — see the spec's scope
assumptions; this is a learning artifact and must not carry real personal data.

## `POST /api/claims/classify`

Classify an uploaded photograph without submitting a claim. Backs FR-039 / US7 #4.

**Request**: `multipart/form-data`, field `image` — JPEG or PNG, max 10 MB.

**200**
```json
{"predicted_severity": "Major Damage", "confidence": 0.87, "model_version": "1"}
```

**415** non-image upload (FR-041) — `{"error": "unsupported_media_type", "message": "..."}`
**413** oversize upload.

## `POST /api/claims`

Submit a claim and receive a triage decision. Backs FR-038 / FR-040 / US7 #5.

**Request**: `multipart/form-data`
| Field | Type | Required | Notes |
|---|---|---|---|
| `image` | file | yes | JPEG or PNG |
| `policy_no` | string | yes | |
| `incident_city` | string | yes | |
| `total_claim_amount` | number | yes | must be > 0 |
| `incident_date` | date | yes | ISO-8601, not in the future |
| `reported_severity` | string | yes | one of the severity domain |
| `collision_type` | string | yes | |
| `num_vehicles_involved` | integer | yes | ≥ 1 |
| `notes` | string | no | |

**201**
```json
{
  "claim_no": "CLM-2026-000517",
  "overall_outcome": "release_funds",
  "predicted_severity": "Major Damage",
  "checks": [
    {"name": "valid_severity",    "result": "pass",          "detail": "Reported severity matches predicted severity"},
    {"name": "valid_amount",      "result": "pass",          "detail": "Claimed 30000.00 within coverage of 50000.00"},
    {"name": "valid_policy_date", "result": "pass",          "detail": "Incident date within policy period"},
    {"name": "valid_speed",       "result": "indeterminate", "detail": "No telematics readings for this vehicle"}
  ]
}
```

`result` is always one of `pass` | `fail` | `indeterminate`. `overall_outcome` is
`release_funds` only when every check is `pass`; otherwise `requires_investigation` (FR-033).

**404** unknown `policy_no` — the claim is still recorded and returned as
`requires_investigation` with the coverage and policy-date checks `indeterminate`, matching the
spec's edge case. It is not a hard error.
**409** duplicate submission — same policy, incident date and amount within a short window;
returns the existing `claim_no` rather than triaging twice.
**422** validation failure, with per-field messages.

## `GET /api/admin/overview`

Backs FR-042 / US7 #6.

**Query**: `severity` (optional, repeatable), `from`, `to` (optional ISO dates).

**200**
```json
{
  "total_claims": 1284,
  "by_severity": [{"severity": "Major Damage", "count": 412}],
  "by_outcome": {"release_funds": 903, "requires_investigation": 381},
  "total_claimed_amount": 38412900.00,
  "claims": [
    {"claim_no": "...", "customer_name": "...", "incident_date": "2026-08-14",
     "reported_severity": "Major Damage", "total_claim_amount": 30000.00,
     "overall_outcome": "requires_investigation"}
  ]
}
```

## `GET /api/admin/claims/{claim_no}`

Backs FR-042 / US7 #7. Must satisfy SC-015 — populated in under two seconds.

**200**
```json
{
  "claim": {"claim_no": "...", "incident_date": "...", "incident_hour": 14,
            "total_claim_amount": 30000.00, "reported_severity": "Major Damage",
            "collision_type": "Multi-vehicle", "num_vehicles_involved": 3},
  "customer": {"customer_id": "...", "first_name": "...", "last_name": "...",
               "address": "...", "email": "..."},
  "policy": {"policy_no": "...", "sum_insured": 50000.00,
             "pol_eff_date": "...", "pol_expiry_date": "...", "chassis_no": "..."},
  "telematics": {"max_speed": 68.4, "avg_speed": 41.2, "reading_count": 240},
  "prediction": {"predicted_severity": "Major Damage", "confidence": 0.87},
  "checks": [{"name": "...", "result": "pass", "detail": "..."}],
  "overall_outcome": "requires_investigation",
  "image_url": "/api/claims/CLM-2026-000517/image"
}
```

`telematics` is `null` when the vehicle has no readings; the client renders the speed check as
indeterminate rather than absent.

**404** unknown claim.

## `GET /api/claims/{claim_no}/image`

Returns the stored accident photograph. `image/jpeg` or `image/png`. **404** if none.

## `GET /health`

**200** `{"status": "ok", "data_source": "lakebase" | "sql_warehouse"}`

`data_source` reports which backing store resolved at startup, making the outcome of spike S2
observable at runtime rather than buried in configuration.

## Data access boundary

Every handler reads through one interface — `ClaimsRepository` — with two implementations,
Lakebase-backed and warehouse-backed, selected at startup. No handler issues SQL directly. This
is what allows spike S2 to fail without any change to the API surface or the UI.
