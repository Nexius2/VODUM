# Changelog

All notable changes to Vodum will be documented in this file.

---

## Unreleased

- Move Monitoring page user search and Now Playing ticker behavior into `static/js/pages/monitoring.js`.

- Vendor frontend runtime dependencies for HTMX, Chart.js, and Flatpickr so admin pages no longer depend on CDN browser access.

- Remove UTF-8 BOM markers from Python sources so AST-based audits parse consistently.

- Store and read update check status next to the configured database path instead of hardcoding `/appdata`.

- Fix upgraded databases missing `user_referral_settings.pending_expire_days`, which broke referral reward and cleanup tasks.

- Move Dashboard card navigation and subscription modal close behavior into `static/js/pages/dashboard.js`.

- Add The Lion King Hakuna Matata quote to dashboard easter eggs.

- Move Backup list menu, restore confirmation, and delete modal behavior into `static/js/pages/backup.js`.

- Move Subscriptions gifts form, search, modal, and history behavior into `static/js/pages/subscriptions-gifts.js`.

- Remove remaining inline delete modal handlers from Communications campaigns.

- Move Communications templates form, modal, and row navigation behavior into `static/js/pages/communications-templates.js`.

- Replace native browser validation on Migrations dry-run analysis with app-controlled localized inline messages.

- Move Migrations list and campaign detail inline behaviors into page scripts.

- Move Communications configuration autosave and provider UI behavior into `static/js/pages/communications-configuration.js`.

- Move Communications history modal behavior into `static/js/pages/communications-history.js`.

- Fix Monitoring policies SQL column interpolation and add a regression test for raw SQL braces.

- Replace Tailwind CDN runtime scripts with local compiled `static/css/vodum.css` and add a reproducible CSS build command.

- Move Communications campaigns inline scripts into static/js/pages/communications-campaigns.js.

- Replace remaining Python SQL wildcard projections with explicit column lists.

- Fix mojibake regressions across source templates, scripts, and monitoring overview route.

- Move Setup Wizard server autofill cleanup script into static/js/pages/setup-wizard.js.

- Move Login password toggle and reset modal script into static/js/pages/login.js.

- Move Backup page restore modal and auto-refresh script into static/js/pages/backup.js.

- Move Logs page filter debounce script into static/js/pages/logs.js.

- Move Tasks page polling and row rendering script into static/js/pages/tasks.js.

- Move global date picker and CSRF helpers from base.html into static/js/app.js.

- Move shared base UI CSS into static/css/app.css and load it from standalone auth/setup templates.

- Replace remaining Migrations route wildcard queries with explicit campaign, user, mapping, and report projections.

- Fix Monitoring Overview live-session projection so it only selects columns present in media_sessions.

- Limit Monitoring Servers live-session CTE to server and transcode fields used by counters.

- Limit Monitoring Libraries top played CTE rows to fields consumed by ranking and artwork enrichment.

- Limit Monitoring Overview live session lookups to Now Playing and artwork fields.

- Limit User detail referral display lookup to fields rendered by the referral panel.

- Limit User detail notification history lookups to displayed comm history fields and label metadata.

- Limit User detail Access server/library lookups to fields rendered by the access tab and forms.

- Limit User detail active policy lookups to displayed rule, scope, provider, priority, and rule JSON fields.

- Limit Monitoring session detail lookups to displayed session fields and event lookup keys.

- Replace Monitoring Policies stream policy wildcard queries with explicit list/editor projections.

- Limit Setup Wizard settings reads to the wizard, localization, communications, and expiration fields it uses.

- Replace Subscriptions stream policy and template duplicate wildcard queries with explicit column projections.

- Replace Servers and Libraries page wildcard queries with explicit list/detail column projections.

- Replace Dashboard access helper server/library wildcard queries with explicit lightweight columns.

- Replace the Users referrals list wildcard query with explicit referral table columns.

- Limit Users merge preview, suggestion, and merge-action user lookups to the fields used by merge logic.

- Limit User detail referral save lookups to the settings/referral fields used by the handler.

- Limit Communications history rows to displayed/modal fields and stop parsing meta JSON server-side.
- Split Communications template editor/list queries so the template list no longer loads full bodies.
- Split Communications campaign editor/list queries so the campaign list no longer loads full bodies.
- Remove unused recent scheduled/history queries from the Communications configuration page.
- Limit Users list row queries to displayed user columns and explicit referral settings fields.
- Limit User detail `vodum_users` lookups to explicit profile, subscription, notification, referral, and Discord columns.
- Limit the Backup page settings query to the retention fields rendered by the form.
- Align the initial Tasks page query with the lean task list API columns and narrow task toggle lookup to id/enabled.
- Reduce global i18n template settings queries to UI-safe columns and limit brute force alert email lookup to address fields.
- Limit Subscriptions settings queries to the columns needed by the templates/settings tabs and expiration policy save handler.
- Limit Communications settings queries to the columns required for template actions, test campaigns, and Email/Discord configuration.
- Reduce user detail settings queries to explicit columns used by the page and save handler.
- Reduce the Users list settings query to the single setting needed by the page instead of loading the full settings row.

















