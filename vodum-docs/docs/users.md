# Users

VODUM separates a logical user from provider accounts. One VODUM user can link
multiple Plex or Jellyfin accounts across several servers. Subscription state
belongs to the logical user; library access belongs to its provider accounts.

## Find and create users

Search, filter by status, choose a page size and sort by name, email, status,
subscription, expiration or access counters. Search also considers profile fields
and linked media usernames. Sort direction and status choices can be remembered;
search text is not kept as a persistent preference.

Use **Create user** to provide contact information, the intended subscription
and provider/library choices. Provider work and notification delivery can finish
separately: inspect the result instead of assuming that creating a local record
means every external invitation has been delivered.

On mobile, each user is a card with contact details, status, subscription,
expiration and access counts. The sort controls and filters remain available.

## User detail

The detail page groups general information, access, media options, monitoring
and notification history. Depending on the linked providers, it supports:

- contact information, phone number, renewal and expiration;
- subscription assignment and permitted per-user stream-limit overrides;
- linked provider accounts and library access;
- notification preferences and email/Discord history;
- Plex sharing options and supported Jellyfin profile/password changes;
- referral information and previews for identity merges.

Access changes record intent and are applied through provider jobs where that
workflow is queued. A pending operation is not confirmed provider state. Consult
[Tasks](tasks.md), synchronization and logs before repeating an action.

## Protected accounts and merges

Plex owners and Jellyfin administrators display their protected role in place
of normal subscription editing. Owners cannot be deleted. Jellyfin administrators
must first lose their native administrator role before ordinary deletion.

Review the merge preview carefully: select the intended canonical user and
inspect transferred identities and access. Names/emails alone do not prove that
two provider subjects belong to one person. Portal-enabled accounts and identity
conflicts can impose additional restrictions; resolve a blocked merge explicitly.

See [Referrals & invitations](referrals.md) for the separate referral tabs and
[User portal](user-portal.md) for account activation and personal access.
