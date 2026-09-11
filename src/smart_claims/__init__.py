"""Smart Claims — an end-to-end car-insurance lakehouse on Databricks.

Subpackages:

    lib/        Pure Python. No Spark import. Imported by everything else.
    setup/      One-off bootstrap: seed source data, fetch images, emit events.
    ml/         Damage classifier and the triage rules engine.
    genie/      Scripted Genie space (no bundle resource type exists for it).
    app/        FastAPI claims portal, customer and admin modes.

Pipeline dataset definitions do NOT live here. They are in
`src/smart_claims_etl/transformations/{bronze,silver,gold}/`, because the pipeline runtime
evaluates those files rather than importing them -- see that tree's README.md. They import
this package for their logic.
"""
