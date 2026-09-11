"""Offline suite. No Spark, no workspace, no network.

This is the suite SC-016 refers to: it must pass from a clean checkout with no profile
configured. Nothing here may import pyspark, databricks.connect, or anything under
`smart_claims` that does (Constitution I + II).
"""
