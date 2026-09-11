"""Pytest configuration for both suites.

Replaces the bundle template's conftest, which initialised Databricks Connect in
`pytest_configure` for EVERY run and fell back to serverless compute. That contradicts
Constitution I: `tests/unit/` must run with no workspace at all. Here, nothing Databricks is
imported until a `workspace`-marked test actually asks for the `spark` fixture.
"""

import os
import sys

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--profile",
        action="store",
        default=None,
        help="Databricks CLI profile for workspace-marked tests. Without it they are skipped.",
    )


def _foreign_site_packages():
    """Site-packages directories on sys.path that belong to neither this venv nor the stdlib.

    This machine's shell exports PYTHONPATH=/opt/ros/jazzy/lib/python3.12/site-packages, and a
    virtualenv does not override PYTHONPATH, so an unrelated dependency tree joins sys.path and
    can shadow project modules -- making SC-016 depend on who runs the tests.

    This check is a BACKSTOP only. The common failure on this machine is worse and happens
    earlier: pytest auto-loads plugins registered by entry point in the foreign tree before any
    conftest is imported, and dies there. Nothing inside conftest can prevent that; use
    ./run-tests.sh, which clears PYTHONPATH before exec'ing pytest.
    """
    prefix = os.path.realpath(sys.prefix)
    base = os.path.realpath(sys.base_prefix)
    return [
        p
        for p in sys.path
        if ("site-packages" in p or "dist-packages" in p)
        and not os.path.realpath(p).startswith((prefix, base))
    ]


def pytest_configure(config):
    if os.environ.get("SMART_CLAIMS_ALLOW_FOREIGN_PYTHONPATH"):
        return
    foreign = _foreign_site_packages()
    if foreign:
        raise pytest.UsageError(
            "Foreign site-packages on sys.path:\n  "
            + "\n  ".join(foreign)
            + "\n\nThese come from PYTHONPATH, which a virtualenv does not override, and they can\n"
            "shadow project modules. Re-run with it cleared:\n\n"
            "    env -u PYTHONPATH pytest ...\n\n"
            "To proceed anyway, set SMART_CLAIMS_ALLOW_FOREIGN_PYTHONPATH=1."
        )


def pytest_collection_modifyitems(config, items):
    """Skip workspace-marked tests when no profile was supplied.

    The marker filter in `addopts` already excludes them by default; this covers the case where
    someone re-selects them with `-m workspace` but has no profile to run them against.
    """
    if config.getoption("--profile"):
        return
    skip = pytest.mark.skip(reason="needs a live workspace: pass --profile <name>")
    for item in items:
        if "workspace" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def profile(request) -> str:
    name = request.config.getoption("--profile")
    if not name:
        pytest.skip("no --profile supplied")
    return name


@pytest.fixture(scope="session")
def spark(profile):
    """A Databricks Connect session, built lazily.

    The import is inside the fixture on purpose: importing databricks.connect at module scope
    would pull Spark into the offline suite through this conftest, defeating the whole split.
    """
    from databricks.sdk.core import Config
    from databricks.connect import DatabricksSession

    return DatabricksSession.builder.sdkConfig(Config(profile=profile)).getOrCreate()
