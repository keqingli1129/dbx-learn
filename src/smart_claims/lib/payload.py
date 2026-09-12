"""Decoding the telematics payload: base64 -> JSON -> a flat str->str mapping.

Mirrors what the ingest pipeline does to the encoded `data` column, kept as pure Python so it is
testable without Spark (Constitution II).

The governing requirement is resilience. Telematics is a continuous feed, and one malformed
record must never fail a whole run, so every failure path returns None instead of raising. A row
that decodes to None reaches silver as nulls and is dropped there by the `chassis_no IS NOT NULL`
expectation, which counts it -- filtering it out here instead would lose that count (FR-016).

Pure stdlib. No Spark import.
"""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any

__all__ = ["decode_telematics"]


def _stringify(value: Any) -> str:
    """Render a JSON value as the string a MAP<STRING, STRING> schema would hold.

    `json.dumps` is used for non-strings so the result matches JSON's own spelling -- `true`,
    `null`, `68.4` -- rather than Python's `True`, `None`. A producer that emits an unquoted
    number must not produce a different value here than it does in Spark.
    """
    if isinstance(value, str):
        return value
    return json.dumps(value)


def decode_telematics(data: object) -> dict[str, str] | None:
    """Decode one base64-encoded JSON payload into a flat str->str mapping.

    Returns None -- never raises -- when the input is not a string, is not valid base64, is not
    valid UTF-8, is not valid JSON, or is JSON that is not an object. A payload that decodes but
    omits an expected key returns the partial mapping instead: that is missing DATA, not a failed
    decode, and the distinction is what lets the silver expectations count it.

    >>> import base64, json
    >>> decode_telematics(base64.b64encode(json.dumps({"speed": 68.4}).encode()).decode())
    {'speed': '68.4'}
    >>> decode_telematics("!!! not base64 !!!") is None
    True
    """
    if not isinstance(data, str):
        return None

    try:
        # validate=True is deliberate. The default DISCARDS characters outside the base64
        # alphabet, so a corrupted payload with junk spliced into it decodes silently to
        # plausible-looking data. Strict mode rejects it instead.
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        return None

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None

    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError, RecursionError):
        return None

    # A MAP<STRING, STRING> schema cannot represent a list, a scalar or null.
    if not isinstance(parsed, dict):
        return None

    try:
        return {str(k): _stringify(v) for k, v in parsed.items()}
    except (TypeError, ValueError, RecursionError):
        return None
