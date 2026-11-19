# Settings

Settings groups common instance behavior. Subscription behavior, communication
configuration and the user portal also have their own dedicated screens.

## General

Choose interface language, timezone, support contact email, application name
and uploaded logo. Branding is shared by administration and the user portal.
Supported logo uploads use the formats shown in the form; selecting/removing
an image takes effect when the form is saved.

Anonymous aggregate telemetry is opt-in. It may include installation-level
language observations when enabled; it is not a user-identification feature.

## Security

The security card groups administrator access, Plex identity linking and web
security. **Manage administrator access** opens email/password, two-factor
settings and Turnstile controls. Follow the displayed requirements for linking,
replacing or removing an administrator Plex identity. Linking a media account is
not the same as granting it administrator login.

HTTPS sessions receive Secure cookies. Direct LAN HTTP has different cookie
requirements; do not copy an HTTPS-only assumption into a local recovery test.
SameSite and proxy trust must match the real deployment. See [Security](security.md)
for trusted-header boundaries and two-factor recovery considerations.

## System

The system group includes scheduler, maintenance/debug behavior, data retention
and provider import options. The scheduler switch updates scheduled task state.
Debug mode also exposes certain experimental settings, including payment-link
controls when enabled; it is not proof that an experimental workflow is production-ready.

## Related settings

- [Subscriptions](subscriptions.md): default duration, expiration and cleanup.
- [Communications](communications.md): SMTP, Discord, timing and channel order.
- [User portal](user-portal.md): public URL, authentication, visible sections and support.
- [Collections](collections.md): shared metadata/source keys and collection schedules.
- [Deployment configuration](configuration.md): environment-only paths, proxy networks and timing.
