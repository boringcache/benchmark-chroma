# BoringCache Chroma benchmark

This repository contains the BoringCache benchmark for Chroma.

Benchmark workflows are in [`.github/workflows/`](.github/workflows/), with configuration in [`.boringcache.toml`](.boringcache.toml).

[`docker/chroma.Dockerfile`](docker/chroma.Dockerfile) is generated from Chroma's pinned `rust/Dockerfile` plus two marked benchmark-only integrations. It installs sccache 0.17.0 from Mozilla's release assets, pins both supported Linux architectures by SHA-256, and keeps sccache out of the final image. It replaces the upstream Cargo Chef planner/cook stages with one workspace build whose Cargo registry, Git checkout, and architecture-scoped `/chroma/target` directories are locked BuildKit cache mounts.

BoringCache supplies `RUSTC_WRAPPER`, the remote sccache endpoint and credentials, and mount persistence. Cold builds populate all three Cargo mounts; later builds restore the downloads, fingerprints, and compiled outputs before Cargo runs. A completely warm target is valid even when Cargo invokes no compiler, while source changes can fall through to sccache. BoringCache builds verify the injected wrapper, endpoint, and populated target, print sccache's JSON statistics, and record `sccache verified` in the report. The GitHub Actions lane receives the same Dockerfile and build inputs but only its standard OCI cache exporter, so it does not gain cross-run persistence for BuildKit cache mounts; its warm source-change build is allowed to rebuild an empty target mount.

The upstream sync workflow refreshes the submodule and regenerates the Dockerfile copy. `scripts/verify-upstream-recipe.py` rejects any untracked difference from upstream or change to the benchmark cache contract.
