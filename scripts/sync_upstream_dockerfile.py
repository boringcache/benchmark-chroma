#!/usr/bin/env python3
"""Keep the benchmark Dockerfile equal to upstream plus its sccache block."""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_DOCKERFILE = ROOT / "upstream/rust/Dockerfile"
BENCHMARK_DOCKERFILE = ROOT / "docker/chroma.Dockerfile"
BLOCK_START = "# BEGIN BORINGCACHE BENCHMARK SCCACHE"
BLOCK_END = "# END BORINGCACHE BENCHMARK SCCACHE"
CHEF_STAGE = re.compile(r"^FROM\s+\S+\s+AS\s+chef[ \t]*$", re.IGNORECASE | re.MULTILINE)


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
    if BLOCK_START in upstream or BLOCK_END in upstream:
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
    return upstream[:insertion] + "\n" + sccache_block + "\n" + upstream[insertion:]


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
