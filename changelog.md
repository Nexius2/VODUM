# Changelog

All notable changes to Vodum will be documented in this file.

---

# VERSION=26.05.14

## Stability & Core Improvements

* Improved overall application startup reliability.
* Improved compatibility between Docker deployments and source/manual launches.
* Improved Flask app initialization and shared import handling.
* General backend cleanup and stability improvements.
* Improved internal route smoke-testing tools and validation workflow.

## Plex Access Synchronization

* Improved Plex access synchronization safety and stability.
* Added safer share-state validation before applying Plex library access changes.
* Added detailed Plex access diff logging (`keep/add/remove`) for easier debugging and monitoring.
* Improved shared server section parsing compatibility with different Plex API responses.
* Added stronger protection against inconsistent Plex API responses during synchronization.

## Media Job Queue System

* Improved Plex and Jellyfin media job queue stability.
* Added safer handling of queued vs running access jobs.
* Added delayed follow-up scheduling when an access update is already running.
* Reduced race-condition risks during grant/revoke/sync operations.

## Fixed

* Fixed several startup/import issues that could prevent Vodum from launching correctly in some environments.
* Fixed Flask app loading and route smoke testing issues.
* Fixed problems in the internal `tools/smoke_routes.py` utility.
* Fixed a dangerous edge case where an invalid or empty sync state could unintentionally revoke all Plex library access for a user.
* Sync jobs no longer fallback to a full revoke operation when Plex section detection fails.
* Fixed an issue where queued access jobs could incorrectly cancel jobs already being processed by workers.
* Prevented overlapping grant/revoke/sync operations for the same user/server combination.
* Reduced risk of inconsistent library access states caused by concurrent media access jobs.

## Ongoing Work

* Continuing work on Plex soft-disable / automatic reactivation logic for expired subscriptions.
* Additional monitoring and playback tracking improvements planned.
* More UI/UX cleanup and optimization still in progress.
* Future improvements planned for the changelog/release system.

### Added

* Added Plex/Jellyfin server version detection and display in the Servers page
* Server versions are now automatically retrieved during health/status checks
* Added `server_version` storage in database for cached version display
* Displayed server version as a dedicated line inside server cards for improved readability

## Stream Policies / Enforcement

- Improved stream enforcement stability and reduced false positive session kills
- Added advanced “smart household” session correlation system
- Added intelligent session deduplication for Plex episode transitions
- Added detailed policy debug logging for IP/device/session analysis
- Added household similarity scoring using:
  - IP/subnet matching
  - device matching
  - client matching
  - machine identifiers
  - media correlation
  - timing correlation
- Improved handling of WiFi ↔ 4G and IPv4 ↔ IPv6 transitions
- Improved `max_ips_per_user` detection logic
- Reduced false positives caused by Plex zombie sessions and episode changes
- Improved enforcement target selection consistency
- Improved policy debugging visibility for stream/IP violations
- Improved cross-server enforcement consistency
- Added temporary smart session memory cache to improve detection stability across Plex episode transitions, network changes, and short-lived zombie sessions