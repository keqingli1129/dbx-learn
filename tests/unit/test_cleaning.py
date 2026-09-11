"""Bronze -> silver cleaning: name splitting, address normalisation, date coercion.

Pure Python so it is testable without Spark (Constitution II). The silver transformations import
these functions rather than reimplementing the logic inside a `@dp.table` body, where it could
not be tested at all.
"""

import datetime as dt

import pytest

from smart_claims.lib import cleaning


class TestSplitName:
    def test_splits_a_two_token_name(self):
        assert cleaning.split_name("Ada Lovelace") == ("Ada", "Lovelace")

    def test_first_token_is_the_given_name_and_the_rest_is_the_surname(self):
        """Convention: first token is the given name, EVERYTHING after it is the surname.

        Pinned deliberately. Compound surnames ("van der Berg", "de la Cruz") are far more common
        in this data than compound given names, so absorbing the middle tokens into the surname
        loses less information than the reverse. Ambiguous either way -- the point is that the
        rule is explicit and asserted, not decided per caller.
        """
        assert cleaning.split_name("Ada King Lovelace") == ("Ada", "King Lovelace")
        assert cleaning.split_name("Jan van der Berg") == ("Jan", "van der Berg")

    def test_single_token_name_has_no_surname(self):
        assert cleaning.split_name("Cher") == ("Cher", None)

    def test_collapses_and_strips_surrounding_whitespace(self):
        assert cleaning.split_name("  Ada   Lovelace  ") == ("Ada", "Lovelace")
        assert cleaning.split_name("\tAda\nLovelace ") == ("Ada", "Lovelace")

    @pytest.mark.parametrize("empty", ["", "   ", "\t\n", None])
    def test_empty_or_missing_name_yields_two_nulls(self, empty):
        assert cleaning.split_name(empty) == (None, None)

    @pytest.mark.parametrize("bad", [42, [], {}, object()])
    def test_non_string_yields_two_nulls_rather_than_raising(self, bad):
        assert cleaning.split_name(bad) == (None, None)

    def test_preserves_case_and_accents(self):
        assert cleaning.split_name("Ángela MÜLLER") == ("Ángela", "MÜLLER")


class TestNormalizeAddress:
    def test_collapses_internal_whitespace_and_strips(self):
        assert cleaning.normalize_address("  123   Elm   St  ") == "123 ELM ST"

    def test_uppercases(self):
        """Canonical form is uppercase, following postal-address convention.

        A single canonical case matters because the address is a human-matching key during claim
        investigation; "123 elm st" and "123 Elm St" must not read as two different addresses.
        """
        assert cleaning.normalize_address("123 Elm St") == "123 ELM ST"
        assert cleaning.normalize_address("123 ELM ST") == "123 ELM ST"

    def test_is_idempotent(self):
        once = cleaning.normalize_address("  456  oak AVE ")
        assert cleaning.normalize_address(once) == once

    def test_normalises_newlines_and_tabs_to_single_spaces(self):
        assert cleaning.normalize_address("12 Main St\nApt 4\tB") == "12 MAIN ST APT 4 B"

    @pytest.mark.parametrize("empty", ["", "   ", "\n", None])
    def test_empty_or_missing_address_yields_none(self, empty):
        assert cleaning.normalize_address(empty) is None

    @pytest.mark.parametrize("bad", [42, [], object()])
    def test_non_string_yields_none_rather_than_raising(self, bad):
        assert cleaning.normalize_address(bad) is None


class TestDateFormatsAreDeclaredOnce:
    """Each format is declared once, paired with its Spark equivalent.

    Python and Spark date patterns are different languages (`%m/%d/%Y` vs `MM/dd/yyyy`), so one
    string cannot serve both. Keeping the pair adjacent in a single table is what stops the
    silver transformation and this test drifting apart on what a column's format actually is.
    """

    def test_all_five_source_formats_are_declared(self):
        assert set(cleaning.DATE_FORMATS) == {
            "US_SLASH",      # MM/dd/yyyy  -- incident_date, date_of_birth
            "ISO_DASH",      # yyyy-MM-dd  -- pol_eff_date, pol_expiry_date
            "EU_DASH",       # dd-MM-yyyy  -- pol_issue_date
            "EU_SLASH",      # dd/MM/yyyy  -- driver_license_issue_date
            "ISO_DATETIME",  # yyyy-MM-dd HH:mm:ss -- claim_date
        }

    @pytest.mark.parametrize("name,python_pattern,spark_pattern", [
        ("US_SLASH",     "%m/%d/%Y",          "MM/dd/yyyy"),
        ("ISO_DASH",     "%Y-%m-%d",          "yyyy-MM-dd"),
        ("EU_DASH",      "%d-%m-%Y",          "dd-MM-yyyy"),
        ("EU_SLASH",     "%d/%m/%Y",          "dd/MM/yyyy"),
        ("ISO_DATETIME", "%Y-%m-%d %H:%M:%S", "yyyy-MM-dd HH:mm:ss"),
    ])
    def test_each_format_pairs_the_python_and_spark_patterns(self, name, python_pattern, spark_pattern):
        fmt = cleaning.DATE_FORMATS[name]
        assert fmt.python == python_pattern
        assert fmt.spark == spark_pattern


