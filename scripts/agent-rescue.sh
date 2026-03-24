#!/bin/bash
# ═══════════════════════════════════════════════════════════════
#  agent-rescue — Instantly open a Claude terminal for any agent
#  Install: sudo cp to /usr/local/bin/jarvis-rescue etc.
# ═══════════════════════════════════════════════════════════════
#
#  Usage: <agent>-rescue
#    jarvis-rescue  →  opens claude in /home/jarvis/
#    rick-rescue    →  opens claude in /home/rick/
#    morty-rescue   →  opens claude in /home/morty/

SCRIPT_NAME=$(basename "$0")
AGENT="${SCRIPT_NAME%-rescue}"

case "$AGENT" in
    jarvis) HOME_DIR="/home/jarvis" ;;
    rick)   HOME_DIR="/home/freq-ops/dev-ops/rick" ;;
    morty)  HOME_DIR="/home/morty" ;;
    *)      echo "Unknown agent: $AGENT"; exit 1 ;;
esac

# Fix terminal first
stty sane 2>/dev/null
tput cnorm 2>/dev/null

# Kill any broken nexus state
pgrep -u "$(id -u)" -f "nexus" 2>/dev/null | grep -v "$$" | xargs kill 2>/dev/null || true

echo ""
echo "  ══════════════════════════════════"
echo "  ${AGENT^^} RESCUE — bare-bones Claude"
echo "  ══════════════════════════════════"
echo ""

if [ ! -d "$HOME_DIR" ]; then
    echo "  ERROR: $HOME_DIR does not exist"
    echo "  Ask JARVIS to create the account first"
    exit 1
fi

if [ ! -f "$HOME_DIR/CLAUDE.md" ]; then
    echo "  WARNING: No CLAUDE.md in $HOME_DIR"
    echo "  Agent will start without a constitution"
    echo ""
fi

CLAUDE_BIN=$(which claude 2>/dev/null || echo "$HOME/.local/bin/claude")
if [ ! -x "$CLAUDE_BIN" ]; then
    echo "  ERROR: Claude Code not found"
    echo "  Install: curl -fsSL https://claude.ai/install.sh | bash"
    exit 1
fi

echo "  Home: $HOME_DIR"
echo "  Claude: $CLAUDE_BIN"
echo ""
echo "  Launching..."
echo ""

cd "$HOME_DIR"
exec "$CLAUDE_BIN"
