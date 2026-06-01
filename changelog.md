# Changelog

All notable changes to Vodum will be documented in this file.

---



### Added
- Added a new `warmup_artwork_cache` scheduled task to proactively preload artwork used by Monitoring and Dashboard pages.
- Added automatic preloading of recent Plex and Jellyfin posters/backdrops based on recent activity history.
- Added support for warming both poster and backdrop artwork references stored in Monitoring sessions.
- Added multilingual translations for the new artwork cache warmup task (FR, EN, DE, ES, IT).
- Added a scheduled artwork cache cleanup task to remove old poster/backdrop cache files.
- Added automatic cleanup of orphaned artwork cache files and temporary cache files.
- Added multilingual labels/descriptions for the new artwork cache cleanup task.
- Existing installs now receive the new task automatically through database bootstrap without SQL migration.
- Added a scheduled database integrity check task.
- Added regular SQLite quick checks and foreign key consistency checks.
- Added optional full SQLite integrity checks with `VODUM_DB_INTEGRITY_FULL=1`.
- Existing installs receive the new integrity check task automatically through database bootstrap.
- Added an **Active policies** section at the bottom of the user detail General tab.
- The user detail page now displays all active policies currently applied to the user, ordered by priority.
- Policies now show their rule, origin, scope, provider, priority and applied value directly from the user profile.

### Improved
- Improved Dashboard and Monitoring loading times by reducing first-request artwork downloads.
- Reduced artwork cache misses by automatically refreshing frequently used artwork in the background.
- Reduced artwork requests sent to Plex and Jellyfin during page loads thanks to proactive cache population.
- Added new database indexes to improve performance on large Vodum instances.
- Optimized user listing, dashboard counters, expiration checks and subscription-template lookups.
- Improved scalability for installations with many users, media accounts and servers.
- Existing installs receive the new indexes automatically through database bootstrap.
- Improved artwork cache warmup coverage for Monitoring > Libraries.
- Warmup now preloads recent live/history artwork and top-by-library posters/backdrops.
- Warmup now uses the same artwork resolver as the UI to avoid caching stale or obsolete references.
- Added more detailed warmup logs with candidate and unique artwork reference counts.
- Added automatic startup synchronization of expiration-related background tasks based on the configured expiration mode.
- Added automatic recovery of expiration enforcement after restart, ensuring playback restrictions remain active without manual intervention.
- Improved consistency between subscription expiration settings, policy generation, and stream enforcement.
- Improved policy debugging for expired users and subscription-based limits.
- Admins can now quickly verify whether system, subscription or manual policies are actually applied without leaving the user detail page.
- Added multilingual labels for the new Active policies section.
- Improved the Active policies section in the user detail page with aligned columns for priority, provider and value.
- Clarified policy visibility by showing global policies that effectively apply to the user, in addition to user-specific subscription and system policies.

### Fixed
- Fixed an issue where the **"Subscription expired → warning then disable after X days"** mode could stop working after an application restart.
- Fixed a synchronization issue between **Subscription Settings** and the **Expired subscriptions manager** task.
- Expired users now correctly receive the automatic system policy that blocks playback (`max_streams_per_user = 0`) when the expiration warning mode is enabled.
- Fixed a case where expired users could continue streaming because the expiration enforcement task remained disabled.




