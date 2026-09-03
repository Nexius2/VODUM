# Audit des en-tetes HTTP et de la CSP

Date: 2026-08-30

## En-tetes globaux verifies

Toutes les reponses traversant la fabrique Flask recoivent par defaut :

- `X-Content-Type-Options: nosniff`;
- `X-Frame-Options: SAMEORIGIN`;
- `Referrer-Policy: strict-origin-when-cross-origin`;
- `Permissions-Policy: camera=(), microphone=(), geolocation=()`.

`Strict-Transport-Security: max-age=31536000; includeSubDomains` est ajoute
uniquement lorsque Flask considere la requete HTTPS. Derriere un reverse proxy,
cela depend de `ConditionalProxyFix`, qui n'accepte `X-Forwarded-Proto` que pour
un pair appartenant aux reseaux de proxy approuves. HSTS n'est volontairement
pas emis sur l'acces HTTP LAN direct.

## Inventaire CSP

Les ressources applicatives principales (HTMX, Chart.js, QRCode et scripts de
pages) sont servies depuis `/static`. Cloudflare Turnstile est l'unique origine
de script/frame/connect externe necessaire et reste limite a
`https://challenges.cloudflare.com`.

L'administration contient encore des styles inline, quelques blocs JavaScript
inline et de nombreux attributs `onclick`, `onchange`, `onsubmit` et `oninput`.
Une CSP admin stricte les casserait. Autoriser globalement `unsafe-inline` pour
les scripts reduirait fortement l'interet de la politique. Aucune CSP
d'enforcement n'est donc ajoutee a l'administration dans ce lot; la migration
devra externaliser progressivement ces handlers avant activation.

## Finding corrige

### MEDIUM - Scripts portail bloques par la CSP existante

- Fichiers : `templates/portal/base.html` et
  `templates/portal/subscription.html`.
- Comportement initial : la CSP du portail declarait `script-src 'self'` sans
  `unsafe-inline`, tandis que la prevention de soumission en preview admin et la
  modale de paiement utilisaient des scripts inline.
- Prerequis : ouvrir la preview administrateur ou la page d'abonnement avec le
  paiement affiche dans un navigateur appliquant la CSP.
- Impact : fonctionnalites client bloquees; dans la preview, un formulaire
  pouvait etre soumis contrairement au comportement d'interface attendu.
- Exploitabilite : probleme de disponibilite/contrat UI, pas une execution de
  script attaquant confirmee.
- Correction : deplacement des deux comportements vers
  `static/js/pages/portal-base.js`, charge depuis l'origine `self` par le layout.
- Risque de regression : faible; les selecteurs et comportements sont inchanges.
- Statut : corrige.

## CSP portail appliquee

Les pages `/portal*` et API `/api/portal/*` recoivent une CSP d'enforcement avec :

- ressources par defaut limitees a `self`;
- scripts limites a `self` et Turnstile, sans `unsafe-inline`;
- styles `self` et inline, necessaires aux templates actuels;
- images `self`, `data:` et Turnstile;
- frames et connexions externes limitees a Turnstile;
- `object-src 'none'`, `base-uri 'self'`, `form-action 'self'` et
  `frame-ancestors 'self'`.

Le portail conserve aussi `Cache-Control: no-store` pour ses pages et API
authentifiees.

## Tests

- presence des cinq en-tetes globaux attendus;
- HSTS present sur HTTPS et absent sur HTTP LAN;
- CSP et `no-store` sur page et API portail;
- absence de `unsafe-inline` dans `script-src`;
- presence de `object-src 'none'`;
- absence de tout script executable inline dans les templates portail;
- parcours et isolation des pages portail inchanges.
