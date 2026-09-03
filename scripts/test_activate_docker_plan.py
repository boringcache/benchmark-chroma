from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]


class ActivateDockerPlanTest(unittest.TestCase):
    def activate(self, push: str) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / ".boringcache.toml"
            plan.write_text((ROOT / ".boringcache.toml").read_text())
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "activate-docker-plan.py"),
                    "--push",
                    push,
                    "--image",
                    "ghcr.io/acme/chroma:boringcache",
                    "--plan",
                    str(plan),
                ],
                check=True,
            )
            return tomllib.loads(plan.read_text())

    def test_keeps_local_output_without_publication(self) -> None:
        command = self.activate("false")["adapters"]["docker"]["command"]
        self.assertIn("chroma-benchmark:local", command)
        self.assertNotIn("--push", command)

    def test_resolves_publication_into_direct_docker_argv(self) -> None:
        command = self.activate("true")["adapters"]["docker"]["command"]
        self.assertEqual(command[:3], ["docker", "buildx", "build"])
        self.assertIn("ghcr.io/acme/chroma:boringcache", command)
        self.assertIn("--push", command)


if __name__ == "__main__":
    unittest.main()
