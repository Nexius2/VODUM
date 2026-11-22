# Dashboard

The dashboard summarizes users by status, configured servers, collections,
subscriptions, current playback, scheduled work and recent operational logs.
Cards link to the corresponding administration section.

## Collections at a glance

The collection card appears when at least one configuration exists. It counts
configurations once, rather than counting individual target libraries:

- **Successful**: every selected library has a successful last synchronization.
- **To review**: at least one warning, failure or absent result needs attention.

Missing catalog titles or pending ARR acquisition can coexist with a successful
synchronization. Open [Collections](collections.md) for the per-library result
and acquisition details. If a historical result was already purged before the
persisted summary existed, a new synchronization supplies the next result.

## Progressive loading

Historical usage risk, subscription summaries, server peaks and task information
can load after the initial document. The last known server state can be visible
before its historical figures. Current playback and cached artwork have their
own refresh paths. A loading or unavailable widget does not mean its count is zero.

## Mobile navigation

On phones, the bottom bar provides Dashboard, Users, Monitoring and Servers,
with a complete menu for other sections. User lists become readable cards,
controls have larger touch targets, and standard tables become labeled cards.
This includes libraries, monitoring users/libraries and My collections. Sort links
remain in a horizontal strip; menus and collection actions stay in each card.
Refreshing rows keeps the card layout. Complex matrices retain horizontal scrolling.
On desktop the sidebar remains the main navigation and tables remain tabular.
