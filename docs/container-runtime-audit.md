# Container runtime and dependency audit

Audit date: 2026-08-28.

## Runtime inventory

- Official `python:3.12-slim` base image.
- Debian `sqlite3` CLI for bootstrap and migrations.
- Waitress production WSGI server; six threads by default.
- No Node.js runtime in the final image. Tailwind, Chart.js, Flatpickr and htmx
  are development or vendored frontend assets rather than container services.
- Persistent database, logs and backups are mounted below `/appdata` by default.

## Corrected findings

- **HIGH:** Waitress 3.0.0 predated the 3.0.1 fixes for a half-open socket busy
  loop and a request-smuggling race. The runtime now pins 3.0.2.
- **MEDIUM:** the Compose healthcheck called `/`, accepted its login redirect as
  success and therefore did not prove application readiness. VODUM now exposes
  an explicit `/health` endpoint and probes it without a shell.
- **LOW:** `curl` was installed only for the ineffective healthcheck. It was
  removed, and APT now uses `--no-install-recommends`.
- **LOW:** the image publishing workflow contained a dangling malformed step and
  printed the registry username. Both were removed.
- **INFO:** static INFO metadata claimed exact Python and SQLite versions that
  did not match the Dockerfile. It now describes Python 3.12 and system SQLite.

## Dependency result

Direct Python dependencies were updated and resolved successfully for Python
3.12. `pip-audit` 2.10.1 reported no known vulnerabilities for the resulting
`requirements.txt` on 2026-08-28.

The htmx 1.9 to 2.x change is intentionally deferred: it is a major frontend
migration and is not required by a confirmed advisory. Chart.js 4.5.1 and
Flatpickr 4.6.13 remain current for the versions vendored by VODUM.

## Remaining production checks

- Build and scan the Linux image in CI; Docker is not installed on the audit
  workstation, so OS-package CVEs and the final image layers were not scanned.
- Test a non-root runtime against real Unraid/Docker bind-mount ownership before
  changing `USER`; forcing it now could make the database and backups unwritable.
- Consider a digest-pinned base image only with an automated rebuild process,
  otherwise the image would stop receiving Python and Debian security patches.
