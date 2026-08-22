#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 /path/to/extracted/th06" >&2
  exit 1
fi

source_dir="$(cd -- "$1" && pwd)"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/.." && pwd)"
dest_dir="${repo_root}/reference/retail/game/th06"

if [[ ! -d "${source_dir}" ]]; then
  echo "source directory does not exist: ${source_dir}" >&2
  exit 1
fi

if [[ -e "${dest_dir}" ]]; then
  echo "destination already exists: ${dest_dir}" >&2
  echo "remove it manually if you want to rebuild the isolated copy" >&2
  exit 1
fi

mkdir -p "${dest_dir}"
cp -a "${source_dir}/." "${dest_dir}/"
echo "isolated game directory ready at ${dest_dir}"
