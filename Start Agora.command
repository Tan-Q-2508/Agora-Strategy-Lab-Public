#!/bin/bash
# Double-click to start Agora on macOS. See docs/RUNBOOK.md section 1.
cd "$(dirname "$0")" || exit 1
printf '\033]0;Agora: keep this window open\007'
mkdir -p data/logs
LOG="data/logs/launcher.log"
echo "==== $(date) ====" >> "$LOG"
export PATH="$HOME/.local/bin:$PATH"

fail() {
  echo
  echo "$1"
  echo "Details are in data/logs/launcher.log"
  echo "$1" >> "$LOG"
  echo
  read -r -p "Press Enter to close this window." _
  exit 1
}

echo
echo "  Agora"
echo "  ====="
echo

# 1. Make sure uv (which installs Python and Agora's parts) is available.
if ! command -v uv >/dev/null 2>&1; then
  echo "Setting up Agora for the first time. This takes a few minutes..."
  curl -LsSf https://astral.sh/uv/install.sh | sh >> "$LOG" 2>&1
  command -v uv >/dev/null 2>&1 ||
    fail "Agora couldn't download its setup tool. Check your internet connection and try again."
fi

# 2. Install or update Python and Agora's parts.
echo "Getting everything ready. The first time takes a few minutes..."
uv sync --frozen --no-dev >> "$LOG" 2>&1 ||
  fail "Agora couldn't install its parts. Check your internet connection and try again."

# 3. Hand over to the menu-bar icon (D-124): Agora runs in the background, opens in its own
#    window, and this Terminal window can be closed.
if [ -x ".venv/bin/python" ]; then
  echo "Starting Agora. It opens in its own window; look for the Agora icon in the menu bar."
  nohup .venv/bin/python -m backend.desktop.tray >> "data/logs/launcher.log" 2>&1 &
  exit 0
fi
if ! uv run --frozen --no-dev python -m backend.launch; then
  echo
  read -r -p "Press Enter to close this window." _
  exit 1
fi
