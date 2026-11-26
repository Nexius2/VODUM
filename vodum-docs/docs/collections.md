# Collections

Collections creates and maintains curated collections in selected Plex or
Jellyfin libraries. Each saved configuration has a model, target libraries,
filters, publication choices and a schedule. Models differ in their source,
matching rules and provider capabilities; see [Models & sources](collection-sources.md).

## Before you start

1. Add and synchronize your [media server and libraries](servers-libraries.md).
2. Open **Collections → Settings** and configure the shared TMDb API key.
3. Add any additional key required by the selected source, such as a
   MyAnimeList Client ID. AniList does not require its own API key.
4. For acquisition, configure a compatible Sonarr/Radarr server, its saved
   request defaults and the route on each destination library.

Secrets are masked when returning to the settings form. An empty key field
preserves the stored key; the explicit reveal action is administrative. Do not
paste credentials into a collection name, description or support report.

## Create and preview

1. Choose a model and give the configuration a recognizable name.
2. Select compatible movie/series libraries. A second library is available for
   models that support it; libraries remain separate publication targets.
3. Choose the source ranking, country, language, limits and filters offered by
   that model. A limit of zero means unlimited where the editor offers it.
4. Choose the publication/acquisition mode and schedule, then save.
5. Run **Preview** and inspect selected titles, missing titles and planned ARR work.
6. Run the configuration to publish or process acquisitions.

Preview does not publish a provider collection or submit acquisition requests.
An ARR-only configuration requests missing media without publishing a collection.
Optional home visibility, ordering and priority depend on provider support;
an unsupported option must not be interpreted as applied successfully.

## Collection from a media list

In **More ways to discover**, choose **Media list**. Search the VODUM and custom
lists, then select one. The picker shows eight results per page in a bounded
area; the selected list stays visible when searching or changing pages.
The collection takes its name from the selected list.

Choose a movie library, a series library, or a movie/series pair, then configure
the usual limit, order, schedule, visibility and optional Arr acquisition.
Only enabled entries of the selected list matching each library type are used.
List edits take effect at the next run; Preview lets you inspect them first.
Unlike Franchise, this model publishes one selected list per library without
requiring two locally present movies. Lists in use cannot be deleted.

TMDb is still required for publication identity matching. Entries whose external
identity cannot be resolved may be absent from a new collection; partial runs
preserve existing members rather than removing them on incomplete information.
IMDb display metadata in the Lists tab does not guarantee a TMDb match.

## Delete a custom list

Open the custom list in **Lists** and use the trash icon beside the content
heading. Confirm the VODUM dialog to delete the list and its local entries.
Cancel or Escape leaves it intact. Media files in Plex/Jellyfin are retained.
VODUM bundled lists cannot be deleted. If the list is still linked, unlink it
from Franchise configurations first; for a Media list collection, change its
source or remove that configuration before deleting the source list.

## Chronological order of a list

VODUM lists come with a reference story order for the main continuity of each
franchise (for example the Star Wars saga from *The Acolyte* to *The Rise of
Skywalker*, or the MCU timeline). Entries without a clear place in that story,
such as LEGO titles, Elseworlds, separate continuities and specials, follow by
release date. Lists without a reference order, and your own lists, follow the
release dates.

To use your own order, open the list in **Lists** and expand **Chronological
order**. Move entries with the arrows, type a position, or drag them, then
choose **Save order**. Your saved order always wins over the VODUM order.
**Back to the VODUM order** removes your saved order (on lists without a VODUM
order the button is **Back to release order**). **Sort by release date** ignores
every chronological order for this list; **Use the chronological order** turns
it back on.

Every entry of the list is part of the order, including disabled ones. An
entry added later appears at the end, marked *Not placed yet*, until the order
is saved again. The order applies at the next synchronization.

Plex shows the collection in this custom order. Jellyfin cannot sort a
collection manually: the order is kept in VODUM and Jellyfin keeps its own
sort. Media files, paths and names are never changed.

