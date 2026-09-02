#!/usr/bin/env python3
"""Keep the benchmark Dockerfile aligned with upstream plus Cargo cache support."""

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
CARGO_CACHE_START = "# BEGIN BORINGCACHE BENCHMARK CARGO CACHE MOUNTS"
CARGO_CACHE_END = "# END BORINGCACHE BENCHMARK CARGO CACHE MOUNTS"
CHEF_STAGE = re.compile(
    r"^(FROM\s+\S+\s+AS\s+)chef[ \t]*$", re.IGNORECASE | re.MULTILINE
)
WORKSPACE_SECTION = "# --- Workspace compile"
WORKSPACE_BUILD = "cargo build ${build_target} --workspace"
UPSTREAM_BASE_HEADER = """# ============================================================================
# chef: shared toolchain base (rust + protoc + cargo-chef).
#
# This is the slow-changing setup layer. It is shared by the `planner` and
# `builder` stages below so the toolchain/protoc install is built and cached
# once, regardless of source changes.
# ============================================================================"""
BENCHMARK_BASE_HEADER = """# ============================================================================
# build-tools: shared Rust, protoc, and sccache toolchain.
#
# This slow-changing setup stage is inherited by the builder. Cargo downloads
# and compiled output are persisted independently with BuildKit cache mounts.
# ============================================================================"""
UPSTREAM_CARGO_CHEF_INSTALL = r"""# cargo-chef lets us cache the dependency compile as a content-addressed image
# LAYER (keyed on the dependency graph) instead of leaving it in a volatile
# `--mount=type=cache` directory that is wiped on a cold/contended builder.
RUN --mount=type=cache,sharing=locked,target=/usr/local/cargo/registry/ \
  cargo install cargo-chef --locked

"""
UPSTREAM_PLANNER = """# ============================================================================
# planner: emit recipe.json (the dependency graph only).
#
# This stage is cheap. Its only purpose is to produce a `recipe.json` that
# changes ONLY when dependencies change (Cargo.toml / Cargo.lock), giving the
# `builder` stage a stable cache key for the dependency compile.
# ============================================================================
FROM chef AS planner

COPY idl/ idl/
COPY Cargo.toml Cargo.toml
COPY Cargo.lock Cargo.lock
COPY rust/ rust/

RUN cargo chef prepare --recipe-path recipe.json

"""
UPSTREAM_BUILDER_HEADER = """# ============================================================================
# builder: cook dependencies into a durable layer, then build the workspace.
#
# `cargo chef cook` compiles ONLY third-party dependencies, writing them to
# ./target. Because this step's only input is recipe.json (and we do NOT mount
# a cache over ./target), its result is captured as a regular image layer:
#   * content-addressed on recipe.json -> reused on every build whose deps are
#     unchanged (the common case: app-only source change),
#   * never thrashed cross-arch (each arch builds its own layer),
#   * exportable to a registry (a `--mount=type=cache` dir can never be).
#
# The subsequent `cargo build` then compiles only the first-party workspace
# crates, reusing the cooked dependencies already present in ./target.
# ============================================================================
FROM chef AS builder"""
BENCHMARK_BUILDER_HEADER = f"""# ============================================================================
# builder: compile Chroma with persistent Cargo and compiler caches.
# ============================================================================
FROM build-tools AS builder

{CARGO_CACHE_START}
ARG TARGETARCH
{PROOF_START}
ARG BORINGCACHE_BENCHMARK_SCCACHE_PROOF=0
{PROOF_END}
{CARGO_CACHE_END}"""
UPSTREAM_COOK = r"""# Packages whose bins we ship in images. Used for `cargo chef cook -p ...`
# because cook does not support `--exclude` (LukeMathWalker/cargo-chef#181);
# cooking the full workspace would also pull in pyo3/napi build deps.
ENV COOK_PACKAGES="chroma-cli garbage_collector chroma-load chroma-log-service s3heap-service worker rust-sysdb spanner-migrations"

# --- Dependency compile (durable layer, keyed on recipe.json) ----------------
# Note: cache mounts are kept ONLY for the crate download dirs (registry/git);
# the compiled output in ./target is intentionally a layer, not a mount, which
# is what makes cargo-chef effective.
COPY --from=planner /chroma/recipe.json recipe.json
RUN --mount=type=cache,sharing=locked,target=/usr/local/cargo/registry/ \
  --mount=type=cache,sharing=locked,target=/usr/local/cargo/git/ \
  if [ "$ENABLE_AVX512" = "1" ]; then \
  export CXXFLAGS="-mavx512f -mavx512dq -mavx512bw -mavx512vl" && \
  export CFLAGS="-mavx512f -mavx512dq -mavx512bw -mavx512vl" && \
  export RUSTFLAGS="${RUSTFLAGS} -C target-feature=+avx,+fma" ; \
  fi && \
  build_target=$( [ "${ADDRESS_SANITIZER}" = "1" ] && echo '--target x86_64-unknown-linux-gnu' || echo '' ) && \
  release_flag=$( [ "$RELEASE_MODE" = "1" ] && echo '--release' || echo '' ) && \
  cargo chef cook ${build_target} $(printf -- '-p %s ' $COOK_PACKAGES) ${release_flag} --recipe-path recipe.json

"""
UPSTREAM_WORKSPACE_TARGET_NOTE = """# No `--mount=type=cache` on ./target here: the cooked dependencies live in the
# layer produced above, and mounting a cache over ./target would shadow them."""
CARGO_CACHE_NOTE = f"""{CARGO_CACHE_START}
# BoringCache persists Cargo's registry, Git checkouts, and target output across
# ephemeral builders. Target output is architecture-scoped to prevent mixing it.
{CARGO_CACHE_END}"""
UPSTREAM_CARGO_MOUNTS = (
    r"""RUN --mount=type=cache,sharing=locked,target=/usr/local/cargo/registry/ \
  --mount=type=cache,sharing=locked,target=/usr/local/cargo/git/ """
    + "\\"
)
BENCHMARK_CARGO_MOUNTS = (
    r"""RUN --mount=type=cache,id=chroma-target-${TARGETARCH},sharing=locked,target=/chroma/target \
  --mount=type=cache,sharing=locked,target=/usr/local/cargo/registry/ \
  --mount=type=cache,sharing=locked,target=/usr/local/cargo/git/ """
    + "\\"
)
PROOF_COMMAND = r"""  done && \
  if [ "${BORINGCACHE_BENCHMARK_SCCACHE_PROOF}" = "1" ]; then \
  test "${RUSTC_WRAPPER##*/}" = "sccache" && \
  test -n "${SCCACHE_WEBDAV_ENDPOINT:-}" && \
  test -n "$(find /chroma/target -mindepth 1 -print -quit)" && \
  printf 'BORINGCACHE_CARGO_TARGET_READY=1\n' && \
  sccache_stats="$(sccache --show-stats --stats-format=json)" && \
  printf 'BORINGCACHE_SCCACHE_STATS=%s\n' "${sccache_stats}"; \
  fi"""


