#!/bin/bash
# Start Microcks and load the eTransactions PA API mock specs for local runs of
# the integration tests (etransactions/tests/integration).
#
# All paths resolve relative to this script, so it can be run from anywhere:
#   apps/etransactions/etransactions/components/mocks/microcks-up.sh
#
# Once up, point the site at it:
#   bench --site <site> set-config microcks_url http://localhost:8585
# and the integration tests will drive real HTTP against the mocked Plateformes
# Agréées instead of skipping. CI does NOT use this script — it runs Microcks as
# a service and seeds the same specs via curl (see .gitlab-ci.yml).
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MICROCKS_URL="http://localhost:8585"

echo "Starting Microcks..."
docker compose -f "$SCRIPT_DIR/docker-compose.microcks.yml" up -d

echo "Waiting for Microcks to be ready..."
until curl -sf "$MICROCKS_URL/api/keycloak/config" >/dev/null 2>&1; do
  sleep 1
done

echo "Loading PA API mock specs into Microcks..."
for spec in "$SCRIPT_DIR"/*-mock.yaml; do
  name="$(basename "$spec")"
  result=$(curl -s -X POST "$MICROCKS_URL/api/artifact/upload" \
    -F "file=@$spec" -F "mainArtifact=true")
  echo "  $name → $result"
done

echo ""
echo "Microcks ready — all PA APIs mocked at $MICROCKS_URL"
echo ""
echo "Point your test site at it:"
echo "  bench --site <site> set-config microcks_url $MICROCKS_URL"
echo ""
echo "Browse mocked services at $MICROCKS_URL"
echo "Stop with: docker compose -f $SCRIPT_DIR/docker-compose.microcks.yml down"
