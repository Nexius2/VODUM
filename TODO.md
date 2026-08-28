# VODUM - Feuille de route

Ce fichier contient uniquement le travail restant. Les changements termines
sont documentes dans `changelog.md`.

Derniere mise a jour: 2026-08-24

## Principes de suivi

- Garder ici seulement les sujets encore utiles a traiter.
- Retirer une ligne quand elle est terminee et la tracer dans `changelog.md`.
- Prioriser les gains qui servent a la fois l'administration actuelle et la
  partie utilisateur exposee sur internet.
- Eviter les gros changements non valides sur la vraie base sans test terrain.

## P0 - correction & bug constaté.





## P8 - Partie utilisateur et ouverture externe

Objectif: ouvrir un portail distinct de l'administration, desactive par defaut,
dans lequel chaque utilisateur ne peut consulter et modifier que ses propres
donnees. Les lots ci-dessous sont a traiter dans l'ordre; chaque lot doit inclure
ses migrations, tests, traductions et documentation.

### U0 - Cadrage fonctionnel et architecture

- [x] Valider le perimetre du premier portail utilisateur (MVP):
  - accueil/resume, profil, abonnement, acces Plex/Jellyfin, monitoring personnel,
    aide/support et deconnexion;
  - fonctions volontairement reportees: paiement integre, API publique,
    administration deleguee et personnalisation avancee.
- [x] Definir des URL et layouts distincts pour l'administration et le portail
  utilisateur (`/admin` a terme ou routes admin existantes, et `/portal`), sans
  exposer les vues, API ou donnees administratives au role utilisateur.
- [x] Etablir une matrice des permissions par ressource et par action pour les
  roles `admin` et `user`, extensible a de futurs roles. L'autorisation doit etre
  verifiee cote serveur; masquer un bouton ne suffit pas.
- [x] Definir les donnees que l'utilisateur peut voir et modifier, notamment les
  champs internes interdits: notes admin, IP completes, details des autres
  utilisateurs, secrets provider, journaux techniques et regles internes.
- [x] Choisir le comportement des comptes lies et fusionnes: une personne VODUM,
  plusieurs identites de connexion possibles, sans creer de doublon Plex/Jellyfin.

### U1 - Configuration admin du portail

Socle realise: reglages persistants ajoutes et desactives par defaut. Il reste a
creer la page admin, ses validations et ses diagnostics.

- [x] Ajouter un menu admin "Portail utilisateurs" et une page de configuration.
- [x] Permettre d'activer/desactiver le portail, desactive par defaut, avec un
  ecran public neutre lorsqu'il est ferme.
- [x] Configurer l'URL publique de base, l'identite et les fonctions visibles:
  - [x] URL publique; hostname deduit de cette URL; marque et contact support
    herites des reglages generaux; fonctions visibles configurables;
  - [x] ajouter l'import global d'un logo, sans creer de doublon propre au portail;
    les CGU ne font volontairement pas partie de VODUM.
- [x] Configurer les methodes de connexion autorisees: email/mot de passe, Plex
  et Jellyfin, independamment les unes des autres, avec au moins une methode de
  recuperation valide avant activation.
  - La selection independante est disponible. Tant que les parcours provider U4
    ne sont pas termines, l'activation exige la methode locale et sa recuperation
    email operationnelle; activer Plex/Jellyfin ne les expose pas prematurement.
- [x] Ajouter un diagnostic de publication: URL, HTTPS, cookies securises,
  proxy de confiance, envoi d'email et callback des providers; ne pas automatiser
  la configuration DNS ou du reverse proxy dans le MVP.

### U2 - Identites, roles et sessions

Socle realise: tables `portal_accounts`, `portal_auth_identities`, `portal_roles`
et `portal_account_roles`, contraintes d'unicite provider et roles systeme
`admin`/`user`. Le principal de session versionne et les gardes reutilisables
`admin_required`/`portal_login_required` sont ajoutes; les sessions admin legacy
sont converties automatiquement. La politique centrale classe maintenant les
routes publiques, setup, authentification, portail et admin avec repli admin par
defaut. Les sessions utilisateur sont persistantes, expirables et revocables.

