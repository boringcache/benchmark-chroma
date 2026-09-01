# syntax=docker/dockerfile:1

# ============================================================================
# chef: shared toolchain base (rust + protoc + cargo-chef).
#
# This is the slow-changing setup layer. It is shared by the `planner` and
# `builder` stages below so the toolchain/protoc install is built and cached
# once, regardless of source changes.
# ============================================================================
FROM rust:1.92.0 AS chef

# BEGIN BORINGCACHE BENCHMARK SCCACHE
# The image owns the compiler tool. BoringCache supplies only its runtime cache
# endpoint, credentials, and read/write policy to BuildKit RUN steps.
ARG SCCACHE_VERSION=0.17.0
ARG TARGETARCH
RUN set -eux; \
  case "${TARGETARCH}" in \
  amd64) \
  sccache_target="x86_64-unknown-linux-musl"; \
  sccache_sha256="67c4a96dd237c1f518f6b36083f270f9976d516f1e57fce891755ea782e50006" \
  ;; \
  arm64) \
  sccache_target="aarch64-unknown-linux-musl"; \
  sccache_sha256="821a86343191aa1cbab74bd42f9e93c9a63bf85e4742945f40d3ae84193c1c77" \
  ;; \
  *) \
  echo "Unsupported sccache architecture: ${TARGETARCH}" >&2; \
  exit 1 \
  ;; \
  esac; \
  archive="sccache-v${SCCACHE_VERSION}-${sccache_target}.tar.gz"; \
  curl --fail --location --show-error --silent \
  "https://github.com/mozilla/sccache/releases/download/v${SCCACHE_VERSION}/${archive}" \
  --output "/tmp/${archive}"; \
  printf '%s  %s\n' "${sccache_sha256}" "/tmp/${archive}" | sha256sum --check --strict; \
  tar --extract --gzip --file "/tmp/${archive}" --directory /tmp; \
  install --mode=0755 "/tmp/sccache-v${SCCACHE_VERSION}-${sccache_target}/sccache" /usr/local/bin/sccache; \
  rm --recursive --force "/tmp/${archive}" "/tmp/sccache-v${SCCACHE_VERSION}-${sccache_target}"; \
  sccache --version
# END BORINGCACHE BENCHMARK SCCACHE

ARG PROTOC_VERSION=31.1

# ADDRESS_SANITIZER is an optional build argument to enable Address Sanitizer.
ARG ADDRESS_SANITIZER
RUN if [ "$ADDRESS_SANITIZER" = "1" ]; then \
  apt-get update && \
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  build-essential gcc g++ libssl-dev ca-certificates && \
  rustup default nightly && \
  rustup target add x86_64-unknown-linux-gnu ; \
  fi

RUN ARCH=$(uname -m) && \
  if [ "$ARCH" = "x86_64" ]; then \
  PROTOC_ZIP=protoc-${PROTOC_VERSION}-linux-x86_64.zip; \
  elif [ "$ARCH" = "aarch64" ]; then \
  PROTOC_ZIP=protoc-${PROTOC_VERSION}-linux-aarch_64.zip; \
  else \
  echo "Unsupported architecture: $ARCH" && exit 1; \
  fi && \
  curl -OL https://github.com/protocolbuffers/protobuf/releases/download/v${PROTOC_VERSION}/$PROTOC_ZIP && \
  unzip -o $PROTOC_ZIP -d /usr/local bin/protoc && \
  unzip -o $PROTOC_ZIP -d /usr/local 'include/*' && \
  rm -f $PROTOC_ZIP && \
  chmod +x /usr/local/bin/protoc && \
  protoc --version  # Verify installed version

# cargo-chef lets us cache the dependency compile as a content-addressed image
# LAYER (keyed on the dependency graph) instead of leaving it in a volatile
# `--mount=type=cache` directory that is wiped on a cold/contended builder.
RUN --mount=type=cache,sharing=locked,target=/usr/local/cargo/registry/ \
  cargo install cargo-chef --locked

WORKDIR /chroma

# ============================================================================
# planner: emit recipe.json (the dependency graph only).
#
# This stage is cheap. Its only purpose is to produce a `recipe.json` that
# changes ONLY when dependencies change (Cargo.toml / Cargo.lock), giving the
# `builder` stage a stable cache key for the dependency compile.
# ============================================================================
FROM chef AS planner

COPY idl/ idl/
COPY Cargo.toml Cargo.toml
COPY Cargo.lock Cargo.lock
COPY rust/ rust/

RUN cargo chef prepare --recipe-path recipe.json

# ============================================================================
# builder: cook dependencies into a durable layer, then build the workspace.
#
# `cargo chef cook` compiles ONLY third-party dependencies, writing them to
# ./target. Because this step's only input is recipe.json (and we do NOT mount
# a cache over ./target), its result is captured as a regular image layer:
#   * content-addressed on recipe.json -> reused on every build whose deps are
#     unchanged (the common case: app-only source change),
#   * never thrashed cross-arch (each arch builds its own layer),
#   * exportable to a registry (a `--mount=type=cache` dir can never be).
#
# The subsequent `cargo build` then compiles only the first-party workspace
# crates, reusing the cooked dependencies already present in ./target.
# ============================================================================
FROM chef AS cooked

