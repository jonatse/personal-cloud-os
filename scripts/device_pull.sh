#!/usr/bin/env bash
# device_pull.sh — pull latest code and verify version
# Args: <project_dir> <expected_version>
# Writes: ~/.local/share/pcos/deploy/pull_status.json
#
# Exit codes: 0 = pulled and version matches, 1 = error

PROJECT_DIR="${1:-$HOME/Projects/personal-cloud-os}"
EXPECTED_VERSION="${2:-}"

STATUS_DIR="$HOME/.local/share/pcos/deploy"
STATUS_FILE="$STATUS_DIR/pull_status.json"

mkdir -p "$STATUS_DIR"

write_status() {
  local status="$1" msg="$2" version="$3"
  local ts; ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '{"status":"%s","msg":"%s","version":"%s","ts":"%s"}\n' \
    "$status" "$msg" "$version" "$ts" > "$STATUS_FILE"
}

# Verify project dir exists
if [ ! -d "$PROJECT_DIR" ]; then
  write_status "error" "project_dir_not_found:_$PROJECT_DIR" ""
  echo "PCOS pull: ERROR - project dir not found: $PROJECT_DIR"
  exit 1
fi

cd "$PROJECT_DIR" || exit 1

echo "PCOS pull: fetching from origin..."

# Fetch and hard-reset to origin/master
if ! git fetch --all 2>&1; then
  write_status "error" "git_fetch_failed" ""
  echo "PCOS pull: ERROR - git fetch failed"
  exit 1
fi

if ! git reset --hard origin/master 2>&1; then
  write_status "error" "git_reset_failed" ""
  echo "PCOS pull: ERROR - git reset failed"
  exit 1
fi

# Read version from version.py
ACTUAL_VERSION=$(python3 -c "
import sys
sys.path.insert(0, 'src')
from core.version import __version__
print(__version__)
" 2>/dev/null || echo "unknown")

COMMIT=$(git log --oneline -1 2>/dev/null || echo "unknown")
echo "PCOS pull: at $COMMIT (v$ACTUAL_VERSION)"

# Verify version if expected version was provided
if [ -n "$EXPECTED_VERSION" ] && [ "$ACTUAL_VERSION" != "$EXPECTED_VERSION" ]; then
  write_status "error" "version_mismatch:_expected_${EXPECTED_VERSION}_got_${ACTUAL_VERSION}" "$ACTUAL_VERSION"
  echo "PCOS pull: ERROR - version mismatch (expected $EXPECTED_VERSION, got $ACTUAL_VERSION)"
  exit 1
fi

# Clear log on pull (fresh start)
LOG_FILE="$HOME/.local/share/pcos/logs/app.log"
if [ -f "$LOG_FILE" ]; then
  > "$LOG_FILE"
  echo "PCOS pull: log cleared"
fi

write_status "ok" "pulled_$COMMIT" "$ACTUAL_VERSION"
echo "PCOS pull: done (v$ACTUAL_VERSION)"
exit 0
