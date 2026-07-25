# Selector maintenance

FL.ru pages are HTML rather than a versioned public API, so selector maintenance is an expected operational task.

## Drift signals

The parser intentionally raises `SelectorDriftError` when candidate project links are present but no typed project cards can be extracted. `ParseDiagnostics` also exposes:

- matched selector names;
- candidate link count;
- parsed card count;
- missing required fields;
- warnings;
- field provenance;
- page fingerprint;
- confidence score.

## Safe update procedure

1. Save the failing HTML using `store_failed_html=True`.
2. Remove personal data, cookies, tokens, and unrelated user content before committing a fixture.
3. Add the sanitized HTML under `tests/fixtures/`.
4. Write a regression test that fails before selector changes.
5. Prefer structured sources in this order: JSON-LD, Open Graph/meta, semantic attributes, stable URL patterns, CSS selectors, then text/regex fallback.
6. Keep existing fallbacks unless they are demonstrably incorrect.
7. Run `make check` and inspect the diagnostic confidence on both old and new fixtures.

Never add CAPTCHA-solving or authentication-bypass logic.
