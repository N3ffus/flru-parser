# Changelog

All notable changes are documented here. The project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.3.1] - 2026-07-26

### Added

- Block-response diagnostics: sanitized response headers and body are saved under
  `.flru-debug/blocked-.../` when CAPTCHA or anti-bot protection is detected.
- `BlockedError.status_code` and `BlockedError.debug_path` for programmatic diagnostics.
- Persistent server-set cookies shared by the transport's existing clients.
- A conservative 0.5-second minimum interval between request starts by default.

### Changed

- CAPTCHA responses are never retried; batches and iterators stop immediately on a block.
- Retry handling honors `Retry-After` for both HTTP 429 and HTTP 503 responses.
- Block detection now requires strong evidence and ignores isolated `captcha` text in normal scripts.

## [0.3.0] - 2026-07-25

### Added

- Recommended high-level async `Client` with flat production options.
- Simple methods: `projects`, `stream_projects`, `project`, `user`, `freelancers`, `new_projects`, `page`, and `stats`.
- One-shot async helpers: `fetch_projects`, `fetch_project`, `fetch_user`, and `fetch_freelancers`.
- Matching synchronous `flru.sync.Client` and one-shot sync functions.
- Direct project filters through `query`, `category`, budgets, types, and `with_budget`.
- Automatic SQLite state handling when `new_projects()` receives a filesystem path.
- Convenience model properties: `budget_min`, `budget_max`, `currency`, `customer_username`, `Money.amount`, and `to_dict()`.
- Russian and English aliases for common project types.
- Dedicated simple API documentation and concise examples.

### Changed

- Documentation now presents the simple API first and keeps `FLClient` as the advanced escape hatch.
- The synchronous facade uses a dedicated event-loop thread and can coexist safely with async applications.
- Package version and parser metadata updated to 0.3.0.

### Compatibility

- `FLClient`, configuration dataclasses, typed filters, batch APIs, state stores, parsers, and all 0.2.x low-level methods remain available.


## [0.2.0] - 2026-07-25

### Added

- Parse diagnostics, confidence scores, field provenance, fingerprints, and explicit selector-drift errors.
- Pagination traversal based on `next_url` and `has_next`.
- Typed `ProjectFilters` and `ProjectType`.
- `BatchResult`/`BatchError` APIs.
- Incremental crawling with checkpoints and content hashes.
- Memory, SQLite, optional PostgreSQL, and optional Redis state stores.
- Bounded project-detail worker pipeline with backpressure.
- Per-endpoint/per-proxy circuit breakers.
- Shared 429 cooldown, retry deadlines, and total delay budgets.
- Stable user-agent per session/proxy.
- Safe redirect and allowed-host enforcement.
- Proxy credential redaction.
- Timezone-aware dates and source/schema/parser metadata.
- Structured logging, Prometheus, and OpenTelemetry adapters.
- Synchronous facade and live canary CLI.
- PyPI release workflow using Trusted Publishing.

### Changed

- `ClientConfig` is immutable and `from_cookie_file()` no longer mutates a caller-provided config.
- Profile subpages and multi-page sections are fetched concurrently.
- Empty catalog pages are no longer silently accepted unless classified as catalog end.

### Compatibility

- Existing `FLClient`, `get_projects()`, `get_projects_batch()`, `get_project()`, and profile methods remain available.

### Fixed

- Prevented duplicate retry metric increments.
- Made `ClientConfig.headers` and `ClientConfig.cookies` immutable snapshots.
- Ensured proxy-health output always redacts credentials.
- Hardened optional PostgreSQL JSONB decoding for both string and decoded-object codecs.
- Added a scheduled dependency-vulnerability audit workflow.

## [0.1.1] - 2026-07-25

- Counted one circuit-breaker failure per logical request rather than per retry.
- Prevented direct connections from entering proxy cooldown.
- Added the HTTP/2 dependency extra.

## [0.1.0] - 2026-07-25

- Initial asynchronous parser/client release.
