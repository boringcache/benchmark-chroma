# syntax=docker/dockerfile:1

# ============================================================================
# build-tools: shared Rust, protoc, and sccache toolchain.
#
# This slow-changing setup stage is inherited by the builder. Cargo downloads
# and compiled output are persisted independently with BuildKit cache mounts.
# ============================================================================
FROM rust:1.92.0 AS build-tools

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

WORKDIR /chroma

# ============================================================================
# builder: compile Chroma with persistent Cargo and compiler caches.
# ============================================================================
FROM build-tools AS builder

# BEGIN BORINGCACHE BENCHMARK CARGO CACHE MOUNTS
ARG TARGETARCH
# BEGIN BORINGCACHE BENCHMARK COMPILER CACHE PROOF
ARG BORINGCACHE_BENCHMARK_SCCACHE_PROOF=0
# END BORINGCACHE BENCHMARK COMPILER CACHE PROOF
# END BORINGCACHE BENCHMARK CARGO CACHE MOUNTS

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

# --- Workspace compile (first-party crates) ----------------------------------
COPY idl/ idl/
COPY Cargo.toml Cargo.toml
COPY Cargo.lock Cargo.lock
COPY rust/ rust/

# Note: Using flag ENABLE_AVX512 to build AVX512 optimizations for hnswlib, and
# AVX for Rust. Once Rust supports AVX512, the target-features will be updated
# to use AVX512.
# BEGIN BORINGCACHE BENCHMARK CARGO CACHE MOUNTS
# BoringCache persists Cargo's registry, Git checkouts, and target output across
# ephemeral builders. Target output is architecture-scoped to prevent mixing it.
# END BORINGCACHE BENCHMARK CARGO CACHE MOUNTS
RUN --mount=type=cache,id=chroma-target-${TARGETARCH},sharing=locked,target=/chroma/target \
  --mount=type=cache,sharing=locked,target=/usr/local/cargo/registry/ \
  --mount=type=cache,sharing=locked,target=/usr/local/cargo/git/ \
  if [ "$ENABLE_AVX512" = "1" ]; then \
  export CXXFLAGS="-mavx512f -mavx512dq -mavx512bw -mavx512vl" && \
  export CFLAGS="-mavx512f -mavx512dq -mavx512bw -mavx512vl" && \
  export RUSTFLAGS="${RUSTFLAGS} -C target-feature=+avx,+fma" ; \
  fi && \
  build_target=$( [ "${ADDRESS_SANITIZER}" = "1" ] && echo '--target x86_64-unknown-linux-gnu' || echo '' ) && \
  release_flag=$( [ "$RELEASE_MODE" = "1" ] && echo '--release' || echo '' ) && \
  if [ -f "rust/.boringcache-warm-source-change" ] && [ "${BORINGCACHE_BENCHMARK_SCCACHE_PROOF}" = "1" ]; then \
  test -n "$(find /chroma/target -mindepth 1 -print -quit)" && \
  printf 'BORINGCACHE_CARGO_TARGET_RESTORED=1\n'; \
  fi && \
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
  test -n "$(find /chroma/target -mindepth 1 -print -quit)" && \
  printf 'BORINGCACHE_CARGO_TARGET_READY=1\n' && \
  sccache_stats="$(sccache --show-stats --stats-format=json)" && \
  printf 'BORINGCACHE_SCCACHE_STATS=%s\n' "${sccache_stats}"; \
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
