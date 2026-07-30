// Point every Rust Bake target at the generated target-mount Dockerfile. This
// file is applied before the optional sccache override, so the latter can
// compose both benchmark options without changing Chroma's target graph.

target "rust-log-service" {
  dockerfile = "rust/Dockerfile.target-mountcache"
}

target "rust-sysdb-service" {
  dockerfile = "rust/Dockerfile.target-mountcache"
}

target "rust-sysdb-migration" {
  dockerfile = "rust/Dockerfile.target-mountcache"
}

target "rust-frontend-service" {
  dockerfile = "rust/Dockerfile.target-mountcache"
}

target "query-service" {
  dockerfile = "rust/Dockerfile.target-mountcache"
}

target "compactor-service" {
  dockerfile = "rust/Dockerfile.target-mountcache"
}

target "garbage-collector" {
  dockerfile = "rust/Dockerfile.target-mountcache"
}

target "load-service" {
  dockerfile = "rust/Dockerfile.target-mountcache"
}

target "work-queue-service" {
  dockerfile = "rust/Dockerfile.target-mountcache"
}

target "fn-consumer" {
  dockerfile = "rust/Dockerfile.target-mountcache"
}
