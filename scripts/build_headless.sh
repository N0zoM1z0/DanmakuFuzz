#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/.." && pwd)"
headless_dir="${repo_root}/third_party/th06-headless"
premake_bin="${PREMAKE5_BIN:-}"

if [[ ! -d "${headless_dir}" ]]; then
  echo "missing submodule: ${headless_dir}" >&2
  echo "run: git submodule update --init --recursive third_party/th06-headless" >&2
  exit 1
fi

if [[ -z "${premake_bin}" ]]; then
  if command -v premake5 >/dev/null 2>&1; then
    premake_bin="$(command -v premake5)"
  elif [[ -x "${repo_root}/tmp/tools/premake5" ]]; then
    premake_bin="${repo_root}/tmp/tools/premake5"
  else
    echo "premake5 is required" >&2
    echo "set PREMAKE5_BIN or place an executable at tmp/tools/premake5" >&2
    exit 1
  fi
fi

(
  cd "${headless_dir}"
  "${premake_bin}" gmake --no-asoundlib
  make -C build config=release -j"${JOBS:-4}"
)
