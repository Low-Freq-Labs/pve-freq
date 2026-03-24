#!/usr/bin/env bash
# freqdev-screen.sh — Launch or reattach the FREQDEV screen session
# Window 0: freq-dev Claude Code session
# Window 1: Live debug feed (tail -f debug.log)

SESSION="FREQDEV"
LOG="/home/freq-ops/dev-ops/rick/logs/debug.log"

# Ensure log exists
touch "$LOG"

# Check if session already exists
if screen -ls | grep -q "$SESSION"; then
  echo "Session $SESSION already exists."
  echo ""
  echo "To add a debug window to the existing session:"
  echo "  1. Attach:  screen -r $SESSION"
  echo "  2. New window:  Ctrl-a c"
  echo "  3. Run:  tail -f $LOG"
  echo "  4. Switch windows:  Ctrl-a n  (next) / Ctrl-a p  (prev)"
  echo "  5. Name the window:  Ctrl-a A  then type 'debug'"
  echo ""
  echo "Or kill the old session and start fresh:"
  echo "  screen -S $SESSION -X quit"
  echo "  bash $0"
  exit 0
fi

# Create new session with two windows
screen -dmS "$SESSION" -t "freq-dev" bash
screen -S "$SESSION" -X screen -t "debug" bash -c "echo '═══ FREQ-DEV DEBUG FEED ═══'; echo ''; tail -f $LOG"

echo "Screen session '$SESSION' created with:"
echo "  Window 0: freq-dev  (run Claude Code here)"
echo "  Window 1: debug     (live tail of debug.log)"
echo ""
echo "Attach with:  screen -r $SESSION"
echo "Switch windows: Ctrl-a n / Ctrl-a p"
