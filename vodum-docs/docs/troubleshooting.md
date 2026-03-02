---
title: 🧯 Troubleshooting
---

<!-- Auto-generated improved docs for GitHub Pages (MkDocs Material) -->

<div align="left">

# 🧯 Troubleshooting

<span class="hint-badge">Common issues • Diagnostics • Logs • Checks</span>

<br><br>

</div>


## First reflex: check Logs

Most issues are visible in:
- UI Logs page → [Logs](logs.md)
- Container logs (`docker logs vodum`)

---

## Common issues

??? question "Server shows offline but it is reachable"
    - Check URL (http/https, port, trailing slash)
    - Check DNS resolution inside container
    - Check token validity
    - Check network routing (Unraid custom networks, VPN containers)

??? question "Policies don't apply"
    - Confirm tasks are enabled and running → [Tasks](tasks.md)
    - Check last execution timestamps
    - Review task logs for errors

??? question "Emails not sent"
    - Verify SMTP settings
    - Verify templates exist
    - Check mailing history
    - Check logs for SMTP/auth errors

??? question "Discord not sending"
    - Validate token
    - Ensure the bot is in the server and has permissions
    - Check logs for “not ready” / validation errors

---

## Provide useful info when opening an issue

Include:
- VODUM version
- Docker logs excerpt (sanitized)
- Screenshots (tokens hidden)
- Steps to reproduce

GitHub Issues: https://github.com/Nexius2/VODUM/issues
