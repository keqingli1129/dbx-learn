"""Folding individual check results into one triage outcome.

The smallest module here and the one that decides whether a claim pays out automatically or goes
to a human. Its entire job is to keep `indeterminate` distinct from `pass` and `fail` all the way
to the verdict.

Pure stdlib, no Spark import (Constitution II).
"""

from __future__ import annotations

from enum import Enum
from typing import Iterable

__all__ = ["CheckResult", "Outcome", "from_sql_bool", "overall_outcome"]


class _NoTruthiness(Enum):
    """An Enum whose members cannot be used in a boolean context.

    Without this, `if check:` compiles and silently treats INDETERMINATE as a pass, because every
    Enum member is truthy by default. Raising turns a subtle wrong answer into a loud error.
    """

    def __bool__(self) -> bool:
        raise TypeError(
            f"{type(self).__name__} has no truth value -- compare explicitly, e.g. "
            f"`result is {type(self).__name__}.PASS`. A three-valued result cannot be "
            f"collapsed to a boolean without losing the distinction that matters."
        )


class CheckResult(_NoTruthiness):
    """The outcome of one rule against one claim."""

    PASS = "pass"
    FAIL = "fail"
    #: The rule could not be evaluated because an operand was missing -- no telematics for the
    #: incident date, no image, no policy. NOT a failure: the system has no evidence either way.
    INDETERMINATE = "indeterminate"


class Outcome(_NoTruthiness):
    """The verdict for a claim."""

    RELEASE_FUNDS = "release_funds"
    REQUIRES_INVESTIGATION = "requires_investigation"


def from_sql_bool(value: object) -> CheckResult:
    """Map a SQL three-valued boolean onto a CheckResult.

    `True` -> PASS, `False` -> FAIL, `NULL` -> INDETERMINATE. This mapping is the mechanism behind
    every missing-data edge case in the spec: a vehicle with no telematics makes `max_speed` NULL,
    so `max_speed <= 45` is NULL, so the speed check is indeterminate and a human reviews it.

    Anything else raises. Coercing `0` to False would turn "the query returned no rows" into "the
    check failed", which reports a driver as speeding on no evidence at all.
    """
    if value is None:
        return CheckResult.INDETERMINATE
    if value is True:
        return CheckResult.PASS
    if value is False:
        return CheckResult.FAIL
    raise TypeError(
        f"expected True, False or None from a SQL boolean, got {value!r} ({type(value).__name__}). "
        "Refusing to coerce -- a truthy or falsy non-boolean here would silently change a verdict."
    )


def overall_outcome(results: Iterable[CheckResult]) -> Outcome:
    """Release funds only when at least one check ran and every check passed.

    The "at least one" clause is not pedantry. Read as plain universal quantification, "every rule
    passed" is vacuously true over an empty set -- so emptying the rule table, or disabling every
    rule, would auto-approve every claim. An empty rule set means nothing was verified, which is
    not the same as all-clear (FR-033).
    """
    seen = False
    all_passed = True
    for result in results:
        if not isinstance(result, CheckResult):
            raise TypeError(
                f"expected a CheckResult, got {result!r} ({type(result).__name__}). "
                "Raw strings are rejected so a typo like 'Pass' cannot silently block release."
            )
        seen = True
        if result is not CheckResult.PASS:
            all_passed = False

    if seen and all_passed:
        return Outcome.RELEASE_FUNDS
    return Outcome.REQUIRES_INVESTIGATION
