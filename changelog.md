# Changelog

All notable changes to Vodum will be documented in this file.

---

- Added a centralized server cooldown mechanism for unreachable Plex and Jellyfin servers.
- Offline servers are now skipped by monitoring, sync, access update and stream enforcement tasks during cooldown.
- Reduced noisy stacktraces for unreachable media servers outside debug mode.
- Added database fields to track server unavailability, cooldown expiration and last failure reason.

### Fixed
- Fixed a server edit issue that could trigger a HTTP 500 error when saving existing Plex or Jellyfin servers.
- Fixed missing `server_type` submission in the server edit form, preventing invalid server type validation failures.
- Fixed an exception path in server save operations caused by an undefined logger reference.
- Improved server configuration update reliability and error handling.