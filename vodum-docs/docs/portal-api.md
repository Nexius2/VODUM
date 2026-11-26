# User portal API

The first public-facing API is intentionally read-only and session-authenticated.
It is not an anonymous API and does not issue permanent API keys.

`GET /api/portal/v1/me` returns only the authenticated portal user's profile,
subscription summary and media access. The server derives the user identifier
from the revocable portal session; query-string or body `user_id` values are
ignored. Responses use `Cache-Control: no-store` and are limited to 120 requests
per 15 minutes and client IP. A limit response is HTTP 429 with `Retry-After`.

The response excludes provider identifiers, tokens, passwords, internal server
URLs, IP addresses, raw provider payloads and global statistics. Version `v1`
may only receive backward-compatible additions; breaking changes require a new
URL version.
