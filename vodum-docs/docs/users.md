# Users

VODUM separates a logical user from provider accounts. One VODUM user may be
linked to multiple Plex or Jellyfin identities and servers.

## User list

Search, filter and sort users by identity, status, expiration and subscription.
Protected Plex owners and Jellyfin administrators display their role instead of
an editable expiration or subscription.

## User detail

The detail page manages:

- contact and profile data;
- expiration, renewal and subscription assignment;
- linked provider accounts and library access;
- notification channel/order overrides;
- per-user stream-limit overrides;
- referral relationships and operational history;
- Jellyfin password changes for selected native accounts.

Access changes are queued as provider jobs. The UI records intent first; workers
apply changes and later synchronization confirms provider state.

Owners cannot be deleted. Jellyfin administrators must first lose their native
administrator role. Merge and delete actions provide previews/protection checks
before changing identities.
