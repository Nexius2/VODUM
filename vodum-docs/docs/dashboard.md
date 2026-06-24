# Dashboard

The Dashboard is an operational preview, not the source of configuration.

## What it shows

- User totals by active, expiring, reminder and expired state.
- Streams killed during the last seven days.
- Subscription-plan distribution.
- **Now Playing** sessions with provider, playback mode, server, user and client.
- Server reachability and seven-day peak streams.
- Usage-risk summary and upgrade suggestions.
- Next scheduled tasks and latest logs.

Now Playing uses a short live window. When the sequential task queue is busy,
VODUM may retain recent unconfirmed sessions for a bounded period and marks the
card as delayed. Posters and backdrops are served through an authenticated,
locally cached artwork proxy.

Use **View all** links to open Monitoring, Tasks or Logs for complete details.
