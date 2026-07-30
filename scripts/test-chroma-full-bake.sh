#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
upstream_bake="$repo_root/upstream/.github/actions/tilt-setup-prebuild/docker-bake.hcl"
override_bake="$repo_root/fixtures/chroma-sccache-bake.override.hcl"
target_override_bake="$repo_root/fixtures/chroma-target-mountcache-bake.override.hcl"
test_root="$(mktemp -d "${TMPDIR:-/tmp}/chroma-full-bake.XXXXXX")"
trap 'rm -rf "$test_root"' EXIT
[[ -f "$upstream_bake" && -f "$override_bake" && -f "$target_override_bake" ]]

rendered_dockerfile="$repo_root/upstream/rust/Dockerfile.sccache"
trap 'rm -rf "$test_root"; rm -f "$rendered_dockerfile"' EXIT
"$repo_root/scripts/render-chroma-sccache-dockerfile.sh" "$rendered_dockerfile"

expected_targets=(
  rust-log-service
  rust-sysdb-service
  sysdb
  sysdb-migration
  rust-sysdb-migration
  rust-frontend-service
  query-service
  compactor-service
  garbage-collector
  load-service
  work-queue-service
  fn-consumer
)
expected_rust_targets=(
  rust-log-service
  rust-sysdb-service
  rust-sysdb-migration
  rust-frontend-service
  query-service
  compactor-service
  garbage-collector
  load-service
  work-queue-service
  fn-consumer
)

printed="$test_root/bake.json"
(
  cd "$repo_root/upstream"
  docker buildx bake --print \
    --file .github/actions/tilt-setup-prebuild/docker-bake.hcl \
    --file ../fixtures/chroma-sccache-bake.override.hcl \
    "${expected_targets[@]}"
) > "$printed"

jq -r '.target | keys[]' "$printed" > "$test_root/actual-targets.txt"
printf '%s\n' "${expected_targets[@]}" | sort > "$test_root/expected-targets.txt"
diff -u "$test_root/expected-targets.txt" "$test_root/actual-targets.txt"

for target in "${expected_rust_targets[@]}"; do
  [[ "$(jq -r --arg target "$target" '.target[$target].dockerfile' "$printed")" == "rust/Dockerfile.sccache" ]]
done
[[ "$(jq -r '.target.sysdb.dockerfile' "$printed")" == "go/Dockerfile" ]]
[[ "$(jq -r '.target["sysdb-migration"].dockerfile' "$printed")" == "go/Dockerfile.migration" ]]

echo "Chroma full Bake target graph is valid."

target_dockerfile="$repo_root/upstream/rust/Dockerfile.target-mountcache"
trap 'rm -rf "$test_root"; rm -f "$rendered_dockerfile" "$target_dockerfile"' EXIT
"$repo_root/scripts/render-chroma-target-mountcache-dockerfile.sh" "$target_dockerfile"
CHROMA_SOURCE_DOCKERFILE="$target_dockerfile" \
  "$repo_root/scripts/render-chroma-sccache-dockerfile.sh" "$rendered_dockerfile"
grep -Fq 'id=chroma-cargo-target' "$rendered_dockerfile"
grep -Fq 'sccache' "$rendered_dockerfile"

target_printed="$test_root/bake-target.json"
(
  cd "$repo_root/upstream"
  docker buildx bake --print \
    --file .github/actions/tilt-setup-prebuild/docker-bake.hcl \
    --file ../fixtures/chroma-target-mountcache-bake.override.hcl \
    "${expected_targets[@]}"
) > "$target_printed"
for target in "${expected_rust_targets[@]}"; do
  [[ "$(jq -r --arg target "$target" '.target[$target].dockerfile' "$target_printed")" == "rust/Dockerfile.target-mountcache" ]]
done

combined_printed="$test_root/bake-target-sccache.json"
(
  cd "$repo_root/upstream"
  docker buildx bake --print \
    --file .github/actions/tilt-setup-prebuild/docker-bake.hcl \
    --file ../fixtures/chroma-target-mountcache-bake.override.hcl \
    --file ../fixtures/chroma-sccache-bake.override.hcl \
    "${expected_targets[@]}"
) > "$combined_printed"
for target in "${expected_rust_targets[@]}"; do
  [[ "$(jq -r --arg target "$target" '.target[$target].dockerfile' "$combined_printed")" == "rust/Dockerfile.sccache" ]]
done

echo "Chroma full Bake target mount graph is valid."
