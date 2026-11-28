# Library growth

Open **Monitoring → Libraries** to see, for each library, how much was played and
how much was added. Choose a period of **7 days**, **30 days** or **1 year**.

## What the columns mean

- **Media added**: change in the number of films or episodes, for example `+12` or `−3`.
- **Media growth**: change in the total file size reported by Plex or Jellyfin.

VODUM compares two daily scans of each library. It does not use the "date added"
of Plex or Jellyfin, because they reset it when media is re-added (rescan, new
path, library rebuild): a re-added library is not counted as new. For series,
added episodes are counted, not new shows.

## Why a figure is missing

- **Awaiting a second scan**: growth needs two daily scans. After installing or
  upgrading, wait for the second day.
- **Since <date>**: the history does not cover the whole period yet.
- **Scan failed, check logs**: the last scan failed. Hover it to see the date of
  the attempt; the previous figures are kept.
- Some servers do not report every file size; incomplete sizes are marked as such.

To scan again by hand, run **Refresh library growth statistics** in [Tasks](tasks.md).
If a server was briefly offline, it is scanned again at the end of the run.

??? info "Technical details"
    Each library scan has a 30-minute budget. For series libraries VODUM reads
    episodes, so a library of 8,000 shows can mean hundreds of thousands of items.
    Search the logs for `refresh_library_growth` to find the library and server
    IDs, the time spent and the budget.

## Playback rankings

The most-watched titles load when you scroll to them. A section that is still
loading does not mean the library has no playback.
