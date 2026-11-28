# Troubleshooting

## First checks

1. Open **Tasks**: look for tasks in error or waiting for a long time.
2. Open **Logs**: filter by level or search for the feature, and download the
   anonymized logs if you need help.
3. If VODUM does not start, read `docker compose logs vodum`.
4. Check that the database, logs, backups and encryption key are on persistent storage.

## Common problems

**A server is shown offline.** Check its URL from inside the container (not only
from your browser), its token or API key, and any HTTPS certificate or redirect.
After a failed check, VODUM tries the server again after 5 minutes.

**A library access change is not applied.** Access changes are sent to Plex or
Jellyfin by the **Apply Plex access updates** and **Apply Jellyfin access updates**
tasks. In **Tasks**, check that they are enabled and not in error, click **Run**,
then run **Plex sync** or **Jellyfin sync** to confirm the result.

**Messages are not sent.** Send a test from **Communications**, check the delivery
history, and check the user's email address or Discord account.

**Now Playing is late.** Check the **Monitoring: collect sessions** task. While
VODUM is busy, it can show the previous snapshot for a short time.

**A poster is missing in Now Playing.** Search the logs for `Artwork fetch failed`.
`plex_request_queue_busy` means Plex was busy the whole time; an `http_status`
value is Plex's own answer for that image. The poster is retried at the next refresh.

**Dashboard API errors.** `401`: the token is missing, unknown or revoked.
`403`: the token lacks that access, or your address is blocked by the IP filter.
`429`: more than 60 calls per minute. See [Dashboard API](api.md#errors).

**Statistics task error `sql_budget_exceeded`.** A statistics view needed more
than its 90-second budget. The previous figures stay visible. See
[Performance](performance.md#persisted-historical-monitoring-statistics).

**A restore fails.** Check the archive format, that the encryption key matches,
the free disk space and the ZIP size limits. Keep the original backup unchanged.

## Locked out of administration

If you lost the administrator password or your two-factor device (the login
page also shows this command):

1. On the host, create a file named `password.reset` in the VODUM data folder
   (the folder mounted as `/appdata`) containing the word `RECOVER`:

    ```bash
    echo "RECOVER" > /path/to/vodum-appdata/password.reset
    ```

2. Restart the container.
3. Open VODUM and create the administrator email and password again.
   A Plex or Jellyfin sign-in linked to the administrator is not removed.

At startup VODUM clears the administrator email, password and two-factor
setting, then deletes the file, so the reset happens only once. The rest of the
data is kept. A file with any other content is ignored. The file name and the
word can be changed with `VODUM_RESET_FILE` and `VODUM_RESET_MAGIC`
(see [Deployment configuration](configuration.md)). Never make this folder
reachable from the internet.

## A page is slow or a section keeps loading

Some sections (Monitoring overview, Plex server suggestions…) load after the rest
of the page. A section that is still loading does not mean the data is empty:
wait, or reload the section. If pages stay slow, the [Performance](performance.md)
guide explains how to measure where the time goes.

## A media request does not complete

Open the request result in the portal, then check the Sonarr/Radarr or Seerr
server and its settings in [Media requests](media-requests.md#if-a-request-does-not-complete).
Do not submit the same request again before checking whether the media was
already added.

## Library growth or collection status is missing

[Library growth](library-growth.md) needs at least two daily scans before showing
figures. A collection shows a result only after it has run on each library; no
history does not mean success. See [Collections](collections/index.md#understand-the-result).
