#!/usr/bin/env python3
"""Verify Chroma's amd64 release-container benchmark plan."""

import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = ["docker", "buildx", "build", "--file", "upstream/rust/Dockerfile", "--target", "cli", "--platform", "linux/amd64", "--build-arg", "RELEASE_MODE=1", "--tag", "chroma-benchmark:local", "upstream"]

def require(value: bool, message: str) -> None:
    if not value:
        raise RuntimeError(message)

def main() -> int:
    try:
        plan = tomllib.loads((ROOT / ".boringcache.toml").read_text())
        require(plan["adapters"]["docker"]["command"] == EXPECTED, "Docker plan changed")
        upstream = (ROOT / "upstream/.github/workflows/_build_release_container.yml").read_text()
        for fragment in ("platform: [amd64, arm64]", "docker_platform: linux/amd64", "file: rust/Dockerfile", "target: cli", "platforms: ${{ matrix.docker_platform }}", "RELEASE_MODE=1", "push: ${{ inputs.push }}"):
            require(fragment in upstream, f"upstream release job changed: {fragment}")
        action = (ROOT / ".github/actions/chroma-docker-benchmark/action.yml").read_text()
        require(action.count("RELEASE_MODE=1") == 3, "providers disagree on RELEASE_MODE")
        require(action.count("platforms: linux/amd64") == 3, "providers disagree on amd64 target")
        require("LOG_SERVICE_CARGO_FEATURES=faults" not in action, "non-upstream build arg remains")
    except (KeyError, OSError, RuntimeError, tomllib.TOMLDecodeError) as error:
        print(f"Chroma recipe mismatch: {error}", file=sys.stderr)
        return 1
    print("Verified Chroma release-container amd64 plan.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
