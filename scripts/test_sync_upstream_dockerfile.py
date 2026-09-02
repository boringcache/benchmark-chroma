import unittest

from scripts.sync_upstream_dockerfile import (
    BLOCK_END,
    BLOCK_START,
    CARGO_CACHE_END,
    CARGO_CACHE_START,
    PROOF_END,
    PROOF_START,
    UPSTREAM_DOCKERFILE,
    DockerfileSyncError,
    extract_sccache_block,
    render_benchmark_dockerfile,
)


class SyncUpstreamDockerfileTest(unittest.TestCase):
    def setUp(self) -> None:
        self.block = f"{BLOCK_START}\nRUN sccache --version\n{BLOCK_END}"
        self.upstream = UPSTREAM_DOCKERFILE.read_text()

    def test_replaces_cargo_chef_with_one_persistent_cargo_build(self) -> None:
        rendered = render_benchmark_dockerfile(self.upstream, self.block)

        self.assertIn(
            f"FROM rust:1.92.0 AS build-tools\n\n{self.block}", rendered
        )
        self.assertIn("FROM build-tools AS builder", rendered)
        self.assertIn(
            f"{PROOF_START}\n"
            "ARG BORINGCACHE_BENCHMARK_SCCACHE_PROOF=0\n"
            f"{PROOF_END}",
            rendered,
        )
        self.assertEqual(rendered.count(CARGO_CACHE_START), 2)
        self.assertEqual(rendered.count(CARGO_CACHE_END), 2)
        self.assertEqual(
            rendered.count("cargo build ${build_target} --workspace"), 1
        )
        for fragment in (
            "cargo-chef",
            "cargo chef",
            "recipe.json",
            "COOK_PACKAGES",
            "FROM chef",
            "FROM cooked",
            "planner",
            "fallback",
        ):
            self.assertNotIn(fragment, rendered)
        self.assertEqual(extract_sccache_block(rendered), self.block)

    def test_mounts_all_cargo_state_on_the_workspace_build(self) -> None:
        rendered = render_benchmark_dockerfile(self.upstream, self.block)
        workspace_build = rendered.index("cargo build ${build_target} --workspace")
        run_start = rendered.rfind("\nRUN ", 0, workspace_build)
        next_stage = rendered.index("\n\nFROM ", workspace_build)
        run_block = rendered[run_start:next_stage]

        target = (
            "id=chroma-target-${TARGETARCH},sharing=locked,"
            "target=/chroma/target"
        )
        registry = "sharing=locked,target=/usr/local/cargo/registry/"
        git = "sharing=locked,target=/usr/local/cargo/git/"
        self.assertEqual(rendered.count("target=/chroma/target"), 1)
        self.assertEqual(rendered.count("target=/usr/local/cargo/registry/"), 1)
        self.assertEqual(rendered.count("target=/usr/local/cargo/git/"), 1)
        self.assertLess(run_block.index(target), run_block.index(registry))
        self.assertLess(run_block.index(registry), run_block.index(git))
        self.assertLess(run_block.index(git), run_block.index("cargo build"))

    def test_proof_accepts_a_fully_warm_target_cache(self) -> None:
        rendered = render_benchmark_dockerfile(self.upstream, self.block)

        self.assertIn(
            'test -n "$(find /chroma/target -mindepth 1 -print -quit)"',
            rendered,
        )
        self.assertIn("BORINGCACHE_CARGO_TARGET_READY=1", rendered)
        self.assertIn("sccache --show-stats --stats-format=json", rendered)
        self.assertNotIn('"cache_(hits|misses)"', rendered)

    def test_rejects_an_upstream_file_without_one_chef_stage(self) -> None:
        upstream = self.upstream.replace(" AS chef", " AS changed", 1)

        with self.assertRaisesRegex(DockerfileSyncError, "exactly one chef stage"):
            render_benchmark_dockerfile(upstream, self.block)

    def test_rejects_benchmark_markers_in_upstream(self) -> None:
        upstream = self.upstream + f"\n{BLOCK_START}\n"

        with self.assertRaisesRegex(DockerfileSyncError, "benchmark markers"):
            render_benchmark_dockerfile(upstream, self.block)

    def test_rejects_changed_cargo_chef_sections(self) -> None:
        upstream = self.upstream.replace(
            "cargo install cargo-chef --locked",
            "cargo install cargo-chef --version latest --locked",
            1,
        )

        with self.assertRaisesRegex(DockerfileSyncError, "Cargo Chef install"):
            render_benchmark_dockerfile(upstream, self.block)

    def test_rejects_an_upstream_file_without_the_workspace_build(self) -> None:
        upstream = self.upstream.replace(
            "cargo build ${build_target} --workspace",
            "cargo build --workspace",
            1,
        )

        with self.assertRaisesRegex(DockerfileSyncError, "workspace Cargo build"):
            render_benchmark_dockerfile(upstream, self.block)

    def test_rejects_an_upstream_file_without_the_workspace_section(self) -> None:
        upstream = self.upstream.replace(
            "# --- Workspace compile (first-party crates) ----------------------------------",
            "# Build the workspace",
        )

        with self.assertRaisesRegex(DockerfileSyncError, "workspace compile section"):
            render_benchmark_dockerfile(upstream, self.block)


if __name__ == "__main__":
    unittest.main()
