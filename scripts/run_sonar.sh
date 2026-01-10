#!/usr/bin/env bash
# Run SonarScanner against the local SonarQube instance for trestle-transport.
# Usage:
#   SONAR_TOKEN=xxxxx [SONAR_HOST_URL=http://localhost:9000] scripts/run_sonar.sh
# Any additional sonar-scanner options can be appended to the command.

set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SONAR_HOST_URL=${SONAR_HOST_URL:-http://localhost:9000}

if ! command -v sonar-scanner >/dev/null 2>&1; then
  echo "sonar-scanner is not installed or not on PATH" >&2
  exit 2
fi

if [[ -z "${SONAR_TOKEN:-}" ]]; then
  echo "SONAR_TOKEN must be set to authenticate with the local Sonar server" >&2
  exit 3
fi

cd "$REPO_ROOT"

echo "Running SonarScanner for $(basename "$REPO_ROOT") against $SONAR_HOST_URL"

sonar-scanner \
  -Dsonar.host.url="$SONAR_HOST_URL" \
  -Dsonar.login="$SONAR_TOKEN" \
  "$@"
