# Settings

The unified Settings page contains four groups.

## General

Interface language, timezone, administrator email/password, brand name and
anonymous aggregate telemetry.

## Subscription

Default duration, cleanup delay and expiration mode. `warn_then_disable` also
defines the grace period before access removal.

## Notifications

Pre-notice/reminder timing, global channel order and whether users may override
notification preferences.

## System

Global scheduler switch, maintenance/debug mode, Plex user import strategy,
secure-cookie behavior, SameSite and trusted-proxy behavior.

Changing the scheduler switch updates dependent task state immediately. Setting
SameSite to `None` forces secure cookies. Trust proxy should only be enabled with
a narrow `VODUM_TRUSTED_PROXY_NETS` configuration.

Some deployment settings remain environment-only; see [Security](security.md).