## Link lists to Franchise configurations

In **Lists**, open a list and expand **Manage Franchise links** inside
**Linked collections and libraries**. Search by collection or library name,
then check or uncheck a configuration. Eight results are shown per page.
Each choice applies atomically to all libraries of the configuration, including
a movie/series pair. A running configuration cannot be changed this way.

The Franchise editor shows only its linked lists. Add links from the Lists tab;
new custom lists are not automatically included. Older configurations without
an explicit selection default to VODUM lists only. Explicit saved selections
are preserved, and removing the last link leaves an empty selection.

Changes apply at the next synchronization. Unlinking can retire the VODUM
collection created for that list in that configuration; media files are retained.
Other models with a fixed discovery source cannot use these lists. For the
single-source **Media list** model, change the source in its collection editor.

## List posters and franchise recovery

Media thumbnails in Lists are cached on VODUM's persistent data volume, in
`collection_posters` beside the configured database (normally
`/appdata/collection_posters`). `VODUM_COLLECTION_POSTER_CACHE_DIR` overrides the
location. The cache is populated on demand, reused for 30 days, and periodically
trimmed toward 256 MiB. An older cached image remains usable during a provider
outage. It is safe to remove this cache: it will be rebuilt as images are viewed.
IMDb images are requested as thumbnails rather than oversized originals.

Franchise updates retain a known VODUM child's identity when its internal key
changes, including after an unsuccessful run left an unused reservation. Remote
ownership is still checked before publication. A same-title collection outside
that configuration remains a collision; it is not adopted, deleted or overwritten.
Stargate's series list is supported; a reported title collision can prevent its
publication even when its members were identified.

## Jellyfin display order

When any selected library uses Jellyfin, the Media order publication control is
hidden and replaced with an explanation, including mixed Plex/Jellyfin groups.
Jellyfin manages the displayed order; VODUM does not apply a custom source ranking
to its collection. The review step also indicates this limitation. Selecting only
Plex libraries makes the control available again.

Existing saved source/selection order is preserved, including for the Plex target
of a mixed group. Opening the editor does not reorder or republish an existing
collection automatically.

## Run, stop and resume

Saved configurations can be edited, duplicated, enabled/disabled and run manually.
Schedules depend on the global scheduler and the relevant worker being enabled.
A run may be queued while a server is unavailable, inventory is being refreshed
or another worker is busy. Inspect the explanation shown on the configuration.

**Stop** requests a controlled stop; it does not guarantee immediate interruption
of an external request already in flight. Large inventories and catalog acquisition
use bounded passes and can continue from saved progress. Review the current job
and history before submitting the same work again.

The page refreshes more frequently during queued/running/stopping jobs, less often
while idle, and refreshes when returning to the foreground.

## Understand the result

Open run history for per-library results, title details and ARR outcomes. A
successful publication, missing catalog titles and pending acquisition are
separate facts. A green configuration can still have titles awaiting download.
Only actionable warnings, failures and absent synchronization results require
review. A shortfall against the requested title limit, pending acquisition and
known Jellyfin display/home limitations remain visible as information without
turning an otherwise successful run or presentation command into a failure.
Actual publication, source, artwork or acquisition failures still need review.

Older log levels and technical details are preserved. Informational historical
warnings receive an explanation that does not call them failed publications.
After upgrading, run synchronization again to update previously stored execution
and presentation states.

Unknown or incomplete metadata can prevent a confident match. VODUM protects
members it cannot safely reconcile instead of treating every unresolved title
as absent. An existing collection owned outside the configuration is protected
by ownership checks; a name collision is not permission to overwrite it.

## Remove a configuration

Read the deletion confirmation and its provider cleanup choices before proceeding.
The configuration, queued work and provider collections are related but distinct;
verify the stated scope rather than assuming that deletion only hides a card.
Back up before removing configurations used on live servers.
