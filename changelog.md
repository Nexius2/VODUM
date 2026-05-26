# Changelog

All notable changes to Vodum will be documented in this file.

---

# VERSION=26.05.20


### Monitoring & task system improvements

- Removed duplicate `monitor_collect_sessions` auto-enable call in task engine.
- Monitoring auto-enable logic now correctly uses the new monitoring pipeline:
  - `monitor_enqueue_refresh`
  - `media_jobs_worker`
- Legacy `monitor_collect_sessions` task now remains properly disabled.

### Media server cooldown system

- Added automatic temporary cooldown system for unreachable Plex/Jellyfin servers.
- Down servers are now temporarily skipped by:
  - monitoring refresh queue
  - Jellyfin synchronization tasks
- Prevents repeated connection attempts and excessive error spam when a server is offline.
- Cooldown is automatically cleared as soon as `check_servers` detects the server online again.
- Added new server database fields:
  - `unavailable_since`
  - `cooldown_until`
  - `last_failure`

### Stability & performance improvements

- Reduced unnecessary monitoring/network load on offline servers.
- Reduced duplicated stacktraces and scheduler noise for unreachable servers.
- Improved scalability for large installations with many servers/users.
- Fixed SQLite schema issue in `tables.sql`.
- Fixed compatibility issue with `sqlite3.Row` handling in cooldown helper.

### Task scheduler improvements

- Added versioned task schedule migration for existing Vodum installations.
- Existing admins now receive updated default task schedules after upgrading.
- Admin-customized task schedules are preserved and not overwritten.
- Fixed invalid cron expression for pending invite reminders.
- Improved default task spacing to reduce unnecessary background activity.


