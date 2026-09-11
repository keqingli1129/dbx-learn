"""The severity vocabulary shared by customer reports, model predictions and ground-truth labels.

One vocabulary, defined once. If the customer's self-assessment and the model's prediction were
compared across two spellings of the same idea, the severity check would fail silently for every
claim and look like a model accuracy problem.
"""

import pytest

from smart_claims.lib import severity


class TestDomain:
    def test_domain_is_exactly_the_four_reportable_severities(self):
        assert severity.SEVERITY_DOMAIN == (
            "Trivial Damage",
            "Minor Damage",
            "Major Damage",
            "Total Loss",
        )

    def test_domain_is_ordered_least_to_most_severe(self):
        # Ordering is load-bearing: a future "within one level" comparison would rely on it.
        assert severity.rank("Trivial Damage") < severity.rank("Minor Damage")
        assert severity.rank("Minor Damage") < severity.rank("Major Damage")
        assert severity.rank("Major Damage") < severity.rank("Total Loss")

    def test_domain_is_immutable(self):
        with pytest.raises((AttributeError, TypeError)):
            severity.SEVERITY_DOMAIN[0] = "something else"  # type: ignore[index]


class TestNormalize:
    @pytest.mark.parametrize("raw", [
        "Major Damage", "major damage", "MAJOR DAMAGE", "MaJoR dAmAgE",
        "  Major Damage  ", "\tMajor Damage\n", "Major  Damage",
    ])
    def test_case_and_whitespace_insensitive(self, raw):
        assert severity.normalize(raw) == "Major Damage"

    def test_returns_the_canonical_spelling_not_the_input(self):
        assert severity.normalize("total loss") == "Total Loss"

    def test_is_idempotent(self):
        once = severity.normalize("  minor damage ")
        assert severity.normalize(once) == once

    @pytest.mark.parametrize("bad", ["", "   ", "Catastrophic", "Major", "damage", "okay"])
    def test_unknown_label_raises_rather_than_defaulting(self, bad):
        # Silently defaulting would let a bad label pass the severity check as a match.
        with pytest.raises(severity.UnknownSeverityError):
            severity.normalize(bad)

    @pytest.mark.parametrize("bad", [None, 42, object()])
    def test_non_string_raises(self, bad):
        with pytest.raises(severity.UnknownSeverityError):
            severity.normalize(bad)  # type: ignore[arg-type]


class TestModelLabelMapping:
    def test_model_emits_exactly_three_classes(self):
        # The transcript's confusion matrix has three: okay / minor / major.
        assert severity.MODEL_LABELS == ("okay", "minor", "major")

    def test_every_model_label_maps_into_the_domain(self):
        for label in severity.MODEL_LABELS:
            assert severity.from_model_label(label) in severity.SEVERITY_DOMAIN

    @pytest.mark.parametrize("model_label,expected", [
        ("okay", "Trivial Damage"),
        ("minor", "Minor Damage"),
        ("major", "Major Damage"),
    ])
    def test_mapping_is_the_documented_one(self, model_label, expected):
        assert severity.from_model_label(model_label) == expected

    def test_mapping_is_deterministic(self):
        assert [severity.from_model_label(x) for x in severity.MODEL_LABELS] == \
               [severity.from_model_label(x) for x in severity.MODEL_LABELS]

    def test_model_label_lookup_is_case_insensitive(self):
        assert severity.from_model_label("MAJOR") == severity.from_model_label("major")

    def test_unknown_model_label_raises(self):
        with pytest.raises(severity.UnknownSeverityError):
            severity.from_model_label("catastrophic")

    def test_total_loss_is_unreachable_from_any_model_label(self):
        """The model cannot predict Total Loss -- there is no fourth class.

        This is asserted, not merely documented, so that adding a fourth model class forces a
        deliberate update here rather than silently changing how Total Loss claims are triaged.
        The consequence for the severity rule (a Total Loss claim can never be *confirmed* by the
        model) is decided in the rules engine, not here.
        """
        predicted = {severity.from_model_label(x) for x in severity.MODEL_LABELS}
        assert "Total Loss" not in predicted
        assert severity.MODEL_UNREACHABLE == ("Total Loss",)
