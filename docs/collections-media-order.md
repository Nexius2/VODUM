# Media order

Every model offers Ranking, Date added and Random in addition to its existing native sorts. The backend saves those choices without forcing a model-specific sort over them.

Ranking preserves the native order of the selected chart/model. Date added sorts selected media by the server addition timestamp, newest first; unknown dates sort last. Random uses a new random seed per engine invocation and a deterministic per-ID key within that invocation, so preview/result and repeated publication steps agree. Seasonal daily random retains its original local-date-based behavior.

These three common orders arrange the selected membership; model eligibility, chart/year/category selection, acquisition requests and limits remain authoritative. The common adapter applies ordering again after bounded partial-membership merging, which cannot increase the configured limit. Plex publishes a custom item order. Jellyfin retains the existing explicit custom-order-unsupported warning; its collection API cannot reproduce Plex custom item ordering through this adapter.
