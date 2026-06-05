# Changelog

All notable changes to Vodum will be documented in this file.

---

### improved
- Improved communication template variable modal responsiveness with better handling of long placeholders and large variable lists on smaller screens.
- Reworked the Gift Subscription user picker with a fast searchable user selector.
- Added live search support for username, first name, last name, primary email, secondary email, Discord name, and linked Plex/Jellyfin accounts.
- Improved usability for large user databases by replacing the single-user dropdown with instant filtering.
- Enhanced search result highlighting and hover feedback for easier user selection.
- Hidden disabled tasks from the Tasks page by default for a cleaner interface.
- Disabled and internal system tasks are now only visible when Debug Mode is enabled.
- Improved task list readability by focusing on active and actionable scheduled jobs.
- Redesigned the Dashboard task summary area for better readability and space usage.
- Moved task health statistics (active tasks and errors) into the Latest Logs panel for improved context.
- Added a new subscription overview widget displaying subscriber counts per active subscription plan.
- Added a 48-hour kill counter directly on the Dashboard for quick policy enforcement monitoring.
- Hidden inactive subscription plans from the Dashboard summary.
- Added support for displaying the most popular subscription plans first, with an expandable view when many plans exist.
- Improved visual consistency across Dashboard widgets with better alignment, spacing and separators.
- Added a 7-day peak stream indicator to each server card on the Dashboard.
- Improved server cards layout with a clearer Last Check display.
- Highlighted peak stream values for better visibility.
- Optimized Dashboard peak stream calculation to avoid slow page loading.
- Improved Plex websocket handling for offline or unreachable servers to prevent repeated error spam and reduce unnecessary reconnection attempts.
- Improved first setup flow with a dedicated welcome screen when no media server is configured.
- Added direct backup restore access during fresh installations, before adding a Plex or Jellyfin server.
- Added a multilingual restore progress modal to clearly indicate that backup restoration is running.
- Reclassified temporary update-check network failures as warnings instead of application errors.

### Fixed
- Improved Monitoring Activity event details for Plex and Jellyfin sessions.
- Added reliable series metadata tracking (series title, season number and episode number) to media events.
- Fixed missing `SxxExx` information for TV episodes in activity history.
- Fixed incomplete `stop` events that could lose media information when playback ended.
- Improved activity display to consistently show server type, server name, media title and username.
