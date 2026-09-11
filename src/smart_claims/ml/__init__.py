"""Damage-severity classifier and the claims triage rules engine.

Trains and registers the model, scores accident images in bulk, and evaluates
the rule store into `gold.claim_insights`. Rules are rows in a table, not code,
so a rule can be added without changing the evaluator.
"""
