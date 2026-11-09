# Kids

A clickable model under More ways to discover (beside IMDb and Recently added) for movie and series libraries, including a paired movie/series configuration.

- Top includes all release years. Top latest restricts release/first-air dates to the last 365 days, retaining popularity order. The selection is saved as kids_chart and reflected in the translated collection title.
- Country selects streaming availability, not production country.
- TMDb Discover ranks eligible titles by popularity: Family (10751) for movies, Kids (10762) for TV. Animation alone is insufficient.
- Original-language filtering uses the existing language selector and runs before the title limit. Display language controls titles and metadata.
- Subscription, free and ad-supported offers are included. Adult and unreleased titles are excluded.
- Up to five discovery pages (100 candidates) are read per media type and market, cached for six hours. Default collection limit: 30.
- Reuses collection ownership, Plex/Jellyfin publication, priority, scheduling, previews, cleanup and optional Arr acquisition.
- Requires the shared TMDb key. Discovery failures preserve the published collection.

References: https://developer.themoviedb.org/reference/discover-movie and https://developer.themoviedb.org/reference/discover-tv
