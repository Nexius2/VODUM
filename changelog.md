Changelog
Unreleased — November 23, 2026
Media Requests
- Added Seerr integration (Overseerr/Jellyseerr) as an alternative to VODUM's built-in Sonarr/Radarr request engine, with per-library configuration, account matching, availability indicators, season and 4K options, and request tracking.
- Added a configurable recent-requests limit in the user portal.
- Improved Sonarr/Radarr request reliability: unavailable instances no longer block eligible destinations, and requests can fall back to the next available instance according to configured priorities. Uncertain submissions are never automatically repeated.
- Improved error reporting for failed media requests.
Collections & Lists
- Introduced a Lists management interface for movies and TV shows, including custom lists, media search, activation, deletion safeguards, and links to collections and libraries.
- Added a Media List collection type, allowing collections to be generated from a selected VODUM or custom list.
- Moved Franchise collections to locally managed lists instead of relying on downloaded public lists, with support for mixed movie/TV content and explicit list associations.
- Expanded the built-in franchise catalog to 32 lists, including Stargate, Harry Potter, Middle-earth, Jurassic Park, James Bond, Doctor Who, Dragon Ball, and more.
- Added dedicated franchise artwork and improved poster caching and metadata lookup, including IMDb ID fallback and identifier-based search.
- Improved franchise synchronization and recovery from collection-name conflicts without overwriting unrelated collections.
- Added contextual warnings when a collection requires missing TMDb or MyAnimeList credentials.
Monitoring & Performance
- Moved historical Monitoring statistics and additional filtered views to background precomputation, reducing heavy work during page requests while keeping live indicators current.
- Improved Monitoring diagnostics and worker time limits for Plex/Jellyfin data collection.
- Optimized user searches, collection status polling, user profile loading, log filtering, and merge suggestions to reduce unnecessary database work.
- Added CPU and RAM indicators to server cards on the dashboard.
Security & Reliability
- Fixed trusted reverse-proxy header handling under Waitress, preserving VODUM's proxy validation and HTTPS/client-address detection.
- Improved Plex session termination verification to avoid treating malformed or incomplete responses as successful termination.
These changes are currently listed as unreleased. Production deployment and validation are not implied.