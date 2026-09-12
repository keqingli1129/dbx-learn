"""Turning pipeline/job configuration into fully-qualified names.

Unplanned but load-bearing: `mode: development` renames schemas to `dev_<user>_<name>` (research
R13), so no code may hardcode a schema. This module is the single place that resolves them, which
makes it the single place a mistake would silently point every read at the wrong table.
"""

import pytest

from smart_claims.lib.config import Config, MissingConfigError

RESOLVED = {
    "smart_claims.catalog": "smart_claims_dev",
    "smart_claims.schema.source": "dev_keqingli1129_source",
    "smart_claims.schema.landing": "dev_keqingli1129_landing",
    "smart_claims.schema.bronze": "dev_keqingli1129_bronze",
    "smart_claims.schema.silver": "dev_keqingli1129_silver",
    "smart_claims.schema.gold": "dev_keqingli1129_gold",
    "smart_claims.speed_threshold": "45",
}


def getter(overrides=None):
    data = {**RESOLVED, **(overrides or {})}
    return lambda key, default=None: data.get(key, default)


class TestLoading:
    def test_reads_every_required_key(self):
        cfg = Config.from_getter(getter())
        assert cfg.catalog == "smart_claims_dev"
        assert cfg.speed_threshold == 45.0

    @pytest.mark.parametrize("missing", sorted(RESOLVED))
    def test_a_missing_required_key_raises_rather_than_defaulting(self, missing):
        """Defaulting would produce a plausible name pointing at a table that does not exist,
        or worse, one that does and is wrong. Fail at startup instead."""
        data = {k: v for k, v in RESOLVED.items() if k != missing}
        with pytest.raises(MissingConfigError) as exc:
            Config.from_getter(lambda k, d=None: data.get(k, d))
        assert missing in str(exc.value)

    def test_speed_threshold_is_numeric_not_text(self):
        cfg = Config.from_getter(getter({"smart_claims.speed_threshold": "62.5"}))
        assert cfg.speed_threshold == 62.5
        assert isinstance(cfg.speed_threshold, float)

    def test_non_numeric_speed_threshold_raises(self):
        with pytest.raises(MissingConfigError):
            Config.from_getter(getter({"smart_claims.speed_threshold": "fast"}))


class TestNameResolution:
    def test_schema_resolves_the_logical_name(self):
        cfg = Config.from_getter(getter())
        assert cfg.schema("bronze") == "dev_keqingli1129_bronze"

    def test_table_is_fully_qualified(self):
        cfg = Config.from_getter(getter())
        assert cfg.table("bronze", "telematics") == \
            "smart_claims_dev.dev_keqingli1129_bronze.telematics"

    def test_resolution_actually_uses_config_rather_than_the_logical_name(self):
        """Guards the whole point of this module: a literal `bronze` must not leak through."""
        prod = Config.from_getter(getter({"smart_claims.schema.bronze": "bronze"}))
        dev = Config.from_getter(getter())
        assert prod.table("bronze", "telematics") == "smart_claims_dev.bronze.telematics"
        assert dev.table("bronze", "telematics") != prod.table("bronze", "telematics")

    @pytest.mark.parametrize("unknown", ["platinum", "Bronze", "", "landing "])
    def test_unknown_logical_schema_raises(self, unknown):
        cfg = Config.from_getter(getter())
        with pytest.raises(MissingConfigError):
            cfg.schema(unknown)

    def test_every_medallion_schema_is_addressable(self):
        cfg = Config.from_getter(getter())
        for logical in ("source", "landing", "bronze", "silver", "gold"):
            assert cfg.schema(logical).endswith(logical)


class TestVolumePaths:
    def test_volume_path_is_rooted_in_the_landing_schema(self):
        cfg = Config.from_getter(getter())
        assert cfg.volume_path("telematics_raw") == \
            "/Volumes/smart_claims_dev/dev_keqingli1129_landing/telematics_raw"

    def test_subpaths_are_joined_without_duplicate_separators(self):
        cfg = Config.from_getter(getter())
        assert cfg.volume_path("claims", "images") == \
            "/Volumes/smart_claims_dev/dev_keqingli1129_landing/claims/images"
        assert cfg.volume_path("claims", "archive", "2026") == \
            "/Volumes/smart_claims_dev/dev_keqingli1129_landing/claims/archive/2026"

    def test_leading_and_trailing_slashes_in_parts_are_tolerated(self):
        cfg = Config.from_getter(getter())
        assert cfg.volume_path("claims", "/images/") == cfg.volume_path("claims", "images")


class TestImmutability:
    def test_config_is_frozen(self):
        cfg = Config.from_getter(getter())
        with pytest.raises((AttributeError, TypeError)):
            cfg.catalog = "someone_elses_catalog"  # type: ignore[misc]
