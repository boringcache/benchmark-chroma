// Keep Chroma's upstream Bake graph unchanged. Only point the Rust targets at
// the generated fixture that makes the sccache executable available; the
// BoringCache CLI supplies all cache and secret wiring at runtime.

target "rust-log-service" {
  dockerfile = "rust/Dockerfile.sccache"
}

target "rust-sysdb-service" {
  dockerfile = "rust/Dockerfile.sccache"
}

target "rust-sysdb-migration" {
  dockerfile = "rust/Dockerfile.sccache"
}

target "rust-frontend-service" {
  dockerfile = "rust/Dockerfile.sccache"
}

target "query-service" {
  dockerfile = "rust/Dockerfile.sccache"
}

target "compactor-service" {
  dockerfile = "rust/Dockerfile.sccache"
}

target "garbage-collector" {
  dockerfile = "rust/Dockerfile.sccache"
}

target "load-service" {
  dockerfile = "rust/Dockerfile.sccache"
}

target "work-queue-service" {
  dockerfile = "rust/Dockerfile.sccache"
}

target "fn-consumer" {
  dockerfile = "rust/Dockerfile.sccache"
}
