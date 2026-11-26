# Award Winners

A clickable collection model in More ways to watch / discover. It supports Oscars, BAFTA, Golden Globes, Emmys, Cannes, Césars, Berlinale and Venice, with a separate bundled poster for each award. The Emmy poster is labelled Television Winners.

The user chooses a reward and period (latest completed edition with winners, a specified year, or all years), library, presentation language, optional original-language filter, sort (award order/newest release/popularity), limit, priority, schedule, activation, visibility and optional Arr acquisition. Movie-only awards restrict library selection; Emmys requires a series library. Golden Globes supports film and series. New configurations default to 30 displayed media; zero means unlimited within the available winner data. The shared adapter cap applies to local editions and partial updates.

## Sources and scope

Event IDs and principal-category filters are recorded in app/data/awards_sources.json. They select the main winning film or series categories. Third-party provenance and license notices are recorded in docs/third-party/collection-sources-provenance.json.

Winner identifiers are read from the public award dataset configured by dataset_url_template. YAML parsing is safe, responses are size-bounded and cached for 24 hours; only winner arrays in the configured categories are accepted. Latest selects the latest edition with actual selected-category winners, skipping empty future editions. All-years deduplicates identities and puts the most recent award years first.

IMDb IDs resolve to typed TMDb identities through /find, cached for 30 days. Opposite media types and episodes are excluded. Unresolved identities produce a partial result; unknown local identities are never acquired. Missing films use Radarr; missing series use Sonarr and verified TVDb identities, through the existing linked-server routes and request journal. Preview uses read-only Arr planning (`preview=True`) and never publishes or adds media. Cleanup needs no source lookup.

Malformed/unavailable source data preserves existing publication. A changed award or edition does not preserve unrelated old winners during a partial refresh. Poster upload follows normal synchronization, keeps custom images and requires deployment to become active on a remote instance.

Read-only source verification during implementation found available latest winner sets for all eight awards and both Golden Globes media types. Plex/Jellyfin writes and actual Arr additions are covered by mocked integration tests, not live production operations.

Source provenance: `docs/third-party/collection-sources-provenance.json`.
