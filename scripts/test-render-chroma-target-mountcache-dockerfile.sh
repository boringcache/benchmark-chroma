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
[[ "$(grep -Fc 'mv /chroma/target /chroma/target-dependency-seed' "$rendered")" -eq 1 ]]
[[ "$(grep -Fc 'id=chroma-cargo-target' "$rendered")" -eq 1 ]]
[[ "$(grep -Fc 'sharing=locked,target=/chroma/target' "$rendered")" -eq 1 ]]
[[ "$(grep -Fc 'cp -a /chroma/target-dependency-seed/. /chroma/target/' "$rendered")" -eq 1 ]]
if grep -Fq 'from=dependency-builder' "$rendered"; then
  echo "Rendered cache mount must be empty before the offloader hydrates it." >&2
  exit 1
fi
[[ "$(grep -Ec '^  cargo chef cook .*--recipe-path recipe.json$' "$rendered")" -eq 1 ]]
[[ "$(grep -Ec '^  cargo build \$\{build_target\} --workspace ' "$rendered")" -eq 1 ]]

target_mount_line="$(grep -nF 'id=chroma-cargo-target' "$rendered" | cut -d: -f1)"
registry_mount_line="$(grep -nF 'target=/usr/local/cargo/registry/' "$rendered" | tail -1 | cut -d: -f1)"
git_mount_line="$(grep -nF 'target=/usr/local/cargo/git/' "$rendered" | tail -1 | cut -d: -f1)"
fallback_line="$(grep -nF 'cp -a /chroma/target-dependency-seed/. /chroma/target/' "$rendered" | cut -d: -f1)"
if ! ((target_mount_line < registry_mount_line && registry_mount_line < git_mount_line && git_mount_line < fallback_line)); then
  echo "Rendered fallback must follow the complete BuildKit mount preamble." >&2
  exit 1
fi

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
