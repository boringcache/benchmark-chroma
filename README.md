# BoringCache Chroma benchmark

This repository contains the BoringCache benchmark for Chroma.

Benchmark workflows are in [`.github/workflows/`](.github/workflows/), with configuration in [`.boringcache.toml`](.boringcache.toml).

[`docker/chroma.Dockerfile`](docker/chroma.Dockerfile) is generated from Chroma's pinned `rust/Dockerfile` plus one marked benchmark-only block that installs sccache 0.17.0 from Mozilla's release assets. Both supported Linux architectures are pinned by SHA-256, and sccache remains in the builder stages rather than the final image.

The upstream sync workflow refreshes the submodule and regenerates the Dockerfile copy. `scripts/verify-upstream-recipe.py` rejects any untracked difference from upstream or change to the benchmark cache contract.
