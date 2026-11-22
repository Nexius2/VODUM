# User map

Open **Monitoring → Location** to explore playback locations associated with
stream IPs. The map is an administrator view; it is not a list of precise user
addresses and is not exposed as the portal's personal monitoring page.

## Current and recent activity

Switch between recent known playback and live-only activity. Filter by server
or country, select active playback where offered, and enable the heatmap to
inspect concentration. Live state follows saved monitoring sessions and their
refresh window; it is not a direct continuous probe of a client device.

## Historical playback

Choose a period of **1 day, 7 days or 30 days** and use the timeline to inspect
a point within that interval. Playback controls advance the selected instant.
The live switch is disabled while a historical period is selected. Return to
the current view to resume live filtering and automatic refresh.

## Interpreting a location

IP-based geolocation is approximate. VPNs, proxies, mobile networks and shared
connections can place multiple people at the same point or move a single person
between locations. Private/local addresses cannot establish a public geographic
location. Missing coordinates should not be treated as inactivity or proof of
account sharing.

Use the map together with session details and [stream policies](policies.md),
not as independent evidence for blocking a user.
