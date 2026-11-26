Changelog
Unreleased — November 26, 2026
Monitoring > Libraries
- "Media growth" and "Media added" now show the net change in each library's size and item count between scans. Media re-added by Plex or Jellyfin (rescan, path change, library rebuild) no longer count as new.
- After updating, both columns wait for a second daily scan, then show "Since <date>" until the history covers the selected period.
- Restored the "Media growth" column name.
- "Media added" now really shows the net item count (for example +12 or −3) instead of every item with a recent addition date. It shows "—" until a second scan.
- A failed scan now shows a short "Scan failed, check logs" message. The date of the attempt is in the tooltip.
- The daily scan no longer skips a server that answers again after a brief outage. Before, a single failed Now Playing poll kept the server marked unavailable until the next server check (up to 30 minutes), so the scan was often skipped and the columns stayed on "Awaiting a second scan". A server still in its 5-minute cooldown is retried at the end of the scan.
- Jellyfin scans read the oldest media first, so media added while a large library is being scanned no longer cause duplicates that made the scan fail.
Collections
- Each collection poster now has a single file. A new version replaces it in place and is sent to Plex/Jellyfin on the next run. Unused old poster versions were removed from the Docker image.
- Dune and Game of Thrones collections now use their latest posters.
- Audited the 32 built-in franchise lists. They stay global (create your own list for a narrower selection), but DC Universe no longer includes adaptations without DC Universe characters (A History of Violence, V for Vendetta, Road to Perdition, Stardust, RED, and others). Added 160 checked titles: the DC TV series (Arrowverse, Smallville, animated series, The Penguin, The Sandman…) and more DC films, the MCU series (Disney+, Marvel Television, Netflix), the Star Trek series, more Star Wars specials and series, Alien: Earth and Avengers: Secret Wars. Fixed the Middle-earth entry for The Return of the King (1980) and removed two untitled Star Trek projects. Existing installations receive these changes on update; entries you added yourself are kept.
- Franchise lists can now have a chronological (story) order. In "Lists", open a list, expand "Chronological order", arrange the entries and save. Plex shows the Franchise collection in this order; without one, the VODUM order (below) or the release dates apply. Jellyfin cannot sort collections manually, so the order is kept in VODUM only.
- VODUM lists now come with a chronological (story) order for the main continuity of 31 franchises, such as Star Wars, the MCU, Star Trek, Middle-earth, the Wizarding World, Alien & Predator and the DCEU/DCU films. Titles outside the main story (LEGO, Elseworlds, separate continuities, specials) follow by release date. Your own saved order still wins, "Back to the VODUM order" removes it, and "Sort by release date" turns chronological ordering off for a list.
Media Requests
- Added Seerr integration (Overseerr/Jellyseerr) as an alternative to VODUM's built-in Sonarr/Radarr request engine, with per-library configuration, account matching, availability indicators, season and 4K options, and request tracking.
- Added a configurable recent-requests limit in the user portal.
- Fixed Seerr requests for series without a TVDB id: the portal now looks up the TVDB series through Seerr's Sonarr lookup, picks a single match automatically and otherwise asks the member to choose, so the request reaches Sonarr.
- Improved Seerr request tracking: a request whose answer was lost is matched to the member's existing Seerr request so its status shows in the portal, and requests are no longer sent when Seerr has no default Sonarr/Radarr for the requested tier.
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
- Servers & libraries no longer briefly shows an empty "Plex · Loading… / Retry" box on each visit. Other Plex servers of the account appear only when there is one to add, or if the check fails.
- Removed the "Historical statistics cover completed playbacks" note from the Monitoring Servers tab.
- Removed the "Statistics computed at …" banners from Monitoring pages. A notice now appears only while statistics are being prepared, or when they are old or their refresh failed.
- A server that misses one Now Playing poll is polled again after its 5-minute pause, instead of staying unavailable until the next server check (up to 30 minutes).
- Now Playing shows each stream's video quality (resolution, codec, HDR/Dolby Vision) for Plex and Jellyfin. When the video is transcoded, it also shows the quality sent to the player (for example "4K HEVC HDR → 1080p H.264").
- Moved historical Monitoring statistics and additional filtered views to background precomputation, reducing heavy work during page requests while keeping live indicators current.
- These pages now only read results prepared in the background instead of calculating on each visit: the dashboard usage-risk card and server stream peaks, the usage-risk level and merge suggestions on a user's page, a Monitoring user's profile and IP addresses, and the Portal home and Monitoring statistics. A first visit may briefly show "Preparing statistics in the background"; live data (now playing, recent Portal playbacks, the Monitoring user history) stays live.
- A Sonarr/Radarr server page no longer waits for Sonarr/Radarr to list quality profiles and root folders: "Check servers" retrieves them in the background. Saving still validates them with the server.
- Improved Monitoring diagnostics and worker time limits for Plex/Jellyfin data collection.
- Optimized user searches, collection status polling, user profile loading, log filtering, and merge suggestions to reduce unnecessary database work.
- Added CPU and RAM indicators to server cards on the dashboard.
Security & Reliability
- Fixed trusted reverse-proxy header handling under Waitress, preserving VODUM's proxy validation and HTTPS/client-address detection.
- Improved Plex session termination verification to avoid treating malformed or incomplete responses as successful termination.
These changes are currently listed as unreleased. Production deployment and validation are not implied.