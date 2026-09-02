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
TARGET_STAGE_START = "# BEGIN BORINGCACHE BENCHMARK TARGET CACHE STAGE"
TARGET_STAGE_END = "# END BORINGCACHE BENCHMARK TARGET CACHE STAGE"
TARGET_MOUNT_START = "# BEGIN BORINGCACHE BENCHMARK PERSISTENT TARGET CACHE"
TARGET_MOUNT_END = "# END BORINGCACHE BENCHMARK PERSISTENT TARGET CACHE"
CHEF_STAGE = re.compile(r"^FROM\s+\S+\s+AS\s+chef[ \t]*$", re.IGNORECASE | re.MULTILINE)
BUILDER_STAGE = re.compile(
    r"^FROM\s+chef\s+AS\s+builder[ \t]*$", re.IGNORECASE | re.MULTILINE
)
WORKSPACE_SECTION = "# --- Workspace compile"
COOK_BUILD = re.compile(r"^(?:RUN |  )cargo chef cook\b[^\n]*$", re.MULTILINE)
WORKSPACE_BUILD = "cargo build ${build_target} --workspace"
UPSTREAM_WORKSPACE_TARGET_NOTE = """# No `--mount=type=cache` on ./target here: the cooked dependencies live in the
# layer produced above, and mounting a cache over ./target would shadow them."""
TARGET_STAGE_BLOCK = f"""{TARGET_STAGE_START}
# Keep Cargo Chef's dependency output as an ordinary OCI fallback. The cook
# step moves it aside so the workspace target mount starts empty for hydration.
FROM cooked AS builder
ARG TARGETARCH
{TARGET_STAGE_END}"""
TARGET_MOUNT_NOTE = f"""{TARGET_MOUNT_START}
# BoringCache hydrates the empty target mount before this RUN starts. When no
# remote target exists, the command seeds it from Cargo Chef's durable fallback.
{TARGET_MOUNT_END}"""
TARGET_CACHE_MOUNT = "--mount=type=cache,id=chroma-target-${TARGETARCH},sharing=locked,target=/chroma/target"
TARGET_CACHE_SEED = """  if [ -z "$(find /chroma/target -mindepth 1 -print -quit)" ]; then \\
  target_cache_source=fallback && \\
  cp -a /chroma/cargo-chef-target/. /chroma/target/; \\
  else \\
  target_cache_source=persistent; \\
  fi && \\"""
WORKSPACE_SETUP = """  if [ "$ENABLE_AVX512" = "1" ]; then \\"""
PROOF_ARG_BLOCK = (
    f"{PROOF_START}\nARG BORINGCACHE_BENCHMARK_SCCACHE_PROOF=0\n{PROOF_END}"
)
PROOF_COMMAND = """  done && \\
  printf 'BORINGCACHE_TARGET_CACHE_SOURCE=%s\\n' "${target_cache_source}" && \\
  if [ "${BORINGCACHE_BENCHMARK_SCCACHE_PROOF}" = "1" ]; then \\
  test "${RUSTC_WRAPPER##*/}" = "sccache" && \\
  test -n "${SCCACHE_WEBDAV_ENDPOINT:-}" && \\
  sccache_stats="$(sccache --show-stats --stats-format=json)" && \\
  printf 'BORINGCACHE_SCCACHE_STATS=%s\\n' "${sccache_stats}" && \\
  if [ "${target_cache_source}" = "fallback" ]; then \\
  printf '%s\\n' "${sccache_stats}" | grep -Eq '"cache_(hits|misses)":\\{"counts":\\{[^}]*"Rust":[1-9][0-9]*'; \\
  fi; \\
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
    benchmark_markers = (
        BLOCK_START,
        BLOCK_END,
        PROOF_START,
        PROOF_END,
        TARGET_STAGE_START,
        TARGET_STAGE_END,
        TARGET_MOUNT_START,
        TARGET_MOUNT_END,
    )
    if any(marker in upstream for marker in benchmark_markers):
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
    builder_stage = builder_stages[0]
    rendered = (
        rendered[: builder_stage.start()]
        + "FROM chef AS cooked"
        + rendered[builder_stage.end() :]
    )

    cook_builds = list(COOK_BUILD.finditer(rendered))
    if len(cook_builds) != 1:
        raise DockerfileSyncError(
            "upstream Dockerfile must contain exactly one Cargo Chef cook"
        )
    cook_build = cook_builds[0]
    if cook_build.group().endswith("\\"):
        raise DockerfileSyncError("upstream Cargo Chef cook command shape changed")
    rendered = (
        rendered[: cook_build.end()]
        + " && \\\n  mv /chroma/target /chroma/cargo-chef-target"
        + rendered[cook_build.end() :]
    )

    if rendered.count(WORKSPACE_SECTION) != 1:
        raise DockerfileSyncError(
            "upstream Dockerfile must contain exactly one workspace compile section"
        )
    workspace_section = rendered.index(WORKSPACE_SECTION)
    rendered = (
        rendered[:workspace_section]
        + TARGET_STAGE_BLOCK
        + "\n\n"
        + PROOF_ARG_BLOCK
        + "\n\n"
        + rendered[workspace_section:]
    )

    if rendered.count(UPSTREAM_WORKSPACE_TARGET_NOTE) != 1:
        raise DockerfileSyncError(
            "upstream Dockerfile workspace target-cache note changed"
        )
    rendered = rendered.replace(
        UPSTREAM_WORKSPACE_TARGET_NOTE, TARGET_MOUNT_NOTE, 1
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
    if not run_block.startswith("RUN --mount="):
        raise DockerfileSyncError(
            "upstream workspace build must begin with BuildKit cache mounts"
        )
    run_block = run_block.replace(
        "RUN ", f"RUN {TARGET_CACHE_MOUNT} \\\n  ", 1
    )
    if run_block.count(WORKSPACE_SETUP) != 1:
        raise DockerfileSyncError("upstream workspace setup command changed")
    run_block = run_block.replace(
        WORKSPACE_SETUP, TARGET_CACHE_SEED + "\n" + WORKSPACE_SETUP, 1
    )
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
