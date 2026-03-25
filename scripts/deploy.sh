#!/usr/bin/env bash
# deploy.sh — PCOS deploy orchestrator
#
# Phases (all phases run in parallel where possible):
#   1. Version bump (optional)
#   2. Git commit + push           ← parallel with Phase 3
#   3. Kill both machines          ← parallel with Phase 2
#   4. Wait: push confirmed + both dead
#   5. Pull both machines          ← parallel
#   6. Wait: both pulled + version verified
#   7. Restart both machines       ← parallel
#   8. Wait: both healthy + version in log confirmed
#   9. Tail both logs live
#
# Usage:
#   ./scripts/deploy.sh                    # deploy current code
#   ./scripts/deploy.sh --bump-version     # increment patch (1.2.6 → 1.2.7)
#   ./scripts/deploy.sh --bump-minor       # increment minor (1.2.6 → 1.3.0)
#   ./scripts/deploy.sh --bump-major       # increment major (1.2.6 → 2.0.0)
#   ./scripts/deploy.sh --no-tail          # deploy and exit (no log tail)
#
# Requirements:
#   SSH passwordless access to jonathansoberg@192.168.1.82
#   scripts/device_kill.sh, device_pull.sh, device_restart.sh in same dir

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="$(dirname "$SCRIPT_DIR")"
LOCAL_DIR="$PROJECT"

LAPTOP_USER="jonathansoberg"
LAPTOP_HOST="192.168.1.82"
LAPTOP_DIR="~/Projects/personal-cloud-os"

LOG_LOCAL="$HOME/.local/share/pcos/logs/app.log"
LOG_LAPTOP="~/.local/share/pcos/logs/app.log"
DEPLOY_DIR_LOCAL="$HOME/.local/share/pcos/deploy"
DEPLOY_DIR_LAPTOP="~/.local/share/pcos/deploy"

POLL_INTERVAL=2
PHASE_TIMEOUT=60    # seconds before a phase is declared failed

# ── Flags ─────────────────────────────────────────────────────────────
BUMP_PATCH=false
BUMP_MINOR=false
BUMP_MAJOR=false
NO_TAIL=false

for arg in "$@"; do
  case $arg in
    --bump-version) BUMP_PATCH=true ;;
    --bump-minor)   BUMP_MINOR=true ;;
    --bump-major)   BUMP_MAJOR=true ;;
    --no-tail)      NO_TAIL=true ;;
  esac
done

# ── Colours ───────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

ok()   { echo -e "${GREEN}  ✓ $*${RESET}"; }
info() { echo -e "${CYAN}  ▸ $*${RESET}"; }
warn() { echo -e "${YELLOW}  ⚠ $*${RESET}"; }
fail() { echo -e "${RED}  ✗ $*${RESET}"; exit 1; }
hdr()  { echo -e "\n${BOLD}${CYAN}══ $* ${RESET}"; }

# ── Helpers ───────────────────────────────────────────────────────────

# Analyze git commits since last tag to suggest version bump type
# Returns: "major", "minor", or "patch"
analyze_commits() {
  local last_tag
  last_tag=$(cd "$PROJECT" && git describe --tags --abbrev=0 2>/dev/null || echo "")
  
  if [ -z "$last_tag" ]; then
    echo "patch"
    return
  fi
  
  local commits
  commits=$(cd "$PROJECT" && git log "$last_tag.." --format="%s" 2>/dev/null || echo "")
  
  if echo "$commits" | grep -qi "BREAKING CHANGE"; then
    echo "major"
    return
  fi
  
  if echo "$commits" | grep -q "^feat:"; then
    echo "minor"
    return
  fi
  
  echo "patch"
}

# Upload scripts to laptop once (idempotent)
upload_scripts() {
  info "Syncing scripts to laptop..."
  scp -q "$SCRIPT_DIR/device_kill.sh" \
         "$SCRIPT_DIR/device_pull.sh" \
         "$SCRIPT_DIR/device_restart.sh" \
         "$LAPTOP_USER@$LAPTOP_HOST:$LAPTOP_DIR/scripts/"
  ssh "$LAPTOP_USER@$LAPTOP_HOST" \
    "chmod +x $LAPTOP_DIR/scripts/device_kill.sh \
               $LAPTOP_DIR/scripts/device_pull.sh \
               $LAPTOP_DIR/scripts/device_restart.sh"
  ok "Scripts uploaded to laptop"
}

