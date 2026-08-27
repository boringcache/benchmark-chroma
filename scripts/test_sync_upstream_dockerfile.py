import unittest

from scripts.sync_upstream_dockerfile import (
    BLOCK_END,
    BLOCK_START,
    PROOF_END,
    PROOF_START,
    DockerfileSyncError,
    extract_sccache_block,
    render_benchmark_dockerfile,
)


class SyncUpstreamDockerfileTest(unittest.TestCase):
    def setUp(self) -> None:
        self.block = f"{BLOCK_START}\nRUN sccache --version\n{BLOCK_END}"
        self.upstream = """FROM rust:1 AS chef

ARG TOOL=1

FROM chef AS builder

RUN echo prepare && \\
  cargo build ${build_target} --workspace --release && \\
  for bin in app; do \\
  cp "target/${bin}" "./${bin}"; \\
  done

FROM scratch AS runner
"""

    def test_renders_sccache_install_and_proof_into_upstream(self) -> None:
        rendered = render_benchmark_dockerfile(self.upstream, self.block)

        self.assertIn(f"FROM rust:1 AS chef\n\n{self.block}\n\nARG TOOL=1", rendered)
        self.assertIn(
            f"FROM chef AS builder\n\n{PROOF_START}\n"
            "ARG BORINGCACHE_BENCHMARK_SCCACHE_PROOF=0\n"
            f"{PROOF_END}",
            rendered,
        )
        self.assertIn("sccache --show-stats --stats-format=json", rendered)
        self.assertIn('"cache_(hits|misses)"', rendered)
        self.assertEqual(extract_sccache_block(rendered), self.block)

    def test_rejects_an_upstream_file_without_one_chef_stage(self) -> None:
        with self.assertRaisesRegex(DockerfileSyncError, "exactly one chef stage"):
            render_benchmark_dockerfile("FROM rust:1 AS builder\n", self.block)

    def test_rejects_benchmark_markers_in_upstream(self) -> None:
        upstream = f"FROM rust:1 AS chef\n{BLOCK_START}\n"

        with self.assertRaisesRegex(DockerfileSyncError, "benchmark markers"):
            render_benchmark_dockerfile(upstream, self.block)

    def test_rejects_an_upstream_file_without_the_workspace_build(self) -> None:
        upstream = self.upstream.replace(
            "cargo build ${build_target} --workspace --release", "cargo build --release"
        )

        with self.assertRaisesRegex(DockerfileSyncError, "workspace Cargo build"):
            render_benchmark_dockerfile(upstream, self.block)


if __name__ == "__main__":
    unittest.main()
