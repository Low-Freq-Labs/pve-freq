#!/usr/bin/env bash
# deploy-test.sh — sync dev repo to E2E test VM
#
# Usage: ./contrib/deploy-test.sh [host_ip]
# Default: 10.25.255.55 (VM 5005)
#
# Clean target: full rsync (bootstraps source tree)
# Existing target: git bundle (incremental, fast)
# Then syncs to /opt/pve-freq runtime install if present.

set -euo pipefail

TARGET="${1:-10.25.255.55}"
USER="freq-ops"
REMOTE_DIR="/tmp/pve-freq-dev"
RUNTIME_DIR="/opt/pve-freq"
BUNDLE="/tmp/pve-freq-deploy-bundle.git"

echo "=== Deploy to ${USER}@${TARGET}:${REMOTE_DIR} ==="

# Check if target has an existing source tree
TARGET_HEAD=$(ssh -n "${USER}@${TARGET}" "cd ${REMOTE_DIR} && git rev-parse HEAD 2>/dev/null" 2>/dev/null || echo "")

if [ -z "$TARGET_HEAD" ]; then
    # Clean target — full rsync bootstrap.
    # Exclude runtime-state directories entirely. Developer workspaces may
    # contain keys/vault files with 0600 perms owned by a different user,
    # which would fail rsync with 'permission denied' (exit code 23).
    # Only the source code tree should be synced to the dev target.
    echo "[1/4] Clean target — bootstrapping source tree..."
    ssh -n "${USER}@${TARGET}" "mkdir -p ${REMOTE_DIR}"
    rsync -az --delete \
        --exclude='__pycache__' --exclude='*.pyc' \
        --exclude='.venv/' --exclude='.ruff_cache/' --exclude='~freq-ops/' \
        --exclude='/data/' --exclude='/tls/' --exclude='/build/' \
        ./ "${USER}@${TARGET}:${REMOTE_DIR}/"
    echo "  Full source synced to ${REMOTE_DIR}"
else
    LOCAL_HEAD=$(git rev-parse HEAD)

    # Dirty-target self-heal. /tmp/pve-freq-dev on the E2E VM is a
    # disposable dev tree — any uncommitted local edits there are
    # leftovers from the previous run (e.g. mid-test diagnostics or
    # a hot-patch). If we leave them in place, `git pull --ff-only`
    # during the bundle apply aborts with "Your local changes to the
    # following files would be overwritten by merge", and the whole
    # E2E run is blocked. Reset hard + clean so the fast-path becomes
    # deterministic regardless of what state the dev tree was in.
    TARGET_DIRTY=$(ssh -n "${USER}@${TARGET}" "cd ${REMOTE_DIR} && git status --porcelain 2>/dev/null" || echo "")
    if [ -n "$TARGET_DIRTY" ]; then
        echo "[1/4] Target tree dirty — resetting ${REMOTE_DIR} to ${TARGET_HEAD:0:8}"
        echo "$TARGET_DIRTY" | sed 's/^/    /'
        ssh -n "${USER}@${TARGET}" "cd ${REMOTE_DIR} && git reset --hard HEAD && git clean -fd"
    fi

    if [ "$TARGET_HEAD" = "$LOCAL_HEAD" ]; then
        echo "[1/4] Already up to date (${LOCAL_HEAD:0:8}) — skipping bundle"
    else
        # Count commits between target and source. If git log fails (target commit
        # unknown locally), BEHIND=0 and we skip the bundle path to avoid empty bundles.
        BEHIND=0
        if git rev-parse --quiet --verify "${TARGET_HEAD}" >/dev/null 2>&1; then
            BEHIND=$(git log --oneline "${TARGET_HEAD}..HEAD" 2>/dev/null | wc -l)
        fi

        if [ "$BEHIND" -eq 0 ]; then
            echo "[1/4] Target ${TARGET_HEAD:0:8} unknown or equal to source — skipping bundle"
        else
            echo "[1/4] Target at ${TARGET_HEAD:0:8}, source at ${LOCAL_HEAD:0:8} (${BEHIND} commits behind)"

            # Create and apply bundle
            echo "[2/4] Creating bundle..."
            git bundle create "$BUNDLE" "${TARGET_HEAD}..HEAD"
            echo "[3/4] Copying bundle..."
            scp -q "$BUNDLE" "${USER}@${TARGET}:/tmp/"
            echo "[4/4] Applying..."
            ssh -n "${USER}@${TARGET}" "cd ${REMOTE_DIR} && git pull /tmp/pve-freq-deploy-bundle.git HEAD --ff-only"
            rm -f "$BUNDLE"
            ssh -n "${USER}@${TARGET}" "rm -f /tmp/pve-freq-deploy-bundle.git" 2>/dev/null || true
        fi
    fi
fi

# Remove any editable pip install that shadows /opt/pve-freq with /tmp/
# paths. These finders install at site-packages level and override
# freq.__file__ even when PYTHONPATH is set correctly, causing CLI
# surfaces (doctor, init --check) to read the wrong install dir.
echo "[5a/6] Removing editable pip installs (if any)..."
ssh -n "${USER}@${TARGET}" "
for SITE in /usr/local/lib/python3.*/dist-packages /home/*/.local/lib/python3.*/site-packages; do
    if [ -d \"\$SITE\" ]; then
        sudo find \"\$SITE\" -maxdepth 1 -name '__editable__*pve*' -delete 2>/dev/null || true
        sudo find \"\$SITE\" -maxdepth 1 -name '__editable___pve*' -delete 2>/dev/null || true
    fi
done
echo 'Editable shadows cleared'
"

# Sync to runtime install path if it exists
echo "[5/6] Syncing to runtime install..."
ssh -n "${USER}@${TARGET}" "
if [ -d ${RUNTIME_DIR}/freq ]; then
    # Clean stale setuptools build artifacts that could survive rsync
    # and leak contaminated assets into the import path
    sudo rm -rf ${RUNTIME_DIR}/build 2>/dev/null || true
    sudo rsync -a --delete \
        --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
        --exclude='/conf/' --exclude='/data/' --exclude='/tls/' --exclude='/build/' \
        ${REMOTE_DIR}/ ${RUNTIME_DIR}/
    echo 'Runtime synced'

    # Ensure pve-freq.pth exists in every /usr/local/lib/python3.*/dist-packages
    # so plain 'sudo python3 -m freq ...' works on the installed VM without
    # the /usr/local/bin/freq wrapper. install.sh drops this during fresh
    # installs; deploy-test refreshes it on every fast-path so pre-existing
    # VMs (installed before this commit) also get the contract.
    for SITE in /usr/local/lib/python3.*/dist-packages; do
        if [ -d \"\$SITE\" ]; then
            echo '${RUNTIME_DIR}' | sudo tee \"\$SITE/pve-freq.pth\" >/dev/null
        fi
    done
    echo 'pve-freq.pth refreshed'
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
FINAL=$(ssh -n "${USER}@${TARGET}" "cd ${REMOTE_DIR} && git rev-parse --short HEAD 2>/dev/null || echo 'no-git'")
echo ""
echo "=== Done: ${TARGET} now at ${FINAL} ==="
