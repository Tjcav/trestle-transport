#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION_FILE="$REPO_ROOT/.trestle/standards.version"
PRECOMMIT_FILE="$REPO_ROOT/.pre-commit-config.yaml"

if [[ ! -f "$VERSION_FILE" ]]; then
  echo "Missing standards pin at $VERSION_FILE" >&2
  exit 1
fi

STANDARDS_VERSION="$(tr -d '[:space:]' < "$VERSION_FILE")"
if [[ -z "$STANDARDS_VERSION" ]]; then
  echo "Standards pin is empty in $VERSION_FILE" >&2
  exit 1
fi

if [[ -f "$PRECOMMIT_FILE" ]]; then
  if ! grep -q "id: standards-validate" "$PRECOMMIT_FILE"; then
    echo "Pre-commit config must use the standards validation hook." >&2
    exit 1
  fi
fi

STANDARDS_REPO_URL="${STANDARDS_REPO_URL:-https://github.com/tjcav/trestle-spec.git}"

if git ls-remote --exit-code "$STANDARDS_REPO_URL" "refs/tags/$STANDARDS_VERSION" >/dev/null 2>&1; then
  exit 0
fi

if git ls-remote "$STANDARDS_REPO_URL" 2>/dev/null | awk '{print $1}' | grep -q "^$STANDARDS_VERSION$"; then
  exit 0
fi

echo "Standards pin '$STANDARDS_VERSION' not found in $STANDARDS_REPO_URL." >&2
exit 1
