#!/bin/bash
# Manual cleanup of merged claude/* branches and orphaned worktrees.
# Usage: bash scripts/cleanup-branches.sh [--dry-run]

DRY_RUN=false
if [ "$1" = "--dry-run" ]; then
    DRY_RUN=true
    echo "[dry-run] No changes will be made."
fi

echo "=== Branch & Worktree Cleanup ==="
echo ""

# Count before
branch_count=$(git branch --list "claude/*" | wc -l)
worktree_count=$(git worktree list | wc -l)
echo "Before: $branch_count claude/* branches, $worktree_count worktrees"
echo ""

# Find merged branches
merged=$(git branch --merged main | grep "claude/" | grep -v "\\*")
if [ -n "$merged" ]; then
    count=$(echo "$merged" | wc -l)
    echo "Found $count merged claude/* branches:"
    echo "$merged" | sed 's/^/  /'
    if [ "$DRY_RUN" = false ]; then
        echo "$merged" | xargs git branch -d 2>/dev/null
        echo "  -> Deleted."
    fi
else
    echo "No merged claude/* branches found."
fi
echo ""

# Find worktrees with no matching branch
echo "Checking worktree directories..."
orphaned=0
for dir in .claude/worktrees/*/; do
    [ -d "$dir" ] || continue
    branch_name=$(basename "$dir")
    if ! git branch --list "claude/$branch_name" | grep -q .; then
        echo "  Orphaned worktree: $dir"
        if [ "$DRY_RUN" = false ]; then
            rm -rf "$dir"
            echo "    -> Removed."
        fi
        orphaned=$((orphaned + 1))
    fi
done
if [ "$orphaned" -eq 0 ]; then
    echo "  No orphaned worktree directories."
fi
echo ""

# Prune git worktree refs
if [ "$DRY_RUN" = false ]; then
    git worktree prune 2>/dev/null
fi

# Count after
if [ "$DRY_RUN" = false ]; then
    branch_count_after=$(git branch --list "claude/*" | wc -l)
    worktree_count_after=$(git worktree list | wc -l)
    echo "After: $branch_count_after claude/* branches, $worktree_count_after worktrees"
else
    echo "[dry-run] Run without --dry-run to apply changes."
fi
