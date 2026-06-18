# Changelog

All notable changes to Vodum will be documented in this file.

---
- Added an isolated fresh-database runtime smoke test covering idempotent bootstrap, SQLite integrity and foreign keys, all templates, authentication, route rendering, CSRF, maintenance mode, brute-force locking and open-redirect protection.
- Fixed legacy `/settings/<section>` URLs returning HTTP 500 after the settings views were unified; they now redirect to the existing settings page.
- Made `db_bootstrap.py` resilient to non-UTF-8 host consoles instead of aborting on Unicode log symbols.
- Centralized the imports directory and derived it from `DATABASE_PATH` (or `VODUM_IMPORTS_DIR`) so backup restore, setup uploads and Tautulli cleanup use the same configurable location.
- Isolated the Jellyfin credential validator from host log paths so the full validation suite runs without `/appdata` access.
- Updated the runtime startup documentation to match the centralized startup sequence.
- Centralized the post-registration application startup sequence with ordered steps, consistent timing logs and explicit fatal/non-fatal failure policies.
- Fixed Plex Now Playing artwork when session payloads omit `ratingKey` by deriving media identifiers from `key`, `thumb` or `art` paths.
- Added Plex artwork fallback from expired versioned paths to canonical metadata paths, and removed broken images cleanly from HTMX-updated media cards.
- Added a strict five-minute grace period for probable one-stream device switches when the same media is detected on a new session; larger overages and different media still trigger immediately.
- Subscription upgrade suggestions now use the unified scheduled delivery pipeline with channel fallback, ten retries and cooldown activation only after a successful delivery.
- Stream-blocked templates now expose the killed stream, other/all active streams, stream and IP counts, configured policy limits and observed values.
- Expanded the default stream-blocked message with the killed stream, policy usage and the user's other active streams.
- Added a global Communications summary for email, Discord, the last 24 hours and the scheduled pending/error queue.
- Updated the Plex server validation test to cover the required plex.tv account-token check.
- Reorganized the sidebar so operational diagnostics are grouped together, with Tasks immediately following Logs.
- Owner and administrator accounts now display concise role labels instead of server-qualified expiration values in user lists and details.
- Plex owners can no longer be deleted, while Jellyfin administrators expose a disabled delete action with an explanatory tooltip; both restrictions are also enforced server-side.
- Added complete pagination to Monitoring Policies recent enforcements instead of limiting access to the latest twelve entries.
- Reworded telemetry as anonymous aggregate telemetry consistently across all five languages.
- Now Playing retains recent unconfirmed sessions for a bounded period while the sequential task queue delays media collection, and clearly marks the delayed refresh state.
- Improved dashboard responsiveness by stacking dense summary cards and allowing subscription statistics to wrap cleanly at narrower resolutions.
- Added subscription name column to the Users list, with sorting support.
- Improved Plex server validation by detecting tokens accepted locally but rejected by plex.tv.
- Locked expiration date editing for Plex owners and Jellyfin admins in user detail.
- Display owner/admin role instead of expiration date when expiration is managed by server role.
- Added backend protection to prevent expiration changes for protected owner/admin accounts.
- Added randomized telemetry interval between 2 and 7 days, while keeping the 7-day maximum safety limit.
- Hidden subscription editing for Plex owner and Jellyfin admin accounts.
- Displayed Owner/Admin instead of subscription name for protected media accounts.
- Locked expiration date and subscription changes for protected owner/admin accounts.
- Kept owner/admin protection reversible after the next media server sync.