# Poll a remote JSON status file until it contains "ok" or timeout
# Usage: wait_for_status <host_label> <ssh_dest> <remote_status_file> <timeout>
# Returns 0 on ok, 1 on timeout/error
wait_for_status() {
  local label="$1" ssh_dest="$2" remote_file="$3" timeout="$4"
  local elapsed=0
  while [ "$elapsed" -lt "$timeout" ]; do
    local result
    result=$(ssh "$ssh_dest" "cat $remote_file 2>/dev/null || echo '{}'" 2>/dev/null || echo '{}')
    local status
    status=$(echo "$result" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))" 2>/dev/null || echo "")
    local msg
    msg=$(echo "$result" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('msg',''))" 2>/dev/null || echo "")
    local version
    version=$(echo "$result" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('version',''))" 2>/dev/null || echo "")

    if [ "$status" = "ok" ]; then
      ok "$label: $msg${version:+ (v$version)}"
      return 0
    elif [ "$status" = "error" ]; then
      warn "$label: FAILED — $msg"
      return 1
    fi
    sleep "$POLL_INTERVAL"
    elapsed=$((elapsed + POLL_INTERVAL))
    info "$label: waiting... (${elapsed}s)"
  done
  warn "$label: timed out after ${timeout}s"
  return 1
}

# Same but for local status file
wait_for_status_local() {
  local label="$1" local_file="$2" timeout="$3"
  local elapsed=0
  while [ "$elapsed" -lt "$timeout" ]; do
    if [ -f "$local_file" ]; then
      local result; result=$(cat "$local_file" 2>/dev/null || echo '{}')
      local status; status=$(echo "$result" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))" 2>/dev/null || echo "")
      local msg;    msg=$(echo "$result"    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('msg',''))" 2>/dev/null || echo "")
      local version; version=$(echo "$result" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('version',''))" 2>/dev/null || echo "")

      if [ "$status" = "ok" ]; then
        ok "$label: $msg${version:+ (v$version)}"
        return 0
      elif [ "$status" = "error" ]; then
        warn "$label: FAILED — $msg"
        return 1
      fi
    fi
    sleep "$POLL_INTERVAL"
    elapsed=$((elapsed + POLL_INTERVAL))
    info "$label: waiting... (${elapsed}s)"
  done
  warn "$label: timed out after ${timeout}s"
  return 1
}

# ── Main ──────────────────────────────────────────────────────────────

echo ""
echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${CYAN}║          PCOS Deploy Orchestrator        ║${RESET}"
echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════╝${RESET}"

# ── Phase 0: Version bump ─────────────────────────────────────────────
hdr "Phase 0: Prep"

VERSION_FILE="$PROJECT/src/core/version.py"
CURRENT_VERSION=$(grep '__version__' "$VERSION_FILE" | grep -o '"[^"]*"' | tr -d '"')

if $BUMP_MAJOR || $BUMP_MINOR || $BUMP_PATCH; then
  IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT_VERSION"
  
  if $BUMP_MAJOR; then
    MAJOR=$((MAJOR + 1)); MINOR=0; PATCH=0
  elif $BUMP_MINOR; then
    MINOR=$((MINOR + 1)); PATCH=0
  else
    PATCH=$((PATCH + 1))
  fi
  
  NEW_VERSION="$MAJOR.$MINOR.$PATCH"
  sed -i "s/__version__ = \"$CURRENT_VERSION\"/__version__ = \"$NEW_VERSION\"/" "$VERSION_FILE"
  CURRENT_VERSION="$NEW_VERSION"
  ok "Version bumped to v$CURRENT_VERSION"
else
  suggested=$(analyze_commits)
  info "Deploying v$CURRENT_VERSION (use --bump-version, --bump-minor, or --bump-major)"
  if [ "$suggested" != "patch" ]; then
    warn "Note: commits since last tag suggest --bump-$suggested"
  fi
fi

TARGET_VERSION="$CURRENT_VERSION"

# Clear old deploy status files
mkdir -p "$DEPLOY_DIR_LOCAL"
rm -f "$DEPLOY_DIR_LOCAL"/{kill,pull,restart}_status.json

# Upload helper scripts to laptop
upload_scripts

