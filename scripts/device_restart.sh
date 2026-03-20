#!/usr/bin/env bash
# device_restart.sh — start the PCOS app and wait for healthy startup
# Args: <project_dir> <expected_version>
# Writes: ~/.local/share/pcos/deploy/restart_status.json
#
# Exit codes: 0 = started and healthy, 1 = failed

PROJECT_DIR="${1:-$HOME/Projects/personal-cloud-os}"
EXPECTED_VERSION="${2:-}"

STATUS_DIR="$HOME/.local/share/pcos/deploy"
STATUS_FILE="$STATUS_DIR/restart_status.json"
LOG_FILE="$HOME/.local/share/pcos/logs/app.log"
HEALTH_TIMEOUT=30   # seconds to wait for "All services started" in log
POLL_INTERVAL=1

mkdir -p "$STATUS_DIR"

write_status() {
  local status="$1" msg="$2" version="$3"
  local ts; ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '{"status":"%s","msg":"%s","version":"%s","ts":"%s"}\n' \
    "$status" "$msg" "$version" "$ts" > "$STATUS_FILE"
}

# Guard: don't start if already running
if pgrep -f 'python3.*main.py' > /dev/null 2>&1; then
  write_status "error" "already_running" ""
  echo "PCOS restart: ERROR - process already running (kill first)"
  exit 1
fi

if [ ! -d "$PROJECT_DIR" ]; then
  write_status "error" "project_dir_not_found" ""
  exit 1
fi

cd "$PROJECT_DIR" || exit 1

echo "PCOS restart: starting app..."

# Truncate log so we can watch for fresh startup messages
> "$LOG_FILE" 2>/dev/null || true

# Launch in background
nohup python3 src/main.py --start > /dev/null 2>&1 &
APP_PID=$!
echo "PCOS restart: PID $APP_PID"

# Wait for PID to actually be live
sleep 1
if ! kill -0 "$APP_PID" 2>/dev/null; then
  write_status "error" "process_died_immediately" ""
  echo "PCOS restart: ERROR - process died immediately"
  exit 1
fi

# Poll log for "All services started" within HEALTH_TIMEOUT seconds
echo "PCOS restart: waiting for healthy startup (up to ${HEALTH_TIMEOUT}s)..."
elapsed=0
HEALTHY=false

while [ "$elapsed" -lt "$HEALTH_TIMEOUT" ]; do
  if [ -f "$LOG_FILE" ] && grep -q "All services started" "$LOG_FILE" 2>/dev/null; then
    HEALTHY=true
    break
  fi
  sleep "$POLL_INTERVAL"
  elapsed=$((elapsed + POLL_INTERVAL))
  
  # Check process didn't die
  if ! kill -0 "$APP_PID" 2>/dev/null; then
    write_status "error" "process_died_during_startup" ""
    echo "PCOS restart: ERROR - process died during startup"
    exit 1
  fi
done

if ! $HEALTHY; then
  write_status "error" "startup_timeout_after_${HEALTH_TIMEOUT}s" ""
  echo "PCOS restart: ERROR - startup health check timed out"
  exit 1
fi

# Verify version in log matches expected
LOGGED_VERSION=$(grep -o 'v[0-9]*\.[0-9]*\.[0-9]*' "$LOG_FILE" 2>/dev/null | head -1 | tr -d 'v')

if [ -n "$EXPECTED_VERSION" ] && [ "$LOGGED_VERSION" != "$EXPECTED_VERSION" ]; then
  write_status "error" "version_in_log_${LOGGED_VERSION}_expected_${EXPECTED_VERSION}" "$LOGGED_VERSION"
  echo "PCOS restart: ERROR - wrong version in log ($LOGGED_VERSION != $EXPECTED_VERSION)"
  exit 1
fi

write_status "ok" "healthy_pid_${APP_PID}" "${LOGGED_VERSION:-$EXPECTED_VERSION}"
echo "PCOS restart: healthy (v${LOGGED_VERSION:-$EXPECTED_VERSION}, PID $APP_PID)"
exit 0
