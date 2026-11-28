Changelog
Unreleased — November 28, 2026

Servers
- After adding a server, the confirmation now says "Server added" with the detected type (Plex, Jellyfin, Sonarr, Radarr, Seerr) and mentions synchronization only when one actually starts (Plex and Jellyfin).
Collections
- Added Hulu and Peacock to By platform, with dedicated posters for movie and series collections. Availability depends on the selected country. No database migration; restart VODUM after updating.
Telemetry dashboard
- The telemetry dashboard now looks like VODUM and groups its charts by theme (Overview, Versions, Platforms, Capacity, Features, Media requests, User portal, Communications, Server configuration, Activity, Collections, Languages, Security, Geography) with a side menu. A search box (shortcut /) filters metrics instantly, and the period, search and section are kept when switching period. Details that were hidden in pop-ups are now shown directly. Same privacy rules as before.
- Anonymous telemetry now also reports which VODUM features are used and at what scale: media requests, referrals and payments, portal support, server configuration and compliance, migrations, communications, stream policy rules, collection lists, admin security, retention settings, scheduled tasks, connected Radarr/Sonarr/Seerr, library types and size range, and 30-day usage peaks. Only counts and on/off flags are sent, never names, addresses, titles or identifiers. Deployment order: apply `worker_telemetry/migration_20261128.sql`, deploy the worker, then update VODUM. Older workers still receive the previous report format. See [feature telemetry](docs/telemetry-features.md).
Navigation
- The admin side menu is grouped by theme into collapsible groups: Users, Servers, Media and VODUM. Only the group of the current page is open. Clicking a group title opens its main page (Users, Servers & libraries, Collections, Settings). Dashboard, Monitoring and Log out stay outside the groups. Works the same on desktop and mobile.
- Migrations is now always in the menu. Without two compatible servers, its page explains what migrations are for and why none is possible yet.
Documentation
- Clearer side menu in the documentation site: section titles (Administration, Monitoring…) now look like labels, pages look like links, and sub-pages are indented under their parent.
- Clicking "Collections" in the documentation menu now opens the Collections page; the separate "Overview" entry is gone. The page address is unchanged.
- The documentation menu is reorganized: a Help tab (Troubleshooting, FAQ, About) and an Advanced tab (deployment, security, APIs, performance, architecture). Menu names now match the page titles and the app ("Location map", "Stream policies"…).
- "Stream policies" is now a real page (rules, scope, where to create them and follow enforcements) instead of a "page has moved" notice.
- The first-run wizard (Plex, Jellyfin or local account) is now explained in Installation & upgrades.
- Troubleshooting explains how to regain access to administration with the password.reset file.
- Up-to-date screenshots on the main pages (Dashboard, Users, Subscriptions, Collections, Monitoring, user portal).
- Guides are rewritten in plainer language, with a quick start at the top of the main pages, a richer FAQ, and technical details folded away. Internal development notes were removed.
Translations and display
- In the Docker image, some portal and admin texts were shown as raw keys or in English because they only existed in the legacy language files. They are now in the main catalogs.
- German, Spanish and Italian now cover the whole interface, many leftover English texts are translated, and broken accented characters are fixed. French accents are corrected too.
- Texts that were written in the pages instead of translated (login, setup wizard, servers, monitoring, communications, dashboard, gift form) now follow the chosen language.
- Dashboard: upcoming task names are now translated instead of showing their internal name.
- Phones: pages no longer overflow sideways at 390 px (Settings, Communications templates, Servers, Monitoring tabs).
- The remaining English texts are translated: Monitoring cards, Now Playing, user detail tabs, stream policies, the update badge, backup and Tautulli import status, server messages after saving, and modal close buttons.
- Setup wizard: the token field now reads "Plex token" or "Jellyfin API key" depending on the server type, in the chosen language.
- Collections: continent collections, content languages and the extra streaming countries are now named in the collection's language. Existing collections are renamed on their next run.
Default data
- Bundled message templates now come in all five languages, so each user receives them in their own language. Templates you edited are left untouched.
- Bundled template and subscription plan names follow the admin interface language, and switch when you change it. Names you changed are kept.
- The default stop messages shown on Plex or Jellyfin when a stream is cut are now in the user's language. Custom messages are kept as written.
Server configuration
- Added a Compliance section (menu, Servers group) to view, compare and align the settings of your Plex and Jellyfin servers. It has five tabs: Overview, Settings, Profiles, Groups and History, and the operating mode is shown as a badge on every tab, where it can be changed.
- The Overview lists your servers as compliant, not compliant, not verified, unreachable or not managed, with the number of settings that differ and the last check. Click a counter to filter, search, filter by platform or group, sort, and browse by pages of 50. Servers without a profile are shown as not managed, never as compliant.
- The Settings tab shows each setting once, with how the servers are spread over its values (for example "Automatic ×15 servers · Fast ×3 servers"; a value found on one server only has no count), the recommended and expected values, and how many servers are off profile. Show all servers of a platform, a group or your own selection, and filter on different values, off profile, not as recommended or settings with a recommendation. With one server, its whole configuration is shown.
- Click a setting to open a side panel with the servers grouped by value. In Manual remediation, tick servers (one by one, "Select all" on a value shared by several servers, the ones off profile or the ones not as recommended), pick the new value or take the recommended one, and preview: nothing is written before you confirm, and each server is read back afterwards. A setting can also be kept as a local exception for one server from there.
- Recommended values come from the official Plex and Jellyfin documentation (transcoder, hardware acceleration, HDR tone mapping, secure connections, Relay, database maintenance…), with the reason and a link to the source. Nothing is applied automatically. Other settings show the platform default.
- Pages load from the last read of each server kept in VODUM instead of calling every server, so they stay fast with many servers. Servers never read are read when the page opens, and "Read again" and "Check now" go through the servers a few at a time with a progress counter. Tokens, e-mails, identifiers and passwords are never stored nor shown.
- Settings that are expected to differ between servers (name, ports, paths…) are shown in a neutral style and not counted as differences. A setting that Plex names differently on each server (such as the GPU transcode limit) is shown on one line, and settings of a library missing on some servers are shown in grey.
- Added configuration profiles: save a server's settings as a profile (secrets and machine-specific values are left out), edit, duplicate or delete it. Added server groups (Plex and Jellyfin can be mixed). Assign profiles to servers or groups; when two profiles disagree on a setting, VODUM asks which one is the reference.
- Compliance is checked automatically with the server check (every 30 minutes by default), or on demand with "Check now". Only the settings of the profile are read, and servers are not called at all while no profile is assigned. Plex reads from this check wait behind posters and Now Playing. Settings changed directly in Plex or Jellyfin are listed under "Changes detected on the servers", and the logs report a deviation once, not at every check.
- Added deployments to apply a profile, or the current settings of a server, to servers chosen one by one, by group or all at once. VODUM first reads the targets and shows a preview with every change and the settings left out with the reason; nothing is written before you confirm. Servers are then changed one at a time, each change is read back to check it, and failures can be retried. Past deployments are listed in the History tab.
- Changes to servers are off by default: the operating mode starts on "Monitoring only" and must be switched to "Manual remediation" before VODUM may write anything. Network and remote access settings are left out of deployments unless you include them explicitly; secrets, identifiers, paths, ports and other server-specific values are never deployed.
- In manual remediation, the Overview can fix one server or every deviation, always through the same preview and confirmation.
- Confirmations in Settings > API access, in Compliance, when deleting a migration draft and in the Access tab of a user (force access resync, delete a removed provider account) now use a VODUM-styled window instead of the browser's own dialog.
- In the side panel of a setting, servers that do not offer the setting are now explained (not returned by the server at its last read, or library missing) and cannot be ticked. When the selected servers already have the chosen value, the panel says so and the preview stays off.
- Settings that Plex hides while another setting turns them off, such as "Enable HEVC Optimization" while "Enable HEVC video Encoding" is on "Never", are now explained in the side panel and can be changed: the preview first turns the other setting back on, and VODUM writes the two in that order.
- The Settings list has column headers again (Setting, Values on the servers, Recommended / expected, Differences), with fixed columns that no longer shift when a row has badges.
- Libraries missing on some servers no longer count as differences: "Different values" leaves them out, an "Include libraries" box shows or hides every library setting, and compliance ignores the settings of a library the server does not have. Profiles created or imported from a server can leave out library settings.
- The Settings filters are simpler. With several servers, "Show" picks one view at a time (All, Different values, Different from profile, Not as recommended, With a recommendation), each with its count, and "Include libraries" and "Include advanced settings" only add or remove settings. "Different from profile" replaces "Off profile" and only appears when a server has a profile. With a single server, its whole configuration is listed with only the two "Include" boxes.
- The Compliance documentation now covers the whole section: a quick start, the words used, the operating modes, each tab, the filters with one or several servers, the side panel, settings hidden by another setting (such as HEVC) and library settings.
- A local exception can now be removed: the side panel of the setting shows "Local exception" next to the server with a "Remove the exception" button, and the Settings list shows how many exceptions each setting has.
- In the Compliance Overview, click anywhere on a server's line to open it; the separate "Open" button is gone.
- Compliance now fits phones: the tabs scroll on one line, filters and "Show" choices wrap instead of overflowing, setting badges no longer cover the setting name, the server picker stays on screen, previews list each change as a card titled with the setting, and the side panel keeps room for the servers. In the side panel, the button that leads to the preview is now called "Apply…" and no longer touches the new value field.
- In French, "No" was shown in English across the interface; it now reads "Non".
API
- Added a read-only API for dashboards such as Homepage, Homarr or Grafana. Create named tokens in Settings > API access, choose what each one may read (statistics, servers, playback, user counts) and revoke them at any time. Each new token is shown once in a window over the settings page. Tokens are limited to 60 calls per minute, and never expose emails, IP addresses, server credentials or payments. See the Dashboard API documentation.
Docker
- Fixed the Docker image build on Python 3.14 (Debian trixie): the image now installs libatomic1, which the Playwright installer needs.
Monitoring
- Now Playing posters no longer go missing while VODUM is busy with Plex in the background (collections, scans). Posters now go ahead of background Plex requests instead of timing out behind them.
- The statistics refresh no longer reports an error when its time budget runs out on a view that started late. That view keeps its previous figures and is refreshed on the next run.
Monitoring > Libraries
- "Media growth" and "Media added" now show the net change in each library's size and item count between scans. Media re-added by Plex or Jellyfin (rescan, path change, library rebuild) no longer count as new.
- After updating, both columns wait for a second daily scan, then show "Since <date>" until the history covers the selected period.
- Restored the "Media growth" column name.
- "Media added" now really shows the net item count (for example +12 or −3) instead of every item with a recent addition date. It shows "—" until a second scan.
- A failed scan now shows a short "Scan failed, check logs" message. The date of the attempt is in the tooltip.
- The daily scan no longer skips a server that answers again after a brief outage. Before, a single failed Now Playing poll kept the server marked unavailable until the next server check (up to 30 minutes), so the scan was often skipped and the columns stayed on "Awaiting a second scan". A server still in its 5-minute cooldown is retried at the end of the scan.
- Jellyfin scans read the oldest media first, so media added while a large library is being scanned no longer cause duplicates that made the scan fail.
Collections
- The dashboard Collections card now shows collections in error in red, apart from those that only need a review. On wide screens the counters stay on one line, so the row of cards keeps its height.
- In Collections, the status dot of a collection in error is now red instead of orange.
- Top Streaming by Country now builds movies and TV the same way: the top of each major subscription platform in the country (up to 10, as listed by TMDb for that country, Canal+ included), with Netflix's official Top 10 first on Netflix, combined rank by rank. TV no longer uses weekly global TMDb trends, which brought in long-running anime. Each platform is read deeper when needed, so overlaps no longer leave the collection short of the number of displayed media. The selection changes on the next run.
- Top Streaming by Country: Netflix Top 10 titles, published in English, are now matched in English and shown in the collection language. A title that cannot be matched is left out quietly (the TMDb Netflix ranking fills the place) instead of logging an error at every run.
- Top Streaming by Country now ranks each platform by its JustWatch popularity in the country instead of TMDb's worldwide popularity, so titles mostly watched elsewhere (such as Japanese anime) no longer crowd the collection. JustWatch is used through its free public interface, without account or key; if it is unavailable for a platform, that platform falls back to TMDb with a warning.
- The chronological order is now edited straight from the media table of a list: the table shows the entries in order, ↑ ↓ arrows between Origin and Enabled move an entry and save right away, and a ↺ button in the column header goes back to the default order after a confirmation in the collections window. The separate "Chronological order" panel and its Save button are gone.
- Each collection poster now has a single file. A new version replaces it in place and is sent to Plex/Jellyfin on the next run. Unused old poster versions were removed from the Docker image.
- Dune and Game of Thrones collections now use their latest posters.
- Audited the 32 built-in franchise lists. They stay global (create your own list for a narrower selection), but DC Universe no longer includes adaptations without DC Universe characters (A History of Violence, V for Vendetta, Road to Perdition, Stardust, RED, and others). Added 160 checked titles: the DC TV series (Arrowverse, Smallville, animated series, The Penguin, The Sandman…) and more DC films, the MCU series (Disney+, Marvel Television, Netflix), the Star Trek series, more Star Wars specials and series, Alien: Earth and Avengers: Secret Wars. Fixed the Middle-earth entry for The Return of the King (1980) and removed two untitled Star Trek projects. Existing installations receive these changes on update; entries you added yourself are kept.
- Franchise lists can now have a chronological (story) order. In "Lists", open a list, expand "Chronological order", arrange the entries and save. Plex shows the Franchise collection in this order; without one, the VODUM order (below) or the release dates apply. Jellyfin cannot sort collections manually, so the order is kept in VODUM only.
- VODUM lists now come with a chronological (story) order for the main continuity of 31 franchises, such as Star Wars, the MCU, Star Trek, Middle-earth, the Wizarding World, Alien & Predator and the DCEU/DCU films. Titles outside the main story (LEGO, Elseworlds, separate continuities, specials) follow by release date. Your own saved order still wins, "Back to default order (chronological)" removes it, and "Sort by release date" turns chronological ordering off for a list.
Media Requests
- Added an optional request limit per user in User portal > Media request settings (off by default): a number of requests per day, 7 days or 30 days, for VODUM and Seerr requests sent from the portal.
- When Sonarr/Radarr's answer to a request is lost, VODUM now checks that instance later and shows whether the media was added, instead of leaving the request uncertain. The request is never sent twice.
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
- Updated the Docker image to Python 3.14 (Debian trixie) and the Python dependencies pytz 2026.6, python-dateutil 4.0, croniter 7.0 and Playwright 1.65. Default task schedules are unaffected by the croniter 7 changes; a schedule edited by hand that starts a step at a field's maximum (such as `59/15`) now means that single value.
- Fixed trusted reverse-proxy header handling under Waitress, preserving VODUM's proxy validation and HTTPS/client-address detection.
- Improved Plex session termination verification to avoid treating malformed or incomplete responses as successful termination.
These changes are currently listed as unreleased. Production deployment and validation are not implied.
