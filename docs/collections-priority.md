# Collection priority

All 16 collection models use the same ordering rules. A lower priority number
comes first. Equal priorities follow configuration creation time, then the stable
configuration group ID (the same order as the VODUM table). Children of a single
configuration remain together and are sorted by title within that group. Paired
movie/series libraries share the parent group's ordering key.

Plex's collection-list sort title and its managed recommendation hubs use this
same key. The visible collection title is unchanged. Only VODUM-owned objects
in the selected library are modified; external hubs are not directly moved.
Plex's title-based collection view reflects sort titles; a client explicitly
sorted by another field may show a different order.

Priority is saved before membership reconciliation so a large continent's
publication timeout cannot leave it with an unprioritized sort title. Editing
priority or publication destinations queues a lightweight visibility job without
rebuilding membership, calling discovery providers or submitting Arr requests.
If a refresh was already queued, a durable `priority_pending` flag applies the
presentation update before discovery starts, while preserving that refresh.
The flag is added automatically to existing collection schemas.

Upgrading also queues one lightweight presentation repair for active configurations
with published objects. It repairs verified Plex objects still named `VODUM <id>`,
including those recorded as `synced`. The expected name comes from the saved child
record; artwork comes from its allowlisted franchise/platform/continent/model key.
Plex metadata is reloaded to confirm the renamed title. Membership, media files,
Arr requests and collection IDs are untouched. Custom artwork of already finalized
collections is not changed by this repair.

One unavailable/unverified owned object produces a warning and does not prevent
the remaining children or models from receiving their priority. Visibility-only
jobs reorder Plex's library hubs once after all child updates.

Jellyfin receives the same sort-name key; control of its home layout remains
unsupported and is reported by the existing warning.
