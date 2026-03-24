#!/usr/bin/env bash
# debug-post.sh — PostToolUse hook for freq-dev
LOG="/home/freq-ops/dev-ops/rick/logs/debug.log"
INPUT=$(cat)

TOOL=$(echo "$INPUT" | jq -r '.tool_name // "unknown"')
TS=$(date '+%H:%M:%S')

case "$TOOL" in
  Bash)
    RESP_TEXT=$(echo "$INPUT" | jq -r '
      if (.tool_response | type) == "string" then .tool_response
      elif (.tool_response | type) == "object" then (.tool_response.stdout // .tool_response.output // (.tool_response | tostring))
      else (.tool_response | tostring)
      end' 2>/dev/null | head -c 1000)

    HAS_ERROR=false
    if echo "$RESP_TEXT" | grep -qiE '(error|Error|ERROR|exit code [1-9]|FAILED|fatal|Fatal|FATAL|traceback|Traceback|panic)'; then
      HAS_ERROR=true
    fi

    if [ "$HAS_ERROR" = true ]; then
      echo "[$TS] ✗ BREAK — error detected:" >> "$LOG"
      ERROR_LINES=$(echo "$RESP_TEXT" | grep -iE '(error|Error|fatal|Fatal|traceback|Traceback|panic|FAILED|exception|Exception)' | head -3)
      if [ -n "$ERROR_LINES" ]; then
        echo "$ERROR_LINES" | while IFS= read -r line; do
          echo "[$TS]   $line" >> "$LOG"
        done
      else
        echo "[$TS]   $(echo "$RESP_TEXT" | tail -3 | head -3)" >> "$LOG"
      fi
      echo "[$TS] ─── waiting for fix ───" >> "$LOG"
    else
      echo "[$TS] ✓ OK" >> "$LOG"
    fi
    ;;
  Write)
    FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // ""')
    echo "[$TS] ✓ WROTE $FILE" >> "$LOG"
    ;;
  Edit)
    FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // ""')
    echo "[$TS] ✓ EDITED $FILE" >> "$LOG"
    ;;
  Read)
    echo "[$TS] ✓ read complete" >> "$LOG"
    ;;
  Agent)
    DESC=$(echo "$INPUT" | jq -r '.tool_input.description // ""')
    echo "[$TS] ✓ AGENT done: $DESC" >> "$LOG"
    ;;
  *)
    echo "[$TS] ✓ $TOOL complete" >> "$LOG"
    ;;
esac
