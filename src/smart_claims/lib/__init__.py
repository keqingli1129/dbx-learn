"""Pure-Python logic shared by pipelines, jobs and the app.

RULE (Constitution II): nothing in this package may import pyspark, or depend
on a SparkSession, a Databricks runtime global (`spark`, `dbutils`, `display`)
or a live workspace. Every module here must be importable and testable by
`pytest tests/unit` with no workspace connection at all.

This is not a style preference. `databricks-connect` cannot coexist with a
local `pyspark` install, so there is no offline Spark session available --
separating pure logic from its Spark wrappers is the only way the offline test
suite required by Constitution I can exist.

Pipelines call into these functions; they must not reimplement the logic
inline inside a `@dp.table` body, where it cannot be tested.
"""