- [x] Creer un modele d'identite d'authentification utilisateur distinct de
  `media_users`: lien vers `vodum_users`, provider (`local`, `plex`, `jellyfin`),
  identifiant normalise, hash ou reference provider, dates de validation et de
  derniere connexion, etat actif/revoque et contraintes d'unicite.
- [x] Creer les roles et permissions VODUM avec `admin` et `user` au minimum;
  conserver la compatibilite avec l'admin unique actuel pendant la migration.
- [x] Remplacer progressivement le booleen de session admin par un principal de
  session explicite (`account_id`, role, horodatage/auth level), avec rotation de
  session a la connexion et invalidation/revocation serveur.
  - Les nouvelles connexions n'ecrivent plus les anciennes cles admin. Une
    lecture transitoire convertit puis supprime les sessions deja ouvertes.
- [x] Ajouter des gardes reutilisables `admin_required`, `portal_login_required`
  et controle de propriete des ressources; classer puis tester toutes les routes
  et API existantes comme publiques, portail ou admin.
- [x] Adapter les gardes setup/maintenance pour autoriser uniquement les routes
  publiques necessaires et ne jamais rediriger un utilisateur vers l'admin.

### U3 - Authentification locale et cycle de vie du compte

Socle backend realise: invitations locales atomiques, expirees, revocables et a
usage unique; activation avec hash de mot de passe; authentification locale non
enumerante, formulaires publics, emission admin/email, anti-bruteforce IP/email,
recuperation de mot de passe et sessions serveur revocables. Il reste notamment
le journal d'audit des connexions et la validation de readiness avant activation.

- [x] Implementer connexion/deconnexion utilisateur par email, avec messages
  non enumerants, anti-bruteforce separe par compte/IP et journal d'audit.
- [x] Implementer invitation a usage unique, choix initial du mot de passe,
  validation d'email, renvoi d'invitation et expiration/revocation des jetons.
- [x] Implementer mot de passe oublie/reinitialisation par jeton court et a usage
  unique; ne jamais stocker ni envoyer de mot de passe en clair.
- [x] Definir une politique de mot de passe configurable et proposer la 2FA TOTP
  utilisateur dans un lot ulterieur au MVP, sans reutiliser le secret admin.
- [x] Gerer les etats invite, actif, suspendu, expire et supprime:
  - [x] calcul central de l'etat effectif, refus des nouvelles connexions et des
    sessions ouvertes pour les comptes suspendus, expires ou supprimes;
  - [x] terminer la reconciliation des acces provider et les messages contextuels
    sans compromettre la non-enumeration sur la page de connexion.

### U4 - Connexions Plex et Jellyfin

- [x] Adapter le flux OAuth/PIN Plex pour authentifier un utilisateur et rattacher
  l'identite Plex au bon `vodum_user`, avec confirmation explicite en cas de
  rapprochement ambigu et protection `state`/expiration/rejeu.
- [x] Concevoir la connexion Jellyfin par serveur sans conserver le mot de passe:
  authentifier via l'API, verifier l'identite liee, puis stocker seulement la
  reference/jeton strictement necessaire chiffre et revocable.
- [x] Permettre de lier/delier une methode depuis le portail apres reauthentification,
  sans autoriser la suppression de la derniere methode de connexion utilisable.
- [x] Definir le comportement si un compte provider est supprime, renomme,
  desactive ou present sur plusieurs serveurs.

### U5 - Portail utilisateur MVP

- [x] Creer un layout responsive et accessible, distinct du layout admin:
  - [x] structure responsive, navigation clavier et traductions avec repli anglais;
  - [x] etats vides et erreurs accessibles uniformises; aucun etat de chargement
    artificiel sur les ecrans actuels, integralement rendus cote serveur.
