#!/usr/bin/env bash
# Create the Unity Catalog catalog that the bundle cannot create itself.
#
# Catalog creation via the REST API is refused on accounts with Default Storage enabled, but the
# equivalent SQL succeeds (research R14). Run this ONCE before the first `bundle deploy`; it is
# idempotent, so re-running is harmless.
#
#   ./bootstrap.sh [target] [profile]        defaults: dev DEFAULT
#
# The catalog name is read from the bundle's own resolved `catalog` variable, so this script and
# databricks.yml cannot disagree about what it is called.
set -euo pipefail

TARGET="${1:-dev}"
PROFILE="${2:-DEFAULT}"

CATALOG=$(databricks bundle validate -t "$TARGET" --profile "$PROFILE" -o json \
  | python3 -c 'import sys,json; v=json.load(sys.stdin)["variables"]["catalog"]; print(v.get("value", v.get("default")))')

if [ -z "$CATALOG" ] || [ "$CATALOG" = "None" ]; then
  echo "could not resolve the catalog variable for target '$TARGET'" >&2
  exit 1
fi

echo "creating catalog '$CATALOG' (target=$TARGET, profile=$PROFILE) ..."
databricks experimental aitools tools query \
  "CREATE CATALOG IF NOT EXISTS \`${CATALOG}\`" --profile "$PROFILE"

# Verify with the CLI's own exit status. Piping JSON into `python3 - <<EOF` does not work --
# the heredoc becomes stdin, so the piped data is discarded.
echo "verifying ..."
if databricks catalogs get "$CATALOG" --profile "$PROFILE" >/dev/null 2>&1; then
  echo "  catalog '$CATALOG' exists"
else
  echo "  ERROR: catalog '$CATALOG' was not created" >&2
  exit 1
fi
