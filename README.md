# benchmark-chroma

Experimental Chroma Docker cache qualification benchmark for BoringCache versus GitHub Actions cache.

Stable BoringCache workflows install the verified CLI `v1.16.3` release;
canary dispatches must use an exact immutable CLI tag.

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
- `chroma-full-bake.yml` reproduces Chroma's complete PR prebuild command and
  target graph from
  `.github/actions/tilt-setup-prebuild/docker-bake.hcl`. All 12 targets receive
  managed Docker caching; only the 10 Rust targets receive `sccache`. The two
  Go targets remain unchanged and receive ordinary Docker caching only.

Pinned upstream source:

- see the committed `upstream/` submodule on `main`; the measured proof series
  below remains fixed

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

### Eight-Core Runner Qualification

The same proof was also run on GitHub's 8-core `ubuntu-latest-m` runner. An
isolated seed run
[`30099629778`](https://github.com/boringcache/benchmark-chroma/actions/runs/30099629778)
populated empty caches at `4088bf6`: the unchanged-Dockerfile control took
599 seconds and Docker plus sccache took 668 seconds. The comparable 4-core
fresh run above took 970 and 1,049 seconds respectively.

The 69-second cold sccache population cost was not a final proxy flush. The
BuildKit exports were effectively equal at 56.1 and 56.4 seconds. During the
Rust compile stages, the tool lane handled 1,761 misses and populated 1,753
objects (1.85 GB). Those writes overlapped, reaching 23 completed puts in one
second, with no staging or commit errors or retries.

The next two commits produced valid steady-state rolling comparisons:

| Runner | Upstream change | Run | Docker cache only | Docker + sccache | Time saved | sccache hit rate |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| GitHub 4-core | Source only | [30092677434](https://github.com/boringcache/benchmark-chroma/actions/runs/30092677434) | 830s | 434s | 396s (48%) | 859/861 (99.8%) |
| GitHub 4-core | Lockfile + source | [30093619302](https://github.com/boringcache/benchmark-chroma/actions/runs/30093619302) | 920s | 450s | 470s (51%) | 2,086/2,096 (99.5%) |
| **GitHub 4-core average** | | | **875s** | **442s** | **433s (49%)** | **2,945/2,957 (99.6%)** |
| GitHub 8-core | Source only | [30100507004](https://github.com/boringcache/benchmark-chroma/actions/runs/30100507004) | 438s | 269s | 169s (39%) | 859/861 (99.8%) |
| GitHub 8-core | Lockfile + source | [30101448180](https://github.com/boringcache/benchmark-chroma/actions/runs/30101448180) | 575s | 292s | 283s (49%) | 2,086/2,096 (99.5%) |
| **GitHub 8-core average** | | | **507s** | **281s** | **226s (45%)** | **2,945/2,957 (99.6%)** |

Across both rolling commits, the 8-core runner reduced Docker-plus-sccache wall
time by another 161 seconds (36%) while preserving the same aggregate
compiler-cache hit rate.

## Complete Upstream Bake Graph

The full-graph workflow runs Chroma's actual PR command as one parallel Bake
on GitHub's 8-core `ubuntu-latest-m` runner:

```sh
docker buildx bake -f .github/actions/tilt-setup-prebuild/docker-bake.hcl
```

Its 12 named image targets are 10 Rust targets (`rust-log-service`,
`rust-sysdb-service`, `rust-sysdb-migration`, `rust-frontend-service`,
`query-service`, `compactor-service`, `garbage-collector`, `load-service`,
`work-queue-service`, and `fn-consumer`) plus the Go `sysdb` and
`sysdb-migration` targets. These are Docker Bake target names, not Rust target
triples.

Seed run
[`30112114394`](https://github.com/boringcache/benchmark-chroma/actions/runs/30112114394)
populated an empty isolated tool-cache scope at `4088bf6` and is excluded from
the comparison. The two subsequent runs imported only their preceding rolling
cache and built real upstream commits:

| Upstream change | Run | Docker cache only | Docker + sccache | Wall time saved | Pre-flush Bake, Docker + sccache | Upstream 16-vCPU Bake | sccache hit rate |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Source only (`68efa22`) | [30113095955](https://github.com/boringcache/benchmark-chroma/actions/runs/30113095955) | 598s | 574s | 24s (4%) | 290s | [224s](https://github.com/chroma-core/chroma/actions/runs/30032434118/job/89302419802) | 859/861 (99.8%) |
| Lockfile + source (`ab02926`) | [30113798308](https://github.com/boringcache/benchmark-chroma/actions/runs/30113798308) | 616s | 527s | 89s (14%) | 321s | [195s](https://github.com/chroma-core/chroma/actions/runs/30031630614/job/89289405031) | 2,086/2,096 (99.5%) |
| **Average** | | **607s** | **551s** | **57s (9%)** | **306s** | **210s** | **2,945/2,957 (99.6%)** |

The complete graph does not currently qualify a raw wall-time claim against
Blacksmith. The compiler cache works: before managed Docker-cache shutdown,
the 8-core tool lane is roughly 96 seconds behind Chroma's 16-vCPU sticky-disk
Bake average. The current loss is multi-target Docker-cache publication. Ten
Rust exporters repeatedly stream a shared changed builder layer through the
local proxy. Across the two measured commits, the proxy ingested 28.1 and
36.6 GB for the tool lane even though the remote CAS deduplicated common
content.

The per-target manifests total roughly 45–48 GiB of logical cache graph. That
sum intentionally double-counts shared blobs referenced by multiple targets;
it is not unique physical storage. BoringCache's content-addressed store keeps
one physical copy of shared bodies.

That duplicate local ingestion extends strict shutdown well beyond BuildKit's
visible export spans. For example, the source-only tool Bake finished in about
290 seconds, including an 85-second maximum export span, but the CLI returned
at 574 seconds after pending managed-cache work completed. This is a product
optimization target, not an upstream or `sccache` failure.

Chroma's upstream sticky-disk tax is much smaller: builder attachment took
2–3 seconds, and snapshot commit took about 5 seconds on warm runs (34 seconds
on the seed-like run). The corresponding upstream jobs completed in 211–254
seconds, with 195–224 seconds spent in Bake.

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
