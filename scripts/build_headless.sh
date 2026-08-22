#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/.." && pwd)"
headless_dir="${repo_root}/third_party/th06-headless"

if [[ ! -d "${headless_dir}" ]]; then
  echo "missing submodule: ${headless_dir}" >&2
  echo "run: git submodule update --init --recursive third_party/th06-headless" >&2
  exit 1
fi

if ! command -v premake5 >/dev/null 2>&1; then
  echo "premake5 is required" >&2
  exit 1
fi

(
  cd "${headless_dir}"
  premake5 gmake --no-asoundlib
  make -C build config=release -j"${JOBS:-4}"
)
