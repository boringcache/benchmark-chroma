# benchmark-chroma

Experimental Chroma Docker cache qualification benchmark for BoringCache versus GitHub Actions cache.

Chroma already has a serious Docker caching setup. Its pull-request workflow
uses Blacksmith's persistent BuildKit cache, builds the CI images once, and
then lets downstream jobs clone the warmed snapshot. The upstream workflow
documents the avoided work as roughly six minutes across about 20 jobs.

This benchmark therefore is not evidence for outreach by itself. Its purpose
is to test whether a portable registry-backed cache can produce a useful
cost, portability, or cache-transfer result against an already optimized
sticky-disk setup.

## Prospect Evidence

- Chroma recorded 995 runs of its PR workflow from 2026-06-24 through
  2026-07-24.
- In public run
  [`30032434118`](https://github.com/chroma-core/chroma/actions/runs/30032434118),
  the `Build Docker images (warm sticky disk)` job restored a Blacksmith
  snapshot and reused the cargo-chef dependency layer, but the changed-source
  workspace compile still took 214.2 seconds.
- Chroma merged PR
  [`#7433`](https://github.com/chroma-core/chroma/pull/7433) on 2026-07-14 to
  move Rust dependency compilation into durable cargo-chef image layers.

The honest qualification gate is strict: do not pitch Chroma on raw Docker
cache speed unless benchmark results beat a meaningful existing baseline.
Portability beyond Blacksmith, cache economics, or a separately proven
Docker-plus-sccache path could still create an angle.

## Source Model

- Upstream source lives in the pinned `upstream/` submodule.
- Workflows use the upstream `rust/Dockerfile` unchanged with `upstream/` as
  the Docker context.
- The measured target mirrors Chroma's PR image path: target `cli`, build arg
  `LOG_SERVICE_CARGO_FEATURES=faults`, and platform `linux/amd64`.
- The benchmark does not add `sccache` inside the image. The upstream
  Dockerfile does not currently use it, and modifying the Dockerfile would
  turn this into a different experiment.

Pinned upstream source:

- `ab02926708b49ceca24977793927df7fda537ea1`

## Scenarios

- `cold`
- `warm1`

The fresh lane runs a no-prior-cache cold build plus exactly one warm rerun on
the same pinned source tree. The rolling lane records the upstream commit
build as-is after each upstream sync and skips `warm1`.

BoringCache uses its external registry/OCI BuildKit cache path. It does not
run BoringCache inside upstream Dockerfile `RUN` steps. The optional
BoringCache BuildKit-backend and ECR lanes remain disabled until their
repository variables are configured.

The GitHub-hosted GHA-versus-BoringCache lanes are controlled cache-backend
tests; they are not an equal-hardware comparison with Chroma's 16-vCPU
Blacksmith runners.

## Output

Each workflow uploads machine-readable JSON and Markdown summaries for later
ingestion by the central `boringcache/benchmarks` publisher.

## Token Model

- `BORINGCACHE_RESTORE_TOKEN` for read-only restore and proxy access
- `BORINGCACHE_SAVE_TOKEN` for trusted write paths
- `BORINGCACHE_API_TOKEN` only where a single bearer variable is still
  required for compatibility
