#!/usr/bin/env python3
"""Verify Chroma's amd64 release-container benchmark plan."""

import sys
from pathlib import Path

import tomllib
from sync_upstream_dockerfile import DockerfileSyncError, verify_copy

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = [
    "docker",
    "buildx",
    "build",
    "--file",
    "docker/chroma.Dockerfile",
    "--target",
    "cli",
    "--platform",
    "linux/amd64",
    "--build-arg",
    "RELEASE_MODE=1",
    "--build-arg",
    "BORINGCACHE_BENCHMARK_SCCACHE_PROOF=1",
    "--tag",
    "chroma-benchmark:local",
    "upstream",
]


def require(value: bool, message: str) -> None:
    if not value:
        raise RuntimeError(message)


def main() -> int:
    try:
        plan = tomllib.loads((ROOT / ".boringcache.toml").read_text())
        require(
            plan["adapters"]["docker"]["command"] == EXPECTED, "Docker plan changed"
        )
        require(
            plan["adapters"]["sccache"]["tag"] == "chroma-sccache-local",
            "sccache cache tag changed",
        )
        dockerfile = verify_copy()
        for fragment in (
            "ARG SCCACHE_VERSION=0.17.0",
            "67c4a96dd237c1f518f6b36083f270f9976d516f1e57fce891755ea782e50006",
            "821a86343191aa1cbab74bd42f9e93c9a63bf85e4742945f40d3ae84193c1c77",
            "sha256sum --check --strict",
            "sccache --version",
            "ARG BORINGCACHE_BENCHMARK_SCCACHE_PROOF=0",
            "sccache --show-stats --stats-format=json",
            "FROM rust:1.92.0 AS build-tools",
            "FROM build-tools AS builder",
            "id=chroma-target-${TARGETARCH}",
            "sharing=locked,target=/chroma/target",
            'find /chroma/target -mindepth 1 -print -quit',
            "BORINGCACHE_CARGO_TARGET_READY=1",
            "target=/usr/local/cargo/registry/",
            "target=/usr/local/cargo/git/",
            "ENV CARGO_INCREMENTAL=0",
        ):
            require(fragment in dockerfile, f"benchmark Dockerfile changed: {fragment}")
        require(
            dockerfile.count("target=/chroma/target") == 1,
            "benchmark Dockerfile must have one persistent Cargo target mount",
        )
        require(
            dockerfile.count("target=/usr/local/cargo/registry/") == 1,
            "benchmark Dockerfile must have one persistent Cargo registry mount",
        )
        require(
            dockerfile.count("target=/usr/local/cargo/git/") == 1,
            "benchmark Dockerfile must have one persistent Cargo Git mount",
        )
        require(
            dockerfile.count("cargo build ${build_target} --workspace") == 1,
            "benchmark Dockerfile must have one workspace Cargo build",
        )
        for removed in (
            "cargo-chef",
            "cargo chef",
            "recipe.json",
            "COOK_PACKAGES",
            "FROM chef",
            "FROM cooked",
            "cargo-chef-target",
            "BORINGCACHE_TARGET_CACHE_SOURCE",
        ):
            require(removed not in dockerfile, f"removed Cargo Chef shape remains: {removed}")
        require(
            dockerfile.index("FROM build-tools AS builder")
            < dockerfile.index("target=/chroma/target")
            < dockerfile.index("target=/usr/local/cargo/registry/")
            < dockerfile.index("target=/usr/local/cargo/git/")
            < dockerfile.index("cargo build ${build_target} --workspace"),
            "persistent Cargo mount order changed",
        )
        require(
            dockerfile.index("# END BORINGCACHE BENCHMARK SCCACHE")
            < dockerfile.index("FROM build-tools AS builder"),
            "sccache must remain in Chroma's build toolchain stages",
        )
        upstream = (
            ROOT / "upstream/.github/workflows/_build_release_container.yml"
        ).read_text()
        for fragment in (
            "platform: [amd64, arm64]",
            "docker_platform: linux/amd64",
            "file: rust/Dockerfile",
            "target: cli",
            "platforms: ${{ matrix.docker_platform }}",
            "RELEASE_MODE=1",
            "push: ${{ inputs.push }}",
        ):
            require(fragment in upstream, f"upstream release job changed: {fragment}")
        action = (
            ROOT / ".github/actions/chroma-docker-benchmark/action.yml"
        ).read_text()
        require(
            action.count("RELEASE_MODE=1") == 3, "providers disagree on RELEASE_MODE"
        )
        require(
            action.count("platforms: linux/amd64") == 3,
            "providers disagree on amd64 target",
        )
        require(
            action.count("docker/chroma.Dockerfile") == 3,
            "providers disagree on Dockerfile",
        )
        require(
            action.count("docker-tool-cache: sccache") == 2,
            "BoringCache sccache cache is not enabled",
        )
        require(
            action.count("BORINGCACHE_BENCHMARK_SCCACHE_PROOF=1") == 2,
            "BoringCache builds do not verify the compiler and Cargo caches",
        )
        require(
            "SCCACHE_PROOF: ${{ inputs.strategy == 'boringcache' && 'true' || '' }}"
            in action,
            "benchmark report does not record successful sccache proof",
        )
        require(
            '--sccache-proof "$SCCACHE_PROOF"' in action,
            "benchmark report omits sccache proof",
        )
        require(
            action.count("docker-mount-cache: true") == 2,
            "BoringCache mount cache is not enabled",
        )
        require(
            "upstream/rust/Dockerfile" not in action,
            "provider bypasses the monitored Dockerfile",
        )
        require(
            "LOG_SERVICE_CARGO_FEATURES=faults" not in action,
            "non-upstream build arg remains",
        )
        scope = (ROOT / "scripts/scope-boringcache-run.sh").read_text()
        require("chroma-sccache-local" in scope, "cache scoping omits sccache")
        require("${scope}-sccache" in scope, "sccache cache tag is not run-scoped")
    except (
        DockerfileSyncError,
        KeyError,
        OSError,
        RuntimeError,
        tomllib.TOMLDecodeError,
    ) as error:
        print(f"Chroma recipe mismatch: {error}", file=sys.stderr)
        return 1
    print("Verified Chroma release-container amd64 plan.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