# Verify documentation consistency before deploying
info "Verifying documentation consistency..."
if ! "$SCRIPT_DIR/verify_docs.sh" --all > /dev/null 2>&1; then
  warn "Documentation verification failed — continuing anyway (non-fatal)"
else
  ok "Documentation verified"
fi

# ── Phase 1+2: Push to GitHub AND kill both machines simultaneously ───
hdr "Phase 1+2: Push + Kill (parallel)"

# Push to GitHub in background
(
  cd "$PROJECT"
  if git diff --quiet && git diff --staged --quiet; then
    info "Git: nothing new to commit, pushing existing HEAD..."
  else
    git add -A
    COMMIT_MSG="deploy v$TARGET_VERSION: $(date '+%Y-%m-%d %H:%M')"
    git commit -m "$COMMIT_MSG"
    info "Git: committed — $COMMIT_MSG"
  fi
  git push origin master
  echo "pushed" > "$DEPLOY_DIR_LOCAL/push_done"
  ok "Git: pushed to origin/master"
) &
PUSH_PID=$!

# Kill laptop in background
(
  info "Laptop: triggering kill..."
  rm -f /tmp/pcos_laptop_kill_status.json
  ssh "$LAPTOP_USER@$LAPTOP_HOST" \
    "bash $LAPTOP_DIR/scripts/device_kill.sh" 2>&1 | \
    while IFS= read -r line; do info "  [laptop] $line"; done
  # Copy status file locally for polling
  scp -q "$LAPTOP_USER@$LAPTOP_HOST:$DEPLOY_DIR_LAPTOP/kill_status.json" \
    /tmp/pcos_laptop_kill_status.json 2>/dev/null || true
) &
LAPTOP_KILL_PID=$!

# Kill local in background
(
  info "Desktop: triggering kill..."
  bash "$SCRIPT_DIR/device_kill.sh" 2>&1 | \
    while IFS= read -r line; do info "  [desktop] $line"; done
) &
DESKTOP_KILL_PID=$!

# Wait for all three background jobs
info "Waiting for push + kills to complete..."
wait $PUSH_PID    || fail "Git push failed"
wait $LAPTOP_KILL_PID || warn "Laptop kill process had issues (checking status...)"
wait $DESKTOP_KILL_PID || warn "Desktop kill process had issues (checking status...)"

# Verify kills via status files
KILL_OK=true
wait_for_status_local "Desktop kill" "$DEPLOY_DIR_LOCAL/kill_status.json" 30 || KILL_OK=false
# Laptop kill status was scp'd to /tmp
if [ -f /tmp/pcos_laptop_kill_status.json ]; then
  cp /tmp/pcos_laptop_kill_status.json "$DEPLOY_DIR_LOCAL/laptop_kill_status.json"
  wait_for_status_local "Laptop kill" "$DEPLOY_DIR_LOCAL/laptop_kill_status.json" 5 || KILL_OK=false
else
  # Try fetching directly
  wait_for_status "$LAPTOP_HOST" "$LAPTOP_USER@$LAPTOP_HOST" \
    "$DEPLOY_DIR_LAPTOP/kill_status.json" 30 || KILL_OK=false
fi

if ! $KILL_OK; then
  warn "One or more kills did not confirm — continuing anyway (processes may already be dead)"
fi

# Verify push
if [ ! -f "$DEPLOY_DIR_LOCAL/push_done" ]; then
  fail "Git push did not confirm completion"
fi
ok "Push confirmed"

# ── Phase 3: Pull both machines simultaneously ─────────────────────────
hdr "Phase 3: Pull (parallel)"

rm -f "$DEPLOY_DIR_LOCAL"/{pull,laptop_pull}_status.json

# Pull laptop in background
(
  info "Laptop: triggering pull..."
  ssh "$LAPTOP_USER@$LAPTOP_HOST" \
    "bash $LAPTOP_DIR/scripts/device_pull.sh $LAPTOP_DIR $TARGET_VERSION" 2>&1 | \
    while IFS= read -r line; do info "  [laptop] $line"; done
  scp -q "$LAPTOP_USER@$LAPTOP_HOST:$DEPLOY_DIR_LAPTOP/pull_status.json" \
    "$DEPLOY_DIR_LOCAL/laptop_pull_status.json" 2>/dev/null || true
) &
LAPTOP_PULL_PID=$!

