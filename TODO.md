
# TODO LIST - Améliorations et Fiabilisation du projet Plex-Bot

## Sécurité
- [ ] Ne jamais logger ni afficher les tokens Plex, Tautulli ou autres credentials sensibles.
- [ ] Envisager de chiffrer les tokens sensibles dans la base.
- [ ] Ajouter des vérifications de permissions sur chaque action “admin” (interface, API, scripts critiques).
- [ ] Vérifier l’absence d’injection SQL dans toutes les requêtes : utiliser toujours les paramètres SQL (`?`) au lieu de la concaténation de chaînes.

## Robustesse & Fiabilité
- [ ] Centraliser la gestion des exceptions (API, accès DB, réseau) : ajouter `try/except` et logs détaillés sur toutes les fonctions critiques.
- [ ] Uniformiser le format de toutes les dates (dans la base ET dans le code, idéalement ISO8601 ou timestamp UNIX).
- [ ] Ajouter des contrôles sur les conversions de date : refuser ou logger toute date mal formée.
- [ ] Ajouter des assertions ou des vérifications post-action pour s’assurer que les changements d’accès (user/lib) sont bien effectifs après chaque tâche de fond.

## Organisation et cohérence des données
- [ ] Nettoyer et uniformiser la gestion des accès utilisateur/bibliothèque : utiliser seulement la table la plus pertinente (`shared_libraries`) pour refléter l’état réel ; supprimer ou archiver l’autre (`user_libraries`) si redondante.
- [ ] Ajouter des “valeurs par défaut” pour les nouveaux champs d’accès (ex : `allowSync`, `filterMovies`, etc.), pour éviter les crashs si ces colonnes sont absentes ou non renseignées.
- [ ] Vérifier que la gestion multi-serveur (Plex/Jellyfin) fonctionne partout (tous les scripts doivent filtrer correctement selon le champ `type` de la table `servers`).

## Lisibilité & Maintenabilité
- [ ] Ajouter des docstrings et commentaires explicites sur chaque script/fonction critique (surtout ceux qui modifient la base ou interagissent avec l’extérieur).
- [ ] Factoriser le code commun (accès DB, envoi de mails, gestion des erreurs) dans des helpers pour éviter la duplication.
- [ ] Nettoyer ou centraliser la gestion des tâches automatisées (utiliser ou renforcer la table `task_status` pour un suivi fiable, ou intégrer une “task queue” simple au lieu de scripts éclatés + cron).

## Internationalisation
- [ ] Finaliser la conversion multi-langue :
    - [ ] Vérifier que tous les messages affichés à l’utilisateur passent par le système de fichiers de langue (`lang/*.json`, `translations.json`).
    - [ ] Ajouter un fallback propre en cas de texte absent dans une langue.
    - [ ] Ajouter (si manquant) le sélecteur de langue dans l’interface et le backend (la langue du navigateur doit être prioritaire, possibilité de forcer manuellement).
    - [ ] Tester toutes les pages/messages en français ET en anglais.

## Divers / Quick Wins
- [ ] Intégrer des checks d’intégrité réguliers (tâche de fond : vérifier cohérence entre base, accès Plex, état des users).
- [ ] Mettre à jour la documentation (README) pour intégrer ces nouveaux standards de sécurité et d’architecture.
- [ ] Prévoir une gestion d’alerte (log ou mail admin) en cas d’échec d’une tâche critique.
