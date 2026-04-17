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

# Prune stale worktree refs first
if [ "$DRY_RUN" = false ]; then
    git worktree prune 2>/dev/null
fi

# Find merged branches
merged=$(git branch --merged main | grep "claude/" | grep -v "\*")
if [ -n "$merged" ]; then
    count=$(echo "$merged" | wc -l | xargs)
    echo "Found $count merged claude/* branch(es):"
    echo "$merged" | sed 's/^/  /'
    echo ""
    while IFS= read -r branch; do
        branch=$(echo "$branch" | xargs)
        # Check for associated worktree
        worktree_dir=$(git worktree list | grep "\[$branch\]" | awk '{print $1}')
        if [ -n "$worktree_dir" ]; then
            echo "  Worktree for $branch: $worktree_dir"
            if [ "$DRY_RUN" = false ]; then
                git worktree remove --force "$worktree_dir" 2>/dev/null \
                    && echo "    -> Worktree removed." \
                    || echo "    -> Failed to remove worktree (may be active)."
            fi
        fi
        if [ "$DRY_RUN" = false ]; then
            git branch -d "$branch" 2>/dev/null \
                && echo "  -> Deleted branch: $branch" \
                || echo "  -> Could not delete: $branch (still has worktree?)"
        fi
    done <<< "$merged"
else
    echo "No merged claude/* branches found."
fi
echo ""

# Find leftover worktree directories with no matching branch
echo "Checking for orphaned worktree directories..."
orphaned=0
for dir in .claude/worktrees/*/; do
    [ -d "$dir" ] || continue
    branch_name=$(basename "$dir")
    if ! git branch --list "claude/$branch_name" | grep -q .; then
        echo "  Orphaned: $dir"
        if [ "$DRY_RUN" = false ]; then
            rm -rf "$dir"
            echo "    -> Removed."
        fi
        orphaned=$((orphaned + 1))
    fi
done
if [ "$orphaned" -eq 0 ]; then
    echo "  None found."
fi
echo ""

# Summary
if [ "$DRY_RUN" = false ]; then
    branch_count_after=$(git branch --list "claude/*" | wc -l)
    worktree_count_after=$(git worktree list | wc -l)
    echo "After: $branch_count_after claude/* branches, $worktree_count_after worktrees"
else
    echo "[dry-run] Run without --dry-run to apply changes."
fi
