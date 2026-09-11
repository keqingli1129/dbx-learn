#!/usr/bin/env bash
# Run the test suites with a clean PYTHONPATH.
#
# Why this wrapper exists: if PYTHONPATH points at another Python distribution's site-packages
# (this machine exports ROS 2 Jazzy's), pytest auto-loads any pytest plugins registered there
# via entry points -- BEFORE any conftest runs -- and dies with an unrelated ImportError.
# conftest.py cannot guard against it, because conftest is loaded too late.
#
#   ./run-tests.sh                                   offline suite (default)
#   ./run-tests.sh tests/unit -v                     ditto, verbose
#   ./run-tests.sh tests/integration -m workspace --profile DEFAULT
#
set -euo pipefail
exec env -u PYTHONPATH "$(dirname "$0")/.venv/bin/pytest" "$@"
