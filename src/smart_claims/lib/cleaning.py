"""Bronze -> silver cleaning: name splitting, address normalisation, date coercion.

Pure stdlib, no Spark import (Constitution II). The silver transformations import these functions
and wrap them; they do not reimplement the logic inside a `@dp.table` body, where it could not be
tested offline.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Final, Mapping, NamedTuple

__all__ = [
    "DateFormat", "DATE_FORMATS",
    "split_name", "normalize_address", "parse_date", "parse_timestamp",
]

_WHITESPACE = re.compile(r"\s+")


def _clean_text(value: object) -> str | None:
    """Collapse internal whitespace and strip; None for anything that is not usable text."""
    if not isinstance(value, str):
        return None
    collapsed = _WHITESPACE.sub(" ", value).strip()
    return collapsed or None


class DateFormat(NamedTuple):
    """A date pattern in both dialects that need it.

    Python's `strptime` and Spark's `to_date` use different pattern languages -- `%m/%d/%Y`
    against `MM/dd/yyyy` -- so one string cannot serve both. Holding the pair together is what
    stops a silver transformation and its test drifting on what a column's format actually is.
    """

    python: str
    spark: str


#: Every text-date format present in the source data, declared once.
#:
#: Note that US_SLASH and EU_SLASH are indistinguishable by inspection: "03/04/2026" is valid in
#: both and means a different day in each. That is why `parse_date` REQUIRES the format and never
#: infers it -- see the test of the same name.
DATE_FORMATS: Final[Mapping[str, DateFormat]] = {
    "US_SLASH":     DateFormat("%m/%d/%Y", "MM/dd/yyyy"),            # incident_date, date_of_birth
    "ISO_DASH":     DateFormat("%Y-%m-%d", "yyyy-MM-dd"),            # pol_eff_date, pol_expiry_date
    "EU_DASH":      DateFormat("%d-%m-%Y", "dd-MM-yyyy"),            # pol_issue_date
    "EU_SLASH":     DateFormat("%d/%m/%Y", "dd/MM/yyyy"),            # driver_license_issue_date
    "ISO_DATETIME": DateFormat("%Y-%m-%d %H:%M:%S", "yyyy-MM-dd HH:mm:ss"),  # claim_date
}


def split_name(name: object) -> tuple[str | None, str | None]:
    """Split a combined name into (given name, surname).

    The first token is the given name and EVERYTHING after it is the surname. Compound surnames
    ("van der Berg") are far commoner in this data than compound given names, so absorbing middle
    tokens into the surname loses less. Ambiguous either way; the value is that it is decided once.

    >>> split_name("Jan van der Berg")
    ('Jan', 'van der Berg')
    """
    cleaned = _clean_text(name)
    if cleaned is None:
        return (None, None)
    first, _, rest = cleaned.partition(" ")
    return (first, rest or None)


def normalize_address(address: object) -> str | None:
    """Canonicalise an address: collapse whitespace, strip, uppercase.

    Uppercase follows postal convention. The address is a human-matching key during claim
    investigation, so "123 elm st" and "123 Elm St" must not read as two different addresses.
    """
    cleaned = _clean_text(address)
    return cleaned.upper() if cleaned is not None else None


def parse_timestamp(value: object, fmt: DateFormat) -> dt.datetime | None:
    """Parse `value` with `fmt`, returning None for anything unparseable.

    `fmt` is required, never inferred. `strptime` also rejects trailing content, so
    "2026-03-04 extra" fails rather than silently parsing the prefix.
    """
    cleaned = _clean_text(value)
    if cleaned is None:
        return None
    try:
        return dt.datetime.strptime(cleaned, fmt.python)
    except (ValueError, TypeError):
        return None


def parse_date(value: object, fmt: DateFormat) -> dt.date | None:
    """Parse `value` with `fmt` and return the date part, or None if unparseable."""
    parsed = parse_timestamp(value, fmt)
    return parsed.date() if parsed is not None else None
