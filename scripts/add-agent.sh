#!/bin/bash
# add-agent.sh — Add a new agent/user to NEXUS
# Usage: sudo bash add-agent.sh <username> <color> <role>
#
# Examples:
#   sudo bash add-agent.sh chris blue "Fleet Operator"
#   sudo bash add-agent.sh donny green "Media Manager"
#   sudo bash add-agent.sh sarah orange "Security Lead"
#
# Colors: red, green, blue, orange, purple, yellow, cyan, pink

set -e

if [ $# -lt 3 ]; then
    echo ""
    echo "  Usage: sudo bash add-agent.sh <username> <color> <role>"
    echo ""
    echo "  Colors: red, green, blue, orange, purple, yellow, cyan, pink"
    echo ""
    echo "  Example: sudo bash add-agent.sh chris blue \"Fleet Operator\""
    echo ""
    exit 1
fi

USERNAME="$1"
COLOR="$2"
ROLE="$3"
TEMPLATE="/home/freq-ops/dev-ops/rick/scripts/nexus-bashrc-wip.sh"

# Color map (RGB values)
case "$COLOR" in
    red)    RGB="220;38;38";   RGBLT="255;100;100"; TMUX_BG="#DC2626"; TMUX_FG="#ffffff" ;;
    green)  RGB="63;185;80";   RGBLT="120;220;140"; TMUX_BG="#3FB950"; TMUX_FG="#1a1b26" ;;
    blue)   RGB="56;132;244";  RGBLT="120;170;255"; TMUX_BG="#388BF4"; TMUX_FG="#ffffff" ;;
    orange) RGB="255;166;43";  RGBLT="255;200;120"; TMUX_BG="#FFA62B"; TMUX_FG="#1a1b26" ;;
    purple) RGB="155;79;222";  RGBLT="180;140;255"; TMUX_BG="#9B4FDE"; TMUX_FG="#ffffff" ;;
    yellow) RGB="234;179;8";   RGBLT="255;220;100"; TMUX_BG="#E5C07B"; TMUX_FG="#1a1b26" ;;
    cyan)   RGB="0;188;212";   RGBLT="100;220;240"; TMUX_BG="#00BCD4"; TMUX_FG="#1a1b26" ;;
    pink)   RGB="236;72;153";  RGBLT="255;130;190"; TMUX_BG="#EC4899"; TMUX_FG="#ffffff" ;;
    *)      echo "Unknown color: $COLOR"; exit 1 ;;
esac

echo ""
echo "  Adding agent: $USERNAME"
echo "  Color: $COLOR ($RGB)"
echo "  Role: $ROLE"
echo ""

# 1. Create user
if id "$USERNAME" &>/dev/null; then
    echo "  · User $USERNAME already exists"
else
    useradd -m -s /bin/bash -G freq-ops,sudo "$USERNAME"
    echo "  ✓ User $USERNAME created"
fi

HOME_DIR=$(eval echo "~$USERNAME")

# 2. Build their bashrc from template
if [ -f "$TEMPLATE" ]; then
    sed \
        -e "s|freq-ops@nexus (DC01 Command Center)|${USERNAME}@nexus (DC01 ${ROLE})|" \
        -e "s|\\\\033\[1;33m\]freq-ops|\\\\033[38;2;${RGB}m]${USERNAME}|" \
        -e "s|\\\\033\[1;93m\]nexus|\\\\033[38;2;${RGB}m]nexus|" \
        -e "s|\\\\033\[38;5;228m\]|\\\\033[38;2;${RGBLT}m]|" \
        -e "s|/home/freq-ops/.venv/bin:/home/freq-ops/.local/bin|$HOME_DIR/.local/bin|" \
        -e "/freq-ops.*venv.*activate/d" \
        -e "/source.*freq-ops.*venv/d" \
        "$TEMPLATE" > "$HOME_DIR/.bashrc"
    echo "  ✓ Bashrc deployed (${COLOR} theme)"
else
    echo "  ✗ Template not found: $TEMPLATE"
    exit 1
fi

# 3. Tmux config
cat > "$HOME_DIR/.tmux.conf" << TMUXEOF
# NEXUS — tmux config (${COLOR}) — ${USERNAME} · ${ROLE}
set -g mouse on
set -g history-limit 50000
set -g default-terminal "tmux-256color"
set -sa terminal-overrides ",xterm*:Tc"
set -g status-position bottom
set -g status-style "bg=#1a1b26,fg=#a9b1d6"
set -g status-left-length 40
set -g status-right-length 50
set -g status-left "#[bg=${TMUX_BG},fg=${TMUX_FG},bold] ◆ #S #[default] "
set -g status-right "#[fg=#6B7089]│ #[fg=${TMUX_BG}]${USERNAME} #[fg=#6B7089]│ %H:%M │ %b %d "
set -g status-justify left
set -g window-status-format "#[fg=#6B7089]  #I:#W  "
set -g window-status-current-format "#[fg=${TMUX_BG},bold]  #I:#W  "
set -g window-status-separator ""
set -g pane-border-style "fg=#3b4261"
set -g pane-active-border-style "fg=${TMUX_BG}"
set -g pane-border-status top
set -g pane-border-format "#[fg=#6B7089] #{pane_index}: #{pane_title} "
set -g base-index 1
setw -g pane-base-index 1
set -g allow-rename off
set -sg escape-time 0
setw -g monitor-activity on
set -g visual-activity off
bind | split-window -h -c "#{pane_current_path}"
bind - split-window -v -c "#{pane_current_path}"
bind r source-file ~/.tmux.conf \; display "Config reloaded"
bind x kill-pane
setw -g mode-keys vi
TMUXEOF
echo "  ✓ Tmux config deployed (${COLOR} theme)"

# 4. Nexus scripts
cp /home/freq-ops/nexus-start "$HOME_DIR/nexus-start" 2>/dev/null || cp /home/freq-ops/dev-ops/rick/nexus-start "$HOME_DIR/nexus-start"
cp /home/freq-ops/nexus-stop "$HOME_DIR/nexus-stop" 2>/dev/null || cp /home/freq-ops/dev-ops/rick/nexus-stop "$HOME_DIR/nexus-stop"
chmod +x "$HOME_DIR/nexus-start" "$HOME_DIR/nexus-stop"
echo "  ✓ Nexus scripts deployed"

# 5. (AI-NET mailbox removed — decommissioned 2026-03-18, comms via SendMessage)

# 6. Fix ownership
chown -R "$USERNAME:$USERNAME" "$HOME_DIR"
echo "  ✓ Ownership set"

echo ""
echo "  ═══════════════════════════════════════"
echo "  ✓ $USERNAME is LIVE on NEXUS"
echo "  ═══════════════════════════════════════"
echo ""
echo "  Login:  sudo -u $USERNAME -i"
echo "  NEXUS:  nexus"
echo "  Color:  $COLOR"
echo "  Role:   $ROLE"
echo ""
