# Library growth

Open **Monitoring → Libraries** to compare playback and additions by library.
Choose a growth period of **7 days**, **30 days** or **1 year**.

## What is counted

For each followed library, VODUM compares two successful scans and reports the
net change of the film or episode count (**Media added**, for example `+12` or
`−3`) and of the total file size declared by Plex or Jellyfin (**Media
growth**). Libraries followed for growth can appear even if they have no
playback history. Playback and growth figures are shown together but measure
different activity.

Addition dates are not used: Plex and Jellyfin reset them when media is
re-added (rescan, path change, library rebuild), so a re-added library does not
count as new. Both columns show a dash or "Awaiting a second scan" until a
second daily scan exists, then "Since <date>" until the history covers the
whole period. Added episodes are not a count of new shows.

## Freshness and incomplete data

A daily background task refreshes the stored measurements. On an existing
installation, startup creates the storage and task; allow the first run to
finish before expecting growth figures. A failed refresh preserves the last
available measurement and its timestamp. A server that just had a short
outage is scanned again at the end of the run; the scan is skipped only if the
server still does not answer.

Each library scan has a 30-minute time budget, checked between requests and
items. A request already in progress remains subject to its own network timeout.
For TV libraries, the scan reads episodes rather than shows, so a library with
8,000 shows can involve hundreds of thousands of episodes. To retry manually,
run **Refresh library growth statistics** from **Tasks**. Search the logs for
`refresh_library_growth` to find the library/server IDs, elapsed seconds and
scan budget on completion or failure. In the table, a failed scan shows
"Scan failed, check logs"; hover it to see the date of the attempt.

Some providers or media items may not expose complete file sizes. The interface
marks incomplete sizes rather than claiming an exact total. Compare the saved
measurement time with the provider's current library state when investigating
differences.

## Playback rankings

The library table displays before the most-watched-title rankings. Rankings
load when their section becomes visible and reuse recent aggregates for the
same filters. A section that is still loading does not imply that its library
has no playback history.
