#!/bin/bash
# Double-click to start the festival bot on a Mac.
# Keeps the laptop awake and auto-restarts the bot if it crashes.

cd "$(dirname "$0")" || exit 1
[ -f bot.py ] || cd .. || exit 1

# --- Pick a Python that discord.py's voice support actually works on ----------
# Python 3.13 removed the `audioop` module. We handle it either way, but 3.12
# is the best-tested path, so prefer it when it's installed.
PY=""
for cand in python3.12 python3.11 python3.10 /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12; do
  if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
done
if [ -z "$PY" ]; then PY="python3"; fi

PYVER="$($PY -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null)"
echo "Using Python $PYVER  ($PY)"

if [ ! -d ".venv" ]; then
  echo "First run — setting up (this takes a couple of minutes)..."
  "$PY" -m venv .venv || { echo "Could not create the environment."; read -r -p "Press Enter..."; exit 1; }
  ./.venv/bin/pip install --upgrade pip --quiet
  ./.venv/bin/pip install -r requirements.txt || {
    echo ""
    echo "!! Install failed. Try: rm -rf .venv  then run this again."
    read -r -p "Press Enter to close..."
    exit 1
  }
fi

# Self-heal the Python 3.13+ audioop removal, even in an environment built earlier.
if ! ./.venv/bin/python -c "import audioop" >/dev/null 2>&1; then
  echo "Patching audio support for Python $PYVER..."
  ./.venv/bin/pip install --quiet --upgrade "discord.py[voice]>=2.6.0" audioop-lts 2>/dev/null
fi

if [ ! -f ".env" ]; then
  echo ""
  echo "!! No .env file found."
  echo "!! Copy .env.example to .env, paste your bot token into it, then run this again."
  echo ""
  read -r -p "Press Enter to close..."
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo ""
  echo "!! ffmpeg not found — the bot will run but the kitchen speaker will stay silent."
  echo "!! Fix with:  brew install ffmpeg"
  echo ""
fi

echo "Starting $(date). Keep this window open all day. Ctrl+C to stop."

# caffeinate is built into macOS — stops the laptop sleeping while the bot runs.
while true; do
  caffeinate -dimsu ./.venv/bin/python bot.py
  echo ""
  echo "!! Bot stopped at $(date). Restarting in 5 seconds... (Ctrl+C to quit for good)"
  sleep 5
done