class DockerfileSyncError(RuntimeError):
    pass


def replace_exactly(contents: str, old: str, new: str, description: str) -> str:
    if contents.count(old) != 1:
        raise DockerfileSyncError(f"upstream Dockerfile {description} changed")
    return contents.replace(old, new, 1)


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
        CARGO_CACHE_START,
        CARGO_CACHE_END,
    )
    if any(marker in upstream for marker in benchmark_markers):
        raise DockerfileSyncError(
            "upstream Dockerfile unexpectedly contains benchmark markers"
        )

    rendered = replace_exactly(
        upstream, UPSTREAM_BASE_HEADER, BENCHMARK_BASE_HEADER, "base header"
    )

    stages = list(CHEF_STAGE.finditer(rendered))
    if len(stages) != 1:
        raise DockerfileSyncError(
            "upstream Dockerfile must contain exactly one chef stage"
        )
    stage = stages[0]
    rendered = (
        rendered[: stage.start()]
        + stage.group(1)
        + "build-tools"
        + rendered[stage.end() :]
    )
    line_end = rendered.find("\n", stage.start())
    insertion = len(rendered) if line_end == -1 else line_end + 1
    rendered = rendered[:insertion] + "\n" + sccache_block + "\n" + rendered[insertion:]

    rendered = replace_exactly(
        rendered, UPSTREAM_CARGO_CHEF_INSTALL, "", "Cargo Chef install"
    )
    rendered = replace_exactly(rendered, UPSTREAM_PLANNER, "", "planner stage")
    rendered = replace_exactly(
        rendered,
        UPSTREAM_BUILDER_HEADER,
        BENCHMARK_BUILDER_HEADER,
        "builder header",
    )
    rendered = replace_exactly(rendered, UPSTREAM_COOK, "", "Cargo Chef cook")
    rendered = replace_exactly(
        rendered,
        UPSTREAM_WORKSPACE_TARGET_NOTE,
        CARGO_CACHE_NOTE,
        "workspace target-cache note",
    )
    rendered = replace_exactly(
        rendered,
        UPSTREAM_CARGO_MOUNTS,
        BENCHMARK_CARGO_MOUNTS,
        "workspace Cargo mounts",
    )

    if rendered.count(WORKSPACE_SECTION) != 1:
        raise DockerfileSyncError(
            "upstream Dockerfile must contain exactly one workspace compile section"
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
    rendered = rendered[: run_start + 1] + run_block + rendered[next_stage:]

    removed_fragments = (
        "cargo-chef",
        "cargo chef",
        "recipe.json",
        "COOK_PACKAGES",
        "FROM chef",
        "FROM cooked",
        "cargo-chef-target",
        "BORINGCACHE_TARGET_CACHE_SOURCE",
    )
    for fragment in removed_fragments:
        if fragment in rendered:
            raise DockerfileSyncError(
                f"removed Cargo Chef fragment remains in benchmark: {fragment}"
            )
    return rendered


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
