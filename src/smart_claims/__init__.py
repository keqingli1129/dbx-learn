"""Smart Claims — an end-to-end car-insurance lakehouse on Databricks.

Subpackages:

    lib/        Pure Python. No Spark import. Imported by everything else.
    setup/      One-off bootstrap: seed source data, fetch images, emit events.
    ingest/     Landing and source systems -> bronze.
    transform/  Bronze -> silver -> gold.
    ml/         Damage classifier and the triage rules engine.
    genie/      Scripted Genie space (no bundle resource type exists for it).
    app/        FastAPI claims portal, customer and admin modes.
"""
