# Changelog

All notable changes to Vodum will be documented in this file.

---

### improved
- Improved template variable validation to ensure all advertised placeholders are correctly resolved before sending emails.
- Prevented raw placeholders from appearing in playback interruption notifications.
- Improved subscription selection in user profiles to display only enabled subscription plans.
- Improved `comm_templates` schema upgrade to prevent SQLite from rewriting foreign keys incorrectly during table rename.
- Improved subscription template integrity checks to avoid impossible user configurations.

### Fixed
- Fixed playback-blocked email variable replacement for policy enforcement notifications.
- Fixed legacy communication database migrations that could leave broken foreign keys pointing to `comm_templates_old`.
- Fixed recurring `send_expiration_emails` errors caused by missing `comm_templates_old` table on upgraded installations.

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
