# Compliance

**Compliance** shows the settings of your Plex and Jellyfin servers in one
place, keeps reference profiles, checks that servers follow them and, if you
allow it, changes settings on servers. It stays readable whether you have one
server or hundreds.

By default VODUM only reads your servers. It changes nothing until you switch
the operating mode to **Manual remediation**, and even then only after a
preview and your confirmation. Profiles, groups and exceptions are stored in
VODUM only.

Open **Compliance** in the menu, in the **Servers** group. The section has
five tabs:

| Tab | What it is for |
|---|---|
| [Overview](#overview) | Where each server stands against its profile, and the checks. |
| [Settings](#settings) | Each setting once, with the values of all the servers, and the side panel to change it. |
| [Profiles](#profiles) | The expected values, and which servers they apply to. |
| [Groups](#groups) | Sets of servers, to target profiles and deployments. |
| [History](#history-and-deployments) | Deployments: start one, follow it, see past ones. |

The [operating mode](#operating-mode) is shown as a badge at the top right of
every tab; click **Change** on it to switch mode. With no Plex or Jellyfin
server, the page invites you to add one in
[Servers & libraries](servers-libraries.md).

Every tab works on a phone: the tabs scroll sideways, lists become cards, and
the side panel of a setting takes the whole screen.

## Quick start

1. **Look at your servers.** Open **Settings**: every setting is listed once,
   with the values found on your servers. With several servers, the list opens
   on the settings whose values differ.
2. **Create a profile.** In **Profiles** > **New profile**, start from the
   current settings of a server that is set up the way you like. Tick **Leave
   out library settings** if your servers do not have the same libraries.
3. **Apply it to servers.** On the profile page, under **Applies to**, tick the
   servers or groups it is meant for.
4. **Check.** In **Overview**, click **Check now**. Each server is shown as
   compliant, not compliant, not verified, unreachable or not managed, with the
   number of settings that differ.
5. **Fix, if you want to.** Switch the mode to **Manual remediation**, then use
   **Fix this server**, **Fix all deviations**, the side panel of a setting in
   **Settings**, or a deployment in **History**. Each of these shows a preview
   first, and nothing is written before you confirm.

## Words used on these pages

| Word | Meaning |
|---|---|
| Profile | A set of expected values for one platform (Plex or Jellyfin). |
| Reference profile | The profile a server is compared with. A server with several profiles gets them merged, or you choose one if they disagree. |
| Different from profile | A server does not have the value its reference profile expects. Also called a deviation. |
| Recommended value | The value advised by the official Plex or Jellyfin documentation. Only shown, never applied on its own. |
| Platform default | The value Plex or Jellyfin uses when nobody changed the setting. Shown when there is no recommendation. |
| Local exception | One server keeps its own value for one setting. It is no longer a deviation and is never deployed there, until you remove the exception. |
| Specific to each server | A setting expected to differ between servers (name, ports, paths…). Never counted as a difference. |
| Not present | The server did not return the setting at its last read, or does not have the library. |

## Operating mode

| Mode | What VODUM does |
|---|---|
| Monitoring only (default) | Reads servers and shows deviations. Never changes a server. |
| Manual remediation | Can fix and deploy settings, always after a preview and your confirmation. |
| Automatic remediation | Not available yet. It will never be switched on by itself. |

Switching to manual remediation asks for a confirmation, from the badge at the
top right of every tab or from the **History** tab. You can go back to
monitoring only at any time. In monitoring only, the pages show deviations and
a reminder that they are not fixed, and every button that would write to a
server is hidden.

## Overview

The Overview lists every Plex and Jellyfin server with a badge showing its
type, its status against its reference profile, its profile, its groups, the
number of settings that differ and the date of the last check.

| Status | Meaning |
|---|---|
| Compliant | Every setting of the profile has the expected value. |
| Not compliant | At least one setting differs from the profile, or is absent from the server. Settings of a library the server does not have are ignored. |
| Partly verified | Part of the server could not be read; the settings concerned were not verified. |
| Profile changed | The profile was edited after the last check; the next check updates the result. |
| Profile conflict | The server's profiles disagree; choose its reference profile in **Profiles**. |
| Not checked yet | The server has a profile but has not been checked. |
| Unreachable | The server could not be read: offline, refused access or too slow. |
| Not managed | The server has no profile. It is never considered compliant. |

- The counters at the top filter the list: click one, click it again to show
  every server. **Not verified** groups partly verified, profile changed,
  profile conflict and not checked yet.
- Search a server, filter by platform or group, and sort by status (problems
  first), number of differences, name or last check. Long lists are shown by
  pages of 50.
- Click a server's line to open its whole configuration in the **Settings**
  tab (Ctrl+click or Cmd+click opens it in a new tab). Settings that differ
  from its profile are flagged in the **Differences** column.
- **Check now** checks the servers one after the other, a few at a time, with
  a progress counter, then refreshes the page.
- The number of local exceptions of a server is shown under its name.
- In **Manual remediation** mode, **Fix this server** and **Fix all
  deviations** open a preview of the changes (see [What happens when you
  confirm](#what-happens-when-you-confirm)). Nothing is written before you
  confirm.

### When checks run

- Automatically after each run of the **check_servers** task (every 30 minutes
  by default), after the server statuses are updated. No server is called while
  no profile is assigned.
- On demand with **Check now**.

A check reads only what the profile needs: for Plex, the server preferences
and the libraries named in the profile; for Jellyfin, the sections that hold
the profile's settings. The automatic check reads up to four servers at the
same time and stops after 90 seconds (servers not reached keep their previous
result), and its Plex requests wait behind posters and Now Playing. A server
that is offline during the automatic check is marked unreachable without being
called.

### Changes made on the servers

VODUM keeps the last value seen for each setting of the profile. When a value
changes between two checks, for example after someone changed it in Plex or
Jellyfin, it appears under **Changes detected on the servers** with the old
and new values. The last 50 changes per server are kept.

The VODUM logs (category `server_configuration`) report a deviation when it
appears or changes, and when a server is back in line, not at every check.

## Settings

The **Settings** tab shows each setting once, with the values of all the
servers shown.

### Choose the servers

- **Platform**: Plex or Jellyfin, with the number of servers of each. Only the
  platforms that have at least one server are offered, and the choice is
  hidden when you only use one. Settings are only compared within one
  platform.
- **Servers shown**: all servers of the platform, one group, or **Choose
  servers…** to tick servers in a list with a search field, then **Show these
  servers**.

### Where the values come from

The page works from the last read of each server kept in VODUM, so it opens
quickly even with many servers. The date of the oldest read is shown at the top
right; **Read again** reads the servers shown again, a few at a time, with a
progress counter. A server never read is read on its own when the page opens.
A server that cannot be read is listed above the settings with the reason and
left out of the counts.

Compliance checks and deployments also update the values they read.

### Read a line

The list has four columns:

| Column | What it shows |
|---|---|
| Setting | The name of the setting and its category. For a library setting, the library name comes first, for example *Films · Allow red band trailers*. |
| Values on the servers | How the servers are spread over the values, for example *Automatic ×15 servers · Prefer higher speed encoding ×3 servers*. A value found on one server only has no count. Up to three values are shown; the others are counted as "+N other values". |
| Recommended / expected | The recommended value (or the platform default), and the value expected by the profile when there is one. |
| Differences | How many servers differ from their profile, and how many are not as recommended. |

Values are highlighted when they differ between servers. Lines shown in a
neutral style are not counted as differences:

- *specific to each server*: settings expected to differ, such as the server
  name, ports or paths.
- *same setting under a different name on each server*: a setting that Plex
  names differently on each server, such as the GPU transcode limit, shown on
  one line.
- *library not on every server*: see [Libraries](#libraries).

A dashed **Not present** value means the server did not return the setting.
Hover it, or open the side panel, for the reason.

Masked values (secrets, identifiers) are never stored, compared or shown.

### Filters

Search and **Category** narrow the list in every case. The other filters depend
on the number of servers shown.

**With several servers**, **Show** picks one view at a time. Picking a view
always replaces the previous one, and each view shows how many settings it
holds.

| View | Settings listed |
|---|---|
| All | Every setting. |
| Different values (default) | Settings that do not have the same value everywhere. Settings of a library missing on some servers are not counted as differences. |
| Different from profile | Settings where at least one server differs from its own reference profile, without counting local exceptions. Only offered when a server shown has a profile. |
| Not as recommended | Settings where at least one server differs from the value advised by Plex or Jellyfin. |
| With a recommendation | Settings for which Plex or Jellyfin advise a value. |

**With a single server**, there is no **Show** choice: its whole configuration
is listed. Settings that differ from its profile or from the recommendation are
still flagged in the **Differences** column.

In both cases, two boxes only add or remove settings, whatever the view, and
the counts follow them:

- **Include libraries** (ticked by default): the settings of each library.
- **Include advanced settings**: the settings Plex or Jellyfin mark as advanced.
  A search finds them even when the box is not ticked.

### Recommended values

For the settings where the official Plex or Jellyfin documentation advises a
value, such as the transcoder quality, hardware acceleration, HDR tone
mapping, secure connections, Relay or the database maintenance tasks, VODUM
shows it with the reason and a link to the source page. Recommendations are
only shown: VODUM never applies them on its own. Other settings show the
platform default.

### Side panel of a setting

Click a line to open its panel. It shows the recommended and expected values,
then the servers grouped by value, values with servers that differ from their
profile first. Long groups show their first 12 servers; **Show all** opens the
rest. Each server that differs from its profile shows the expected value and
**Keep as exception**. Press Escape or click outside to close the panel.

In **Manual remediation** mode, the panel can change the setting:

1. Tick the servers to change: one by one, or **Select all** next to a value
   shared by several servers. Above the value field, **Select off profile**,
   **Select not as recommended**, **Select all** and **Select none** work on
   every value at once. With one server, it is already ticked.
2. Choose the **New value**: a list for settings with choices, Yes/No, or a
   field. **Use the recommended value** fills it in.
3. **Apply…** opens the usual preview, which shows every change with
   its current value. Nothing is written before you confirm it there. Each
   server is then changed and read again to check the new value.

If the selected servers already have the chosen value, the panel says so and
**Apply…** stays off. One preview covers up to 50 servers; the panel
says when the selection is larger. A server's own name, ports or paths can be
changed this way, on that server only. Secrets and scheduled tasks cannot be
changed. In **Monitoring only** mode the panel is read-only.

#### Servers marked Not present

A server marked **Not present** did not return the setting at its last read.
Plex and Jellyfin list some settings only depending on other settings, the
hardware they detect or their version. For a library setting, the library does
not exist on that server. Such a server cannot be ticked; once it offers the
setting, click **Read again** and it can be changed.

#### Settings hidden by another setting

Plex hides some settings while another setting turns them off. For example
**Enable HEVC Optimization** is not returned while **Enable HEVC video
Encoding** is set to **Never**. The panel says so on the servers concerned,
and they can still be ticked:

- the preview also sets the other setting to its default value (here
  **HEVC/AV1 Sources Only**), and shows both changes;
- VODUM writes that setting first, then the hidden one;
- if the first change fails, the hidden setting is not written.

### Local exceptions

**Keep as exception** tells VODUM that one server keeps its own value for a
setting, for example a heavier transcoding setting on a more powerful machine.
The setting is no longer counted as a deviation for that server and is never
deployed to it.

A server kept as an exception shows **Local exception** in the panel, and the
line of the setting shows how many exceptions it has in the **Differences**
column. **Remove the exception** next to the server makes it follow its
profile again: a different value counts as a deviation again and can be
deployed. Adding or removing an exception never writes to the server and works
in both operating modes. The Overview shows how many exceptions a server has.

## Libraries

Library settings (Plex library options, Jellyfin library options) are handled
so that a library missing on a server is never reported as a problem:

- Libraries are matched by name, so the "Films" library of two servers is
  compared even if its ID differs.
- When a library is not on every server, its settings are shown in a neutral
  style, marked *library not on every server*, and are not counted in
  **Different values**. The servers without it show **Not present**.
- **Include libraries** in **Settings** shows or hides every library setting.
- Compliance ignores the settings of a library the server does not have, so a
  server is not marked not compliant because of it.
- Profiles created or imported from a server can **Leave out library settings**
  entirely.
- A deployment leaves out the settings of a library the target does not have,
  with the reason **Not available on this server**.

## Profiles

A profile is a set of expected values for one platform. Create one in
**Profiles** > **New profile**:

- **Current settings of a server** copies the settings that can be changed,
  without secrets or values that belong to one machine (server name, paths,
  ports, addresses, hardware devices, identifiers) or scheduled tasks. The
  message after creation tells you how many settings were left out.
- **Leave out library settings**, when creating or importing from a server,
  keeps only the server settings.
- **Empty profile** starts with no settings; use **Import from a server** on
  the profile page to add some.

On the profile page you can rename the profile, edit or remove its values,
import the settings of another server of the same platform (only new settings
are added unless you tick **Also replace the values already in the profile**),
duplicate it, delete it and **Compare servers**, which opens the **Settings**
tab on its servers, on the **Different from profile** view.

**Applies to** lists the servers and groups the profile is meant for. A
profile only applies to servers of its own platform, even inside a mixed group.
Assigning a profile writes nothing to the servers.

### When profiles disagree

A server can get several profiles, directly and through its groups. If they
expect the same values, they are merged. If they expect different values for
a setting, **Reference per server** on the Profiles tab shows the number of
conflicting settings and asks you to choose the reference profile for that
server. You can change this choice at any time. A server without a profile is
shown as **No profile**.

## Groups

Groups gather servers, for example "Family servers". A group has a name, an
optional description and any number of servers; a server can belong to
several groups, and a group can mix Plex and Jellyfin servers. Groups can be
used in **Settings** (servers shown), in **Applies to** of a profile and as
deployment targets. Deleting a group keeps its servers and removes it from the
profiles that targeted it.

## History and deployments

The **History** tab sets the operating mode, starts deployments and lists the
previous ones.

### Deploy settings

1. In **History** > **New deployment**, choose what to apply: a profile, or the
   current settings of a server (secrets and server-specific values are left
   out, as when creating a profile).
2. Choose the targets: servers one by one, groups, or **All compatible
   servers**. Only servers of the same platform are used, up to 50, and never
   the source server itself.
3. Click **Preview changes**. VODUM reads the targets (nothing is written) and
   shows, per server, each setting that would change with its current and
   expected values. Settings that already have the expected value are not
   listed.
4. Untick the changes you do not want, then **Apply the changes** and confirm.
   This button only appears in manual remediation mode. **Discard** drops the
   preview.

Settings left out are shown with the reason:

| Reason | Meaning |
|---|---|
| Local exception of this server | The server keeps its own value (see [Local exceptions](#local-exceptions)). |
| Not available on this server | The server, or its library of that name, does not have this setting. |
| Specific to this server or read-only | Secrets, identifiers, paths, ports, addresses, hardware devices, or values the server does not let VODUM change. Never deployed. |
| Network or remote access: left out by default | Tick **Include network and remote access settings** to deploy them. A wrong value can make a server unreachable. |

### What happens when you confirm

- Servers are changed one at a time, while the page shows the progress. A
  server is never changed by two deployments at the same time.
- After writing, VODUM reads each setting back from the server. A setting is
  **verified** only if the server returns the new value; otherwise it is
  **failed** with the reason (refused, not kept by the server, unreachable…).
- A failure on one server does not undo the others. **Retry failures** (per
  server) or **Retry all failures** applies only what failed.
- The compliance of a changed server is updated from the same read when the
  read covers its whole profile; otherwise at the next check.

How settings are written: Plex server settings and library options are sent
with the Plex API (`/:/prefs` and `/library/sections/{id}/prefs`). For
Jellyfin, VODUM reads the configuration section, changes only the chosen
settings and sends the section back (`/System/Configuration`, its named
sections and `/Library/VirtualFolders/LibraryOptions`, where library folders
are sent back unchanged).

**Previous deployments and fixes** lists the last 20 runs with their result.
Each run keeps the previous value of every changed setting, so you can see
what was changed; VODUM does not undo a deployment automatically.

## What is read

| Platform | Settings read |
|---|---|
| Plex | Server preferences (`/:/prefs`) and the advanced options of each library known to VODUM |
| Jellyfin | General configuration, transcoding (`encoding`), network, metadata and branding, library options and scheduled tasks |

Plex provides the names and descriptions of its settings in English. Jellyfin
provides none, so VODUM shows its technical names in readable form. Reading a
Plex server with many libraries can take a few seconds: Plex is asked at most
one request per second, and a read stops after 45 seconds.

Never stored nor shown: Plex account token, e-mail and machine identifiers,
passwords, certificate passwords, API keys and the folders of Jellyfin
libraries.

## Requirements and errors

The token (Plex) or API key (Jellyfin) saved in **Servers & libraries** must
belong to an administrator of the server.

| Message | What to do |
|---|---|
| The server refused access | Save an administrator token or API key for this server. |
| The server could not be reached | Check the server address and that the server is running. |
| The server took too long to answer | Try again later, for example after a long scan. |
| Unexpected answer | Search the logs for `server_configuration`. |

## Frequently asked questions

**Why does a setting exist on one server and not on another, with the same
version?** Plex only returns some settings depending on other settings or on
the hardware it detects. The side panel explains it on the servers concerned;
for settings hidden by another one, such as HEVC Optimization, see
[Settings hidden by another setting](#settings-hidden-by-another-setting).

**I have many differences, but my servers are set up the same way.** Check
whether they come from libraries that are not on every server: untick
**Include libraries**, or create the profile with **Leave out library
settings**.

**The Different values view is empty.** Your servers have the same value for
every setting listed. Choose **All** to see everything.

**Can VODUM change my servers without me?** No. In **Monitoring only** it never
writes. In **Manual remediation**, it writes only what you confirm in a
preview. Automatic remediation is not available.
