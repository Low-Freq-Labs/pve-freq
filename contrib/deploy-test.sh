#!/usr/bin/env bash
# deploy-test.sh — sync dev repo to E2E test VM via git bundle
#
# Usage: ./contrib/deploy-test.sh [host_ip]
# Default: 10.25.255.55 (VM 5005)
#
# Creates a git bundle of commits since the target's HEAD,
# copies it via scp, and applies via fast-forward merge.
# No SSH keys to GitHub needed on the target.

set -euo pipefail

TARGET="${1:-10.25.255.55}"
USER="freq-ops"
REMOTE_DIR="/tmp/pve-freq-dev"
BUNDLE="/tmp/pve-freq-deploy-bundle.git"

echo "=== Deploy to ${USER}@${TARGET}:${REMOTE_DIR} ==="

# Get target's current HEAD
echo "[1/4] Checking target HEAD..."
TARGET_HEAD=$(ssh -n "${USER}@${TARGET}" "cd ${REMOTE_DIR} && git rev-parse HEAD" 2>/dev/null)
if [ -z "$TARGET_HEAD" ]; then
    echo "ERROR: Could not read HEAD from ${TARGET}:${REMOTE_DIR}"
    exit 1
fi

LOCAL_HEAD=$(git rev-parse HEAD)
if [ "$TARGET_HEAD" = "$LOCAL_HEAD" ]; then
    echo "Already up to date (${LOCAL_HEAD:0:8})"
    exit 0
fi

BEHIND=$(git log --oneline "${TARGET_HEAD}..HEAD" | wc -l)
echo "  Target: ${TARGET_HEAD:0:8}"
echo "  Source: ${LOCAL_HEAD:0:8}"
echo "  Behind: ${BEHIND} commits"

# Create bundle
echo "[2/4] Creating bundle..."
git bundle create "$BUNDLE" "${TARGET_HEAD}..HEAD"

# Copy to target
echo "[3/4] Copying bundle..."
scp -q "$BUNDLE" "${USER}@${TARGET}:/tmp/"

# Apply on target
echo "[4/4] Applying..."
ssh -n "${USER}@${TARGET}" "cd ${REMOTE_DIR} && git pull /tmp/pve-freq-deploy-bundle.git HEAD --ff-only"

# Sync to runtime install path if it exists
RUNTIME_DIR="/opt/pve-freq"
echo "[5/6] Syncing to runtime install..."
ssh -n "${USER}@${TARGET}" "
if [ -d ${RUNTIME_DIR}/freq ]; then
    sudo rsync -a --delete \
        --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
        --exclude='conf/' --exclude='data/' \
        ${REMOTE_DIR}/ ${RUNTIME_DIR}/
    echo 'Runtime synced'
else
    echo 'No runtime install at ${RUNTIME_DIR} — skipped'
fi
"

# Restart dashboard service if running
echo "[6/6] Restarting dashboard..."
ssh -n "${USER}@${TARGET}" "
if sudo systemctl is-active freq-dashboard >/dev/null 2>&1; then
    sudo systemctl restart freq-dashboard
    echo 'Dashboard restarted'
else
    echo 'Dashboard service not running — skipped'
fi
"

# Verify
FINAL=$(ssh -n "${USER}@${TARGET}" "cd ${REMOTE_DIR} && git rev-parse --short HEAD")
echo ""
echo "=== Done: ${TARGET} now at ${FINAL} (was ${TARGET_HEAD:0:8}) ==="

# Cleanup
rm -f "$BUNDLE"
ssh -n "${USER}@${TARGET}" "rm -f /tmp/pve-freq-deploy-bundle.git" 2>/dev/null || true
