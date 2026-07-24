#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
renderer="$repo_root/scripts/render-chroma-sccache-dockerfile.sh"
test_root="$(mktemp -d "${TMPDIR:-/tmp}/chroma-sccache-render.XXXXXX")"
trap 'rm -rf "$test_root"' EXIT

rendered="$test_root/chroma-sccache.Dockerfile"
"$renderer" "$rendered"

[[ "$(grep -Fc 'Benchmark-only prerequisite for boringcache docker --tool-cache sccache.' "$rendered")" -eq 1 ]]
[[ "$(grep -Fc 'sccache --version' "$rendered")" -eq 1 ]]
[[ "$(grep -Ec '^  cargo chef cook ' "$rendered")" -eq 1 ]]
[[ "$(grep -Ec '^  cargo build \$\{build_target\} --workspace ' "$rendered")" -eq 1 ]]

unsupported_source="$test_root/unsupported.Dockerfile"
sed 's/ AS chef$/ AS builder-base/' "$repo_root/upstream/rust/Dockerfile" > "$unsupported_source"
if CHROMA_SOURCE_DOCKERFILE="$unsupported_source" "$renderer" "$test_root/unsupported-rendered.Dockerfile" >/dev/null 2>&1; then
  echo "Expected an unsupported upstream Dockerfile to fail closed." >&2
  exit 1
fi

echo "Chroma sccache Dockerfile rendering is valid."