# Pull local in background
(
  info "Desktop: triggering pull..."
  bash "$SCRIPT_DIR/device_pull.sh" "$LOCAL_DIR" "$TARGET_VERSION" 2>&1 | \
    while IFS= read -r line; do info "  [desktop] $line"; done
) &
DESKTOP_PULL_PID=$!

wait $LAPTOP_PULL_PID || warn "Laptop pull process exited non-zero"
wait $DESKTOP_PULL_PID || warn "Desktop pull process exited non-zero"

# Verify pulls
PULL_OK=true
wait_for_status_local "Desktop pull" "$DEPLOY_DIR_LOCAL/pull_status.json" 30 || PULL_OK=false
wait_for_status_local "Laptop pull"  "$DEPLOY_DIR_LOCAL/laptop_pull_status.json" 30 || PULL_OK=false

if ! $PULL_OK; then
  fail "Pull phase failed — not proceeding to restart"
fi

# ── Phase 4: Restart both machines simultaneously ─────────────────────
hdr "Phase 4: Restart (parallel)"

rm -f "$DEPLOY_DIR_LOCAL"/{restart,laptop_restart}_status.json

# Restart laptop in background
(
  info "Laptop: triggering restart..."
  ssh "$LAPTOP_USER@$LAPTOP_HOST" \
    "bash $LAPTOP_DIR/scripts/device_restart.sh $LAPTOP_DIR $TARGET_VERSION" 2>&1 | \
    while IFS= read -r line; do info "  [laptop] $line"; done
  scp -q "$LAPTOP_USER@$LAPTOP_HOST:$DEPLOY_DIR_LAPTOP/restart_status.json" \
    "$DEPLOY_DIR_LOCAL/laptop_restart_status.json" 2>/dev/null || true
) &
LAPTOP_RESTART_PID=$!

# Restart local in background
(
  info "Desktop: triggering restart..."
  bash "$SCRIPT_DIR/device_restart.sh" "$LOCAL_DIR" "$TARGET_VERSION" 2>&1 | \
    while IFS= read -r line; do info "  [desktop] $line"; done
) &
DESKTOP_RESTART_PID=$!

wait $LAPTOP_RESTART_PID || warn "Laptop restart process exited non-zero"
wait $DESKTOP_RESTART_PID || warn "Desktop restart process exited non-zero"

# Verify restarts
RESTART_OK=true
wait_for_status_local "Desktop restart" "$DEPLOY_DIR_LOCAL/restart_status.json" 60 || RESTART_OK=false
wait_for_status_local "Laptop restart"  "$DEPLOY_DIR_LOCAL/laptop_restart_status.json" 60 || RESTART_OK=false

# ── Summary ───────────────────────────────────────────────────────────
hdr "Deploy Summary"

if $RESTART_OK; then
  echo ""
  echo -e "${GREEN}${BOLD}  ✓ Deploy v$TARGET_VERSION complete — both machines healthy${RESET}"
  echo ""
else
  echo ""
  echo -e "${YELLOW}${BOLD}  ⚠ Deploy v$TARGET_VERSION completed with warnings — check logs${RESET}"
  echo ""
fi

if $NO_TAIL; then
  exit 0
fi

# ── Phase 5: Live log tail ─────────────────────────────────────────────
hdr "Live Logs (Ctrl+C to stop)"
echo ""
echo -e "${CYAN}  [desktop]${RESET} $LOG_LOCAL"
echo -e "${CYAN}  [laptop] ${RESET} $LAPTOP_USER@$LAPTOP_HOST:$LOG_LAPTOP"
echo ""

# Prefix each line with the source
(tail -f "$LOG_LOCAL" 2>/dev/null | while IFS= read -r line; do
  echo -e "${CYAN}[desktop]${RESET} $line"
done) &
TAIL_LOCAL=$!

(ssh "$LAPTOP_USER@$LAPTOP_HOST" "tail -f $LOG_LAPTOP" 2>/dev/null | while IFS= read -r line; do
  echo -e "${YELLOW}[laptop] ${RESET} $line"
done) &
TAIL_SSH=$!

trap "kill $TAIL_LOCAL $TAIL_SSH 2>/dev/null; echo ''; ok 'Log tail stopped'; exit 0" INT TERM
wait
