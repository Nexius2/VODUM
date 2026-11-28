# Collections: models & sources

A model decides where the titles of a collection come from. Choose the model
that matches the collection you want, then use **Preview** on your library: only
titles that are in your library (and match the filters) end up in the collection.

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

The editor only offers the sources, filters and media types that work together.
A film-only model cannot be used on a series library.

## Shared and additional keys

Every model needs the TMDb key (in **Collections → Settings**), even when the
ranking comes from another source: VODUM uses TMDb to recognize the titles.
MyAnimeList also needs its Client ID. AniList needs no key.

## Anime collections

MyAnimeList and AniList provide TV, film and popularity rankings. Each selected
library gets its own collection. Adult titles are excluded. A title can stay
unmatched when its identifiers are missing, even if its name looks the same.

## By platform

Select a country and any available subset of Netflix, Prime Video, Disney+,
Apple TV+, Max, Paramount+, Canal+, Hulu and Peacock. Availability is checked per media type;
unavailable choices are disabled for that country. Collection names include the
country so catalogs remain distinguishable.

Membership uses JustWatch availability exposed through TMDb watch-provider data,
limited to **subscription / flatrate** offers in the selected country. Rental,
purchase and free offers do not qualify. This describes regional availability,
not the studio that produced the work, and is not a direct scrape or exact copy
of the current JustWatch website catalog.

Availability is cached for 24 hours. Only media present in the selected library
are published. With acquisition enabled, the missing titles can be requested from
Sonarr/Radarr through the library's route; a title VODUM cannot identify is never
requested.

## Publication and acquisition are separate

Preview shows what would be published and requested, without doing either. A run
can publish the titles you have, request the missing ones when acquisition is
enabled, or only request (ARR-only mode). Titles already in Sonarr/Radarr or
already requested are not requested again. A large catalog can take several runs.
See [Collections](collections/index.md#understand-the-result).

## Bundled franchise lists

VODUM includes 32 editable film and series lists, among them Jurassic Park/World,
Terminator, Matrix/Animatrix, James Bond, Mission: Impossible,
Conjuring, Indiana Jones, Pirates of the Caribbean, Planet of the Apes,
Ghostbusters, Transformers, Rocky/Creed, John Wick, Resident Evil, Godzilla/Kong,
Narnia, Dune, Shrek/Puss in Boots, The Walking Dead, Game of Thrones, Yellowstone,
Doctor Who and Dragon Ball.

Use **Lists → Linked collections and libraries → Manage Franchise links** to add
them to a Franchise configuration. Updates of VODUM add new bundled lists without
changing your selections or the entries you disabled. Film entries only go to film
libraries, series entries to series libraries.
