---
title: 🔐 Security
---

<!-- Auto-generated improved docs for GitHub Pages (MkDocs Material) -->

<div align="left">

# 🔐 Security

<span class="hint-badge">IP filter • Secrets • Tokens • Best practices</span>

<br><br>

</div>


## IP filtering

Use:

- `VODUM_IP_FILTER=1`
- `VODUM_ALLOWED_NETS=...`

to restrict access to trusted networks.

---

## Secrets and tokens

- Plex tokens / Jellyfin API keys should never be exposed publicly.
- Use strong admin credentials.
- Keep `VODUM_SECRET_KEY` private (required for secure sessions).

---

## Recommended deployment

- Put VODUM behind a reverse proxy (HTTPS)
- Restrict access by IP whenever possible
- Do not expose VODUM publicly without authentication + firewall
