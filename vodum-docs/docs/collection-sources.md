# Collection models & sources

Choose a model based on the collection you want to maintain, then use Preview
against the selected library. Source rankings describe an external catalog;
published membership also depends on local inventory, matching and filters.

| Family | Models / source | Main choices |
| --- | --- | --- |
| Local lists | Media list | One searchable VODUM/custom list, enabled entries and compatible movie/series libraries |
| Rankings | IMDb, TMDb | Source chart, movie/series library, ranking and limits |
| Anime rankings | MyAnimeList, AniList | Top TV Anime, Top Anime Films, Most Popular Anime |
| Streaming discovery | By country, worldwide | Country/region, content language and offered filters |
| Availability | By platform | Country and selected subscription streaming services |
| Freshness | Recent releases, recently added | Release/addition choices exposed by the editor |
| Themes and audience | Seasonal, Kids, Family, Awards | Compatible media types and model-specific filters |
| Geography and series of films | Top country, Continents, Franchises | Origin/region or franchise grouping |
| People / editorial discovery | Memoria, Spotlight, Hidden gems | Model-specific people, discovery and publication rules |

The editor is authoritative for which source, filters and media types are
available together. A movie-only model cannot be applied to a series library.

## Shared and additional keys

TMDb supplies metadata and identity resolution used across the workspace.
Configure its shared key in Collections settings even if the selected ranking
comes from another source. MyAnimeList additionally requires its Client ID.
AniList uses its public GraphQL service and has no separate key field.
Use the settings fields offered by the current editor for other source keys.

## Anime collections

MyAnimeList and AniList provide TV, film and popularity rankings. Popularity
supports the compatible movie or series inventory; resulting collections are
separate per selected library and content type. Non-adult formats and source
limits are applied by the implementation. Missing identity information can
prevent matching a title even if its name appears similar.

## By platform

Select a country and any available subset of Netflix, Prime Video, Disney+,
Apple TV+, Max, Paramount+ and Canal+. Availability is checked per media type;
unavailable choices are disabled for that country. Collection names include the
country so catalogs remain distinguishable.

Membership uses JustWatch availability exposed through TMDb watch-provider data,
limited to **subscription / flatrate** offers in the selected country. Rental,
purchase and free offers do not qualify. This describes regional availability,
not the studio that produced the work, and is not a direct scrape or exact copy
of the current JustWatch website catalog.

Successful per-title availability responses are cached for 24 hours. IDs are
resolved from TMDb/IMDb/TVDb metadata without guessing from a title alone.
Only media in the selected local library are published. Optional ARR acquisition
can look for absent catalog entries through the saved route for that library.
Unknown identities do not establish absence and do not authorize a new request.

## Publication and acquisition are separate

Preview shows planned membership and acquisition without executing either.
A run can publish local members, submit acquisition work when enabled, or use
ARR-only mode. Existing ARR entries and confirmed previous requests are
deduplicated. Bounded passes and saved offsets mean a large catalog can require
more than one execution. See [Collections](collections.md) for run states.

## Bundled franchise lists

VODUM includes 32 editable movie/series lists. The catalogue now also covers
Jurassic Park/World, Terminator, Matrix/Animatrix, James Bond, Mission: Impossible,
Conjuring, Indiana Jones, Pirates of the Caribbean, Planet of the Apes,
Ghostbusters, Transformers, Rocky/Creed, John Wick, Resident Evil, Godzilla/Kong,
Narnia, Dune, Shrek/Puss in Boots, The Walking Dead, Game of Thrones, Yellowstone,
Doctor Who and Dragon Ball.

Use **Lists → Linked collections and libraries → Manage Franchise links** to
add these sources to an existing explicit Franchise selection. Upgrading adds
the bundled lists without overwriting existing selections or local exclusions.
Movie and series entries are matched only to their compatible library type.
