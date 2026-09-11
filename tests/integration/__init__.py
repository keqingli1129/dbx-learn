"""Workspace suite. Every test here MUST carry `@pytest.mark.workspace`.

Excluded from the default run by `addopts = "-m 'not workspace'"`, and skipped outright when
no `--profile` is supplied. Run with:

    env -u PYTHONPATH pytest tests/integration -m workspace --profile DEFAULT
"""
