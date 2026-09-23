from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class BenchmarkReportTest(unittest.TestCase):
    def test_reads_retired_action_outputs_from_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "evidence.json"
            output = root / "results"
            evidence.write_text(
                json.dumps(
                    {
                        "phases": {
                            "restore": {
                                "workspace": "boringcache/benchmark-chroma",
                                "cache_tag": "chroma-docker-test",
                                "mode_evidence": {
                                    "buildkit_cache": {
                                        "cache_from_refs": ["ref-one", "ref-two"]
                                    }
                                },
                            }
                        }
                    }
                )
            )

            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "benchmark-report.py"),
                    "phase",
                    "--benchmark",
                    "chroma",
                    "--strategy",
                    "boringcache",
                    "--lane",
                    "fresh",
                    "--phase",
                    "warm",
                    "--mode",
                    "docker",
                    "--build-seconds",
                    "10",
                    "--sccache-proof",
                    "true",
                    "--evidence",
                    str(evidence),
                    "--output-dir",
                    str(output),
                ],
                check=True,
            )

            report = json.loads(
                (output / "chroma-boringcache-fresh-warm.json").read_text()
            )
            self.assertEqual(report["cache"]["import_refs"], 2)
            self.assertTrue(report["cache"]["sccache_proof"])
            self.assertEqual(report["cache"]["tag"], "chroma-docker-test")
            self.assertEqual(
                report["cache"]["workspace"], "boringcache/benchmark-chroma"
            )

    def test_empty_sccache_proof_is_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "benchmark-report.py"),
                    "phase",
                    "--benchmark",
                    "chroma",
                    "--strategy",
                    "actions-cache",
                    "--lane",
                    "rolling",
                    "--phase",
                    "commit",
                    "--mode",
                    "docker",
                    "--build-seconds",
                    "10",
                    "--sccache-proof",
                    "",
                    "--output-dir",
                    directory,
                ],
                check=True,
            )
            report = json.loads(
                (Path(directory) / "chroma-actions-cache-rolling-commit.json").read_text()
            )
            self.assertIsNone(report["cache"]["sccache_proof"])


if __name__ == "__main__":
    unittest.main()
