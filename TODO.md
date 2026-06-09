# ✅ VODUM – TODO CLEAN

---
* [ ] add migration option from plex to jellyfin
* [x] override expiration date in user profile

# 🚨 URGENT — FIX ACCÈS PLEX

## 🎯 Objectif

Empêcher que les accès Plex soient supprimés après réactivation d’un utilisateur.

---
* [x] Les accès remis ne sont plus supprimés après sync_plex
  - Confirmé dans `app/tasks/sync_plex.py` : si un media_job Plex `queued/running` existe, la sync Plex saute l’utilisateur au lieu d’écraser ses accès.
* [x] Aucun ancien job queued ne casse les droits
  - Confirmé dans `app/core/media_jobs.py` : les anciens jobs `queued` du même user/server sont annulés avant insertion du nouveau job.
  - Confirmé dans `app/api/subscriptions.py` : à la réactivation, les anciens jobs Plex `queued/running/processed=0` sont marqués `canceled` avant de recréer un sync complet.

## 🔴 Résultat attendu

* [x] Les accès remis ne sont plus supprimés après sync_plex
* [x] Aucun ancien job queued ne casse les droits
* [x] Plex reflète correctement la DB — les changements d’options/filtres Plex créent maintenant un media_job `apply_plex_access_updates`
* [~] Les réactivations sont fiables à 100% — logique présente, mais cycle complet réel à valider : invitation → expiration → réactivation → sync_plex

---

# 🚨 URGENT — RÉACTIVATION APRÈS EXPIRATION PLEX

## 🎯 Objectif

Éviter qu’un utilisateur expiré perde totalement la relation de partage Plex, car Plex ne permet plus toujours de le résoudre ensuite sans nouvelle invitation.

---

## 🔴 Problème constaté

* [x] Si Vodum retire toutes les bibliothèques Plex à l’expiration, Plex peut faire disparaître l’utilisateur de la liste des utilisateurs partagés
  - Couvert côté UI par l’avertissement du mode `disable`.
* [x] Après renouvellement, `apply_plex_access_updates` peut échouer avec `[PLEX RESOLVE] unable to resolve user without re-inviting`
  - Couvert par l’ajout du mode `warn_only`, recommandé pour Plex.
* [x] La simple modification de la date de renouvellement ne suffit donc pas toujours à restaurer l’accès
  - Couvert par la création d’un sync Plex complet à la réactivation.

---

## ✅ Solution attendue

* [x] Ajouter/clarifier un mode `soft-disable` Plex : ne jamais casser le partage Plex à l’expiration
  - Réalisé sous le nom `warn_only`.
* [x] En mode avertissement, conserver les bibliothèques et bloquer la lecture via policy `expired_subscription`
  - Confirmé dans `app/tasks/expired_subscription_manager.py` : `warn_only` crée la policy et ne lance pas `_disable_access_for_user`.
* [x] En mode suppression dure, afficher clairement que la réactivation peut nécessiter une nouvelle invitation Plex
  - Confirmé dans `templates/settings/partials/_settings_subscription.html` + traductions.
* [x] Au renouvellement, supprimer automatiquement la policy `expired_subscription` puis déclencher la restauration des accès
  - Confirmé dans `app/api/subscriptions.py` : suppression policy + queue sync Plex complet après réactivation.
* [ ] Ajouter un test complet : actif → expiré → policy appliquée → renouvellement → policy supprimée → accès restauré sans ré-invitation
* [x] Ajouter un message UI/settings expliquant la différence entre expiration avec blocage lecture et expiration avec retrait d’accès Plex

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
* [x] Dans chaque monitoring, les posters liés aux films ne sont pas ceux du film en question

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
  - Encore présent notamment dans `app/routes/servers.py`, `app/routes/users_actions.py`, `app/routes/users_detail.py`.
* [ ] Recenser toutes les routes GET encore non conformes
* [ ] Lister explicitement les exceptions autorisées (proxy média)

---

# 📊 2. Monitoring

## Source de vérité

* [~] Supprimer tout appel live Plex restant dans monitoring/dashboard
* [ ] Implémenter fallback sur dernier snapshot si tâche lente

## Sync Plex

* [ ] Améliorer le matching (name + type + server)
* [~] Éviter pertes de données
  - Partiel : protection ajoutée si job Plex pending/running, mais la fiabilité reste à valider sur cycle réel.
* [ ] Nettoyer les données héritées (Tautulli / thumbs)

## Performance

* [ ] Découper les traitements lourds
* [~] Mettre en cache les résultats complexes
* [~] Limiter fréquence appels Plex — cache disque artwork présent, reste à supprimer les appels live non-images
* [x] Stocker/cache les posters pour éviter requêtes répétées — cache disque `/appdata/artwork_cache` avec TTL + fallback stale
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

* [~] Fiabiliser la réactivation après expiration sans nouvelle invitation Plex quand le mode soft-disable est utilisé
  - Logique `warn_only` présente ; reste test complet.
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
* [x] Sauvegarde filtres — Users mémorise sort/order/status en cookies
* [ ] Indicateur de tri
* [ ] Click ligne → modal

## Cohérence UI

* [~] Uniformiser modals
* [~] Réduire bruit visuel
* [ ] Améliorer design global

## Interactions

* [ ] Supprimer boutons inutiles
* [~] Ajouter bulk actions — partiel : bulk delete policies sécurisé, reste à généraliser aux tableaux principaux
* [x] Recherche complète users — statuts corrigés + panneau filtres amélioré + recherche multi-champs déjà étendue
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


