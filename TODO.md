# ✅ VODUM – TODO CLEAN

---

# 🚨 URGENT — FIX ACCÈS PLEX

## 🎯 Objectif

Empêcher que les accès Plex soient supprimés après réactivation d’un utilisateur.

---

## 🔴 Résultat attendu

* [x] Les accès remis ne sont plus supprimés après sync_plex
* [x] Aucun ancien job ne casse les droits
* [ ] Plex reflète correctement la DB
* [ ] Les réactivations sont fiables à 100%

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

* [ ] Sortir complètement la création de `media_jobs` des routes web
* [ ] Recenser toutes les routes GET encore non conformes
* [ ] Lister explicitement les exceptions autorisées (proxy média)

---

# 📊 2. Monitoring

## Source de vérité

* [ ] Supprimer tout appel live Plex restant dans monitoring/dashboard
* [ ] Implémenter fallback sur dernier snapshot si tâche lente

## Sync Plex

* [ ] Améliorer le matching (name + type + server)
* [ ] Éviter pertes de données
* [ ] Nettoyer les données héritées (Tautulli / thumbs)

## Performance

* [ ] Découper les traitements lourds
* [ ] Mettre en cache les résultats complexes
* [ ] Limiter fréquence appels Plex
* [ ] Stocker les posters pour éviter requêtes répétées

---

# 📬 3. Communications & Campaigns

## Fiabilité

* [ ] Garantir qu’une campagne ne reste jamais bloquée
* [ ] Reprise automatique après redémarrage
* [ ] Rattrapage des emails manqués

## Logique métier

* [ ] Unifier expiration / campaigns / scheduled
* [x] Empêcher doublons

## Améliorations

* [x] Retry sur erreurs
* [x] Logs détaillés
* [ ] Résumé global (Discord/email)

---

# 👤 4. Gestion des utilisateurs & accès

## Plex access

* [ ] Corriger états incohérents (already invited / request sent)
* [x] Conserver droits si utilisateur non accepté
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
* [ ] Sauvegarde filtres
* [ ] Indicateur de tri
* [ ] Click ligne → modal

## Cohérence UI

* [ ] Uniformiser modals
* [ ] Réduire bruit visuel
* [ ] Améliorer design global

## Interactions

* [ ] Supprimer boutons inutiles
* [ ] Ajouter bulk actions
* [ ] Recherche complète users
* [ ] Vérifier multilangue partout

---

# ⚙️ 7. Settings & Configuration

* [x] Ajouter toggle `VODUM_TRUST_PROXY`
* [ ] Finaliser système multilangue
* [x] Sauvegarde/restauration DB via UI
* [ ] SMTP simple + OAuth

---

# 🔄 8. Automatisation & tâches

* [x] Script envoi emails quotidien
* [x] Désactivation users expirés (12h)
* [x] Vérification serveurs (horaire)
* [ ] Mode `--summary-only`

---

# 🧪 9. Data quality & repair

* [x] Script réparation DB au boot
* [ ] Nettoyage entrées invalides
* [ ] Vérification intégrité régulière

---

# 🧱 10. Refactor code

* [ ] Découper fichiers >1000 lignes
* [ ] Séparer routes / services / providers
* [ ] Uniformiser accès DB
* [ ] Supprimer code mort

---

# 🚀 11. Bonus / Futur

* [ ] Support Jellyfin complet
* [ ] Notifications Discord enrichies
* [ ] Dashboard avancé
* [ ] API publique

---

