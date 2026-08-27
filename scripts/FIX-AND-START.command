#!/bin/bash
# ============================================================
#  SMSM Festival — one-click fix and start
#  Double-click this file. It does everything:
#    1. stops any bot that's already running
#    2. makes sure the speech engine is installed
#    3. downloads the speech model (first time only)
#    4. starts the bot
#  Safe to run any time. Nothing is deleted.
# ============================================================

cd "$(dirname "$0")" || exit 1
[ -f bot.py ] || cd .. || exit 1
HERE="$(pwd)"

echo "============================================================"
echo " SMSM Festival — fixing and starting"
echo " Folder: $HERE"
echo "============================================================"
echo ""

# --- 1. Stop anything already running --------------------------------------
# The bot launches as "./.venv/bin/python bot.py", so the folder name never
# appears in the process list. The reliable handle is whoever holds the port.
echo "[1/4] Stopping any bot that's already running..."

PORT=$(./.venv/bin/python -c "import json;print(json.load(open('config.json'))['dashboard']['port'])" 2>/dev/null \
       || python3 -c "import json;print(json.load(open('config.json'))['dashboard']['port'])" 2>/dev/null)
[ -z "$PORT" ] && PORT=8080

pkill -f "python.*bot\.py" 2>/dev/null
pkill -f "caffeinate.*bot\.py" 2>/dev/null

for attempt in 1 2 3 4 5 6 7 8 9 10; do
  PIDS=$(lsof -ti tcp:"$PORT" 2>/dev/null)
  [ -z "$PIDS" ] && break
  echo "      Port $PORT still held by PID(s): $PIDS — closing..."
  kill -9 $PIDS 2>/dev/null
  sleep 1
done

if [ -n "$(lsof -ti tcp:"$PORT" 2>/dev/null)" ]; then
  echo "      !! Port $PORT is still busy. The bot will use the next free port"
  echo "      !! and print the new screen address below."
else
  echo "      Done — port $PORT is free."
fi
echo ""

# --- 2. Environment --------------------------------------------------------
if [ ! -d ".venv" ]; then
  echo "[2/4] No environment found — building one (a few minutes)..."
  PY="python3"
  command -v python3.12 >/dev/null 2>&1 && PY="python3.12"
  "$PY" -m venv .venv || { echo "Could not create environment."; read -r -p "Press Enter..."; exit 1; }
  ./.venv/bin/python -m pip install --upgrade pip --quiet
  ./.venv/bin/python -m pip install -r requirements.txt || {
    echo "!! Install failed. Delete the .venv folder and run this again."
    read -r -p "Press Enter to close..."; exit 1; }
else
  echo "[2/4] Checking the speech engine..."
  if ./.venv/bin/python -c "import faster_whisper" >/dev/null 2>&1; then
    echo "      Already installed."
  else
    echo "      Installing faster-whisper (a few minutes, ~400 MB)..."
    ./.venv/bin/python -m pip install faster-whisper || {
      echo ""
      echo "!! Install failed. The bot will still run and voice messages will"
      echo "!! still play out loud - they just won't update the board."
      echo ""
      sleep 3; }
  fi
fi
echo ""

# --- 3. Pre-download the speech model so the festival never waits on it -----
echo "[3/4] Preparing the speech model..."
MODEL=$(./.venv/bin/python -c "import json;print(json.load(open('config.json')).get('voice_input',{}).get('model','base.en'))" 2>/dev/null)
[ -z "$MODEL" ] && MODEL="base.en"
echo "      Model: $MODEL  (first run downloads ~150 MB - please wait)"
./.venv/bin/python - <<PYEOF
try:
    from faster_whisper import WhisperModel
    WhisperModel("$MODEL", device="cpu", compute_type="int8")
    print("      Speech model ready.")
except ImportError:
    print("      Speech engine not installed - voice messages will play but not update the board.")
except Exception as e:
    print(f"      Could not prepare the model: {e}")
    print("      Voice messages will still play out loud.")
PYEOF
echo ""

# --- 4. Checks and launch --------------------------------------------------
if [ ! -f ".env" ]; then
  echo "!! No .env file found in this folder. Copy .env.example to .env and"
  echo "!! paste your bot token into it, then run this again."
  read -r -p "Press Enter to close..."; exit 1
fi

if [ ! -f "web/kitchen.html" ]; then
  echo "!! The web folder is missing from this folder - the big screens won't load."
  echo "!! Copy the 'web' folder in from the download, then run this again."
  read -r -p "Press Enter to close..."; exit 1
fi

command -v ffmpeg >/dev/null 2>&1 || {
  echo "!! ffmpeg not found - the kitchen speaker will stay silent."
  echo "!! Fix with:  brew install ffmpeg"
  echo ""; }

echo "[4/4] Starting the bot. Keep this window open all day."
echo "      Watch for:  [ok] Speech-to-text ready"
echo "      Ctrl+C twice to stop."
echo "============================================================"
echo ""

while true; do
  caffeinate -dimsu ./.venv/bin/python bot.py
  echo ""
  echo "!! Bot stopped at $(date). Restarting in 5 seconds... (Ctrl+C to quit)"
  sleep 5
done
