# Stream policies

Stream policies limit what users can play at the same time: number of streams,
public IPs, bitrate, transcodes or devices. VODUM checks active playback every
60 seconds and warns the user, or stops a stream, when a rule is broken.

## Quick start

1. Open **Subscriptions → Policies**.
2. Choose a **Rule** and a **Limit value** (for example *Maximum streams per user*, limit `2`).
3. Choose the **Scope**: global, one server or one user (leave the ID empty for global).
4. Choose which stream is stopped first in **Target selection**, then fill in the
   **Warning title** and **Warning message** shown to the user.
5. Click **Create policy**, then follow the results in **Monitoring → Policies**.

!!! tip "Start gently"
    Try a new rule with a generous limit and watch **Monitoring → Policies**
    for a few days before tightening it.

## Available rules

| Rule | What it limits |
| --- | --- |
| Maximum streams per user | Simultaneous streams of one user |
| Max IPs per user | Public IP addresses used at the same time by one user |
| Maximum streams per IP | Simultaneous streams from the same public IP |
| Maximum transcodes (global) | Simultaneous transcodes on a server |
| Maximum bitrate | Bitrate of remote streams, in kbps |
| Block 4K transcoding | Transcoding of 4K media |
| Allowed devices | Devices allowed to play (comma-separated names) |

**Provider** limits a rule to Plex, Jellyfin or both. **Priority** decides which
rule applies first: a lower value means a higher priority.

## Policies from plans and users

A plan can carry its own policies (**Subscriptions → Plans**), so every user on
that plan gets them. The user page lists the **Active policies** applied to that
user, by priority. When a subscription expires in *Warn only* mode, VODUM adds a
system policy that is removed again on renewal (see [Subscriptions](subscriptions.md#start-and-expiration)).

## Follow what happened

**Monitoring → Policies** lists the policies by scope and the recent
enforcements: who was warned or stopped, on which server, from which IP and
device, and which streams were running at that moment. Group by user to see one
person's history.

When a stream is stopped, the user sees the warning message on their player.

!!! note "Good to know"
    IP addresses and locations are approximate (VPN, mobile networks, shared
    connections). Check the enforcement details before concluding that an
    account is being shared.