ARG RELEASE_MODE=
ARG ENABLE_AVX512=
ARG LOG_SERVICE_CARGO_FEATURES=
ARG ADDRESS_SANITIZER

ENV RUSTFLAGS=${ADDRESS_SANITIZER:+'-Z sanitizer=address'}
ENV CC_x86_64_unknown_linux_gnu=${ADDRESS_SANITIZER:+gcc}
ENV CXX_x86_64_unknown_linux_gnu=${ADDRESS_SANITIZER:+g++}
ENV AR_x86_64_unknown_linux_gnu=${ADDRESS_SANITIZER:+ar}
ENV CARGO_INCREMENTAL=0

# Skip building these as they're not needed by images (and if Python bindings
# are built, the final binaries are unnecessarily linked against Python).
ENV EXCLUDED_PACKAGES="chromadb_rust_bindings chromadb-js-bindings chroma-benchmark "

# Packages whose bins we ship in images. Used for `cargo chef cook -p ...`
# because cook does not support `--exclude` (LukeMathWalker/cargo-chef#181);
# cooking the full workspace would also pull in pyo3/napi build deps.
ENV COOK_PACKAGES="chroma-cli garbage_collector chroma-load chroma-log-service s3heap-service worker rust-sysdb spanner-migrations"

# --- Dependency compile (durable layer, keyed on recipe.json) ----------------
# Note: cache mounts are kept ONLY for the crate download dirs (registry/git);
# the compiled output in ./target is intentionally a layer, not a mount, which
# is what makes cargo-chef effective.
COPY --from=planner /chroma/recipe.json recipe.json
RUN --mount=type=cache,sharing=locked,target=/usr/local/cargo/registry/ \
  --mount=type=cache,sharing=locked,target=/usr/local/cargo/git/ \
  if [ "$ENABLE_AVX512" = "1" ]; then \
  export CXXFLAGS="-mavx512f -mavx512dq -mavx512bw -mavx512vl" && \
  export CFLAGS="-mavx512f -mavx512dq -mavx512bw -mavx512vl" && \
  export RUSTFLAGS="${RUSTFLAGS} -C target-feature=+avx,+fma" ; \
  fi && \
  build_target=$( [ "${ADDRESS_SANITIZER}" = "1" ] && echo '--target x86_64-unknown-linux-gnu' || echo '' ) && \
  release_flag=$( [ "$RELEASE_MODE" = "1" ] && echo '--release' || echo '' ) && \
  cargo chef cook ${build_target} $(printf -- '-p %s ' $COOK_PACKAGES) ${release_flag} --recipe-path recipe.json

# BEGIN BORINGCACHE BENCHMARK TARGET CACHE STAGE
# Keep Cargo Chef's dependency output as an ordinary OCI layer, then use it to
# initialize the persistent target cache whenever that cache is new or absent.
FROM cooked AS builder
ARG TARGETARCH
# END BORINGCACHE BENCHMARK TARGET CACHE STAGE

# BEGIN BORINGCACHE BENCHMARK COMPILER CACHE PROOF
ARG BORINGCACHE_BENCHMARK_SCCACHE_PROOF=0
# END BORINGCACHE BENCHMARK COMPILER CACHE PROOF

# --- Workspace compile (first-party crates) ----------------------------------
COPY idl/ idl/
COPY Cargo.toml Cargo.toml
COPY Cargo.lock Cargo.lock
COPY rust/ rust/

