#!/usr/bin/env python3
"""Resolve GitHub-only image publication in the committed Docker plan."""

import argparse
import json
from pathlib import Path

import tomllib

PLAN = Path(__file__).resolve().parents[1] / ".boringcache.toml"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--push", choices=("true", "false"), required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--plan", type=Path, default=PLAN)
    args = parser.parse_args()

    source = args.plan.read_text()
    if args.push == "true":
        needle = '  "--tag", "chroma-benchmark:local",\n  "upstream",'
        replacement = (
            f'  "--tag", {json.dumps(args.image)},\n  "--push",\n  "upstream",'
        )
        if source.count(needle) != 1:
            raise SystemExit("committed Chroma output plan changed")
        source = source.replace(needle, replacement, 1)
        args.plan.write_text(source)

    tomllib.loads(source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
