# Library growth

Open **Monitoring → Libraries** to compare playback and additions by library.
Choose a growth period of **7 days**, **30 days** or **1 year**.

## What is counted

For each followed library, VODUM reports added films or episodes and the size
of their files as declared by Plex or Jellyfin. Libraries followed for growth
can appear even if they have no playback history. Playback and growth figures
are shown together but measure different activity.

These values describe media **still present in the provider library**, using its
addition dates. They are not a historical storage audit and do not reconstruct
items deleted before the measurement. Added episodes are not a count of new shows.

## Freshness and incomplete data

A daily background task refreshes the stored measurements. On an existing
installation, startup creates the storage and task; allow the first run to
finish before expecting growth figures. A failed refresh preserves the last
available measurement and its timestamp.

Each library scan has a 30-minute time budget, checked between requests and
items. A request already in progress remains subject to its own network timeout.
For TV libraries, the scan reads episodes rather than shows, so a library with
8,000 shows can involve hundreds of thousands of episodes. To retry manually,
run **Refresh library growth statistics** from **Tasks**. Search the logs for
`refresh_library_growth` to find the library/server IDs, elapsed seconds and
scan budget on completion or failure.

Some providers or media items may not expose complete file sizes. The interface
marks incomplete sizes rather than claiming an exact total. Compare the saved
measurement time with the provider's current library state when investigating
differences.

## Playback rankings

The library table displays before the most-watched-title rankings. Rankings
load when their section becomes visible and reuse recent aggregates for the
same filters. A section that is still loading does not imply that its library
has no playback history.
