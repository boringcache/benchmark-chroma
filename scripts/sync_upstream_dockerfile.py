#!/usr/bin/env python3
"""Keep the benchmark Dockerfile equal to upstream plus its sccache proof."""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_DOCKERFILE = ROOT / "upstream/rust/Dockerfile"
BENCHMARK_DOCKERFILE = ROOT / "docker/chroma.Dockerfile"
BLOCK_START = "# BEGIN BORINGCACHE BENCHMARK SCCACHE"
BLOCK_END = "# END BORINGCACHE BENCHMARK SCCACHE"
PROOF_START = "# BEGIN BORINGCACHE BENCHMARK COMPILER CACHE PROOF"
PROOF_END = "# END BORINGCACHE BENCHMARK COMPILER CACHE PROOF"
CHEF_STAGE = re.compile(r"^FROM\s+\S+\s+AS\s+chef[ \t]*$", re.IGNORECASE | re.MULTILINE)
BUILDER_STAGE = re.compile(
    r"^FROM\s+chef\s+AS\s+builder[ \t]*$", re.IGNORECASE | re.MULTILINE
)
WORKSPACE_BUILD = "cargo build ${build_target} --workspace"
PROOF_ARG_BLOCK = (
    f"{PROOF_START}\nARG BORINGCACHE_BENCHMARK_SCCACHE_PROOF=0\n{PROOF_END}"
)
PROOF_COMMAND = """  done && \\
  if [ "${BORINGCACHE_BENCHMARK_SCCACHE_PROOF}" = "1" ]; then \\
  test "${RUSTC_WRAPPER##*/}" = "sccache" && \\
  test -n "${SCCACHE_WEBDAV_ENDPOINT:-}" && \\
  sccache_stats="$(sccache --show-stats --stats-format=json)" && \\
  printf 'BORINGCACHE_SCCACHE_STATS=%s\\n' "${sccache_stats}" && \\
  printf '%s\\n' "${sccache_stats}" | grep -Eq '"cache_(hits|misses)":\\{"counts":\\{[^}]*"Rust":[1-9][0-9]*'; \\
  fi"""


class DockerfileSyncError(RuntimeError):
    pass


def extract_sccache_block(contents: str) -> str:
    if contents.count(BLOCK_START) != 1 or contents.count(BLOCK_END) != 1:
        raise DockerfileSyncError(
            "benchmark Dockerfile must contain exactly one sccache block"
        )

    start = contents.index(BLOCK_START)
    end = contents.index(BLOCK_END, start) + len(BLOCK_END)
    return contents[start:end]


def render_benchmark_dockerfile(upstream: str, sccache_block: str) -> str:
    if any(
        marker in upstream
        for marker in (BLOCK_START, BLOCK_END, PROOF_START, PROOF_END)
    ):
        raise DockerfileSyncError(
            "upstream Dockerfile unexpectedly contains benchmark markers"
        )

    stages = list(CHEF_STAGE.finditer(upstream))
    if len(stages) != 1:
        raise DockerfileSyncError(
            "upstream Dockerfile must contain exactly one chef stage"
        )

    line_end = upstream.find("\n", stages[0].end())
    insertion = len(upstream) if line_end == -1 else line_end + 1
    rendered = upstream[:insertion] + "\n" + sccache_block + "\n" + upstream[insertion:]

    builder_stages = list(BUILDER_STAGE.finditer(rendered))
    if len(builder_stages) != 1:
        raise DockerfileSyncError(
            "upstream Dockerfile must contain exactly one builder stage"
        )
    line_end = rendered.find("\n", builder_stages[0].end())
    insertion = len(rendered) if line_end == -1 else line_end + 1
    rendered = (
        rendered[:insertion] + "\n" + PROOF_ARG_BLOCK + "\n" + rendered[insertion:]
    )

    if rendered.count(WORKSPACE_BUILD) != 1:
        raise DockerfileSyncError(
            "upstream Dockerfile must contain exactly one workspace Cargo build"
        )
    workspace_build = rendered.index(WORKSPACE_BUILD)
    run_start = rendered.rfind("\nRUN ", 0, workspace_build)
    next_stage = rendered.find("\n\nFROM ", workspace_build)
    if run_start == -1 or next_stage == -1:
        raise DockerfileSyncError("could not isolate the upstream workspace build RUN")

    run_block = rendered[run_start + 1 : next_stage]
    loop_end = "  done"
    if not run_block.endswith(loop_end) or run_block.count("\n" + loop_end) != 1:
        raise DockerfileSyncError(
            "upstream workspace build must end with exactly one binary copy loop"
        )
    run_block = run_block[: -len(loop_end)] + PROOF_COMMAND
    return rendered[: run_start + 1] + run_block + rendered[next_stage:]


def expected_copy() -> str:
    current = BENCHMARK_DOCKERFILE.read_text()
    upstream = UPSTREAM_DOCKERFILE.read_text()
    return render_benchmark_dockerfile(upstream, extract_sccache_block(current))


def update_copy() -> None:
    expected = expected_copy()
    if BENCHMARK_DOCKERFILE.read_text() != expected:
        BENCHMARK_DOCKERFILE.write_text(expected)


def verify_copy() -> str:
    current = BENCHMARK_DOCKERFILE.read_text()
    if current != expected_copy():
        raise DockerfileSyncError(
            "benchmark Dockerfile drifted from upstream; run "
            "python3 scripts/sync_upstream_dockerfile.py --update and review the result"
        )
    return current


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update",
        action="store_true",
        help="merge the current upstream Dockerfile into the benchmark copy",
    )
    args = parser.parse_args()

    try:
        if args.update:
            update_copy()
        verify_copy()
    except (DockerfileSyncError, OSError) as error:
        print(f"Chroma Dockerfile sync failed: {error}", file=sys.stderr)
        return 1

    action = "Updated" if args.update else "Verified"
    print(
        f"{action} benchmark Dockerfile against {UPSTREAM_DOCKERFILE.relative_to(ROOT)}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
