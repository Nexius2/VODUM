# Collection parameter audit — 2026-10-26

## Halloween exceeding a configured limit

Two independent paths could exceed the displayed-media limit: a limited list of TMDb titles can resolve to several local edition IDs per title; and partial provider failures deliberately preserve previous membership while new, daily-random titles are added. Thirty previous members plus thirty new members can therefore become sixty.

The shared matching engine now caps unique local media IDs, not just discovery titles. Both publication adapters also enforce a final membership cap. For a partial refresh with a finite limit, verified desired members take precedence and previous members fill remaining capacity only. Excess collection associations are removed; media files are never deleted. With a zero/unlimited limit, partial-refresh preservation is unchanged. Full discovery/connection failures still preserve the remote collection until a successful synchronization is possible.

## Scope checked

| Model | Selection and sorting | Limit scope | Acquisition |
|---|---|---|---|
| Seasonal | Per event; country calendar; local/web/both; daily random, release or popularity | Per event and library, unique media IDs | Optional for web/both; rejected for local |
| Streaming country | Country market charts; optional original language before limit; source rank | Per library | Optional |
| Streaming worldwide / continent | Global or aggregated continental ranking; original language filter | Per library | Optional |
| IMDb | Allowlisted chart and matching movie/TV library; chart order | Per library | Optional |
| TMDb | Allowlisted movie/TV top-rated/popular chart; chart order; source cap 250 | Per library | Optional |
| Kids | Family movies / Kids series, country availability, Top/last-365-days, original and required audio languages | Per library; required audio before local limit | Missing titles cannot be acquired when audio is mandatory |
| Family | Local Family/Kids genres only; server rating or latest release; optional regional audio | Per library | Rejected |
| Recently added | Server addition timestamp, descending | Per library | Rejected |
| Latest releases by country | Original-language country group, descending release date, bounded resumable metadata analysis | Per library | Rejected |
| Memoria | Credits, tribute eligibility, popularity threshold, max people, retention and chosen media sort | Per person collection and library | Optional |
| Spotlight | Eligibility dates, digital release window, min score, audio, retention and incremental membership | Per library | Rejected |

Shared parameters (limit, priority, language, weekly schedule, activation and visibility) are round-trip tested for every catalog model, including invalid bounds. Existing model-specific tests cover selection, language, Arr, ownership, preview and cleanup. Adapter tests reproduce sixty-to-thirty partial trimming and repeated daily changes without growth in Plex, and trimming of excess collection associations in Jellyfin.

API defaults now come from the catalog, matching creation through the UI. Spotlight's saved sort is normalized to availability. Family's sort selector follows its Top/latest chart instead of offering a contradictory ignored sort.

## Deployment

Changes are local to this repository. After deploying, a successful normal synchronization of the existing owned Halloween collection will apply the cap; no collection recreation or media deletion is required. An old collection above the cap is preserved while its sources or media server remain completely unavailable. This audit uses local tests, not a live inspection of the pictured server.
