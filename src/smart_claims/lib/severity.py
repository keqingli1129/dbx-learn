"""The one severity vocabulary, shared by customer reports, model predictions and labels.

Customers self-assess a claim's severity, the classifier predicts one, and the training images
carry ground-truth labels. All three must speak the same vocabulary, or the severity check
compares two spellings of the same idea and reports a mismatch for every claim -- a failure that
looks like poor model accuracy and is nothing of the sort.

Pure stdlib. No Spark import (Constitution II).
"""

from __future__ import annotations

import re
from typing import Final, Mapping


class UnknownSeverityError(ValueError):
    """Raised for a label outside the vocabulary.

    Deliberately an error rather than a default. Returning a fallback severity would let a
    garbage label compare equal to something and pass the severity check as a match.
    """


#: Reportable severities, ordered least to most severe. The order is load-bearing: `rank()`
#: depends on it, and any future "within one level" comparison would too.
SEVERITY_DOMAIN: Final[tuple[str, ...]] = (
    "Trivial Damage",
    "Minor Damage",
    "Major Damage",
    "Total Loss",
)

#: Classes the image classifier emits. Three, not four -- see MODEL_UNREACHABLE.
MODEL_LABELS: Final[tuple[str, ...]] = ("okay", "minor", "major")

#: How each model class maps onto the reportable vocabulary.
MODEL_LABEL_MAP: Final[Mapping[str, str]] = {
    "okay": "Trivial Damage",
    "minor": "Minor Damage",
    "major": "Major Damage",
}

_CANONICAL: Final[Mapping[str, str]] = {s.casefold(): s for s in SEVERITY_DOMAIN}
_WHITESPACE = re.compile(r"\s+")


def _key(value: object) -> str | None:
    """Fold a raw label to a lookup key, or None if it is not usable text."""
    if not isinstance(value, str):
        return None
    collapsed = _WHITESPACE.sub(" ", value).strip()
    return collapsed.casefold() if collapsed else None


def normalize(label: object) -> str:
    """Return the canonical spelling of `label`, ignoring case and whitespace.

    >>> normalize("  major   damage ")
    'Major Damage'

    Raises UnknownSeverityError for anything outside SEVERITY_DOMAIN, including model labels
    such as "major" -- those go through `from_model_label`, which is a different vocabulary.
    """
    key = _key(label)
    if key is None or key not in _CANONICAL:
        raise UnknownSeverityError(
            f"not a reportable severity: {label!r}. Expected one of {SEVERITY_DOMAIN}."
        )
    return _CANONICAL[key]


def rank(label: object) -> int:
    """Position in SEVERITY_DOMAIN, 0 = least severe. Accepts any spelling `normalize` accepts."""
    return SEVERITY_DOMAIN.index(normalize(label))


def from_model_label(label: object) -> str:
    """Map a classifier output ("major") to the reportable vocabulary ("Major Damage")."""
    key = _key(label)
    if key is None or key not in MODEL_LABEL_MAP:
        raise UnknownSeverityError(
            f"not a model label: {label!r}. Expected one of {MODEL_LABELS}."
        )
    return MODEL_LABEL_MAP[key]


#: Severities no prediction can ever produce, derived from the mapping rather than hardcoded --
#: adding a fourth model class updates this automatically, and the test asserting its contents
#: then fails, forcing a deliberate decision about how the severity rule should treat it.
#:
#: Today that is ("Total Loss",): a customer can report a total loss, but the classifier has no
#: corresponding class, so the model can neither confirm nor refute one. The rules engine decides
#: what that means for triage -- see contracts/rules-engine.md.
MODEL_UNREACHABLE: Final[tuple[str, ...]] = tuple(
    s for s in SEVERITY_DOMAIN if s not in set(MODEL_LABEL_MAP.values())
)
