# Getting started

## Requirements

- Docker Engine and Docker Compose.
- Persistent storage for `/appdata`.
- A Plex token and/or Jellyfin API key.
- Optional SMTP and Discord credentials.

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

The wizard creates the administrator account, chooses the interface language
and guides initial server configuration. Use a strong password and keep the
application restricted to trusted networks.

After setup:

1. Add a server and validate its credentials.
2. Run the provider synchronization task.
3. Confirm libraries and users were imported.
4. Configure expiration behavior and Communications.
5. Review enabled tasks before turning on global scheduling.
6. Create a full backup.

## Upgrade

```bash
docker compose pull
docker compose up -d
docker compose logs -f vodum
```

Startup applies idempotent database bootstrap and migrations automatically.
Do not interrupt the first start after an upgrade.
