# Route access policy

VODUM classifies paths centrally before views execute. New or misspelled paths
fall back to the administrator scope; they do not become public accidentally.

| Scope | Examples | Boundary |
| --- | --- | --- |
| Public | Explicit static/branding assets, login artwork, `/health` | No account required; IP filtering still applies |
| Administrator authentication | Login/logout, administrator setup and Plex login callbacks | Validated authentication/setup workflow |
| Setup | Wizard and initial linking callbacks | Setup state and authorization checked by the flow |
| Portal authentication | Portal login, activation, recovery and provider callbacks | Enabled, validated portal authentication flows |
| Portal | `/portal/...`, `/api/portal/...` | Session, role/feature permissions and user ownership as required |
| Administrator | Other administration pages and APIs | Valid administrator session and role |

The existing monitoring artwork proxy remains administrative. A portal-specific
proxy or route must enforce the portal boundary separately.

A configured public portal host is checked for portal requests. Strict separation
of administration on a different virtual host additionally requires the explicit
administrator host configuration. With a shared host, `/login` and `/portal/login`
coexist and the role/session boundary still applies. See [Security](security.md).

Public assets are identified before reading authentication settings so loading
CSS/scripts does not wait for the shared database lock. Protected requests still
read fresh authorization state; this optimization does not cache permissions.
