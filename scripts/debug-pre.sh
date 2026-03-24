#!/usr/bin/env bash
# debug-pre.sh — PreToolUse hook for freq-dev
# 1. Safety checks (VM protection, credential protection)
# 2. Debug logging
# Reads JSON from stdin (Claude Code hook protocol)

LOG="/home/freq-ops/dev-ops/rick/logs/debug.log"
INPUT=$(cat)

TOOL=$(echo "$INPUT" | jq -r '.tool_name // "unknown"')
TS=$(date '+%H:%M:%S')

# ═══════════════════════════════════════
# SAFETY CHECKS (Bash only)
# ═══════════════════════════════════════
if [ "$TOOL" = "Bash" ]; then
  CMD=$(echo "$INPUT" | jq -r '.tool_input.command // ""')

  # Block operations on VMs outside 5000-5999 range (the devspace).
  # Match qm commands with VM IDs that are NOT 5xxx
  if echo "$CMD" | grep -qiE "qm\s+(destroy|stop|start|create|set|clone|migrate|template)"; then
    # Extract the VM ID from the command
    VMID=$(echo "$CMD" | grep -oP 'qm\s+\w+\s+\K[0-9]+' | head -1)
    if [ -n "$VMID" ]; then
      if [ "$VMID" -lt 5000 ] || [ "$VMID" -gt 5999 ]; then
        echo "[$TS] ✗ BLOCKED — VM $VMID outside devspace (5000-5999)" >> "$LOG"
        echo "[$TS]   CMD: $CMD" >> "$LOG"
        echo "BLOCKED: Only VMs 5000-5999 allowed (devspace). VM $VMID is off-limits." >&2
        exit 2
      fi
    fi
  fi

  # Block access to prod credentials
  if echo "$CMD" | grep -qiE "credentials/root-pass|credentials/ssh-credentials|credentials/api-keys"; then
    echo "[$TS] ✗ BLOCKED — prod credential access attempted" >> "$LOG"
    echo "BLOCKED: Production credentials are off-limits." >&2
    exit 2
  fi
fi

# ═══════════════════════════════════════
# DEBUG LOGGING
# ═══════════════════════════════════════
case "$TOOL" in
  Bash)
    CMD=$(echo "$INPUT" | jq -r '.tool_input.command // ""')
    if echo "$CMD" | grep -qE '^ssh |sshpass'; then
      HOST=$(echo "$CMD" | grep -oP '(?:ssh\s+|@)\K[^\s"]+' | head -1)
      REMOTE_CMD=$(echo "$CMD" | sed -n 's/.*"\(.*\)".*/\1/p' | head -c 200)
      if [ -n "$REMOTE_CMD" ]; then
        echo "[$TS] SSH  → $HOST  \$ $REMOTE_CMD" >> "$LOG"
      else
        echo "[$TS] SSH  → $HOST" >> "$LOG"
      fi
    else
      echo "[$TS] BASH \$ $(echo "$CMD" | head -c 300)" >> "$LOG"
    fi
    ;;
  Read)
    FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // ""')
    echo "[$TS] READ $FILE" >> "$LOG"
    ;;
  Write)
    FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // ""')
    LINES=$(echo "$INPUT" | jq -r '.tool_input.content // ""' | wc -l)
    echo "[$TS] WRITE $FILE (${LINES} lines)" >> "$LOG"
    ;;
  Edit)
    FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // ""')
    echo "[$TS] EDIT $FILE" >> "$LOG"
    ;;
  Glob)
    PATTERN=$(echo "$INPUT" | jq -r '.tool_input.pattern // ""')
    echo "[$TS] GLOB $PATTERN" >> "$LOG"
    ;;
  Grep)
    PATTERN=$(echo "$INPUT" | jq -r '.tool_input.pattern // ""')
    echo "[$TS] GREP /$PATTERN/" >> "$LOG"
    ;;
  Agent)
    DESC=$(echo "$INPUT" | jq -r '.tool_input.description // ""')
    echo "[$TS] AGENT spawn: $DESC" >> "$LOG"
    ;;
  *)
    echo "[$TS] TOOL $TOOL" >> "$LOG"
    ;;
esac
