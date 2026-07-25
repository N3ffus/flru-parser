# Security policy

## Supported versions

Security fixes are provided for the latest released minor version.

## Reporting a vulnerability

Do not open a public issue for a vulnerability involving credential exposure, redirect/host validation, cookie handling, proxy secrets, or dependency compromise. Use a private GitHub Security Advisory in the repository.

Include the affected version, reproduction steps, impact, and a minimal proof of concept. Do not include real FL.ru credentials or private user data.

## Security boundaries

This package is read-only. It does not bypass CAPTCHA, automate login, submit responses, or call undocumented write endpoints. Redirect targets are validated against an allowlist before requests are sent, and proxy credentials are redacted from events and health snapshots.
