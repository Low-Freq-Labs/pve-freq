#!/usr/bin/env bash
# Claude Code status line — converted from ~/.bashrc PS1
# Installed by statusline-setup agent

input=$(cat)

cwd=$(echo "$input" | jq -r '.workspace.current_dir // .cwd // empty')
[ -z "$cwd" ] && cwd=$(pwd)

model=$(echo "$input" | jq -r '.model.display_name // empty')

# Context usage calculation — three-tier fallback for persistence across sessions:
# 1. used_percentage: pre-calculated by Claude Code (accurate, but null before first API call)
# 2. total_input_tokens + total_output_tokens: cumulative session totals (always present after first message)
# 3. current_usage: last API call snapshot (least reliable for persistence, used as last resort)
used=$(echo "$input" | jq -r '
  if (.context_window.used_percentage != null) then
    .context_window.used_percentage
  elif ((.context_window.total_input_tokens // 0) > 0) then
    ((.context_window.total_input_tokens // 0) + (.context_window.total_output_tokens // 0)) as $used |
    ((.context_window.context_window_size // 0) | if . > 0 then . else 200000 end) as $size |
    ($used / $size * 100)
  elif (.context_window.current_usage != null) then
    (.context_window.current_usage.cache_read_input_tokens // 0)
    + (.context_window.current_usage.cache_creation_input_tokens // 0)
    + (.context_window.current_usage.input_tokens // 0)
    + (.context_window.current_usage.output_tokens // 0)
    as $used |
    ((.context_window.context_window_size // 0) | if . > 0 then . else 200000 end) as $size |
    ($used / $size * 100)
  else empty
  end
')

# user@host:cwd  (green user@host, blue cwd — matches original PS1 palette)
printf "\033[01;32m%s@%s\033[00m:\033[01;34m%s\033[00m" \
    "$(whoami)" "$(hostname -s)" "$cwd"

# model name (dimmed)
if [ -n "$model" ]; then
    printf "  \033[02m%s\033[00m" "$model"
fi

# context bar: filled = used, empty = remaining. Label says "used" explicitly.
# Example at 14% used: [#--------- 14% used]
if [ -n "$used" ]; then
    pct=$(printf "%.0f" "$used")
    filled=$(( pct / 10 ))
    empty=$(( 10 - filled ))
    bar=""
    for i in $(seq 1 $filled); do bar="${bar}#"; done
    for i in $(seq 1 $empty);  do bar="${bar}-"; done

    # color thresholds based on how much is USED:
    # green = plenty left (<50% used), yellow = getting tight (50-80% used), red = critical (>80% used)
    if [ "$pct" -lt 50 ]; then
        color="\033[02;32m"   # dimmed green
    elif [ "$pct" -lt 80 ]; then
        color="\033[02;33m"   # dimmed yellow
    else
        color="\033[02;31m"   # dimmed red
    fi

    printf " ${color}[%s %s%% used]\033[00m" "$bar" "$pct"
fi
