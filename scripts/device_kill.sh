#!/usr/bin/env bash
# device_kill.sh — stop the PCOS app and report status
# Writes: ~/.local/share/pcos/deploy/kill_status.json
#
# Exit codes: 0 = killed or already dead, 1 = failed after retries

STATUS_DIR="$HOME/.local/share/pcos/deploy"
STATUS_FILE="$STATUS_DIR/kill_status.json"
MAX_RETRIES=5
RETRY_DELAY=2

mkdir -p "$STATUS_DIR"

write_status() {
  local status="$1" msg="$2"
  local ts; ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '{"status":"%s","msg":"%s","ts":"%s"}\n' \
    "$status" "$msg" "$ts" > "$STATUS_FILE"
}

# Check if already dead
if ! pgrep -f 'python3.*main.py' > /dev/null 2>&1; then
  write_status "ok" "already_dead"
  echo "PCOS: already dead"
  exit 0
fi

echo "PCOS: killing..."

# Try SIGTERM first, then SIGKILL
for attempt in $(seq 1 $MAX_RETRIES); do
  pkill -f 'python3.*main.py' 2>/dev/null || true
  sleep "$RETRY_DELAY"
  
  if ! pgrep -f 'python3.*main.py' > /dev/null 2>&1; then
    write_status "ok" "killed_after_${attempt}_attempt(s)"
    echo "PCOS: dead after $attempt attempt(s)"
    exit 0
  fi
  
  # Escalate to SIGKILL after attempt 2
  if [ "$attempt" -ge 2 ]; then
    pkill -9 -f 'python3.*main.py' 2>/dev/null || true
    sleep 1
    if ! pgrep -f 'python3.*main.py' > /dev/null 2>&1; then
      write_status "ok" "force_killed"
      echo "PCOS: force killed"
      exit 0
    fi
  fi
done

write_status "error" "failed_to_kill_after_${MAX_RETRIES}_attempts"
echo "PCOS: ERROR - could not kill after $MAX_RETRIES attempts"
exit 1