- [x] Accueil:
  - [x] afficher uniquement le statut du compte, l'abonnement courant, l'echeance,
    les nombres de serveurs/bibliotheques et l'activite de l'utilisateur connecte;
  - [x] ajouter les alertes utiles et les liens d'aide/support configures.
- [x] Profil:
  - [x] autoriser l'edition du nom et de l'email secondaire valide, sans accepter
    d'identifiant utilisateur fourni par le navigateur;
  - [x] ajouter langue, preferences de notification et changement du mot de passe local.
- [ ] Abonnement (historique differe jusqu'au modele de donnees dedie):
  - [x] afficher formule, valeur, dates, statut, limites effectives et methode de
    renouvellement; ne rendre cliquables que les URL HTTPS;
  - [x] ajouter un lien de paiement/renouvellement HTTPS et son libelle configures par l'admin;
  - [ ] ajouter l'historique lorsqu'un modele de donnees dedie sera disponible.
- [x] Acces media: afficher les comptes Plex/Jellyfin lies, serveurs/bibliotheques
  accordes, etat de l'invitation et liens officiels de telechargement/configuration.
- [x] Monitoring personnel: afficher uniquement les sessions et statistiques du
  `vodum_user` connecte; filtrer cote requete et ne jamais accepter un `user_id`
  arbitraire fourni par le navigateur.
- [x] Support: afficher contact, documentation et informations de diagnostic
  partageables, sans logs ni secrets.

### U6 - Administration des acces utilisateurs

- [x] Depuis la fiche admin existante, afficher l'etat du compte portail, ses
  identites, roles, derniere connexion et invitations en attente.
- [x] Permettre d'inviter, renvoyer/revoquer une invitation, suspendre/reactiver
  le portail, forcer la deconnexion, reinitialiser les methodes d'authentification
  et consulter un journal d'audit cible.
- [x] Prevoir creation automatique, assistee ou controlee des comptes
  Plex/Jellyfin et rendre chaque action provider idempotente et explicite.
- [x] Ajouter des emails traduits: invitation, validation, reinitialisation,
  changement sensible, suspension/reactivation et alerte de nouvelle connexion.

### U7 - Securite, confidentialite et exploitation publique

- [x] Etendre CSRF, CSP, cookies `Secure`/`HttpOnly`/`SameSite`, limites de taille,
  rate limiting et en-tetes HTTP a toutes les nouvelles routes publiques.
- [x] Ajouter Cloudflare Turnstile selon la section "Securite des acces publics":
  - [x] configuration chiffree, modes compact/invisible, connexion admin et
    portail, reset utilisateur, controle serveur/hostname et recuperation locale;
  - [x] ajouter un bouton de test admin affichant l'etat de validite des cles.
- [x] Journaliser les connexions et actions sensibles sans mot de passe, jeton,
  secret, contenu prive de lecture ni IP complete dans les vues utilisateur.
- [x] Definir retention, export et suppression des donnees personnelles, ainsi que
  le comportement des sauvegardes et restaurations pour les nouvelles tables.
- [x] Ajouter tests d'isolation horizontale (IDOR), autorisations par role, CSRF,
  fixation/revocation de session, enumeration de comptes, callbacks provider et
  indisponibilite des services externes.
- [ ] Verifier le parcours complet derriere un reverse proxy HTTPS:
  - [x] tester automatiquement la confiance conditionnelle du proxy, le schema
    HTTPS, le hostname, la readiness, et documenter publication, recuperation et rollback;
  - [ ] executer la checklist manuelle sur une instance representative avec le
    reverse proxy reel avant toute activation sur internet.

### U8 - Evolutions apres le MVP

- [x] Ajouter les possibilites de profil provider supportees: edition idempotente
  du nom local Jellyfin apres controle de propriete; profil Plex global en lecture
  seule avec renvoi explicite vers le compte Plex.
- [x] Ajouter un mecanisme ou un lien de paiement aux profils utilisateurs.
- [x] Ajouter une API publique apres cadrage: donnees exposees, objectifs,
  securite, quotas et authentification.
- [x] Ameliorer la creation d'utilisateur et les emails d'invitation depuis
  l'espace web VODUM:
  - [x] creation automatique, assistee ou controlee des comptes Plex/Jellyfin;
  - [x] liens officiels de telechargement des lecteurs media dans l'interface et les emails;
  - [x] aide a la configuration du lecteur dans l'interface et les emails.

### Securite des acces publics

- [x] Integrer Cloudflare Turnstile comme protection anti-automatisation
  optionnelle des formulaires publics.
  - [x] Ajouter la configuration dans la modale de securite Settings, sous la 2FA,
    tout en gardant Turnstile independant de la 2FA.
  - [x] Prevoir les modes compact et invisible, avec choix des formulaires
    proteges: connexion admin, reinitialisation du mot de passe et futurs acces
    utilisateurs.
  - [x] Demander une Site Key et une Secret Key; masquer et chiffrer la Secret Key
    avec le mecanisme de secrets existant.
  - [x] N'autoriser l'activation que lorsque la configuration est complete et
    proposer un test affichant clairement son etat de validite.
  - [x] Valider chaque jeton cote serveur via l'endpoint Cloudflare `siteverify`,
    avec timeout court, controle du hostname et journalisation sans secret.
  - [x] Definir explicitement le comportement en cas d'indisponibilite Cloudflare
    afin de ne pas verrouiller accidentellement toute l'administration.
  - [x] Conserver les protections anti-bruteforce et 2FA existantes: Turnstile les
    complete et ne les remplace pas.
  - [x] Prevoir un moyen de recuperation locale/admin en cas de cle ou de widget
    mal configure, ainsi que les traductions et ajustements CSP necessaires.

## Notes de prudence

- `GET /api/monitoring/poster/<server_id>` est une exception GET autorisee :
  proxy authentifie de posters et backgrounds avec cache local, declaree dans
  `tools/audit_get_routes.py`.
- Ne pas supprimer le cache artwork existant: il est utile et deja raccorde
  aux headers HTTP.
- Ne pas remplacer `sync` par `revoke` partout cote provider: Plex a
  volontairement un garde-fou contre sync vide.
- Les optimisations SQL doivent etre validees avec la vraie base et
  `EXPLAIN QUERY PLAN`; ajouter trop d'index peut ralentir les ecritures et le
  bootstrap.
- Les modifications de fichiers contenant du texte corrige doivent rester
  ciblees pour eviter de recreer du mojibake.


## Security audit & hardening before public Internet exposure

VODUM is intended to be exposed to the Internet and has privileged access to
Plex/Jellyfin servers and other sensitive services.

Perform a complete defensive security review of the application.

IMPORTANT — AUDIT BEFORE MODIFYING:

- Do NOT assume that unusual existing behavior is a vulnerability.
- Understand the purpose and complete call flow before changing existing code.
- Check existing protections before implementing new ones.
- Preserve working behavior and backward compatibility.
- Do not perform unrelated refactors during the security audit.
- Prefer small, targeted fixes over architectural rewrites.
- For every potential vulnerability:
  1. Identify the existing behavior and protection.
  2. Determine whether the issue is actually exploitable.
  3. Evaluate the impact.
  4. Check whether fixing it could break an existing feature.
  5. Only then implement the smallest safe correction.
- Add regression tests for security fixes whenever practical.
- Document findings that do not require code changes instead of modifying code unnecessarily.


### Authentication and global access control

- [ ] Audit authentication and authorization for EVERY registered Flask route and blueprint.

- [ ] Build an explicit inventory of routes intentionally accessible without authentication (login, setup when appropriate, health, static resources, Plex authentication callbacks, login artwork, etc.).

- [ ] Verify that no administrative route can accidentally be accessed without an authenticated VODUM administrator.

- [ ] Review the global authentication/IP `before_request` guard currently located in `app/routes/tasks.py`.

      This guard currently protects the whole application even though it lives
      inside the Tasks route module.

      First verify exactly how and when it is registered.

      If confirmed that application security depends on the Tasks module being
      imported/registered, move the guard to a dedicated security/auth module
      explicitly registered by `create_app()`.

      Preserve the exact existing authentication/IP behavior while moving it.
      Do not change access semantics as part of this refactor.

- [ ] Add regression tests proving that removing/disabling an unrelated route module cannot disable global authentication.


### Login, sessions and 2FA

- [ ] Audit the complete local administrator login flow.

- [ ] Audit Plex administrator authentication/login flow.

- [ ] Audit TOTP verification and TOTP enrollment.

- [ ] Audit the local TOTP trust mechanism and trust cookie.

- [ ] Verify session fixation protection after successful local and Plex authentication.

- [ ] Verify session invalidation on logout.

- [ ] Verify session lifetime and permanent-session behavior.

- [ ] Verify Secure / HttpOnly / SameSite cookie behavior both:
      - direct LAN access
      - HTTPS reverse-proxy access

- [ ] Verify brute-force protection by IP and account/email.

- [ ] Verify that authentication errors do not leak whether an administrator account exists.


### CSRF and HTTP methods

- [ ] Audit the existing global CSRF implementation before modifying it.

- [ ] Verify that every POST / PUT / PATCH / DELETE endpoint is protected.

- [ ] Search for GET endpoints that modify persistent state.

- [ ] No GET endpoint should modify users, servers, settings, tasks, provider access or other persistent state unless there is a documented and reviewed reason.

- [ ] Add regression tests proving that state-changing requests without a valid CSRF token are rejected.


### XSS and frontend rendering

- [ ] Perform a complete XSS audit.

- [ ] Search Jinja templates for:
      `|safe`
      `Markup`
      manually generated HTML

- [ ] Search JavaScript for:
      `innerHTML`
      `outerHTML`
      `insertAdjacentHTML`
      dynamic HTML/template generation

- [ ] Pay particular attention to externally controlled/provider-controlled values:
      - Plex usernames
      - Jellyfin usernames
      - media titles
      - server names
      - metadata
      - email/communication content
      - Discord-related data
      - logs
      - error messages
      - imported Tautulli data

- [ ] Verify that these values cannot inject executable HTML/JavaScript into an authenticated administrator session.

- [ ] Audit existing security headers.

- [ ] Evaluate adding a Content-Security-Policy.

      Do NOT blindly introduce a strict CSP that breaks the existing UI.

      First inventory existing inline scripts/styles and external resources.

      Introduce CSP progressively and test all major pages/features.

- [ ] Preserve/verify:
      HSTS on HTTPS
      X-Content-Type-Options
      frame protection
      Referrer-Policy
      Permissions-Policy


### SSRF and outbound HTTP requests

- [ ] Perform a complete SSRF audit of all outbound HTTP requests.

- [ ] Inventory every HTTP client usage:
      requests.*
      urllib
      httpx
      Plex/Jellyfin client wrappers
      artwork fetching
      server tests
      discovery
      sync
      migrations/imports
      any other outbound request

- [ ] Review the existing shared HTTP security layer before changing anything.

- [ ] Verify that security-sensitive requests cannot bypass that layer through legacy/direct HTTP calls.

- [ ] Test potentially dangerous destinations where applicable:
      localhost
      loopback
      private networks
      link-local addresses
      IPv6 equivalents
      redirects to unsafe destinations

IMPORTANT:

VODUM legitimately connects to Plex/Jellyfin servers located on the LAN.

Do NOT globally block private IP ranges and thereby break legitimate local
Plex/Jellyfin connections.

SSRF protection must distinguish between explicitly configured/trusted media
servers and attacker-controlled arbitrary destinations.


### LAN access, public access and reverse proxy

- [ ] Audit IP filtering behavior for both LAN and Internet usage.

- [ ] Preserve easy direct LAN access through private/local networks.

- [ ] Do NOT remove the default local/private network behavior simply because VODUM is becoming Internet accessible.

- [ ] Verify the complete interaction between:
      VODUM_IP_FILTER
      VODUM_ALLOWED_NETS
      VODUM_TRUST_PROXY
      VODUM_TRUSTED_PROXY_NETS

- [ ] Test at least:
      1. direct LAN access
      2. LAN access through reverse proxy
      3. Internet access through trusted reverse proxy
      4. requests attempting to spoof X-Forwarded-For
      5. requests attempting to spoof X-Forwarded-Proto
      6. requests coming from an untrusted proxy/source

- [ ] Ensure forwarded headers are only trusted from explicitly trusted proxy networks.

- [ ] Audit Host / X-Forwarded-Host handling and determine whether Host-header validation is required.

- [ ] Verify HTTPS detection behind Nginx so Secure cookies and HSTS behave correctly.


### Secrets and credentials

- [ ] Audit storage, encryption, usage and exposure of every sensitive secret:
      - Plex tokens
      - Jellyfin API tokens
      - SMTP password
      - SMTP OAuth token
      - Discord bot token
      - administrator TOTP secret
      - Flask secret key
      - VODUM encryption key
      - any future provider credentials

- [ ] Review the existing encryption implementation before modifying it.

- [ ] Verify that secrets are never exposed through:
      HTML
      JSON APIs
      logs
      exception messages
      debug pages
      telemetry
      frontend JavaScript
      diagnostic endpoints

- [ ] Verify that secret redaction is consistently applied.

- [ ] Verify permissions on persistent secret/key files.

- [ ] Verify behavior when encryption keys are missing, invalid or replaced.

- [ ] Never silently generate a new encryption key if doing so would make existing encrypted credentials unrecoverable.


### Backup / restore security

- [ ] Perform an end-to-end security audit of backup creation, download, upload and restore.

- [ ] Review existing protections before modifying them.

- [ ] Verify protection against:
      Zip Slip / path traversal
      absolute paths
      `..` traversal
      symlinks
      hard links if relevant
      zip bombs
      excessive member counts
      excessive extracted size
      malicious filenames
      overwriting unexpected application files

- [ ] Verify that EVERY ZIP extraction path uses the configured security limits.

- [ ] Verify SQLite/database validation before restoration.

- [ ] Verify restoration behavior for the VODUM encryption key.

- [ ] Verify that restoring a database without its matching encryption key cannot silently destroy or overwrite the currently working key/configuration.

- [ ] Treat backups as sensitive because they may contain credentials or the material required to decrypt credentials.

- [ ] Verify backup download responses cannot be cached by shared/public caches.


### Tautulli imports and upload limits

- [ ] Audit upload-size limits BY UPLOAD TYPE.

IMPORTANT:

`VODUM_MAX_UPLOAD_MB=4096` may intentionally exist to support large Tautulli
database imports.

Do NOT blindly reduce this global value.

- [ ] Determine the real size requirements for:
      - Tautulli database imports
      - VODUM backup restores
      - other uploads

- [ ] Consider separate upload limits per feature if this improves security without breaking legitimate large Tautulli imports.

- [ ] For multi-GB Tautulli imports verify:
      disk-space protection
      temporary-file handling
      cleanup after failure
      timeouts
      database validation
      memory usage
      request handling
      concurrent import behavior

- [ ] Ensure a large upload is streamed/stored safely and is not unnecessarily loaded entirely into RAM.


### SQL injection

- [ ] Audit all SQL construction.

- [ ] Search especially for:
      f-strings containing SQL
      `.format()` SQL
      string concatenation used for SQL

- [ ] Verify all user-controlled and provider-controlled values are passed as SQL parameters.

- [ ] Dynamic table names, column names, ORDER BY fields or similar SQL identifiers must come from strict internal allowlists.

- [ ] Do not rewrite safe dynamic SQL merely because it uses an f-string if all interpolated identifiers are trusted constants/allowlisted.


### Filesystem and command execution

- [ ] Audit every filesystem operation involving variable paths.

- [ ] Verify protection against:
      path traversal
      arbitrary file read
      arbitrary file write
      unsafe deletion
      symlink attacks
      temporary-file collisions

- [ ] Audit subprocess / shell / os.system usage.

- [ ] Verify no user/provider-controlled value can become shell syntax or an executable command.

- [ ] Prefer subprocess argument arrays without `shell=True` where command execution is required.


### API / IDOR / object authorization

- [ ] Audit every JSON/API endpoint.

- [ ] Verify resource IDs are authorized and validated.

- [ ] Test whether changing IDs can expose or modify:
      another user
      another media account
      another server
      another backup
      policies
      communications
      tasks
      monitoring information

- [ ] Verify sensitive internal information is not returned unnecessarily.


### Error handling and information leakage

- [ ] Audit 4xx/5xx responses and exception handlers.

- [ ] Production responses must not expose:
      Python stack traces
      filesystem paths
      SQL queries
      database internals
      tokens
      passwords
      secrets
      provider responses containing credentials

- [ ] Ensure debug mode cannot accidentally be enabled for a public production instance without a clear warning/protection.

- [ ] Audit logs for the same sensitive-data leakage risks.


### Cache and sensitive pages

- [ ] Review caching behavior of authenticated/admin responses.

- [ ] Consider `Cache-Control: no-store` for pages/API responses containing sensitive administration data.

- [ ] Do not globally disable caching for static assets or safe public artwork unnecessarily.


### Denial-of-service protections

- [ ] Audit endpoints capable of expensive operations.

Focus on:
      login attempts
      live Plex/Jellyfin checks
      monitoring queries
      artwork proxy
      backup/restore
      Tautulli imports
      sync triggers
      task triggers
      large API responses
      search/filter endpoints

- [ ] Verify reasonable:
      HTTP timeouts
      pagination limits
      input-size limits
      concurrency controls
      rate limits where justified

- [ ] Do not introduce aggressive rate limiting that breaks normal VODUM administration or background provider synchronization.


### Docker / production runtime

- [ ] Audit the production Docker configuration.

- [ ] Check:
      container user/root usage
      writable filesystem locations
      mounted volumes
      Linux capabilities
      exposed ports
      filesystem permissions
      secret-file permissions
      debug mode
      development server usage

- [ ] Determine whether the current Flask serving configuration is appropriate for an Internet-facing production deployment.

- [ ] Do not replace the runtime/server blindly; first evaluate compatibility with scheduler behavior, websockets, SQLite and the existing Docker/Unraid deployment model.


### Dependencies

- [ ] Audit Python dependencies for known security vulnerabilities.

- [ ] Identify obsolete/unmaintained dependencies.

- [ ] Upgrade only when required or beneficial.

- [ ] Before upgrading a dependency, evaluate breaking changes and compatibility with the existing VODUM codebase.


### Security regression tests

- [ ] Add automated regression tests for confirmed security requirements.

At minimum cover:

      unauthenticated access to admin routes
      authentication allowlist
      CSRF rejection
      unsafe redirect rejection
      login brute-force protection
      session behavior
      Plex Owner deletion protection
      Jellyfin Admin deletion protection
      path traversal
      malicious ZIP paths
      ZIP extraction limits
      SSRF protection where applicable
      trusted proxy behavior
      spoofed forwarded headers
      secret redaction
      security headers

Tests must preserve legitimate LAN Plex/Jellyfin access and large Tautulli import
use cases.


### Final security report

- [ ] Produce a final audit report after the review.

Classify findings as:

      CRITICAL
      HIGH
      MEDIUM
      LOW
      INFO

For every finding document:

      affected file/function
      current behavior
      existing protection, if any
      attack prerequisites
      realistic exploit scenario
      potential impact
      whether exploitation was confirmed or theoretical
      recommended correction
      regression risk
      tests added/performed
      final status

IMPORTANT:

Do not report something as a vulnerability simply because the implementation
looks unusual.

Confirm the actual execution path and existing protections first.

The goal is to harden VODUM for public Internet exposure WITHOUT breaking
working Plex/Jellyfin integration, LAN access, reverse-proxy operation,
Tautulli imports, backup/restore, scheduler tasks or existing administrator
workflows.
