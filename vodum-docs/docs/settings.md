# Settings

**Settings** holds the general options of your VODUM instance. Subscriptions,
Communications and the user portal have their own settings screens.

## General

Interface language, time zone, support email, application name and logo. The
name and logo are also used by the user portal. A new or removed logo applies
when you save the form.

Anonymous statistics (telemetry) are off unless you turn them on. They never
identify your users.

## Security

- **Manage administrator access**: email and password, two-factor authentication
  and Turnstile (anti-bot check on the login page).
- **Plex identity**: link, replace or remove the Plex account you use to sign in.
  Linking a media account does not by itself give it administrator access.
- Web security: cookies and proxy settings must match how VODUM is reached
  (HTTPS behind a proxy, or plain HTTP on your local network).

See [Security](security.md) for details.

## System

The scheduler switch turns all scheduled tasks on or off. This group also holds
maintenance and debug mode, data retention and import options. Debug mode shows
some experimental settings (such as payment links); they are not ready for
production use.

## API access

Create, review and revoke read-only tokens for dashboards such as Homepage or
Grafana. See [Dashboard API](api.md).

## Other settings screens

- [Subscriptions](subscriptions.md): duration, expiration and cleanup.
- [Communications](communications.md): SMTP, Discord, timing and channel order.
- [User portal](user-portal.md): public address, sign-in, visible sections and support.
- [Collections](collections/index.md): API keys of the sources and schedules.
- [Deployment configuration](configuration.md): options set in the Docker environment.
