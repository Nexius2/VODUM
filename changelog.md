# Changelog

All notable changes to Vodum will be documented in this file.

---

### improved
- Improved template variable validation to ensure all advertised placeholders are correctly resolved before sending emails.
- Prevented raw placeholders from appearing in playback interruption notifications.
- Improved subscription selection in user profiles to display only enabled subscription plans.
- Improved `comm_templates` schema upgrade to prevent SQLite from rewriting foreign keys incorrectly during table rename.

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

