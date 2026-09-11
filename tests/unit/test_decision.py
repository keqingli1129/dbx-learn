"""Folding individual check results into one triage outcome.

This is the smallest module in the project and the one most worth getting right: it decides
whether a claim pays out automatically or goes to a human. Its whole purpose is to keep
`indeterminate` distinct from `pass` and `fail` all the way to the final verdict.
"""

import pytest

from smart_claims.lib.decision import CheckResult, Outcome, from_sql_bool, overall_outcome

PASS = CheckResult.PASS
FAIL = CheckResult.FAIL
UNKNOWN = CheckResult.INDETERMINATE


class TestThreeValuesAreDistinct:
    def test_the_three_results_are_not_equal_to_each_other(self):
        assert PASS != FAIL != UNKNOWN != PASS

    def test_indeterminate_is_not_truthy_or_falsy_by_accident(self):
        """Guards against `if result:` silently treating INDETERMINATE as a pass or a fail.

        A plain string or a bool-like enum would make `if check:` compile and do the wrong thing
        without any error. Comparisons must be explicit.
        """
        with pytest.raises(TypeError):
            bool(UNKNOWN)

    def test_string_values_match_the_contract(self):
        assert PASS.value == "pass"
        assert FAIL.value == "fail"
        assert UNKNOWN.value == "indeterminate"
        assert Outcome.RELEASE_FUNDS.value == "release_funds"
        assert Outcome.REQUIRES_INVESTIGATION.value == "requires_investigation"


class TestSqlBooleanMapping:
    """`NULL -> indeterminate` is the mechanism behind every missing-data edge case."""

    def test_true_is_a_pass(self):
        assert from_sql_bool(True) is PASS

    def test_false_is_a_fail(self):
        assert from_sql_bool(False) is FAIL

    def test_null_is_indeterminate_not_a_fail(self):
        """A vehicle with no telematics yields `max_speed IS NULL`, so `max_speed <= 45` is NULL.

        Mapping that to FAIL would report the driver as speeding on no evidence at all.
        Mapping it to PASS would approve an unverified claim. Neither is acceptable.
        """
        assert from_sql_bool(None) is UNKNOWN

    @pytest.mark.parametrize("falsy", [0, "", [], {}, 0.0])
    def test_falsy_non_booleans_are_rejected_not_coerced(self, falsy):
        # Coercing 0 to False would turn "no rows" into a failed check.
        with pytest.raises(TypeError):
            from_sql_bool(falsy)

    @pytest.mark.parametrize("truthy", [1, "true", "pass", [1]])
    def test_truthy_non_booleans_are_rejected_not_coerced(self, truthy):
        with pytest.raises(TypeError):
            from_sql_bool(truthy)


class TestOverallOutcome:
    def test_all_pass_releases_funds(self):
        assert overall_outcome([PASS, PASS, PASS, PASS]) is Outcome.RELEASE_FUNDS

    def test_a_single_fail_requires_investigation(self):
        assert overall_outcome([PASS, PASS, FAIL, PASS]) is Outcome.REQUIRES_INVESTIGATION

    def test_a_single_indeterminate_requires_investigation(self):
        assert overall_outcome([PASS, PASS, UNKNOWN, PASS]) is Outcome.REQUIRES_INVESTIGATION

    def test_indeterminate_alone_is_enough_to_block_release(self):
        """FR-033: release only when EVERY check passes. Not "no check failed"."""
        assert overall_outcome([UNKNOWN]) is Outcome.REQUIRES_INVESTIGATION

    def test_mixed_fail_and_indeterminate_requires_investigation(self):
        assert overall_outcome([FAIL, UNKNOWN]) is Outcome.REQUIRES_INVESTIGATION

    def test_outcome_does_not_depend_on_order(self):
        assert overall_outcome([UNKNOWN, PASS]) is overall_outcome([PASS, UNKNOWN])
        assert overall_outcome([FAIL, PASS]) is overall_outcome([PASS, FAIL])

    def test_accepts_any_iterable_not_only_a_list(self):
        assert overall_outcome(r for r in (PASS, PASS)) is Outcome.RELEASE_FUNDS
        assert overall_outcome((PASS, UNKNOWN)) is Outcome.REQUIRES_INVESTIGATION

    def test_no_rules_requires_investigation_rather_than_releasing(self):
        """An empty rule set means NOTHING was verified -- that is not the same as all-clear.

        Read literally, "release when every rule passed" is vacuously true for zero rules, so a
        naive implementation auto-approves every claim the moment the rule table is empty or all
        rules are disabled. That is the worst possible failure direction for this system: a
        configuration mistake silently pays out every claim. Pinned to the safe reading; the
        contract has been corrected to match.
        """
        assert overall_outcome([]) is Outcome.REQUIRES_INVESTIGATION

    @pytest.mark.parametrize("bad", ["pass", None, True, 1, object()])
    def test_rejects_values_that_are_not_check_results(self, bad):
        # Accepting the raw string "pass" would let a typo like "Pass" silently block release.
        with pytest.raises(TypeError):
            overall_outcome([PASS, bad])


class TestRealisticScenarios:
    """The four seeded rules, in the combinations the spec's edge cases describe."""

    def test_a_fully_compliant_claim_is_released(self):
        checks = {"valid_amount": PASS, "valid_severity": PASS,
                  "valid_policy_date": PASS, "valid_speed": PASS}
        assert overall_outcome(checks.values()) is Outcome.RELEASE_FUNDS

    def test_vehicle_with_no_telematics_is_investigated_not_released(self):
        checks = {"valid_amount": PASS, "valid_severity": PASS,
                  "valid_policy_date": PASS, "valid_speed": UNKNOWN}
        assert overall_outcome(checks.values()) is Outcome.REQUIRES_INVESTIGATION

    def test_orphan_claim_with_no_policy_is_investigated(self):
        # Missing policy makes both coverage and policy-date unevaluable.
        checks = {"valid_amount": UNKNOWN, "valid_severity": PASS,
                  "valid_policy_date": UNKNOWN, "valid_speed": PASS}
        assert overall_outcome(checks.values()) is Outcome.REQUIRES_INVESTIGATION

    def test_claim_exceeding_coverage_is_investigated(self):
        checks = {"valid_amount": FAIL, "valid_severity": PASS,
                  "valid_policy_date": PASS, "valid_speed": PASS}
        assert overall_outcome(checks.values()) is Outcome.REQUIRES_INVESTIGATION
