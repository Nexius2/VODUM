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
| `VODUM_ALLOWED_NETS` | CIDRs allowed by the application IP filter |

`VODUM_IMPORTS_DIR` defaults to an `imports` directory beside
`DATABASE_PATH`. If the database location changes, ensure its parent and all
configured data directories are persistent and writable.

Additional security overrides include `VODUM_SECRET_KEY`,
`VODUM_ENCRYPTION_KEY`, cookie settings and authentication rate-limit values.
Prefer persistent generated keys over inline secrets when possible.

## Initial administrator account

The installation wizard offers three choices: **Plex**, **Jellyfin**, or a
**local VODUM account**. This selects how you sign in to administration. With
either media provider, additional Plex/Jellyfin servers and media accounts can
be added after installation; the first connection does not limit the instance
to that server or those media accounts. VODUM still has a single administrator
account, with separately linked provider identities.

At the media-server step, select the suggested Plex servers and click
**Continue** to validate and add them before advancing. The success message
lists the servers ready to use. If any selected server fails, the wizard stays
on this step, retains successful additions, and keeps failed servers selected
for retry. **Add more servers** expands the separate manual-entry form.

For Jellyfin, enter the server's base address (including any configured base
path). Quick Connect must be enabled. In an already signed-in Jellyfin client,
open the administrator account settings, choose **Quick Connect**, enter the
code displayed by VODUM, then click **I approved the connection** in VODUM.
An active Jellyfin administrator account is required. The request expires after
five minutes; an approval still pending can be checked again without restarting.

VODUM validates the server and the authenticated user, adds that first server
using the existing validated-server workflow, and stores its access token
encrypted. It does not request or retain the Jellyfin password. Subsequent
VODUM logins offer **Sign in with Jellyfin** and must authenticate the same
server/user identity; another administrator on that server cannot use the link.
The server must remain reachable and Quick Connect enabled for these logins.
Changing its base address requires updating the binding, rather than accepting
an arbitrary server address on the public login page. This initial setup flow
does not add a Jellyfin identity-management screen to Security settings.

The local email/password form appears only when local credentials exist.
Provider-only installations retain their provider login buttons. The Jellyfin
portal login is separate and does not grant VODUM administrator access.

The Jellyfin binding uses the existing provider-neutral administrator identity
store. Startup adds the `admin_auth_flows` table and its expiry index to enforce
single-use approvals on the server, including if an old browser cookie is
replayed. No existing data is rewritten. Deploy the bootstrap and Python modules,
templates and five translation files together, then restart VODUM before using
the new login. Verification
of this flow used local databases and simulated Jellyfin responses; it is not
a production validation.

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
