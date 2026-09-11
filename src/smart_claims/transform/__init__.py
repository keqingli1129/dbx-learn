"""Bronze -> silver -> gold.

Owns the silver schema and the three gold materialized views. Data-quality
rules are declared as expectations; cleaning logic is imported from
`smart_claims.lib.cleaning` rather than written inline (Constitution II).
"""
