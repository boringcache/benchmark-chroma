#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
scenario="${1:-base}"

git -C "${repo_root}/upstream" reset --hard
git -C "${repo_root}/upstream" clean -fdx

case "${scenario}" in
  base)
    ;;
  warm1)
    printf 'Invalidate the Docker source layer without changing Cargo inputs.\n' \
      > "${repo_root}/upstream/rust/.boringcache-warm-source-change"
    ;;
  *)
    echo "Unknown scenario: ${scenario}" >&2
    exit 1
    ;;
esac

git -C "${repo_root}/upstream" status --short
