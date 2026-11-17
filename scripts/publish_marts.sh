#!/usr/bin/env bash
# Publish the exported marts to an orphan branch so a hosted dashboard can read
# them over HTTPS. The branch holds a single commit: data files need no history.
#
# usage: scripts/publish_marts.sh [branch] [remote]
set -euo pipefail

branch="${1:-marts-data}"
remote="${2:-origin}"
repo_root="$(git rev-parse --show-toplevel)"
export_dir="${LVM_DATA_DIR:-$repo_root/data}/export"

shopt -s nullglob
files=("$export_dir"/*.parquet)
if [ "${#files[@]}" -eq 0 ]; then
    echo "no exported marts in $export_dir - run 'lvm export' first" >&2
    exit 1
fi

# A separate, empty worktree on a throwaway orphan branch keeps the main
# checkout (and any later CI step) untouched. Needs git 2.42 or newer.
scratch="$(mktemp -d)"
worktree="$scratch/publish"
tmp_branch="publish-$$"
cleanup() {
    git -C "$repo_root" worktree remove --force "$worktree" 2>/dev/null || true
    git -C "$repo_root" branch -D "$tmp_branch" >/dev/null 2>&1 || true
    rmdir "$scratch" 2>/dev/null || true
}
trap cleanup EXIT

git -C "$repo_root" worktree add --quiet --orphan -b "$tmp_branch" "$worktree"
cp "${files[@]}" "$worktree/"
date -u +"%Y-%m-%dT%H:%M:%SZ" > "$worktree/PUBLISHED_AT"
# The marts are derived from CC BY 4.0 data: the licence requires attribution
# wherever they are published, including this branch.
cat > "$worktree/README.md" <<'NOTICE'
# Published marts

Aggregate tables produced daily by this repository's pipeline and read by the
dashboard. Generated automatically; do not edit.

Data: AB Regitra (https://data.gov.lt/datasets/2812/) and TRANSEKSTA
(https://data.gov.lt/datasets/2721/), via the Lithuanian open data portal,
licensed under Creative Commons Attribution 4.0
(https://creativecommons.org/licenses/by/4.0/). The data has been cleaned,
de-duplicated and aggregated by this project.
NOTICE

git -C "$worktree" add -f -- .
git -C "$worktree" \
    -c user.name="${GIT_AUTHOR_NAME:-github-actions[bot]}" \
    -c user.email="${GIT_AUTHOR_EMAIL:-41898282+github-actions[bot]@users.noreply.github.com}" \
    commit --quiet -m "Publish marts $(date -u +%F)"
git -C "$worktree" push --quiet --force "$remote" "HEAD:refs/heads/$branch"
echo "published ${#files[@]} marts to $remote/$branch"
