# Changelog

All notable changes to Vodum will be documented in this file.

---


### Improved
- Replaced the dashboard Usage Risk placeholder line with a functional 14-day recommendation history graph.
- Added a smooth gradient area chart, seven-day change indicator and real date labels for upgrade suggestions.
- Dashboard server preview now lists online servers first, then orders servers by their seven-day peak stream count.
- Limited the dashboard server preview to six entries while preserving complete online/offline totals.
- Restricted authenticated Plex/Jellyfin redirects to the server origins explicitly configured in `url`, `local_url` and `public_url`.
- Preserved support for remote media servers and configured aliases during authenticated redirects.
- Server token fields now stay blank in the edit form and preserve the existing secret unless a replacement is submitted.
- Added automated tests for configured-origin redirects and blank secret preservation.
- Added encrypted-at-rest storage for Plex/Jellyfin server tokens and Tautulli API keys.
- Added transparent startup migration of existing plaintext server secrets.
- Preserved linked Plex server discovery after token encryption by comparing decrypted tokens outside SQL.
- Added automated tests for server-secret migration, transparent decryption and linked Plex matching.
- Included `vodum.encryption_key` in full ZIP backups and restored it automatically with rollback protection.
- Added explicit restore protection when `VODUM_ENCRYPTION_KEY` conflicts with the key contained in a backup.
- Documented that full ZIP backups are self-contained and must be stored securely.
- Replaced the Flask development server with the existing Waitress production WSGI server.
- Added `VODUM_PORT` and `VODUM_WAITRESS_THREADS` server configuration.
- Aligned the Waitress request-body limit with `VODUM_MAX_UPLOAD_MB` for large Tautulli imports.
- Added encrypted-at-rest storage for SMTP passwords and Discord tokens using a persistent key stored separately from SQLite.
- Added transparent startup migration of existing plaintext communication secrets.
- Stopped rendering configured SMTP passwords and Discord tokens back into the browser.
- Added encryption key configuration through `VODUM_ENCRYPTION_KEY` and `VODUM_ENCRYPTION_KEY_FILE`.
- Added automated tests for encryption, decryption, key persistence, wrong-key handling and idempotent plaintext migration.
- Increased the default upload limit to 4 GB so large Tautulli databases can be imported.
- Increased the default restored ZIP extraction limit to 8 GB.
- Added configurable upload and archive limits through `VODUM_MAX_UPLOAD_MB`, `VODUM_MAX_ZIP_EXTRACTED_MB` and `VODUM_MAX_ZIP_MEMBERS`.
- Restricted trusted proxy headers to connections originating from `VODUM_TRUSTED_PROXY_NETS`.
- Added security documentation for trusted reverse proxies and large uploads.
- Added automated tests for redirect safety, proxy address handling, archive limits and large Tautulli imports.
- Improved template variable validation to ensure all advertised placeholders are correctly resolved before sending emails.
- Prevented raw placeholders from appearing in playback interruption notifications.
- Improved subscription selection in user profiles to display only enabled subscription plans.
- Improved `comm_templates` schema upgrade to prevent SQLite from rewriting foreign keys incorrectly during table rename.
- Improved subscription template integrity checks to avoid impossible user configurations.
- Improved Usage Risk scoring with stronger fixed-device/IP signals and lower risk for TV + mobile/browser usage.
- Improved User Detail layout with Usage Risk and upgrade recommendation inside the Options card.
- Improved Subscription settings so Stream Blocked messages are forced when expiration warning modes already require them.
- Reworked dashboard layout to improve readability and reduce wasted space.
- Removed the "Kills / Subscription summary" widget.
- Expanded the "Now Playing" section to display media titles more clearly.
- Added subscription plan distribution directly to the top statistics card.
- Added subscription plans donut chart with subscriber counts and percentages.
- Displayed the number of configured subscription plans.
- Improved subscription distribution legend layout and readability.
- Added percentage display styling with muted colors for better visual hierarchy.
- Improved Usage Risk "Top reasons" display with separate styling for counts and percentages.
- Reduced dashboard clutter by consolidating subscription statistics into a single widget.

### Fixed
- Removed the unusable legacy V2-to-V3 rebuild migration that depended on a missing `tables_v3.sql` file and conflicted with existing migration markers.
- Removed the obsolete Jellyfin migration targeting the retired legacy `users` table.
- Fixed the V1-to-V2 import journal marker so it no longer uses structural schema version `3`.
- Added automated validation that `tables.sql` builds successfully with a clean foreign-key check.
- Fixed a potential IP-filter bypass through client-supplied `X-Forwarded-For` headers.
- Fixed open redirects after login and language changes.
- Stopped storing newly submitted Jellyfin user passwords in plaintext.
- Added startup cleanup of legacy plaintext Jellyfin user passwords.
- Added protection against unexpectedly large or highly populated backup ZIP archives.
- Fixed playback-blocked email variable replacement for policy enforcement notifications.
- Fixed legacy communication database migrations that could leave broken foreign keys pointing to `comm_templates_old`.
- Fixed recurring `send_expiration_emails` errors caused by missing `comm_templates_old` table on upgraded installations.
- Fixed Usage Risk detail panel closing due to automatic Monitoring refresh.
- Fixed device extraction for Usage Risk by reading stored `all_sessions` and `target_session` data.
- Fixed upgrade suggestions so they are only sent when enabled and when the minimum kill threshold is reached.

## Added
- Added support for policy, media, client, device and block timestamp variables in message rendering.
- Added Lifetime subscription support with dedicated subscription plan option.
- Lifetime subscriptions now automatically extend expiration dates using the same mechanism as expiration overrides.
- Added Lifetime badge and duration handling in subscription templates.
- Disabled duration editing when Lifetime mode is enabled.
- Added automatic repair at startup for affected tables: scheduled communications, template attachments and communication history.
- Added a new "Subscription expired warning" expiration mode for Plex/Jellyfin.
- Expired users can now be blocked through a system-managed playback policy instead of immediately losing library access.
- Added optional "warn then disable" behavior to display an expiration message before revoking access.
- Automatic cleanup of expired-subscription policies when a subscription is renewed.
- Improved Plex reactivation flow by automatically scheduling access synchronization after renewal.
- Added validation coverage for the full expired → warning → renewal lifecycle.
- Added a grace period for coherent device switches in max IP policies.
- VODUM now detects when the same user appears to switch device while watching the same movie or series.
- Temporary duplicate IP detections can now be ignored for a short delay before enforcing a kill.
- Reduced false positives when Plex keeps an old session visible during TV → phone / phone → TV transitions.
- Added validation for subscription templates to prevent inconsistent policy configurations.
- Max IPs per user can no longer exceed Max Streams per user.
- Added server-side validation to ensure upgrade suggestions and policy enforcement remain coherent.
- Added Usage Risk dashboard widget with High, Medium, Low and suggested upgrade counters.
- Added automatic usage risk recommendation history with cooldown support.
- Added automatic upgrade suggestion notifications through the existing communications system.

