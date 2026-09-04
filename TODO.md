# VODUM - Feuille de route

Ce fichier contient uniquement le travail restant. Les changements termines sont
documentes dans `changelog.md`.

Derniere mise a jour: 2026-09-01

## Principes de suivi

- Retirer une ligne lorsqu'elle est terminee et la tracer dans `changelog.md`.
- Valider les changements de schema et les traitements automatiques sur une copie
  representative de la vraie base avant publication.
- Ajouter des tests de regression aux fonctions sensibles ou exposees sur Internet.
- Ne jamais enregistrer ni journaliser de secret, token ou donnee bancaire.

## P0 - Bugs & fixes

- [x] dans le profil user, le monitoring ne marche plus.
- [x] dans servers & libraries, l'action refresh library ne marche pas.

## P8 - Partie utilisateur et ouverture externe

- [ ] Ajouter l'historique des abonnements lorsqu'un modele de donnees dedie sera
  disponible.
- [ ] Executer la checklist manuelle de publication sur une instance representative
  derriere le reverse proxy HTTPS reel avant toute activation sur Internet.

## Securite - controles restant a terminer

Les audits deja termines sont dans `docs/security-*-audit.md`,
`docs/container-runtime-audit.md` et `changelog.md`. Ne pas les recreer ici.

### Uploads et imports volumineux

- [ ] Determiner les besoins reels par type d'upload: import Tautulli, restauration
  VODUM et autres fichiers; ne pas reduire aveuglement la limite globale de 4096 Mo.
- [ ] Evaluer des limites distinctes par fonction et verifier pour les imports
  multi-Go: espace disque, fichiers temporaires, nettoyage apres echec, timeout,
  validation DB, memoire, streaming et concurrence.

### SQL, fichiers et commandes

- [ ] Auditer les SQL dynamiques (`f-string`, `.format`, concatenation) et confirmer
  que les valeurs externes sont parametrees et les identifiants dynamiques issus
  de listes internes strictes.
- [ ] Auditer les chemins variables, lectures/ecritures/suppressions, symlinks et
  fichiers temporaires hors du perimetre backup deja traite.
- [ ] Auditer `subprocess`, `shell=True` et `os.system`; aucune valeur utilisateur ou
  provider ne doit devenir une commande ou de la syntaxe shell.

### API, erreurs et resistance aux abus

- [ ] Auditer les API JSON contre IDOR et exposition excessive en testant la
  substitution des IDs utilisateur, compte media, serveur, policy, communication,
  backup, task et monitoring.
- [ ] Auditer les erreurs 4xx/5xx et les logs restants contre les traces, chemins,
  SQL, internals DB, secrets et reponses provider sensibles.
- [ ] Auditer les operations couteuses: connexions, checks Plex/Jellyfin, monitoring,
  artwork, backup/restore, imports, synchronisations, tasks, recherches et grosses
  reponses; verifier timeout, pagination, concurrence et limites raisonnables.

### Cloture avant publication

- [ ] Completer les regressions des constats encore ouverts sans casser l'acces LAN,
  Plex/Jellyfin, les imports Tautulli, SQLite, le scheduler ou les reverse proxies.
- [ ] Produire le rapport final classe `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, `INFO`,
  avec chemin reel, protections existantes, exploitabilite, impact, correction,
  risque de regression, tests et statut.

## Notes de prudence

- `GET /api/monitoring/poster/<server_id>` est l'unique exception GET mutante
  autorisee: proxy authentifie d'artwork avec cache local, documente dans
  `tools/audit_get_routes.py`.
- Ne pas supprimer le cache artwork existant ni remplacer globalement `sync` par
  `revoke`; Plex conserve volontairement un garde-fou contre un sync vide.
- Valider les optimisations SQL avec la vraie base et `EXPLAIN QUERY PLAN`; trop
  d'index peut ralentir les ecritures et le bootstrap.
- Garder les modifications de texte ciblees afin de ne pas recreer de mojibake.
