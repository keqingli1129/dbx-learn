"""Landing volumes and source change feeds -> bronze.

Owns every table in the bronze schema; no other package writes there
(Constitution III). Uses the modern pipelines API -- `from pyspark import
pipelines as dp` -- never `import dlt` (Constitution VI).
"""
