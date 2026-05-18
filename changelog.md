# Changelog

All notable changes to Vodum will be documented in this file.

---

# VERSION=26.05.14

## Stability & Core Improvements

* Improved Users page search to also match linked Plex/Jellyfin usernames from media_users, making account lookup more reliable across merged or external media accounts.
* Improved default Users page sorting to keep active users prioritized and provide a more stable, consistent alphabetical order after sync operations.
* Improved Users search normalization to handle extra spaces and inconsistent pasted text more reliably
* Improved Users page filter stability by validating stored status filters and automatically restoring safe defaults when needed.
* Improved Users page sorting stability by adding a deterministic fallback order for identical sort values.
* Improved Users filter robustness by normalizing status values from cookies and URL parameters.
* Improved multilingual support

## Fixed





### Added

* plex user import mode
* telemetry
* backups can be downloaded

