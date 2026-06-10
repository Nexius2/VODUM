---
title: 🔐 Security
---

<!-- Auto-generated improved docs for GitHub Pages (MkDocs Material) -->

<div align="left">

# 🔐 Security

<span class="hint-badge">IP filter • Secrets • Tokens • Best practices</span>

<br><br>

</div>


## IP filtering

Use:

- `VODUM_IP_FILTER=1`
- `VODUM_ALLOWED_NETS=...`

to restrict access to trusted networks.

## Reverse proxy trust

When `VODUM_TRUST_PROXY=1`, configure `VODUM_TRUSTED_PROXY_NETS` with the
address or subnet used by the reverse proxy. Forwarded headers are ignored
when a connection does not come from one of these networks.

Example for a Docker bridge network:

```env
VODUM_TRUST_PROXY=1
VODUM_TRUSTED_PROXY_NETS=127.0.0.1/32,::1/128,172.18.0.0/16
```

Prefer the smallest subnet that contains the reverse proxy.

## Upload limits

Uploads and restored ZIP archives are limited by default:

```env
VODUM_MAX_UPLOAD_MB=4096
VODUM_MAX_ZIP_EXTRACTED_MB=8192
VODUM_MAX_ZIP_MEMBERS=10000
```

The defaults allow large Tautulli databases while still rejecting unexpectedly
large requests and backup archives. A reverse proxy may enforce its own upload
limit, which must also be configured when importing large files.

---

## Secrets and tokens

- Plex tokens / Jellyfin API keys should never be exposed publicly.
- Use strong admin credentials.
- Keep `VODUM_SECRET_KEY` private (required for secure sessions).

SMTP passwords, Discord tokens, Plex/Jellyfin server tokens and Tautulli API
keys are encrypted before being stored in SQLite. Existing plaintext values are
encrypted automatically during startup.
Vodum generates a persistent encryption key at:

```text
/appdata/vodum.encryption_key
```

The location can be changed with `VODUM_ENCRYPTION_KEY_FILE`, or the key can be
provided directly through `VODUM_ENCRYPTION_KEY`.

Vodum full ZIP backups include this key and restore it automatically, making
them self-contained. Treat full backups as highly sensitive because they
contain both the encrypted secrets and the key required to decrypt them.

Raw `.db` and `.sqlite` exports do not contain the key. Keep a separate copy of
the key if those formats are used. When `VODUM_ENCRYPTION_KEY` is supplied as
an environment variable, it must match the key contained in a restored backup.

Vodum decrypts these values only while using them. Linked Plex servers are
matched after decryption rather than by comparing encrypted values in SQL.

Authenticated redirects are accepted only when their destination matches one
of the media server origins explicitly configured in `url`, `local_url` or
`public_url`. Remote servers remain supported; this only prevents a configured
server from forwarding its token to an unrelated destination.

The server-token field is intentionally blank when editing a server. Leaving
it blank preserves the current token, while entering a value replaces it.

---

## Recommended deployment

- Put VODUM behind a reverse proxy (HTTPS)
- Restrict access by IP whenever possible
- Do not expose VODUM publicly without authentication + firewall

Vodum uses Waitress as its production WSGI server. Its listening port and
worker thread count can be configured with:

```env
VODUM_PORT=5000
VODUM_WAITRESS_THREADS=6
```

The Waitress request-body limit is automatically aligned with
`VODUM_MAX_UPLOAD_MB`, so large Tautulli imports are not blocked by the WSGI
server before reaching Vodum.
