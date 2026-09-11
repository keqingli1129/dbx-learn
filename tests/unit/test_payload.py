"""Decoding the telematics payload: base64 -> JSON -> a flat str->str mapping.

This mirrors what the pipeline does to the encoded `data` column, and exists as pure Python so
it is testable without Spark (Constitution II).

The governing requirement is resilience, not correctness alone: telematics arrives as a
continuous feed, and ONE malformed record must never fail an entire ingestion run. Every failure
path therefore returns a sentinel rather than raising, and the row is dropped downstream by the
silver expectation on `chassis_no` with a counted quality violation.
"""

import base64
import json

import pytest

from smart_claims.lib import payload

VALID = {
    "chassis_no": "WVWZZZ1JZXW000001",
    "speed": "68.4",
    "latitude": "48.13",
    "longitude": "11.58",
    "event_timestamp": "2026-09-09T11:59:58Z",
}


def encode(obj) -> str:
    return base64.b64encode(json.dumps(obj).encode("utf-8")).decode("ascii")


class TestHappyPath:
    def test_decodes_to_the_five_documented_keys(self):
        assert payload.decode_telematics(encode(VALID)) == VALID

    def test_every_value_is_a_string(self):
        decoded = payload.decode_telematics(encode(VALID))
        assert all(isinstance(v, str) for v in decoded.values())

    def test_json_numbers_are_coerced_to_strings(self):
        """The pipeline parses with an all-string map schema, so 68.4 must arrive as "68.4".

        If numbers stayed numeric here, the Spark side would silently disagree with the declared
        schema for exactly those rows a producer happened to emit unquoted.
        """
        decoded = payload.decode_telematics(encode({**VALID, "speed": 68.4, "latitude": 48}))
        assert decoded["speed"] == "68.4"
        assert decoded["latitude"] == "48"

    def test_booleans_and_nulls_are_coerced_to_strings(self):
        decoded = payload.decode_telematics(encode({**VALID, "speed": None, "latitude": True}))
        assert isinstance(decoded["speed"], str)
        assert isinstance(decoded["latitude"], str)

    def test_unicode_survives_the_round_trip(self):
        decoded = payload.decode_telematics(encode({**VALID, "chassis_no": "WVW-Ü-001"}))
        assert decoded["chassis_no"] == "WVW-Ü-001"

    def test_extra_keys_are_preserved_not_dropped(self):
        # Schema drift upstream must not be silently discarded at the decode step.
        decoded = payload.decode_telematics(encode({**VALID, "heading": "270"}))
        assert decoded["heading"] == "270"

    def test_missing_keys_yield_a_partial_mapping_not_a_sentinel(self):
        """A payload that decodes but lacks a field is DATA loss, not DECODE failure.

        Returning the partial mapping lets the silver expectation on `chassis_no` catch it and
        count it, instead of the decoder swallowing it as an unparseable blob.
        """
        partial = {k: v for k, v in VALID.items() if k != "speed"}
        decoded = payload.decode_telematics(encode(partial))
        assert decoded == partial
        assert "speed" not in decoded


class TestFailurePathsReturnSentinel:
    @pytest.mark.parametrize("bad,why", [
        ("!!!not base64!!!", "invalid base64 alphabet"),
        ("YWJj===",          "bad padding"),
        ("",                 "empty string"),
        ("   ",              "whitespace only"),
    ])
    def test_malformed_base64_returns_none(self, bad, why):
        assert payload.decode_telematics(bad) is None, why

    def test_base64_of_non_json_returns_none(self):
        raw = base64.b64encode(b"this is not json").decode("ascii")
        assert payload.decode_telematics(raw) is None

    def test_base64_of_truncated_json_returns_none(self):
        raw = base64.b64encode(b'{"chassis_no": "abc"').decode("ascii")
        assert payload.decode_telematics(raw) is None

    @pytest.mark.parametrize("not_a_mapping", [[1, 2, 3], "a bare string", 42, None, True])
    def test_json_that_is_not_an_object_returns_none(self, not_a_mapping):
        # from_json against a MAP schema cannot represent these; treat as undecodable.
        assert payload.decode_telematics(encode(not_a_mapping)) is None

    def test_base64_of_invalid_utf8_returns_none(self):
        raw = base64.b64encode(b"\xff\xfe\xfd").decode("ascii")
        assert payload.decode_telematics(raw) is None

    @pytest.mark.parametrize("bad", [None, 42, b"bytes", [], {}, object()])
    def test_non_string_input_returns_none(self, bad):
        assert payload.decode_telematics(bad) is None


class TestNeverRaises:
    """The contract that keeps a bad record from killing a run."""

    @pytest.mark.parametrize("garbage", [
        "", " ", "\x00", "=", "==", "A", "AB", "ABC", "%%%%", "\n\t",
        "eyJ", "null", "undefined", "-----", "a" * 10_000,
        "8J+Ygg==",           # valid base64 of an emoji, not JSON
        "IA==",               # base64 of a single space
    ])
    def test_arbitrary_input_never_raises(self, garbage):
        result = payload.decode_telematics(garbage)
        assert result is None or isinstance(result, dict)

    def test_a_bad_record_between_two_good_ones_does_not_affect_them(self):
        batch = [encode(VALID), "!!!garbage!!!", encode(VALID)]
        decoded = [payload.decode_telematics(x) for x in batch]
        assert decoded[0] == VALID
        assert decoded[1] is None
        assert decoded[2] == VALID
