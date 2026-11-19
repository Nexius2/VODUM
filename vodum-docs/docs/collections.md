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
