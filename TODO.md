<<<<<<< Updated upstream
# ✅ VODUM – TODO CLEAN

---
* [ ] add migration option from plex to jellyfin
* [x] override expiration date in user profile

# 🚨 URGENT — FIX ACCÈS PLEX

## 🎯 Objectif

Empêcher que les accès Plex soient supprimés après réactivation d’un utilisateur.

---
* [~] Les accès remis ne sont plus supprimés après sync_plex
* [~] Aucun ancien job ne casse les droits

## 🔴 Résultat attendu

* [~] Les accès remis ne sont plus supprimés après sync_plex
* [~] Aucun ancien job ne casse les droits
* [~] Plex reflète correctement la DB — partiel : les changements d’options/filtres Plex créent maintenant un media_job `apply_plex_access_updates`
* [ ] Les réactivations sont fiables à 100% — à valider sur un cycle complet invitation → expiration → réactivation → sync_plex

---

# 🚨 URGENT — RÉACTIVATION APRÈS EXPIRATION PLEX

## 🎯 Objectif

Éviter qu’un utilisateur expiré perde totalement la relation de partage Plex, car Plex ne permet plus toujours de le résoudre ensuite sans nouvelle invitation.

---

## 🔴 Problème constaté

* [ ] Si Vodum retire toutes les bibliothèques Plex à l’expiration, Plex peut faire disparaître l’utilisateur de la liste des utilisateurs partagés
* [ ] Après renouvellement, `apply_plex_access_updates` peut échouer avec `[PLEX RESOLVE] unable to resolve user without re-inviting`
* [ ] La simple modification de la date de renouvellement ne suffit donc pas toujours à restaurer l’accès

---

## ✅ Solution attendue

* [ ] Ajouter/clarifier un mode `soft-disable` Plex : ne jamais casser le partage Plex à l’expiration
* [ ] En mode avertissement, conserver les bibliothèques et bloquer la lecture via policy `expired_subscription`
* [ ] En mode suppression dure, afficher clairement que la réactivation peut nécessiter une nouvelle invitation Plex
* [ ] Au renouvellement, supprimer automatiquement la policy `expired_subscription` puis déclencher la restauration des accès
* [ ] Ajouter un test complet : actif → expiré → policy appliquée → renouvellement → policy supprimée → accès restauré sans ré-invitation
* [ ] Ajouter un message UI/settings expliquant la différence entre expiration avec blocage lecture et expiration avec retrait d’accès Plex

---

# 🧱 1. Architecture

* [ ] Supprimer les dépendances globales encore trop couplées entre routes, tâches et providers

## Règles GET / POST

* [ ] Supprimer les routes GET qui modifient la base
* [ ] Supprimer les routes GET qui déclenchent des jobs
* [ ] Réserver les routes GET à la lecture seule
* [ ] Réserver les POST aux changements d’état
* [ ] Réserver les actions réelles aux workers

## Monitoring (reste à finaliser)

* [ ] Utiliser les posters/background stockés en DB pour les tops (overview / libraries)
* [ ] dans chaque monitoring, les posters liés aux films ne sont pas ceux du films en question

## Task system

* [ ] Réduire les responsabilités trop nombreuses de `tasks_engine.py`

## Boot / structure

* [ ] Rendre la séquence de boot plus lisible et centralisée

## Providers

* [ ] Empêcher toute logique provider dans les routes web
* [ ] Empêcher toute logique provider dans les templates
* [ ] Réserver l’accès provider aux services et tâches

## Routes critiques

* [~] Sortir complètement la création de `media_jobs` des routes web
* [ ] Recenser toutes les routes GET encore non conformes
* [ ] Lister explicitement les exceptions autorisées (proxy média)

---

# 📊 2. Monitoring

## Source de vérité

* [~] Supprimer tout appel live Plex restant dans monitoring/dashboard
* [ ] Implémenter fallback sur dernier snapshot si tâche lente

## Sync Plex

* [ ] Améliorer le matching (name + type + server)
* [ ] Éviter pertes de données
* [ ] Nettoyer les données héritées (Tautulli / thumbs)

## Performance

* [ ] Découper les traitements lourds
* [~] Mettre en cache les résultats complexes
* [~] Limiter fréquence appels Plex — partiel : cache disque des artworks + headers HIT/MISS/STALE, reste à supprimer les appels live non-images
* [~] Stocker/cache les posters pour éviter requêtes répétées — cache disque `/appdata/artwork_cache` avec TTL + fallback stale
* [x] Ajouter une tâche de warmup cache artwork pour précharger dashboard/monitoring
* [x] Ajouter nettoyage périodique du cache artwork trop ancien
* [ ] Déplacer la logique proxy/cache artwork hors route vers un service dédié
* [x] Optimiser les index DB pour les grosses instances

---

# 📬 3. Communications & Campaigns

## Fiabilité

* [~] Garantir qu’une campagne ne reste jamais bloquée
* [ ] Reprise automatique après redémarrage
* [ ] Rattrapage des emails manqués

## Logique métier

* [ ] Unifier expiration / campaigns / scheduled
* [x] Empêcher doublons

## Améliorations

* [~] Retry sur erreurs
* [~] Logs détaillés
* [ ] Résumé global (Discord/email)

---

# 👤 4. Gestion des utilisateurs & accès

## Plex access

* [ ] Fiabiliser la réactivation après expiration sans nouvelle invitation Plex quand le mode soft-disable est utilisé
* [ ] Corriger états incohérents (already invited / request sent)
* [ ] Décaler expiration si compte non utilisé

## Actions globales

* [ ] Grant access à tous
* [ ] Remove access global

## DB & cohérence

* [ ] Nettoyage automatique incohérences
* [ ] Compteur utilisateurs par library

---

# 🧩 5. Libraries & Media

* [ ] Corriger association library ↔ media
* [ ] Prioriser posters Plex
* [ ] Corriger affichage séries (poster série)
* [ ] Top played fiable
* [ ] Masquer libraries sans activité


---

# 🧠 6. UI / UX

## Tables

* [ ] Pagination standard
* [x] Sauvegarde filtres — partiel : Users mémorise sort/order/status en cookies
* [ ] Indicateur de tri
* [ ] Click ligne → modal

## Cohérence UI

* [~] Uniformiser modals
* [~] Réduire bruit visuel
* [ ] Améliorer design global

## Interactions

* [ ] Supprimer boutons inutiles
* [~] Ajouter bulk actions — partiel : bulk delete policies sécurisé, reste à généraliser aux tableaux principaux
* [x] Recherche complète users — partiel : filtres statuts corrigés et panneau filtres amélioré, reste recherche multi-champs complète
* [ ] Vérifier multilangue partout

---

# ⚙️ 7. Settings & Configuration

* [ ] Finaliser système multilangue
* [ ] SMTP simple + OAuth

---

# 🔄 8. Automatisation & tâches

* [ ] Mode `--summary-only`

---

# 🧪 9. Data quality & repair

* [~] Script réparation DB au boot
* [ ] Nettoyage entrées invalides
* [x] Vérification intégrité régulière

---

# 🧱 10. Refactor code

* [ ] Découper fichiers >1000 lignes
* [~] Séparer routes / services / providers
* [ ] Uniformiser accès DB
* [ ] Supprimer code mort

---

# 🚀 11. Bonus / Futur

* [ ] Support Jellyfin complet
* [ ] Notifications Discord enrichies
* [ ] Dashboard avancé
* [ ] API publique

---

=======
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
>>>>>>> Stashed changes
