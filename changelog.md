# Changelog

All notable changes to Vodum will be documented in this file.

---
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