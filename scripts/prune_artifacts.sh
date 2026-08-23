#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
artifacts_dir="$repo_root/artifacts"

dry_run=0
if [[ "${1-}" == "--dry-run" ]]; then
  dry_run=1
elif [[ $# -gt 0 ]]; then
  echo "usage: $0 [--dry-run]" >&2
  exit 2
fi

keep_names=(
  replay-corpus-public
  replay-stage-seed-focus-v1
  replay-coordinated-stage4-borrow-focus-v1
  replay-coordinated-extra-v2
  replay-coordinated-corpus-v2
)

keep_match() {
  local base="$1"
  local item
  for item in "${keep_names[@]}"; do
    if [[ "$base" == "$item" ]]; then
      return 0
    fi
  done
  return 1
}

if [[ ! -d "$artifacts_dir" ]]; then
  echo "missing artifacts directory: $artifacts_dir" >&2
  exit 1
fi

echo "artifact prune mode: $([[ $dry_run -eq 1 ]] && echo dry-run || echo delete)"
echo "keeping:"
printf '  %s\n' "${keep_names[@]}"

shopt -s nullglob
for path in "$artifacts_dir"/*; do
  base=$(basename "$path")
  if keep_match "$base"; then
    echo "keep  $path"
    continue
  fi
  echo "prune $path"
  if [[ $dry_run -eq 0 ]]; then
    rm -rf -- "$path"
  fi
done
shopt -u nullglob

while IFS= read -r pycache_dir; do
  [[ -z "$pycache_dir" ]] && continue
  echo "pycache $pycache_dir"
  if [[ $dry_run -eq 0 ]]; then
    rm -rf -- "$pycache_dir"
  fi
done < <(find "$repo_root" \
  \( -path "$repo_root/.git" -o -path "$artifacts_dir" \) -prune -o \
  -type d -name '__pycache__' -print)

