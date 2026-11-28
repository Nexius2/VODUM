# Installation & upgrades

## Requirements

- Docker Engine and Docker Compose. The published image `nexius2/vodum` is
  built for x86-64 (amd64) on Python 3.14 and Debian 13 (trixie).
- Persistent storage for `/appdata`.
- A Plex token and/or Jellyfin API key.
- Optional: SMTP (email) and Discord credentials.

## Install with Compose

```bash
git clone https://github.com/Nexius2/VODUM.git
cd VODUM
cp .env.example .env
mkdir -p appdata logs backups
docker compose up -d
```

Open `http://YOUR_SERVER_IP:8097`. The included Compose file maps:

| Host | Container |
|---|---|
| `./appdata` | `/appdata` |
| `./logs` | `/appdata/logs` |
| `./backups` | `/appdata/backups` |

## First-run wizard

The wizard chooses the interface language, creates the administrator sign-in
and adds your first media servers.

### Choose how you sign in

You can sign in to administration with **Plex**, **Jellyfin** or a **local
VODUM account** (email and password). This only decides how *you* sign in:
you can add more Plex and Jellyfin servers afterwards. VODUM has a single
administrator; Plex or Jellyfin identities are linked to it.

- **Local account**: use a strong password.
- **Plex**: sign in with your Plex account, then select the suggested servers
  and click **Continue**. The servers that fail stay selected so you can retry;
  **Add more servers** opens the manual form.
- **Jellyfin**: enter the server address (with its base path, if any).
  Quick Connect must be enabled on the server. In a Jellyfin app where you are
  signed in as an administrator, open your settings, choose **Quick Connect**,
  enter the code shown by VODUM, then click **I approved the connection**. The
  code is valid for five minutes. VODUM keeps an access token, never your
  Jellyfin password. Later, **Sign in with Jellyfin** only works for that same
  administrator on that same server, which must stay reachable with Quick
  Connect enabled.

### After the wizard

1. Check that your servers appear in **Servers & libraries**.
2. In **Tasks**, run **Plex sync** and/or **Jellyfin sync** to import libraries and users.
3. Check that your libraries and users were imported.
4. Configure [subscriptions](subscriptions.md) (what happens when an account expires)
   and [Communications](communications.md).
5. Review the enabled [tasks](tasks.md) before turning on the global scheduler.
6. Create a full [backup](backup.md).

Keep VODUM reachable only from trusted networks until you have read
[Security](security.md).

## Upgrade

1. Create a full [backup](backup.md).
2. Pull and restart:

    ```bash
    docker compose pull
    docker compose up -d
    docker compose logs -f vodum
    ```

3. Let the first start finish: VODUM updates its database automatically on
   startup. Do not stop the container during that time.

On Unraid, update the container from the **Docker** tab. If you build the image
yourself from the source (for example with `create-container.sh`), rebuild it
after each update.
