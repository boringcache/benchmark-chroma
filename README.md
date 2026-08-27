# BoringCache Chroma benchmark

This repository contains the BoringCache benchmark for Chroma.

Benchmark workflows are in [`.github/workflows/`](.github/workflows/), with configuration in [`.boringcache.toml`](.boringcache.toml).

[`docker/chroma.Dockerfile`](docker/chroma.Dockerfile) is generated from Chroma's pinned `rust/Dockerfile` plus marked benchmark-only sccache integration. It installs sccache 0.17.0 from Mozilla's release assets, pins both supported Linux architectures by SHA-256, and keeps sccache out of the final image. BoringCache builds also fail unless the injected compiler wrapper handles cacheable Rust requests, print sccache's JSON hit/miss statistics in the Docker build log, and record `sccache verified` in the benchmark report.

The upstream sync workflow refreshes the submodule and regenerates the Dockerfile copy. `scripts/verify-upstream-recipe.py` rejects any untracked difference from upstream or change to the benchmark cache contract.
