# BoringCache Chroma benchmark

This repository contains the BoringCache benchmark for Chroma.

Benchmark workflows are in [`.github/workflows/`](.github/workflows/), with configuration in [`.boringcache.toml`](.boringcache.toml).

[`docker/chroma.Dockerfile`](docker/chroma.Dockerfile) is generated from Chroma's pinned `rust/Dockerfile` plus two marked benchmark-only integrations. It installs sccache 0.17.0 from Mozilla's release assets, pins both supported Linux architectures by SHA-256, and keeps sccache out of the final image. It also mounts `/chroma/target` as a locked, architecture-scoped BuildKit cache. BoringCache gets the empty mount first so it can hydrate persisted Cargo state; only a cache miss copies Cargo Chef's cooked dependency layer into the mount. Cargo Chef therefore remains the durable OCI fallback while BoringCache can persist Cargo's first-party fingerprints and build outputs across source changes.

BoringCache builds fail unless the injected compiler wrapper is configured, require cacheable Rust requests when the Cargo target fallback is used, print sccache's JSON hit/miss statistics, and record `sccache verified` in the benchmark report. Build logs also identify the target source as `fallback` or `persistent`. The BoringCache lane enables `docker-mount-cache`, which offloads the target mount between ephemeral builders; the GitHub Actions lane still receives the same Dockerfile and build inputs but uses its standard OCI cache exporter.

The upstream sync workflow refreshes the submodule and regenerates the Dockerfile copy. `scripts/verify-upstream-recipe.py` rejects any untracked difference from upstream or change to the benchmark cache contract.
