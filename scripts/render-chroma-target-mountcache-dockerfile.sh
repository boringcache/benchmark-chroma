#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source_dockerfile="${CHROMA_SOURCE_DOCKERFILE:-${repo_root}/upstream/rust/Dockerfile}"
output_dockerfile="${1:-}"

if [[ -z "$output_dockerfile" ]]; then
  echo "Usage: $0 OUTPUT_DOCKERFILE" >&2
  exit 2
fi
if [[ ! -f "$source_dockerfile" ]]; then
  echo "Chroma source Dockerfile does not exist: ${source_dockerfile}" >&2
  exit 2
fi
if [[ "$(grep -Ec '^FROM chef AS builder$' "$source_dockerfile")" -ne 1 ]] ||
  [[ "$(grep -Ec '^  cargo chef cook .*--recipe-path recipe.json$' "$source_dockerfile")" -ne 1 ]] ||
  [[ "$(grep -Ec '^  cargo build \$\{build_target\} --workspace ' "$source_dockerfile")" -ne 1 ]]; then
  echo "Unsupported Chroma Dockerfile: expected one builder, cargo-chef cook, and workspace build." >&2
  exit 1
fi

output_dir="$(dirname "$output_dockerfile")"
mkdir -p "$output_dir"
source_dockerfile="$(cd "$(dirname "$source_dockerfile")" && pwd)/$(basename "$source_dockerfile")"
output_dockerfile="$(cd "$output_dir" && pwd)/$(basename "$output_dockerfile")"
if [[ "$output_dockerfile" == "$source_dockerfile" ]]; then
  echo "Generated Dockerfile must not replace Chroma's source Dockerfile." >&2
  exit 2
fi

rendered_dockerfile="$(mktemp "$(dirname "$output_dockerfile")/chroma-target-mountcache.Dockerfile.XXXXXX")"
trap 'rm -f "$rendered_dockerfile"' EXIT

awk '
  BEGIN { dependency_stage = 0; build_mount = 0; cooked = 0; injecting_build = 0; skip_shadow_comment = 0 }
  /^FROM chef AS builder$/ {
    print "FROM chef AS dependency-builder"
    dependency_stage += 1
    next
  }
  /^  cargo chef cook .*--recipe-path recipe.json$/ {
    print
    print ""
    print "# Keep cargo-chef output in an ordinary layer so the cache mount starts empty for hydration."
    print "RUN mv /chroma/target /chroma/target-dependency-seed"
    print ""
    print "# Benchmark option: preserve first-party Cargo state with an empty-cache fallback."
    print "FROM dependency-builder AS builder"
    cooked = 1
    next
  }
  cooked && /^# No `--mount=type=cache` on \.\/target here:/ {
    print "# Seed only after hydration so a remote mount can win over the cargo-chef fallback."
    skip_shadow_comment = 1
    next
  }
  skip_shadow_comment {
    skip_shadow_comment = 0
    next
  }
  cooked && /^RUN --mount=type=cache,sharing=locked,target=\/usr\/local\/cargo\/registry\// {
    print "RUN --mount=type=cache,id=chroma-cargo-target,sharing=locked,target=/chroma/target \\"
    sub(/^RUN /, "  ")
    print
    injecting_build = 1
    next
  }
  injecting_build && /^  --mount=type=cache,/ {
    print
    next
  }
  injecting_build {
    print "  if [ -z \"$(find /chroma/target -mindepth 1 -maxdepth 1 -print -quit)\" ]; then \\"
    print "    cp -a /chroma/target-dependency-seed/. /chroma/target/; \\"
    print "  fi && \\"
    print
    build_mount += 1
    cooked = 0
    injecting_build = 0
    next
  }
  { print }
  END {
    if (dependency_stage != 1 || build_mount != 1 || injecting_build != 0) {
      printf "Unsupported Chroma Dockerfile: rendered %d dependency stages and %d target mounts.\n", dependency_stage, build_mount > "/dev/stderr"
      exit 1
    }
  }
' "$source_dockerfile" > "$rendered_dockerfile"

mv "$rendered_dockerfile" "$output_dockerfile"
