# Security

## Network access

```env
VODUM_IP_FILTER=1
VODUM_ALLOWED_NETS=127.0.0.1/32,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16
```

Behind a reverse proxy, enable forwarded-header trust only for its network:

```env
VODUM_TRUST_PROXY=1
VODUM_TRUSTED_PROXY_NETS=127.0.0.1/32,::1/128,172.18.0.0/16
```

Use HTTPS, a firewall and the narrowest possible CIDRs.

## Web protections

VODUM requires administrator authentication, rate-limits failed logins, rejects
unsafe external `next` redirects and applies CSRF validation to POST/PUT/PATCH/
DELETE requests. Cookies are HttpOnly; SameSite and Secure are configurable.

## Secrets and backups

SMTP passwords, Discord tokens and provider tokens are encrypted in SQLite.
The persistent key defaults to `/appdata/vodum.encryption_key` and may be changed
with `VODUM_ENCRYPTION_KEY_FILE` or supplied using `VODUM_ENCRYPTION_KEY`.

Full ZIP backups contain the key and encrypted values. Raw databases do not.
Treat both logs and backups as sensitive.

## Upload limits

`VODUM_MAX_UPLOAD_MB`, `VODUM_MAX_ZIP_EXTRACTED_MB` and
`VODUM_MAX_ZIP_MEMBERS` bound requests and restored archives. A reverse proxy
must allow the desired request size too.
