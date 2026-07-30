#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
renderer="$repo_root/scripts/render-chroma-target-mountcache-dockerfile.sh"
test_root="$(mktemp -d "${TMPDIR:-/tmp}/chroma-target-mountcache.XXXXXX")"
trap 'rm -rf "$test_root"' EXIT

rendered="$test_root/Dockerfile"
"$renderer" "$rendered"

[[ "$(grep -Fc 'FROM chef AS dependency-builder' "$rendered")" -eq 1 ]]
[[ "$(grep -Fc 'FROM dependency-builder AS builder' "$rendered")" -eq 1 ]]
[[ "$(grep -Fc 'id=chroma-cargo-target' "$rendered")" -eq 1 ]]
[[ "$(grep -Fc 'from=dependency-builder,source=/chroma/target,target=/chroma/target' "$rendered")" -eq 1 ]]
[[ "$(grep -Ec '^  cargo chef cook .*--recipe-path recipe.json$' "$rendered")" -eq 1 ]]
[[ "$(grep -Ec '^  cargo build \$\{build_target\} --workspace ' "$rendered")" -eq 1 ]]
source_only_explanation="No \`--mount=type=cache\` on ./target here"
if grep -Fq "$source_only_explanation" "$rendered"; then
  echo "Rendered Dockerfile retained the source-only no-mount explanation." >&2
  exit 1
fi

unsupported_source="$test_root/unsupported.Dockerfile"
sed 's/FROM chef AS builder/FROM chef AS compile/' "$repo_root/upstream/rust/Dockerfile" > "$unsupported_source"
if CHROMA_SOURCE_DOCKERFILE="$unsupported_source" "$renderer" "$test_root/unsupported-rendered.Dockerfile" >/dev/null 2>&1; then
  echo "Expected an unsupported upstream Dockerfile to fail closed." >&2
  exit 1
fi

echo "Chroma target mountcache Dockerfile rendering is valid."
