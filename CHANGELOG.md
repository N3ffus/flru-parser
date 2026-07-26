# Changelog

All notable changes are documented here. The project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.4.0] - 2026-07-26

### Security

- Strip explicit authorization, cookie, and proxy authorization headers on cross-origin
  redirects.
- Pin release and CI GitHub Actions to immutable commit SHAs.
- Restrict manual publishing to TestPyPI; production publishing requires a release tag.

### Fixed

- Admit one logical request to the circuit breaker only once across its retry cycle.
- Guarantee bounded streaming pipeline shutdown after producer errors, cancellation, blocked
  responses, and early consumer exit.
- Use direct access only after configured proxies are unavailable.
- Reset legacy incremental known-item streaks when no resumable page is present.
- Create collision-resistant blocked-response diagnostic directories.

### Added

- `StreamItemResult` and `FLClient.iter_project_details_result()` for observable per-item
  streaming failures.
- Multi-surface live canary checks and structural HTML fingerprints.
- Distribution size and documentation example checks.
- Release operator guidance in `docs/RELEASING.md`.

### Changed

- Production source distributions no longer bundle the test fixture corpus.
- Content fingerprint behavior is now explicitly named and documented.

### Testing

- Added regression coverage for streaming lifecycle, half-open recovery, proxy fallback, and
  redirect credential handling.

### Compatibility

- Existing imports and `iter_project_details()` behavior remain available; changes are additive.

## [0.3.2] - 2026-07-26

### Fixed

- Parse current FL.ru catalog cards as complete cards instead of mistaking title elements
  for card containers, restoring descriptions, budgets, kinds, and other card fields.
- Follow FL.ru's `/projects/page-N/` pagination so `pages="all"` traverses the catalog.
- Default the high-level projects APIs to orders (`kind=1`), preventing vacancies from
  appearing among orders unless explicitly requested through `types`.
- Keep package and parser metadata versions synchronized.

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
