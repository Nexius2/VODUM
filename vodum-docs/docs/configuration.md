# Deployment configuration

Compose loads `.env`. Restart the container after changing environment values.

| Variable | Purpose |
|---|---|
| `TZ` | Container timezone |
| `DATABASE_PATH` | SQLite database path |
| `VODUM_LOG_DIR` | Persistent log directory |
| `VODUM_BACKUP_DIR` | Persistent backup directory |
| `VODUM_IMPORTS_DIR` | Optional import/restore directory override |
| `VODUM_ENCRYPTION_KEY_FILE` | Persistent encryption-key path |
| `VODUM_PORT` | Waitress listening port |
| `VODUM_WAITRESS_THREADS` | Waitress worker threads |
| `VODUM_HTTP_GZIP_LEVEL` | Text response compression level, from 1 to 9 (default: 6) |
| `VODUM_BACKUP_SNAPSHOT_TIMEOUT_SECONDS` | Time budget in seconds for creating the SQLite backup snapshot |
| `VODUM_DEBUG` | Debug mode (`0` or `1`) |
| `VODUM_MAX_UPLOAD_MB` | Maximum complete request size |
| `VODUM_MAX_ZIP_EXTRACTED_MB` | Maximum restored ZIP size after extraction |
| `VODUM_MAX_ZIP_MEMBERS` | Maximum ZIP entry count |
| `VODUM_TRUST_PROXY` | Enable trusted forwarded headers |
| `VODUM_TRUSTED_PROXY_NETS` | CIDRs allowed to supply forwarded headers |
| `VODUM_ALLOWED_NETS` | CIDRs allowed by the application IP filter, including the [Dashboard API](api.md) |
| `VODUM_IP_FILTER` | Application IP filter, on by default (`0` to turn it off) |
| `VODUM_RESET_FILE` | Administrator reset file (default `/appdata/password.reset`), see [Troubleshooting](troubleshooting.md#locked-out-of-administration) |
| `VODUM_RESET_MAGIC` | Text the reset file must contain (default `RECOVER`) |

`VODUM_IMPORTS_DIR` defaults to an `imports` directory beside
`DATABASE_PATH`. If the database location changes, ensure its parent and all
configured data directories are persistent and writable.

Additional security overrides include `VODUM_SECRET_KEY`,
`VODUM_ENCRYPTION_KEY`, cookie settings and authentication rate-limit values.
Prefer persistent generated keys over inline secrets when possible.

## First-run wizard and administrator sign-in

The wizard (Plex, Jellyfin or local administrator account) is described in
[Installation & upgrades](getting-started.md#first-run-wizard). To recover a lost
administrator password, see [Troubleshooting](troubleshooting.md#locked-out-of-administration).

## Response-time diagnostics

Optional route, SQLite, provider/cache, HTTP-worker and supported media-job queue
timings are described in [Performance](performance.md), including their limits
and the CSV reporting commands. They are deployment environment settings and
require a process restart to take effect.

## Separate administrator hostname

When administration and the public portal use different virtual hosts, set the
explicit administrator URL/host (`VODUM_ADMIN_PUBLIC_URL` or
`VODUM_ADMIN_PUBLIC_HOST`) alongside the portal public URL. With one shared host,
role/session controls still separate administration and the portal. Hostnames do
not replace permission checks or a correctly restricted reverse proxy.
