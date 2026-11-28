# Dashboard API

VODUM has a read-only API for dashboards such as Homepage, Grafana or Homarr,
and for your own scripts. It only reads data: nothing can be created, changed
or deleted through it.

This page takes you from creating a token to a working dashboard.

## Quick start

1. Open **Settings**. The **API access** card is in the right column, under
   **System settings**.
2. Enter a name for the token, for example `Homepage`. Use one token per
   application so you can revoke them separately.
3. Tick what the token may read (see [Access](#access)). **Statistics** is
   ticked by default.
4. Click **Create token**. A window opens over the page with the token.
5. Copy the token now. It is shown only once: VODUM keeps a fingerprint of it,
   not the token itself. If you lose it, revoke it and create a new one.
6. Click **Done**, then test the token:

```bash
curl -H "Authorization: Bearer vodum_xxxxxxxx" http://YOUR_SERVER_IP:8097/api/v1/status
```

The answer should look like:

```json
{"api_version": 1, "app": "VODUM", "version": "26.11.26 b1714"}
```

Replace `YOUR_SERVER_IP:8097` with the address you use to open VODUM.

## Manage tokens

The **API access** card lists every token with its access, its creation date,
its last use and its number of calls. Use it to spot a token that is no longer
used.

**Revoke** stops a token at once, after a confirmation. Dashboards using it
then get `401` errors. A revoked token stays in the list, marked **Revoked**,
and cannot be reactivated.

You can keep up to 20 active tokens.

## Access

Each token reads only what it was given when it was created. To change the
access of a token, create a new one and revoke the old one.

| Access in Settings | Endpoint | What it returns |
|---|---|---|
| Any token | `GET /api/v1/status` | VODUM and API versions |
| Statistics | `GET /api/v1/stats` | Live playback, user and server counts |
| Servers | `GET /api/v1/servers` | Each server with its state, playback and CPU/RAM |
| Playback | `GET /api/v1/sessions` | Each current playback |
| User counts | `GET /api/v1/users/summary` | Users by status and by subscription |

## Send the token

Send the token in a header, never in the URL:

```
Authorization: Bearer vodum_xxxxxxxx
```

`X-Api-Key: vodum_xxxxxxxx` also works for tools that cannot send a Bearer
header. A token in the query string (`?token=...`) is ignored.

Only `GET` requests are accepted.

## Endpoints

### `GET /api/v1/status`

Use it to check that the address and the token work. Any valid token can call
it.

```bash
curl -H "Authorization: Bearer vodum_xxxxxxxx" http://YOUR_SERVER_IP:8097/api/v1/status
```

```json
{"api_version": 1, "app": "VODUM", "version": "26.11.26 b1714"}
```

### `GET /api/v1/stats`

Requires **Statistics**.

```bash
curl -H "Authorization: Bearer vodum_xxxxxxxx" http://YOUR_SERVER_IP:8097/api/v1/stats
```

```json
{
  "servers": {"online": 3, "offline": 1, "total": 4, "unknown": 0},
  "sessions": {"direct_plays": 2, "live": 3, "transcodes": 1},
  "users": {"active": 42, "expired": 5, "expiring_soon": 2, "expiring_soon_days": 7}
}
```

- `sessions` counts playback seen in the last 5 minutes, as on the dashboard.
- `users.active` includes users in their notice or reminder period.
- `users.expiring_soon` counts active users whose subscription ends within
  `expiring_soon_days` days.
- `servers` counts every configured server, including Sonarr, Radarr and Seerr.
  `unknown` is a server that has not been checked yet.

### `GET /api/v1/servers`

Requires **Servers**.

```bash
curl -H "Authorization: Bearer vodum_xxxxxxxx" http://YOUR_SERVER_IP:8097/api/v1/servers
```

```json
{"servers": [
  {"id": 1, "name": "MovieEmpire", "type": "plex", "status": "online",
   "live_sessions": 2, "transcodes": 1, "cpu_pct": 12.5, "ram_pct": 40.0},
  {"id": 3, "name": "Radarr", "type": "radarr", "status": "online",
   "live_sessions": 0, "transcodes": 0, "cpu_pct": null, "ram_pct": null}
]}
```

- `status` is `online`, `offline` or `unknown`.
- `cpu_pct` and `ram_pct` are only available for Plex, from the last
  10 minutes. They are `null` otherwise.
- Server addresses and keys are never returned.

### `GET /api/v1/sessions`

Requires **Playback**.

```bash
curl -H "Authorization: Bearer vodum_xxxxxxxx" http://YOUR_SERVER_IP:8097/api/v1/sessions
```

```json
{"count": 1, "sessions": [
  {"title": "Pilot", "grandparent_title": "Show", "parent_title": "Season 1",
   "media_type": "episode", "state": "playing", "server": "MovieEmpire",
   "provider": "plex", "username": "alice", "progress_pct": 50.0,
   "progress_ms": 600000, "duration_ms": 1200000, "playback": "transcode",
   "video_source": "4K HEVC HDR", "video_stream": "1080p H.264",
   "video_transcoded": true}
]}
```

- For an episode, `title` is the episode, `grandparent_title` the series and
  `parent_title` the season. For a film, both are `null`.
- `playback` is `direct` or `transcode`.
- `video_source` is the quality of the file and `video_stream` the quality
  sent to the player, as shown in **Monitoring > Now Playing**. Either can be
  `null` when the server does not report it.
- The player's IP address and location are never returned.

### `GET /api/v1/users/summary`

Requires **User counts**.

```bash
curl -H "Authorization: Bearer vodum_xxxxxxxx" http://YOUR_SERVER_IP:8097/api/v1/users/summary
```

```json
{
  "by_status": {"active": 40, "expired": 5, "invited": 0, "pre_expired": 1,
                "reminder": 1, "suspended": 0, "unfriended": 0, "unknown": 0},
  "by_subscription": [{"name": "Premium", "users": 30}, {"name": null, "users": 17}],
  "total": 47
}
```

`name` is `null` for users without a subscription model. Only counts are
returned: no names, emails or notes.

## Errors

Errors are JSON with an `error` field.

| Code | `error` | Meaning | What to do |
|---|---|---|---|
| 401 | `unauthorized` | No token, an unknown token or a revoked token | Check the header and the token. Create a new token if it was revoked. |
| 403 | `insufficient_scope` | The token does not have the access needed by this endpoint | Create a token with the right access. |
| 403 | (HTML page) | Your address is blocked by the IP filter | See [Limits and security](#limits-and-security). |
| 429 | `rate_limited` | More than 60 calls in a minute with this token | Wait the number of seconds in the `Retry-After` header, and call less often. |
| 503 | `maintenance` | VODUM is in maintenance mode | Wait for maintenance to end. |

```bash
$ curl -i http://YOUR_SERVER_IP:8097/api/v1/stats
HTTP/1.1 401 UNAUTHORIZED
WWW-Authenticate: Bearer realm="vodum"

{"error": "unauthorized"}
```

## Limits and security

- **Rate limit.** Each token can make 60 calls per minute. A dashboard that
  refreshes every 10 seconds makes 6. Beyond the limit, VODUM answers `429`
  with a `Retry-After` header in seconds. The count restarts when VODUM
  restarts.
- **Network.** The API follows the application IP filter (`VODUM_IP_FILTER`,
  `VODUM_ALLOWED_NETS`, see [Security](security.md)). By default only local
  networks can reach it, which suits a dashboard on the same network or the
  same Docker host. A blocked address gets an HTTP 403 page.
- **Separate admin address.** When a distinct admin address is configured, the
  API is not served on the user portal address.
- **Admin sign-in.** The API does not use the admin session. A token is
  required even when admin sign-in is turned off.
- **Logs.** Rejected calls (missing or revoked token, missing access, limit
  reached) are written to the security log with the address and the path,
  never the token. Token creation and revocation are logged too.
- **Caching.** Answers use `Cache-Control: no-store`.
- **Private data.** The API never returns emails, IP addresses, locations,
  server addresses or credentials, passwords, payments, notes or logs.

## Homepage

Use the `customapi` widget with a token that has the **Statistics** access:

```yaml
- VODUM:
    href: http://YOUR_SERVER_IP:8097
    icon: https://raw.githubusercontent.com/Nexius2/VODUM/main/static/icon.png
    widget:
      type: customapi
      url: http://YOUR_SERVER_IP:8097/api/v1/stats
      refreshInterval: 30000
      headers:
        Authorization: Bearer vodum_xxxxxxxx
      mappings:
        - field:
            sessions: live
          label: Streams
        - field:
            sessions: transcodes
          label: Transcodes
        - field:
            users: active
          label: Active users
        - field:
            users: expiring_soon
          label: Expiring soon
```

If Homepage runs in Docker, use an address that Homepage's container can reach,
for example the host's LAN IP or the VODUM container name on a shared Docker
network. That address must also be allowed by the IP filter.

## Grafana

With the [Infinity](https://grafana.com/grafana/plugins/yesoreyeram-infinity-datasource/)
data source:

1. Add an Infinity data source. Under **Authentication**, choose
   **Bearer Token** and paste the token. Add the VODUM address to
   **Allowed hosts**.
2. In a panel, choose type **JSON**, source **URL**, and enter
   `http://YOUR_SERVER_IP:8097/api/v1/servers`.
3. Set **Rows/Root** to `servers` to get one row per server, and add columns
   such as `name`, `status`, `live_sessions`, `cpu_pct` and `ram_pct`.

For single numbers, use `/api/v1/stats` and add a column such as
`sessions.live` or `users.expiring_soon`. For a table of current playback, use
`/api/v1/sessions` with **Rows/Root** set to `sessions`.

## Homarr

Homarr has no widget that reads figures from any JSON API. You can still add
VODUM as an app:

1. Add an app with the VODUM address, for example
   `http://YOUR_SERVER_IP:8097`.
2. For the status check, use `http://YOUR_SERVER_IP:8097/health`. It needs no
   token and answers `{"status": "ok"}` when VODUM is running.

To show VODUM figures, use Homepage or Grafana with the examples above.

## Versioning

Version `v1` only receives backward-compatible additions (new fields or
endpoints). A breaking change will use a new URL version. Your scripts should
ignore fields they do not know.
