# Changelog

All notable changes to Vodum will be documented in this file.

---

## Unreleased

- Centralize the User detail notification order controls in `static/js/app.js` and remove the inline partial script.

- Centralize the Users/Plex form debounce helper in `static/js/app.js` and remove the inline duplicate from the user servers partial.

- Move the Subscriptions settings expiry/stream-blocked checkbox sync out of the inline template into `static/js/pages/subscriptions.js`.

- Move the dashboard Now Playing stable-swap handler out of inline template/header blocks and keep it in `static/js/pages/dashboard.js`.

- Move Servers detail/libraries, Settings notification order, and Backup Tautulli import behavior out of inline templates into page JavaScript files.

- Move Subscriptions application/template confirmation behavior and plan summaries out of inline templates into `static/js/pages/subscriptions.js`.

- Move Users filters, referrals bulk-selection, and Create User modal behavior out of the template into `static/js/pages/users.js`.

- Fix mobile login easter egg artwork loading before authentication, and avoid repainting the dashboard sentence artwork when HTMX receives identical content.

- Add the daily easter egg visual to the login screen, using the media backdrop on desktop browsers and the poster on mobile.

- Improve mobile layouts for Subscriptions and Monitoring policy dialogs by stacking narrow action areas, relaxing dense grids, and constraining large modal content on small screens.

- Improve mobile layouts for Logs, Servers, and Communications modals by stacking action bars and constraining large dialogs on small screens.

- Add dashboard quote rotation so available easter eggs are not repeated until the eligible set has been exhausted, and allow `tv` entries to resolve as shows.

- Add French cinema easter egg quotes for Les Visiteurs, Taxi, Les Trois Fr?res, and Ast?rix & Ob?lix: Mission Cl?op?tre.

- Improve Users and User detail mobile layouts by stacking dense label/value grids and modal action rows on narrow screens.

- Make Monitoring Now Playing cards fluid on small screens so the 380px desktop card minimum no longer creates mobile overflow.

- Improve Monitoring user detail on mobile by stacking chart legends and reducing metric grids to one column on narrow screens.

- Improve the dashboard Usage Risk card on mobile by stacking the metric and chart on small screens.

- Improve mobile action, form, and modal resilience by wrapping action groups and constraining fixed-width controls only on small screens.

