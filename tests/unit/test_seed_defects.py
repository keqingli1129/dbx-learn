"""The deliberate defects planted in the seed data.

These exist so downstream checks can be PROVEN to fire. A silver run that drops zero rows is
ambiguous -- working expectations on clean data look exactly like expectations that never ran.
The manifest turns SC-006 from "some rows were dropped" into an exact equality.
"""

import pytest

from smart_claims.setup.seed_source_data import DEFECT_RATES, generate, inject_defects

N_CUSTOMERS, N_POLICIES, N_CLAIMS = 200, 240, 260


@pytest.fixture
def seeded():
    data = generate(N_CUSTOMERS, N_POLICIES, N_CLAIMS, seed=1234)
    return data, data.pop("_manifest")[0]


class TestManifestIsHonest:
    def test_reports_every_defect_kind(self, seeded):
        _, m = seeded
        assert set(m) == set(DEFECT_RATES) | {
            "claims_silver_should_drop",   # exact figure T064 asserts against
            "orphan_claims",               # planted referential gaps
            "orphan_claim_nos",
            "chassis_without_telematics",  # vehicles the producer must skip (T027)
        }

    def test_counts_match_what_is_actually_in_the_data(self, seeded):
        data, m = seeded
        claims, policies = data["claim"], data["policy"]
        assert sum(1 for r in claims if r["claim_no"] is None) == m["null_claim_no"]
        assert sum(1 for r in claims if not 0 <= r["incident_hour"] <= 23) == m["bad_incident_hour"]
        assert sum(1 for r in claims if r["total_claim_amount"] <= 0) == m["nonpositive_amount"]
        assert sum(1 for r in policies if r["premium"] < 0) == m["negative_premium"]

    def test_drop_total_is_the_plain_sum_because_defects_are_disjoint(self, seeded):
        data, m = seeded
        claims = data["claim"]
        # A row carrying two defects would make the sum over-count what silver actually drops.
        doomed = {
            i for i, r in enumerate(claims)
            if r["claim_no"] is None or not 0 <= r["incident_hour"] <= 23
            or r["total_claim_amount"] <= 0
        }
        assert len(doomed) == m["claims_silver_should_drop"]
        assert len(doomed) == m["null_claim_no"] + m["bad_incident_hour"] + m["nonpositive_amount"]

    def test_defects_are_a_minority_so_the_survivors_are_still_useful(self, seeded):
        data, m = seeded
        assert m["claims_silver_should_drop"] < len(data["claim"]) * 0.1


class TestDefectsExerciseTheRightChecks:
    def test_bad_hours_are_out_of_range_in_both_directions(self, seeded):
        data, _ = seeded
        bad = [r["incident_hour"] for r in data["claim"] if not 0 <= r["incident_hour"] <= 23]
        # A one-sided check (`hour <= 23`) must not pass by accident.
        assert any(h < 0 for h in bad), "no negative hours planted"
        assert any(h > 23 for h in bad), "no above-range hours planted"

    def test_nonpositive_amounts_include_both_zero_and_negative(self, seeded):
        data, _ = seeded
        vals = [r["total_claim_amount"] for r in data["claim"] if r["total_claim_amount"] <= 0]
        assert 0.0 in vals and any(v < 0 for v in vals)

    def test_negative_premiums_survive_abs_cleaning(self, seeded):
        data, _ = seeded
        neg = [r["premium"] for r in data["policy"] if r["premium"] < 0]
        assert neg and all(abs(v) > 0 for v in neg), "abs() must yield a usable premium"


class TestDeterminismAndOptOut:
    def test_same_seed_plants_the_same_defects(self):
        a = generate(N_CUSTOMERS, N_POLICIES, N_CLAIMS, seed=99)
        b = generate(N_CUSTOMERS, N_POLICIES, N_CLAIMS, seed=99)
        assert a == b

    def test_inject_false_yields_clean_data(self):
        data = generate(N_CUSTOMERS, N_POLICIES, N_CLAIMS, seed=1234, inject=False)
        assert "_manifest" not in data
        assert all(r["claim_no"] is not None for r in data["claim"])
        assert all(0 <= r["incident_hour"] <= 23 for r in data["claim"])
        assert all(r["total_claim_amount"] > 0 for r in data["claim"])
        assert all(r["premium"] >= 0 for r in data["policy"])

    def test_rates_are_configurable(self):
        data = generate(N_CUSTOMERS, N_POLICIES, N_CLAIMS, seed=1234, inject=False)
        m = inject_defects(data, rates={**DEFECT_RATES, "null_claim_no": 0.5}, seed=1)
        assert m["null_claim_no"] == int(N_CLAIMS * 0.5)


class TestReferentialIntegrity:
    """Every reference resolves -- except the orphans, which are planted on purpose."""

    def test_every_policy_belongs_to_a_real_customer(self, seeded):
        data, _ = seeded
        ids = {r["customer_id"] for r in data["customer"]}
        assert all(r["customer_id"] in ids for r in data["policy"])

    def test_only_the_planted_orphans_dangle(self, seeded):
        data, m = seeded
        nos = {r["policy_no"] for r in data["policy"]}
        dangling = [r["claim_no"] for r in data["claim"] if r["policy_no"] not in nos]
        assert len(dangling) == m["orphan_claims"]
        assert sorted(dangling) == m["orphan_claim_nos"]

    def test_orphans_survive_the_silver_expectations(self, seeded):
        """Otherwise the edge case never reaches triage and nothing downstream sees it.

        An orphan planted on a claim that silver drops for a null claim number would be a test
        of nothing: the row is gone before any rule evaluates it.
        """
        data, m = seeded
        nos = {r["policy_no"] for r in data["policy"]}
        for r in (c for c in data["claim"] if c["policy_no"] not in nos):
            assert r["claim_no"] is not None
            assert 0 <= r["incident_hour"] <= 23
            assert r["total_claim_amount"] > 0

    def test_some_chassis_are_reserved_to_have_no_telematics(self, seeded):
        data, m = seeded
        silent = set(m["chassis_without_telematics"])
        assert silent, "the indeterminate speed-check case needs at least one silent vehicle"
        known = {r["chassis_no"] for r in data["policy"]}
        assert silent <= known, "a reserved chassis must belong to a real policy"


class TestDistributionIsSkewed:
    """Uniform cardinality would exercise joins and aggregations only at 1-2 rows per group."""

    def test_some_policies_have_no_claims_and_some_have_many(self, seeded):
        from collections import Counter
        data, _ = seeded
        per_policy = Counter(r["policy_no"] for r in data["claim"])
        with_none = len(data["policy"]) - len(per_policy)
        assert with_none > 0, "no zero-claim policy: left joins never see a non-match"
        assert max(per_policy.values()) >= 3, "no policy with several claims: grouping is trivial"

    def test_some_customers_hold_no_policies(self, seeded):
        data, _ = seeded
        owners = {r["customer_id"] for r in data["policy"]}
        assert len(owners) < len(data["customer"])

    def test_totals_are_unchanged_by_the_skew(self, seeded):
        data, _ = seeded
        assert len(data["customer"]) == N_CUSTOMERS
        assert len(data["policy"]) == N_POLICIES
        assert len(data["claim"]) == N_CLAIMS
