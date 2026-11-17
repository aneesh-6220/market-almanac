# Security policy

## Supported versions

Security fixes are made on the latest release on the default branch.

## Reporting a vulnerability

Please report vulnerabilities privately, using the repository host's private vulnerability
reporting (for GitHub: *Security → Report a vulnerability*). Do not open a public issue. Include
affected version or commit, steps to reproduce and impact. You can expect an acknowledgement
within a week.

## Design measures

- **Secrets** are read only from environment variables, held as `SecretStr`, never logged
  (a redacting log formatter removes identifiers, bearer tokens and database passwords), never
  included in cache keys, and never sent to the browser. `.env` is git-ignored; `.env.example`
  documents every variable without values.
- **Outbound requests** go only to an allow-list of provider hosts. The API never fetches
  user-supplied URLs.
- **The API is read-only** (`GET`), validates every identifier against strict patterns, caps
  page sizes, rate-limits per client IP and returns generic messages for unexpected errors
  (no stack traces).
- **CORS** is limited to configured origins and `GET`.
- **Containers** run as non-root users.

## Handling credentials

If a credential is ever committed or logged, rotate it at the provider immediately, then remove
it from history. HDX HAPI app identifiers encode an application name and email address; treat
them as personal data.
