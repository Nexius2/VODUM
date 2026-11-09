# TMDb Top

Clickable model in More ways to watch / discover, beside IMDb.

Eight allowlisted charts: top rated movies/series, popular movies/series, trending movies/series today and trending movies/series this week. Uses TMDb /movie/top_rated, /tv/top_rated, /movie/popular and /tv/popular, plus /trending/movie/day, /trending/tv/day, /trending/movie/week and /trending/tv/week. Reads up to 13 pages to obtain the first 250 ranked titles. No regional streaming constraint is added to these global charts.

Presentation language translates both metadata and collection names. A chart accepts only the matching movie or series library. Default title limit is 250; zero means the whole fetched chart (at most 250). Daily trends are cached for one hour; other charts are cached for six hours; malformed, duplicate or incomplete charts fail before publication, preserving the existing collection.

Uses the shared TMDb key and existing ownership, preview, cleanup, scheduling, priority and optional Arr mechanisms. TMDb IDs are already present, avoiding IMDb-to-TMDb identity resolution.

API references:
- https://developer.themoviedb.org/reference/movie-top-rated-list
- https://developer.themoviedb.org/reference/tv-series-top-rated-list
- https://developer.themoviedb.org/reference/movie-popular-list
- https://developer.themoviedb.org/reference/tv-series-popular-list

## Local count and acquisition scope

A configured limit of 20 means up to 20 identifiable local titles, filled by continuing through the fetched ranking in rank order. Missing titles among the first 20 ranks remain eligible for optional Arr acquisition. Lower ranks only fill local publication slots and do not expand downloads. Arr-only mode remains restricted to the configured top-N. A smaller local collection is possible only if the verified fetched ranking does not contain enough identifiable local media.

Trending uses the official TMDb day/week ranking without recomputing it from popularity. These are global trends, not a regional streaming catalog or a Netflix audience chart. The four trending choices share a bundled TMDb Trending poster.

- https://developer.themoviedb.org/reference/trending-movies
- https://developer.themoviedb.org/reference/trending-tv
