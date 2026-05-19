# Changelog

All notable changes to Vodum will be documented in this file.

---

# VERSION=26.05.18

## Stability & Core Improvements
* Improved Plex user lookup reliability with automatic retry system and username fallback when email lookup temporarily fails.
* Added anonymized logging for Plex account lookup failures to avoid exposing user emails in logs.
* Optimized stream policy evaluation by skipping irrelevant provider/server/user checks before full session filtering.
* Reduced unnecessary stream policy debug spam by only logging policies matching active sessions.
* Optimized household session deduplication to avoid reprocessing identical cached sessions multiple times.
* Reduced excessive household merge logging verbosity by moving repetitive merge logs from INFO to DEBUG level.
* Reduced unnecessary policy debug logs for single-session users without violations.
* Improved overall stream_enforcer performance and reduced CPU/log overhead during live session monitoring.
* Added fallback Plex user lookup via username when email-based lookup fails.
* Optimized live session processing by caching parsed Plex/Jellyfin raw session JSON objects to avoid repeated JSON parsing during policy evaluation.
* Improved household session deduplication logic to prevent repeated processing of identical cached sessions.
* Reduced excessive household debug log spam by moving repetitive merge detection logs to DEBUG level.
* Reduced unnecessary policy debug output for single-session users without active violations.
* Improved stream policy filtering performance with fast pre-checks for provider, server, and user scoped policies.
* Optimized machine identifier extraction and enforcement snapshot generation using shared parsed session cache.
* Fixed Plex `shared_only` user import mode compatibility with newer `/shared_servers` API responses.
* Fixed parsing of `SharedServer` XML nodes instead of legacy `Server` nodes.
* Fixed incorrect Plex user ID detection by prioritizing `userID` over share `id`.
* Added support for `acceptedAt` and `invitedAt` fields from Plex shared server responses.
* Improved reliability of Plex shared user synchronization across multiple server/account configurations.
* Prevented false sync failures when Plex.tv temporarily returns empty shared server responses.

### Scheduler / Tasks Engine Optimizations

* Added intelligent `force_task_run()` support to wake up tasks immediately without waiting for the next cron execution.
* Added `auto_enable_dirty` system to avoid running `run_auto_enable_pass()` every scheduler tick.
* `run_auto_enable_pass()` is now only executed when configuration/state changes actually require it.
* Added automatic wakeup triggers after:
  - settings changes
  - server creation/update
  - Plex library grant/remove actions
* Reduced aggressive polling intervals for several background tasks:
  - `check_mailing_status`
  - `send_comm_campaigns`
  - `apply_plex_access_updates`
  - `monitor_enqueue_refresh`
  - `stream_enforcer`
* Optimized scheduler SQL usage by removing unnecessary per-task `queued_count` queries.
* `queued_count` is now loaded directly in the main scheduler query.
* Reduced unnecessary SQLite wakeups and WAL activity.
* Reduced watchdog wake frequency to lower idle CPU and DB activity.
* Improved scheduler efficiency while preserving:
  - retries
  - queue system
  - monitoring
  - auto-enable logic
  - worker protections
* Improved overall scheduler responsiveness with lower idle resource usage.

## Fixed
* some translations
* telemetry fix


### Added



