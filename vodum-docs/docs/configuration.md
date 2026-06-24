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
| `VODUM_DEBUG` | Debug mode (`0` or `1`) |
| `VODUM_MAX_UPLOAD_MB` | Maximum complete request size |
| `VODUM_MAX_ZIP_EXTRACTED_MB` | Maximum restored ZIP size after extraction |
| `VODUM_MAX_ZIP_MEMBERS` | Maximum ZIP entry count |
| `VODUM_TRUST_PROXY` | Enable trusted forwarded headers |
| `VODUM_TRUSTED_PROXY_NETS` | CIDRs allowed to supply forwarded headers |
| `VODUM_ALLOWED_NETS` | CIDRs allowed by the application IP filter |

`VODUM_IMPORTS_DIR` defaults to an `imports` directory beside
`DATABASE_PATH`. If the database location changes, ensure its parent and all
configured data directories are persistent and writable.

Additional security overrides include `VODUM_SECRET_KEY`,
`VODUM_ENCRYPTION_KEY`, cookie settings and authentication rate-limit values.
Prefer persistent generated keys over inline secrets when possible.
