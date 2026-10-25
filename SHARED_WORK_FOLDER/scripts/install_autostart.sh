#!/bin/bash
# Install (or remove) the macOS LaunchAgents that keep the IWI editor server
# running at login and open its browser tabs.
#
#   scripts/install_autostart.sh             install / reinstall
#   scripts/install_autostart.sh --uninstall remove both agents
#   scripts/install_autostart.sh --no-load   write + lint plists only (testing)
#
# Env override: LAUNCH_AGENTS_DIR (default ~/Library/LaunchAgents)
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AGENTS_DIR="${LAUNCH_AGENTS_DIR:-$HOME/Library/LaunchAgents}"
SERVER_LABEL="com.iwi.editor"
TABS_LABEL="com.iwi.editor-tabs"
SERVER_PLIST="$AGENTS_DIR/$SERVER_LABEL.plist"
TABS_PLIST="$AGENTS_DIR/$TABS_LABEL.plist"
PY="$ROOT/.venv/bin/python"
LOG="$ROOT/app/logs/server.log"
PORT=5051
DOMAIN="gui/$(id -u)"

MODE=install
for a in "$@"; do
  case "$a" in
    --uninstall) MODE=uninstall ;;
    --no-load)   MODE=noload ;;
    -h|--help)   sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "Unknown option: $a" >&2; exit 2 ;;
  esac
done

bootout() { launchctl bootout "$DOMAIN/$1" >/dev/null 2>&1 || true; }

if [ "$MODE" = uninstall ]; then
  bootout "$SERVER_LABEL"; bootout "$TABS_LABEL"
  rm -f "$SERVER_PLIST" "$TABS_PLIST"
  echo "Removed $SERVER_LABEL and $TABS_LABEL."
  exit 0
fi

# --- Check the venv -------------------------------------------------------
if [ ! -x "$PY" ] || ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info[:2]==(3,13) else 1)' 2>/dev/null; then
  echo "ERROR: $PY is missing or is not Python 3.13." >&2
  echo "Create the virtual environment first: see SETUP.md, section \"Install\"." >&2
  exit 1
fi

mkdir -p "$ROOT/app/logs" "$AGENTS_DIR"

# --- Write plists ---------------------------------------------------------
cat > "$SERVER_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$SERVER_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>-u</string>
    <string>app.py</string>
  </array>
  <key>WorkingDirectory</key><string>$ROOT/app</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PLIST

cat > "$TABS_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$TABS_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/sh</string>
    <string>-c</string>
    <string>sleep 15; open http://localhost:$PORT/ http://localhost:$PORT/editor http://localhost:$PORT/plaque</string>
  </array>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
PLIST

for p in "$SERVER_PLIST" "$TABS_PLIST"; do
  plutil -lint "$p" >/dev/null || { echo "ERROR: invalid plist $p" >&2; exit 1; }
done
echo "Wrote and validated:"; echo "  $SERVER_PLIST"; echo "  $TABS_PLIST"

[ "$MODE" = noload ] && { echo "(--no-load: agents not loaded)"; exit 0; }

# --- Load idempotently ----------------------------------------------------
bootout "$SERVER_LABEL"; bootout "$TABS_LABEL"
sleep 1
holder="$(lsof -nP -iTCP:$PORT -sTCP:LISTEN -t 2>/dev/null | head -1)"
if [ -n "$holder" ]; then
  echo "WARNING: port $PORT is already in use by PID $holder ($(ps -p "$holder" -o command= 2>/dev/null | cut -c1-100))." >&2
  echo "         Stop that process (or it will conflict with the new agent)." >&2
fi
launchctl bootstrap "$DOMAIN" "$SERVER_PLIST" || { echo "ERROR: bootstrap failed for $SERVER_LABEL" >&2; exit 1; }
launchctl bootstrap "$DOMAIN" "$TABS_PLIST"   || { echo "ERROR: bootstrap failed for $TABS_LABEL" >&2; exit 1; }

# --- Wait for the server --------------------------------------------------
echo "Waiting for the server on port $PORT ..."
for _ in $(seq 1 20); do
  if curl -s -o /dev/null "http://localhost:$PORT/"; then
    echo "Success. The server is running and will start at every login:"
    echo "  http://localhost:$PORT/"
    echo "  http://localhost:$PORT/editor"
    echo "  http://localhost:$PORT/plaque"
    exit 0
  fi
  sleep 1
done
echo "ERROR: no response from http://localhost:$PORT/ after 20 s. Last 20 lines of $LOG:" >&2
tail -n 20 "$LOG" >&2 2>/dev/null || echo "(no log yet)" >&2
exit 1
