# benchmark-chroma

Experimental Chroma Docker cache qualification benchmark for BoringCache versus GitHub Actions cache.

Chroma already has a serious Docker caching setup. Its pull-request workflow
uses Blacksmith's persistent BuildKit cache, builds the CI images once, and
then lets downstream jobs clone the warmed snapshot. The upstream workflow
documents the avoided work as roughly six minutes across about 20 jobs.

This benchmark is not evidence that BoringCache beats Blacksmith on raw
runner wall time. Its purpose is to test whether a portable remote BuildKit
cache can produce a useful cost, portability, cache-transfer, or compiler
reuse result alongside an already optimized sticky-disk setup.

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
- The primary GHA-versus-BoringCache workflow does not add `sccache` inside
  the image. It is an unchanged-upstream-Dockerfile comparison.
- A separate `chroma-sccache.yml` qualification workflow renders a
  benchmark-only Dockerfile that adds a pinned `sccache` executable. The
  BoringCache CLI owns the compiler environment and remote tool-cache wiring;
  its paired control still builds the unchanged upstream Dockerfile.

Pinned upstream source:

- `ab02926708b49ceca24977793927df7fda537ea1`

## Rolling Proof Series

The benchmark replays these three linear `main` merge commits oldest to
newest. For each merge, the associated PR successfully ran
`Build Docker images (warm sticky disk)`, so the sample matches Chroma's
actual Docker-triggering change detection:

| Merge commit | Upstream proof |
| --- | --- |
| `4088bf614916e7027f891d4dd3c91b2a478eeef3` | [PR #7490 run 30028588454](https://github.com/chroma-core/chroma/actions/runs/30028588454) |
| `68efa222af364d877133ce30e26fd839e7d2b100` | [PR #7489 run 30032434118](https://github.com/chroma-core/chroma/actions/runs/30032434118) |
| `ab02926708b49ceca24977793927df7fda537ea1` | [PR #7478 run 30031630614](https://github.com/chroma-core/chroma/actions/runs/30031630614) |

## Managed Docker Cache Results

The oldest commit populated each rolling cache and is excluded from the
comparison. The next two runs imported only that strategy's preceding cache,
built the changed upstream commit on GitHub-hosted `ubuntu-latest`, and used
the upstream Dockerfile unchanged.

| Upstream commit | Run | GitHub Actions cache | BoringCache | Time saved | GHA export | BoringCache export |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `68efa22` | [30089256374](https://github.com/boringcache/benchmark-chroma/actions/runs/30089256374) | 1,399s | 620s | 779s (56%) | 748.9s | 70.6s |
| `ab02926` | [30091583747](https://github.com/boringcache/benchmark-chroma/actions/runs/30091583747) | 1,828s | 940s | 888s (49%) | 979.7s | 75.9s |
| **Average** | | **1,614s** | **780s** | **834s (52%)** | **864.3s** | **73.3s** |

The earlier middle-commit attempt is excluded because both lanes exhausted
the hosted runner's disk during the Rust/aws-lc build. Enabling the workflow's
disk cleanup fixed it; this was not an npm-cache failure.

## Existing Blacksmith Baseline

Chroma's recent upstream `Build Docker images (warm sticky disk)` jobs ran in
3m59s, 3m31s, and 4m14s on 16-vCPU Blacksmith runners. The managed result
above removes a very large GHA export tail, but does not beat those absolute
times on a GitHub 4-vCPU runner. This is not an equal-hardware or identical
workload comparison, so a raw speed claim against Blacksmith still requires a
same-runner test.

## Docker Plus sccache Qualification

Fresh run
[`30090388085`](https://github.com/boringcache/benchmark-chroma/actions/runs/30090388085)
measured 970 seconds for the unchanged-Dockerfile control and 1,049 seconds
with sccache while both caches were being populated. Its three- and
five-second same-ref warm builds only prove Docker layer-cache parity and are
not compiler-cache evidence.

The rolling proof bootstrapped both isolated caches at `4088bf6`, then built
real changed commits in order. The middle commit changed Rust source only;
the newest also changed `Cargo.lock`. Both sccache rows completed without
cache errors.

| Upstream change | Run | Docker cache only | Docker + sccache | Time saved | sccache hit rate |
| --- | --- | ---: | ---: | ---: | ---: |
| Source only (`68efa22`) | [30092677434](https://github.com/boringcache/benchmark-chroma/actions/runs/30092677434) | 830s | 434s | 396s (48%) | 859/861 (99.8%) |
| Lockfile + source (`ab02926`) | [30093619302](https://github.com/boringcache/benchmark-chroma/actions/runs/30093619302) | 920s | 450s | 470s (51%) | 2,086/2,096 (99.5%) |
| **Average** | | **875s** | **442s** | **433s (49%)** | **2,945/2,957 (99.6%)** |

This is a distinct product experiment, not a rewrite of the primary Docker
cache result: the benchmark-only fixture supplies the executable, while
`boringcache docker --tool-cache sccache` supplies the runtime integration.

## Scenarios

- `cold`
- `warm1`

The fresh lane runs a no-prior-cache cold build plus exactly one warm rerun on
the same pinned source tree. The rolling lane records the upstream commit
build as-is after each upstream sync and skips `warm1`.

The two-entry matrix compares GitHub Actions cache with BoringCache managed
BuildKit. It does not run BoringCache inside upstream Dockerfile `RUN` steps.

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
