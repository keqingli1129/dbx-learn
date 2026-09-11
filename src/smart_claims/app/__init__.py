"""FastAPI claims portal: customer submission and admin review.

All data access goes through the `ClaimsRepository` interface, which has a
Lakebase-backed and a warehouse-backed implementation selected at startup.
No request handler issues SQL directly.

This app has no authentication by design and must never be exposed to real
claimants or loaded with real personal data (Constitution V).
"""
