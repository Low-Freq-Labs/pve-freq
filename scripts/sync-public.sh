#!/bin/bash
set -euo pipefail

REPO_DIR="/data/projects/pve-freq"
PUBLIC_REMOTE="public"
PUBLIC_BRANCH="main"
PAT_FILE="/etc/freq/credentials/github-pat"
TMP_ROOT="$(mktemp -d /tmp/pve-freq-public-sync.XXXXXX)"
WORKTREE_DIR="$TMP_ROOT/worktree"
EXCLUDE_FILE="$REPO_DIR/scripts/public-exclude.txt"
DRY_RUN=0
PUSH_MODE="--force-with-lease"

die() {
    echo "PUBLIC SYNC BLOCKED: $*" >&2
    exit 1
}

cleanup() {
    if [ -d "$WORKTREE_DIR" ]; then
        git -C "$REPO_DIR" worktree remove --force "$WORKTREE_DIR" >/dev/null 2>&1 || true
    fi
    rm -rf "$TMP_ROOT"
}
trap cleanup EXIT

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run)
            DRY_RUN=1
            ;;
        --force)
            PUSH_MODE="--force"
            ;;
        *)
            die "unknown argument: $1"
            ;;
    esac
    shift
done

cd "$REPO_DIR"

git rev-parse --verify HEAD >/dev/null 2>&1 || die "repo has no HEAD"
git fetch "$PUBLIC_REMOTE" "$PUBLIC_BRANCH" >/dev/null 2>&1 || die "failed to fetch $PUBLIC_REMOTE/$PUBLIC_BRANCH"

git worktree add --detach "$WORKTREE_DIR" HEAD >/dev/null
cd "$WORKTREE_DIR"

[ -f "$EXCLUDE_FILE" ] || die "missing exclude file: $EXCLUDE_FILE"

while IFS= read -r path; do
    [ -z "$path" ] && continue
    if git ls-files --error-unmatch "$path" >/dev/null 2>&1; then
        git rm -q --force "$path"
    elif [ -e "$path" ]; then
        rm -rf "$path"
    fi
done < "$EXCLUDE_FILE"

if git ls-files | rg -n '(^|/)(~freq-ops/|CLAUDE\.md|AGENTS\.md)$' >/dev/null; then
    die "internal agent files remain in public export"
fi

if rg -n "INTERNAL — Not for public distribution" . -g '!**/.git/**' >/dev/null; then
    die "internal-only docs remain in public export"
fi

if git status --short | grep -q .; then
    git config user.name "lowfreqlabs"
    git config user.email "git@lowfreqlabs.com"
    git commit -qam "Sync public repo from dev main"
else
    echo "public export tree unchanged"
fi

echo "Prepared public export at commit:"
git show -s --format='%H %cI %s' HEAD
echo
echo "Public remote head before push:"
git show -s --format='%H %cI %s' "$PUBLIC_REMOTE/$PUBLIC_BRANCH"
echo

if [ "$DRY_RUN" -eq 1 ]; then
    echo "Dry run only. No push performed."
    exit 0
fi

[ -f "$PAT_FILE" ] || die "missing GitHub PAT file: $PAT_FILE"
PAT="$(sudo cat "$PAT_FILE")"
[ -n "$PAT" ] || die "GitHub PAT file is empty"

PUSH_URL="https://lowfreqlabs:${PAT}@github.com/Low-Freq-Labs/pve-freq.git"
git push "$PUSH_MODE" "$PUSH_URL" HEAD:"$PUBLIC_BRANCH"

echo
echo "Public sync complete."
git show -s --format='%H %cI %s' HEAD
