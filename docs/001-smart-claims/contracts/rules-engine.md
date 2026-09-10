# Contract: Triage Rules Engine

Rules are rows in `gold.claims_rules`, not code (FR-030). A generic evaluator reads enabled rules
and applies each to every claim, producing `gold.claim_insights`.

## Adding a rule

```sql
INSERT INTO smart_claims_dev.gold.claims_rules
  (rule_id, rule_name, description, check_expr, pass_label, fail_label, enabled, created_at)
VALUES (
  'R005', 'valid_license',
  'Driver licence was issued before the incident date',
  'driver_license_issue_date < incident_date',
  'Licence valid at time of incident',
  'Licence issued after incident date',
  true, current_timestamp()
);
```

Re-running the evaluator re-scores every existing claim against the new rule set (FR-034). No
code change, no redeploy.

## Evaluator contract

**Input**: `gold.customer_claim_policy_telematics` left-joined to `gold.claim_images_predicted`
on `claim_no`; plus all enabled rows of `gold.claims_rules`.

**Output**: `gold.claim_insights` — one row per claim, one result column per rule name.

**Per-rule evaluation** produces exactly one of three values:

| Value | When |
|---|---|
| `pass` | `check_expr` evaluates to `true` |
| `fail` | `check_expr` evaluates to `false` |
| `indeterminate` | `check_expr` evaluates to `NULL` — any operand is missing |

The `NULL → indeterminate` mapping is the whole mechanism behind the spec's missing-data edge
cases. A vehicle with no telematics yields `max_speed IS NULL`, so `max_speed <= 45` is `NULL`,
so the speed check is indeterminate and the claim is routed to a human. Collapsing `NULL` to
`false` would also route it to a human but would report it as speeding, which is wrong. Collapsing
to `true` would approve it, which is worse.

**Overall outcome**:

```
release_funds            when every enabled rule evaluated to pass
requires_investigation   otherwise (any fail, or any indeterminate)
```

## `check_expr` requirements

- A SQL boolean expression valid against the joined input relation.
- References only columns of that relation. No subqueries, no correlated references.
- Must return `NULL`, not `false`, when an operand is missing — do not wrap operands in
  `coalesce` to force a value.

## Invariants

1. Exactly one `claim_insights` row per claim in the input.
2. `overall_outcome = release_funds` ⟺ every rule result is `pass`.
3. Disabling a rule removes its column from consideration in the overall outcome; historical rows
   are recomputed on the next run rather than retaining a stale verdict.
4. Evaluation is deterministic and idempotent — re-running with unchanged inputs and unchanged
   rules produces identical results apart from `evaluated_at`.