class TestParseDate:
    @pytest.mark.parametrize("name,raw,expected", [
        ("US_SLASH", "03/04/2026", dt.date(2026, 3, 4)),
        ("ISO_DASH", "2026-03-04", dt.date(2026, 3, 4)),
        ("EU_DASH",  "04-03-2026", dt.date(2026, 3, 4)),
        ("EU_SLASH", "04/03/2026", dt.date(2026, 3, 4)),
    ])
    def test_parses_each_declared_format(self, name, raw, expected):
        assert cleaning.parse_date(raw, cleaning.DATE_FORMATS[name]) == expected

    def test_the_same_string_means_different_days_in_different_formats(self):
        """THE trap this API exists to prevent.

        "03/04/2026" is valid in BOTH MM/dd/yyyy and dd/MM/yyyy -- March 4th in one, April 3rd in
        the other. Any function that sniffs the format would silently produce the wrong date for
        roughly a third of rows (every day-of-month <= 12), and the error would be invisible: a
        real date, in range, just wrong. The format is therefore a REQUIRED argument, never
        inferred.
        """
        raw = "03/04/2026"
        assert cleaning.parse_date(raw, cleaning.DATE_FORMATS["US_SLASH"]) == dt.date(2026, 3, 4)
        assert cleaning.parse_date(raw, cleaning.DATE_FORMATS["EU_SLASH"]) == dt.date(2026, 4, 3)

    def test_format_argument_is_required(self):
        with pytest.raises(TypeError):
            cleaning.parse_date("2026-03-04")  # type: ignore[call-arg]

    def test_strips_surrounding_whitespace(self):
        assert cleaning.parse_date("  2026-03-04 ", cleaning.DATE_FORMATS["ISO_DASH"]) == dt.date(2026, 3, 4)

    @pytest.mark.parametrize("raw", [
        "2026-03-04",      # right value, wrong format for US_SLASH
        "not a date",
        "02/30/2026",      # February 30th does not exist
        "13/13/2026",      # month 13
        "",
        "   ",
        None,
    ])
    def test_unparseable_returns_none_rather_than_raising(self, raw):
        assert cleaning.parse_date(raw, cleaning.DATE_FORMATS["US_SLASH"]) is None

    @pytest.mark.parametrize("bad", [42, [], {}, dt.date(2026, 1, 1), object()])
    def test_non_string_returns_none(self, bad):
        assert cleaning.parse_date(bad, cleaning.DATE_FORMATS["ISO_DASH"]) is None

    def test_rejects_trailing_content_instead_of_parsing_a_prefix(self):
        # "2026-03-04 extra" must not quietly parse as 2026-03-04.
        assert cleaning.parse_date("2026-03-04 extra", cleaning.DATE_FORMATS["ISO_DASH"]) is None


class TestParseTimestamp:
    def test_parses_the_claim_date_format(self):
        got = cleaning.parse_timestamp("2026-03-04 14:30:00", cleaning.DATE_FORMATS["ISO_DATETIME"])
        assert got == dt.datetime(2026, 3, 4, 14, 30, 0)

    def test_unparseable_returns_none(self):
        assert cleaning.parse_timestamp("2026-03-04", cleaning.DATE_FORMATS["ISO_DATETIME"]) is None

    def test_returns_a_datetime_not_a_date(self):
        got = cleaning.parse_timestamp("2026-03-04 14:30:00", cleaning.DATE_FORMATS["ISO_DATETIME"])
        assert isinstance(got, dt.datetime)
