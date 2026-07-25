# Architecture

`flru-parser` is split into explicit layers so HTTP behavior, HTML extraction, persistence, and application logic can evolve independently.

```text
Client (simple API) / flru.sync.Client
 └─ FLClient (advanced async API)
     ├─ ResilientTransport
     │   ├─ AsyncRateLimiter / shared 429 cooldown
     │   ├─ CircuitBreakerRegistry
     │   ├─ ProxyPool
     │   ├─ redirect and host security policy
     │   └─ metrics and event handlers
     ├─ parsers
     │   ├─ projects
     │   ├─ freelancers
     │   ├─ users
     │   └─ generic page extraction
     ├─ typed Pydantic models + diagnostics
     └─ crawl state
         ├─ Memory
         ├─ SQLite
         ├─ PostgreSQL
         └─ Redis
```

## Public API layers

- `flru.Client` is the recommended async facade. It converts flat arguments into immutable production configuration and offers task-oriented methods.
- `flru.sync.Client` mirrors the simple methods on a dedicated event-loop thread.
- `flru.FLClient` exposes page-level, batch, pipeline and diagnostic primitives.
- The simple async client subclasses `FLClient`, so applications can start simple and use low-level methods without replacing the client instance.

## Design principles

1. **Read-only by design.** The public API does not submit proposals, messages, authentication challenges, or mutations.
2. **No silent empty data.** Strict parsing distinguishes a real catalog end from selector drift and unexpected pages.
3. **Bounded concurrency.** Rate limits and bounded queues prevent unbounded task and memory growth.
4. **Failure isolation.** Circuit breakers can be scoped by endpoint and proxy; batch APIs preserve partial successes.
5. **Safe defaults.** Redirect targets are allowlisted, proxy credentials are redacted, and CAPTCHA pages are detected rather than bypassed.
6. **Reproducibility.** Results include fetch timestamps, parser/schema versions, page fingerprints, provenance, and content hashes.

## Request lifecycle

1. Validate the target URL against `allowed_hosts`.
2. Acquire a healthy proxy or direct route.
3. Check the scoped circuit breaker.
4. Wait for shared rate-limit capacity and any server-directed cooldown.
5. Execute a request and validate each redirect target.
6. Detect authentication, blocking, and retryable HTTP responses.
7. Retry within both attempt and total-time budgets.
8. Parse HTML into typed models with diagnostics.
9. Raise a typed error on likely selector drift or unexplained empty data.
10. Optionally persist incremental state and a crawl checkpoint.

## Extension points

- Add selectors and extraction fallbacks under `src/flru/parsers/`.
- Implement `CrawlStateStore` for another persistence backend.
- Supply a callable `EventHandler` for custom telemetry.
- Use `get_page()` when a public FL.ru page does not yet have a dedicated typed model.
