import unittest

from scripts.sync_upstream_dockerfile import (
    BLOCK_END,
    BLOCK_START,
    DockerfileSyncError,
    extract_sccache_block,
    render_benchmark_dockerfile,
)


class SyncUpstreamDockerfileTest(unittest.TestCase):
    def setUp(self) -> None:
        self.block = f"{BLOCK_START}\nRUN sccache --version\n{BLOCK_END}"

    def test_renders_one_benchmark_block_into_the_chef_stage(self) -> None:
        upstream = "FROM rust:1 AS chef\n\nARG TOOL=1\n\nFROM chef AS builder\n"

        rendered = render_benchmark_dockerfile(upstream, self.block)

        self.assertEqual(
            rendered,
            f"FROM rust:1 AS chef\n\n{self.block}\n\nARG TOOL=1\n\nFROM chef AS builder\n",
        )
        self.assertEqual(extract_sccache_block(rendered), self.block)

    def test_rejects_an_upstream_file_without_one_chef_stage(self) -> None:
        with self.assertRaisesRegex(DockerfileSyncError, "exactly one chef stage"):
            render_benchmark_dockerfile("FROM rust:1 AS builder\n", self.block)

    def test_rejects_benchmark_markers_in_upstream(self) -> None:
        upstream = f"FROM rust:1 AS chef\n{BLOCK_START}\n"

        with self.assertRaisesRegex(DockerfileSyncError, "benchmark markers"):
            render_benchmark_dockerfile(upstream, self.block)


if __name__ == "__main__":
    unittest.main()
