# VODUM - TODO

Ce fichier ne contient que le travail restant. Les changements termines sont
documentes dans `changelog.md`.

## Priorite haute

- [ ] Ajouter une migration guidee Plex vers Jellyfin. (voir fichier User Migration System.md)
- [~] Valider sur une instance reelle le cycle Plex complet : invitation,
  expiration, renouvellement, restauration des acces puis synchronisation.
- [ ] Corriger les etats Plex incoherents (`already invited`, `request sent`).
- [ ] Garantir la reprise automatique des campagnes apres redemarrage.
- [ ] Garantir qu'une campagne ne reste jamais bloquee.

## Architecture et routes

- [ ] Reduire les dependances globales entre routes, taches et providers.
- [ ] Sortir completement la creation de `media_jobs` des routes web.
- [ ] Deplacer toute logique provider des routes/templates vers les services et
  les taches.
- [ ] Separer la route mixte GET/POST `/setup` afin qu'aucun GET ne modifie
  l'etat. Elle est signalee par `tools/audit_get_routes.py`.
- [ ] Corriger toute nouvelle route signalee par
  `python tools/audit_get_routes.py --strict`.
- [ ] Reduire les responsabilites de `tasks_engine.py`.
- [ ] Rendre la sequence de boot plus lisible et centralisee.

### Exceptions GET autorisees

- `GET /api/monitoring/poster/<server_id>` : proxy authentifie de posters et
  backgrounds avec cache local. Cette exception est declaree dans
  `tools/audit_get_routes.py`.

## Monitoring et donnees

- [~] Supprimer les derniers appels live Plex hors proxy d'images.
- [ ] Utiliser les posters/backgrounds stockes en DB pour tous les tops.
- [ ] Implementer un fallback sur le dernier snapshot si une tache est lente.
- [ ] Ameliorer le matching media avec `name + type + server`.
- [ ] Valider et renforcer la protection contre les pertes de donnees Plex.
- [ ] Nettoyer les anciennes donnees Tautulli et thumbs inutiles.
- [ ] Deplacer le proxy/cache artwork vers un service dedie.
- [ ] Decouper les traitements lourds et completer le cache des calculs couteux.
- [ ] Ajouter un nettoyage automatique des entrees invalides.

## Communications

- [ ] Ajouter un rattrapage des emails manques.
- [ ] Unifier expiration, campagnes et envois planifies.
- [~] Completer les retries et les logs d'erreur.
- [ ] Ajouter un resume global email/Discord.

## Utilisateurs et acces

- [ ] Decaler l'expiration tant qu'un compte n'a jamais ete utilise.
- [ ] Ajouter les actions globales d'ajout et de retrait d'acces.
- [ ] Nettoyer automatiquement les incoherences d'acces.
- [ ] Ajouter un compteur d'utilisateurs par bibliotheque.

## UI, configuration et automatisation

- [ ] Uniformiser les paginations et les modales.
- [ ] Generaliser les bulk actions utiles.
- [ ] Reduire le bruit visuel et supprimer les boutons inutiles.
- [ ] Finaliser la traduction de toutes les vues.
- [ ] Ajouter SMTP OAuth.
- [ ] Definir puis ajouter un mode global `--summary-only` aux taches CLI
  concernees.

## Refactor

- [ ] Decouper les fichiers de plus de 1000 lignes.
- [~] Continuer la separation routes / services / providers.
- [ ] Uniformiser les acces DB.
- [ ] Supprimer le code mort.

## Futur

- [ ] Completer le support Jellyfin.
- [ ] Enrichir les notifications Discord.
- [ ] Ajouter un dashboard avance.
- [ ] Ajouter une API publique.
