#!/usr/bin/env bash
# deploy.sh — clean, push, pull, restart both devices in one command
#
# Usage:
#   ./scripts/deploy.sh                   # normal deploy
#   ./scripts/deploy.sh --clear-logs      # also wipe logs on both sides
#   ./scripts/deploy.sh --bump-version    # increment patch version first
#
# Requires: SSH access to laptop as jonathansoberg@192.168.1.82
#           The project lives at ~/Projects/personal-cloud-os on the laptop

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="$(dirname "$SCRIPT_DIR")"
LAPTOP_USER="jonathansoberg"
LAPTOP_HOST="192.168.1.82"
LAPTOP_DIR="~/Projects/personal-cloud-os"
LOG_PATH="~/.local/share/pcos/logs/app.log"

CLEAR_LOGS=false
BUMP_VERSION=false

for arg in "$@"; do
  case $arg in
    --clear-logs)    CLEAR_LOGS=true ;;
    --bump-version)  BUMP_VERSION=true ;;
  esac
done

echo "═══════════════════════════════════════════"
echo "  PCOS Deploy"
echo "═══════════════════════════════════════════"

# ── 1. Optional version bump ──────────────────────────────────────────
if $BUMP_VERSION; then
  VERSION_FILE="$PROJECT/src/core/version.py"
  CURRENT=$(grep '__version__' "$VERSION_FILE" | grep -o '"[^"]*"' | tr -d '"')
  IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT"
  PATCH=$((PATCH + 1))
  NEW_VERSION="$MAJOR.$MINOR.$PATCH"
  sed -i "s/__version__ = \"$CURRENT\"/__version__ = \"$NEW_VERSION\"/" "$VERSION_FILE"
  echo "  Version bumped: $CURRENT → $NEW_VERSION"
fi

# ── 2. Kill local instance ────────────────────────────────────────────
echo "  Stopping local instance..."
pkill -f 'python3.*main.py' 2>/dev/null || true
sleep 1

# ── 3. Clear local log ───────────────────────────────────────────────
if $CLEAR_LOGS; then
  > "$HOME/.local/share/pcos/logs/app.log" 2>/dev/null || true
  echo "  Local log cleared"
fi

# ── 4. Commit and push ────────────────────────────────────────────────
cd "$PROJECT"
if git diff --quiet && git diff --staged --quiet; then
  echo "  Nothing to commit — pushing existing HEAD"
else
  git add -A
  git commit -m "deploy: $(date '+%Y-%m-%d %H:%M')"
fi
git push origin master
echo "  Pushed to origin/master"

# ── 5. Kill, pull, clear log on laptop ───────────────────────────────
echo "  Updating laptop..."
ssh "$LAPTOP_USER@$LAPTOP_HOST" "
  pkill -f 'python3.*main.py' 2>/dev/null || true
  sleep 1
  cd $LAPTOP_DIR
  git fetch --all
  git reset --hard origin/master
  echo '  Laptop: pulled $(git log --oneline -1)'
  $(if $CLEAR_LOGS; then echo '> '$LOG_PATH; echo echo "  Laptop: log cleared"; fi)
"

# ── 6. Start laptop ──────────────────────────────────────────────────
ssh "$LAPTOP_USER@$LAPTOP_HOST" "
  cd $LAPTOP_DIR
  nohup python3 src/main.py --start > /dev/null 2>&1 &
  sleep 3
  pgrep -af 'main.py' | grep -v grep | head -1
" && echo "  Laptop: started"

# ── 7. Start local ───────────────────────────────────────────────────
cd "$PROJECT"
nohup python3 src/main.py --start > /dev/null 2>&1 &
sleep 2
echo "  Local: started (PID $(pgrep -f 'python3.*main.py' | head -1))"

echo ""
echo "  Deploy complete. Tailing logs..."
echo "  (Ctrl+C to stop watching)"
echo "═══════════════════════════════════════════"
echo ""

# ── 8. Tail both logs ────────────────────────────────────────────────
tail -f "$HOME/.local/share/pcos/logs/app.log" &
TAIL_PID=$!
ssh "$LAPTOP_USER@$LAPTOP_HOST" "tail -f $LOG_PATH" &
SSH_TAIL_PID=$!

trap "kill $TAIL_PID $SSH_TAIL_PID 2>/dev/null; exit 0" INT TERM
wait
