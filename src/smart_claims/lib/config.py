"""The single place that turns pipeline/job configuration into fully-qualified names.

`mode: development` renames schemas to `dev_<username>_<name>` (research R13), so
`smart_claims_dev.bronze.telematics` does not exist at the dev target. No code in this project may
hardcode a schema name; every reference resolves through here.

Configuration is supplied by the caller as a getter, not read from Spark. Pipeline code passes
`spark.conf.get`; a job passes `dbutils.widgets.get` or a plain dict lookup. That keeps this
module free of any Spark import (Constitution II) and testable offline.

    cfg = Config.from_getter(spark.conf.get)
    df  = spark.readStream.table(cfg.table("bronze", "telematics"))
    src = cfg.volume_path("telematics_raw")
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Final, Mapping

__all__ = ["Config", "MissingConfigError", "SCHEMAS", "PREFIX"]

#: Configuration keys are namespaced so they cannot collide with Spark's own settings.
PREFIX: Final[str] = "smart_claims"

#: Logical schema names. The resolved value of each is supplied by configuration.
SCHEMAS: Final[tuple[str, ...]] = ("source", "landing", "bronze", "silver", "gold")

Getter = Callable[..., "str | None"]


class MissingConfigError(KeyError):
    """A required configuration key is absent, unparseable, or names an unknown schema.

    Deliberately fatal. A default would produce a plausible-looking identifier pointing at a
    table that does not exist -- or, worse, one that does and is the wrong one.
    """

    def __str__(self) -> str:  # KeyError repr adds quotes that obscure the message
        return self.args[0] if self.args else ""


def _require(get: Getter, key: str) -> str:
    value = get(key, None)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise MissingConfigError(
            f"missing required configuration key {key!r}. "
            f"Pipelines set it under `configuration:` in their resource YAML; jobs pass it as a "
            f"parameter. Schema keys must carry the RESOLVED name "
            f"(${{resources.schemas.<key>.name}}), never a literal like 'bronze'."
        )
    return value.strip()


@dataclass(frozen=True)
class Config:
    """Resolved names for one deployment target."""

    catalog: str
    schemas: Mapping[str, str]
    speed_threshold: float

    @classmethod
    def from_getter(cls, get: Getter) -> "Config":
        catalog = _require(get, f"{PREFIX}.catalog")
        schemas = {name: _require(get, f"{PREFIX}.schema.{name}") for name in SCHEMAS}

        raw_threshold = _require(get, f"{PREFIX}.speed_threshold")
        try:
            speed_threshold = float(raw_threshold)
        except (TypeError, ValueError) as exc:
            raise MissingConfigError(
                f"{PREFIX}.speed_threshold must be a number, got {raw_threshold!r}"
            ) from exc

        return cls(catalog=catalog, schemas=dict(schemas), speed_threshold=speed_threshold)

    def schema(self, logical: str) -> str:
        """Resolved name of a logical schema. `schema("bronze")` -> `dev_keqingli1129_bronze`."""
        try:
            return self.schemas[logical]
        except KeyError as exc:
            raise MissingConfigError(
                f"unknown schema {logical!r}; expected one of {SCHEMAS}"
            ) from exc

    def table(self, logical_schema: str, table: str) -> str:
        """Fully-qualified table name, with the schema resolved."""
        return f"{self.catalog}.{self.schema(logical_schema)}.{table}"

    def volume_path(self, volume: str, *parts: str) -> str:
        """Filesystem path of a landing volume, plus any sub-path.

        Volumes are not renamed by development mode, but the schema containing them is -- so the
        path has to be built from the resolved landing schema, not a literal.
        """
        segments = [p.strip("/") for p in parts if p and p.strip("/")]
        base = f"/Volumes/{self.catalog}/{self.schema('landing')}/{volume.strip('/')}"
        return "/".join([base, *segments])