# Note: Using flag ENABLE_AVX512 to build AVX512 optimizations for hnswlib, and
# AVX for Rust. Once Rust supports AVX512, the target-features will be updated
# to use AVX512.
# BEGIN BORINGCACHE BENCHMARK PERSISTENT TARGET CACHE
# Unlike an empty target mount, this cache starts from the `cooked` stage. It
# preserves Cargo's first-party fingerprints and outputs across source changes
# without giving up the dependency layer when the mutable cache is unavailable.
# END BORINGCACHE BENCHMARK PERSISTENT TARGET CACHE
RUN --mount=type=cache,id=chroma-target-${TARGETARCH},sharing=locked,from=cooked,source=/chroma/target,target=/chroma/target \
  --mount=type=cache,sharing=locked,target=/usr/local/cargo/registry/ \
  --mount=type=cache,sharing=locked,target=/usr/local/cargo/git/ \
  if [ "$ENABLE_AVX512" = "1" ]; then \
  export CXXFLAGS="-mavx512f -mavx512dq -mavx512bw -mavx512vl" && \
  export CFLAGS="-mavx512f -mavx512dq -mavx512bw -mavx512vl" && \
  export RUSTFLAGS="${RUSTFLAGS} -C target-feature=+avx,+fma" ; \
  fi && \
  build_target=$( [ "${ADDRESS_SANITIZER}" = "1" ] && echo '--target x86_64-unknown-linux-gnu' || echo '' ) && \
  release_flag=$( [ "$RELEASE_MODE" = "1" ] && echo '--release' || echo '' ) && \
  cargo build ${build_target} --workspace $(printf -- '--exclude %s ' $EXCLUDED_PACKAGES) ${release_flag} && \
  if [ -n "$LOG_SERVICE_CARGO_FEATURES" ]; then \
  cargo build ${build_target} -p chroma-log-service --bin log_service --features "$LOG_SERVICE_CARGO_FEATURES" ${release_flag}; \
  fi && \
  build_dir=$( [ "$RELEASE_MODE" = "1" ] && echo release || echo debug ) && \
  build_dir=$( [ "${ADDRESS_SANITIZER}" = "1" ] && echo "x86_64-unknown-linux-gnu/${build_dir}" || echo "${build_dir}" ) && \
  for bin in chroma garbage_collector_service chroma-load log_service heap_tender_service query_service compaction_service work_queue_service fn_consumer sysdb_service spanner_migration; do \
  cp "target/${build_dir}/${bin}" "./${bin}"; \
  done && \
  if [ "${BORINGCACHE_BENCHMARK_SCCACHE_PROOF}" = "1" ]; then \
  test "${RUSTC_WRAPPER##*/}" = "sccache" && \
  test -n "${SCCACHE_WEBDAV_ENDPOINT:-}" && \
  sccache_stats="$(sccache --show-stats --stats-format=json)" && \
  printf 'BORINGCACHE_SCCACHE_STATS=%s\n' "${sccache_stats}" && \
  printf '%s\n' "${sccache_stats}" | grep -Eq '"cache_(hits|misses)":\{"counts":\{[^}]*"Rust":[1-9][0-9]*'; \
  fi

FROM debian:stable-slim AS runner
ARG ADDRESS_SANITIZER

ENV ASAN_OPTIONS=${ADDRESS_SANITIZER:+'symbolize=1'}
ENV ASAN_SYMBOLIZER_PATH=${ADDRESS_SANITIZER:+'/usr/bin/llvm-symbolizer'}
# If ADDRESS_SANITIZER is set, set RUST_BACKTRACE to full. Otherwise, set it to 0.
ENV RUST_BACKTRACE=${ADDRESS_SANITIZER:+'full'}${ADDRESS_SANITIZER:-'0'}

RUN if [ "$ADDRESS_SANITIZER" = "1" ]; then apt-get update \
  && apt-get install -y build-essential llvm; \
  fi
RUN apt-get update && apt-get install -y dumb-init libssl-dev ca-certificates && rm -rf /var/lib/apt/lists/*

FROM runner AS cli

COPY --from=builder /chroma/rust/frontend/sample_configs/docker_single_node.yaml /config.yaml
COPY --from=builder /chroma/chroma /usr/local/bin/chroma

EXPOSE 8000

ENTRYPOINT [ "dumb-init", "--", "chroma" ]
CMD [ "run", "/config.yaml" ]

FROM runner AS garbage_collector
COPY --from=builder /chroma/garbage_collector_service .
ENTRYPOINT [ "sh", "-c", "ulimit -c 0 && exec ./garbage_collector_service" ]

FROM runner AS load_service
COPY --from=builder /chroma/chroma-load .
ENTRYPOINT [ "sh", "-c", "ulimit -c 0 && exec ./chroma-load" ]

FROM runner AS log_service
COPY --from=builder /chroma/log_service .
ENTRYPOINT [ "sh", "-c", "ulimit -c 0 && exec ./log_service" ]

FROM runner AS heap_tender_service
COPY --from=builder /chroma/heap_tender_service .
ENTRYPOINT [ "sh", "-c", "ulimit -c 0 && exec ./heap_tender_service" ]

FROM runner AS query_service
COPY --from=builder /chroma/query_service .
ENTRYPOINT [ "sh", "-c", "ulimit -c 0 && exec ./query_service" ]

FROM runner AS compaction_service
COPY --from=builder /chroma/compaction_service .
ENTRYPOINT [ "sh", "-c", "ulimit -c 0 && exec ./compaction_service" ]

FROM runner AS work_queue_service
COPY --from=builder /chroma/work_queue_service .
ENTRYPOINT [ "sh", "-c", "ulimit -c 0 && exec ./work_queue_service" ]

FROM runner AS fn_consumer
COPY --from=builder /chroma/fn_consumer .
ENTRYPOINT [ "sh", "-c", "ulimit -c 0 && exec ./fn_consumer" ]

FROM runner AS sysdb_service
COPY --from=builder /chroma/sysdb_service .
ENTRYPOINT [ "sh", "-c", "ulimit -c 0 && exec ./sysdb_service" ]

FROM runner AS rust-sysdb-migration
COPY --from=builder /chroma/spanner_migration .
ENTRYPOINT ["sh", "-c", "ulimit -c 0 && exec ./spanner_migration" ]
