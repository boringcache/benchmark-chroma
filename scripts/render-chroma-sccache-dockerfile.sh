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
if [[ "$(grep -Ec '^  cargo chef cook ' "$source_dockerfile")" -ne 1 ]] ||
  [[ "$(grep -Ec '^  cargo build \$\{build_target\} --workspace ' "$source_dockerfile")" -ne 1 ]]; then
  echo "Unsupported Chroma Dockerfile: expected the cargo-chef and workspace compile steps exactly once." >&2
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

rendered_dockerfile="$(mktemp "$(dirname "$output_dockerfile")/chroma-sccache.Dockerfile.XXXXXX")"
trap 'rm -f "$rendered_dockerfile"' EXIT

awk '
  BEGIN { chef_stages = 0 }
  /^FROM rust:[^[:space:]]+ AS chef$/ {
    print
    print ""
    print "# Benchmark-only prerequisite for boringcache docker --tool-cache sccache."
    print "# BoringCache injects the compiler cache configuration at build time."
    print "ARG BORINGCACHE_SCCACHE_VERSION=0.14.0"
    print "ARG BORINGCACHE_SCCACHE_SHA256_AMD64=8424b38cda4ecce616a1557d81328f3d7c96503a171eab79942fad618b42af44"
    print "ARG BORINGCACHE_SCCACHE_SHA256_ARM64=62a6c942c47c93333bc0174704800cef7edfa0416d08e1356c1d3e39f0b462f2"
    print "RUN <<SCCACHE_INSTALL"
    print "set -eux"
    print "case \"$(uname -m)\" in"
    print "  x86_64) sccache_target=x86_64-unknown-linux-musl; sccache_sha256=\"$BORINGCACHE_SCCACHE_SHA256_AMD64\" ;;"
    print "  aarch64) sccache_target=aarch64-unknown-linux-musl; sccache_sha256=\"$BORINGCACHE_SCCACHE_SHA256_ARM64\" ;;"
    print "  *) echo \"Unsupported architecture: $(uname -m)\" >&2; exit 1 ;;"
    print "esac"
    print "sccache_archive=\"sccache-v${BORINGCACHE_SCCACHE_VERSION}-${sccache_target}.tar.gz\""
    print "curl -fsSL \"https://github.com/mozilla/sccache/releases/download/v${BORINGCACHE_SCCACHE_VERSION}/${sccache_archive}\" -o \"/tmp/${sccache_archive}\""
    print "printf \"%s  %s\\n\" \"$sccache_sha256\" \"/tmp/${sccache_archive}\" | sha256sum -c -"
    print "tar -xzf \"/tmp/${sccache_archive}\" -C /tmp"
    print "install -m 0755 \"/tmp/sccache-v${BORINGCACHE_SCCACHE_VERSION}-${sccache_target}/sccache\" /usr/local/bin/sccache"
    print "rm -rf \"/tmp/${sccache_archive}\" \"/tmp/sccache-v${BORINGCACHE_SCCACHE_VERSION}-${sccache_target}\""
    print "sccache --version"
    print "SCCACHE_INSTALL"
    chef_stages += 1
    next
  }
  { print }
  END {
    if (chef_stages != 1) {
      printf "Unsupported Chroma Dockerfile: expected one Rust chef stage, found %d.\n", chef_stages > "/dev/stderr"
      exit 1
    }
  }
' "$source_dockerfile" > "$rendered_dockerfile"

mv "$rendered_dockerfile" "$output_dockerfile"
