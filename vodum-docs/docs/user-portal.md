# User portal

The portal is an optional user-facing area under `/portal`. It gives each person
access to their own account information and enabled self-service features.
It never grants access to VODUM administration.

## Enable and configure

1. Open **User portal** in administration and enable the portal or its local-test
   mode for setup.
2. Configure the final public HTTPS URL and the intended authentication methods.
3. Configure operational email delivery for local activation and password recovery.
4. Select the visible sections and configure support and renewal information.
5. Review publication diagnostics, then test using an actual user account.

The diagnostic checks application configuration; it does not provision DNS,
certificates or a reverse proxy. See [Security](security.md) before exposure.
Disabling a section removes navigation and denies its route server-side.

## Sign in and manage linked methods

Local, Plex and Jellyfin methods have independent switches. Local users activate
an invited account and can use password reset. Plex authentication uses the
provider flow. Jellyfin identities are scoped to their server. Linking/unlinking
methods can require reauthentication and ownership checks; a matching display
name alone is not authority to link an identity.

An unavailable method, inactive account, expired session or suspended user can
prevent login. Provider accounts and the portal account are distinct records.
A portal account can own several allowed sign-in methods for the same logical
VODUM user without gaining another user's access.

## Profile

Users can review their identity and account details, update allowed profile
fields and use supported password/provider-profile changes. Primary account
identifiers, subscription status, grants and administrator roles remain under
administrator control. Notification controls follow the enabled communication
channels and administrator policy.

## Subscription and invitations

The subscription page shows plan information, dates and effective limits, with
configured renewal destinations and instructions. Payment links are not themselves
a payment confirmation or a promise of automatic renewal.

When invitations are enabled, active eligible users can invite a friend using
the server-validated subscription/access snapshot. See [Referrals & invitations](referrals.md)
and [Subscriptions & gifts](subscriptions.md).

## Media requests

Enable requests only after configuring compatible ARR defaults and library routes.
Users search films/series and follow queued requests through verification and
results. The permission is limited to the current user's eligible access.
See [Media requests](media-requests.md) for setup, limits and uncertain outcomes.

## System status

The dedicated System status page shows the user's linked media accounts, granted
libraries and saved status/last-check information for related Plex/Jellyfin servers.
Eligible ARR services appear only through compatible enabled routes attached to
that user's libraries. There is no fallback to unrelated services.

Offline services appear before unknown and online services. **Offline since**
uses a saved current-outage timestamp; a missing value is not a recorded start,
and the field is not a complete outage history. The date clears on recovery.
Refresh reloads stored status rather than triggering a live probe. ARR unavailability
can delay requests without implying that playback is down.

The previous `/portal/media-access` link redirects to System status. Existing
visibility choices survive through the retained `portal_show_media_access` setting.
Internal provider addresses, credentials and other users' grants are not shown.

## Personal monitoring

Playback totals, recent media, clients and permitted connection summaries belong
to the signed-in user only. IP information is masked; the administrator map and
global rankings are separate administration features.

## Support

Configure the support contact, whether its email address is visible and whether
quick messages are allowed. When enabled, users write to their own support
conversation and administrators respond through Communications Inbox. The support
address uses the configured contact information, not an assumption about SMTP.

## Branding and mobile use

The portal reuses the application name, uploaded logo and configured public
information. On phones it offers quick navigation to requests, subscription and
profile, plus a menu for other enabled pages. Hidden sections are not advertised
as available destinations. Tables become cards, profile/support include shortcuts
and renewal information opens in a mobile-friendly panel. Desktop navigation
remains in the header.

## Permissions and API

The server derives the current user from a revocable, validated session. Changing
a URL, form field or browser script cannot select another user's data.
See the [permission table](user-portal-permissions.md), [route policy](route-access-policy.md)
and [portal API](portal-api.md). Administrator previews do not impersonate a normal
portal user or authorize one to open administration pages.
