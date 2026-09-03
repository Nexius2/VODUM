# Route access inventory

VODUM applies one application-level access guard registered directly by
`create_app()`. Route modules do not own or enable this protection.

## Intentionally unauthenticated resources

Only the following resources are classified as `public`:

- `/favicon.ico`: browser icon.
- `/static...`: versioned application assets.
- `/branding/...`: public brand images used by login pages.
- `/set_language...`: language selection.
- `/health...`: container and reverse-proxy health checks.
- `/login/artwork/...`: constrained login artwork proxy; it never exposes
  provider credentials.

## Authentication and setup flows

The exact administrator authentication routes are listed in
`ADMIN_AUTH_EXACT`. The one-shot Plex setup routes are listed in
`SETUP_FLOW_EXACT`; other `/setup...` routes use the `setup` scope.

Portal login, activation, reset and provider callback routes use the separate
`portal_auth` scope. Other `/portal...` and `/api/portal/...` routes require a
valid portal user or administrator principal.

Every path that does not match an explicit rule is classified as `admin` and
therefore fails closed behind administrator authentication.

Public and setup prefixes are boundary-aware. Lookalike paths such as
`/health-debug`, `/static-admin` and `/setup-secret` remain classified as
`admin`.

## Audit result — 2026-08-28

The registered Flask URL map contained 178 rules during the audit: 132 admin,
17 authenticated portal, 11 portal authentication, 8 administrator
authentication, 6 setup and 4 public rules. Anonymous requests to admin rules
redirect to administrator login, while an authenticated portal user receives
403. An administrator principal is accepted.

The Jellyfin portal login endpoint (`POST /portal/auth/jellyfin`) was found to
be incorrectly classified as an authenticated portal page. It is now an
explicit `portal_auth` route, subject to the configured portal hostname, its
existing rate limit and provider authentication checks.
