# VODUM - TODO

Ce fichier ne contient que le travail restant. Les changements termines sont
documentes dans `changelog.md`.

## Priorite haute

- [~] Valider sur une instance reelle le cycle Plex complet : invitation,
  expiration, renouvellement, restauration des acces puis synchronisation.

## Extensions futures des migrations

- [ ] Ajouter des strategies Jellyfin avancees : mot de passe temporaire defini
  par l'administrateur, conservation d'un secret deja connu et livraison
  automatique des identifiants par Communications.
- [ ] Ajouter les mappings multiples et les surcharges de bibliotheques par
  utilisateur.
- [ ] Ajouter un rollback destination facultatif retirant uniquement les acces
  ajoutes par la campagne, sans supprimer les comptes utilises.
- [ ] Ajouter de futurs providers au registre de capacites lorsque leurs
  executors seront disponibles.
- [ ] Valider les campagnes Migrations sur de grandes instances reelles Plex et
  Jellyfin avant d'activer davantage d'automatisations destructives.

## Architecture et routes

- [~] Reduire les dependances globales entre routes, taches et providers.
- [~] Deplacer toute logique provider des routes/templates vers les services et
  les taches.
- [~] Reduire les responsabilites de `tasks_engine.py` (file d'attente
  dedupliquee et execution strictement sequentielle; decoupage structurel
  restant).
- [ ] Rendre la sequence de boot plus lisible et centralisee.

### Exceptions GET autorisees

- `GET /api/monitoring/poster/<server_id>` : proxy authentifie de posters et
  backgrounds avec cache local. Cette exception est declaree dans
  `tools/audit_get_routes.py`.

## Monitoring et donnees

- [~] Valider et renforcer la protection contre les pertes de donnees Plex.

## Communications

- [~] Completer les retries et les logs d'erreur.
- [ ] Ajouter un resume global email/Discord.

## Utilisateurs et acces

- [ ] ameliorer les actions globales d'ajout et de retrait d'acces.

## UI, configuration et automatisation

- [ ] Uniformiser les paginations et les modales.
- [ ] Generaliser les bulk actions utiles.
- [ ] Reduire le bruit visuel et supprimer les boutons inutiles.
- [~] Finaliser la traduction de toutes les vues (les catalogues ont maintenant
  une parite de cles validee automatiquement).
- [ ] Ajouter SMTP OAuth.
- [ ] Definir puis ajouter un mode global `--summary-only` aux taches CLI
  concernees.
  [ ] reorganiser le menu, du plus utile au moins utile. (tasks devrait etre a coté des logs)
  [ ] pour les owner et admin de plex / jellyfin, dans le champs date d'expiration, indiquer juste Owner ou admin, pas besoin d'ecrire le nom du serveur. sinon, c'est pas lisible en cas de nombreux serveurs.
  [x] owner et admin ne devrait pas avoir d'abonnement, il faut les cacher comme pour la date d'expiration. c'est visible dans user detail et dans le tableau user. il faudrait indiquer owner ou admin seulement a la place
  [ ] quand le user est owner plex, on ne devrait pas avoir le bouton supprimer vu que c'est techniquement impossible. 
  [ ] quand le user est admin jellyfin, on ne devrait avoir le bouton grisé vu qu'il est admin, et avec un hover "remove admin to delete". 

## Refactor

- [ ] Decouper les fichiers de plus de 1000 lignes.
- [~] Continuer la separation routes / services / providers.
- [ ] Uniformiser les acces DB.
- [ ] Supprimer le code mort.
- [ ] better readme.md for github
- [ ] better documentation on vodum... 

## Futur

- [ ] Completer le support Jellyfin.
- [ ] compte admin connectable via plex account
- [ ] mise en place de double authentification
- [ ] Enrichir les notifications Discord.
- [ ] Ajouter un dashboard avance.
- [ ] créé un acces web utilisateur completement independant de l'application (port different) pour que le user ai acces a toutes ses infos. il faut donc un compte d'acces, voir pour utiliser compte plex, compte jellyfin et compte mail standard.
- [ ] ajouter un mecanisme de paiement ou lien de paiement sur les profil utilisateurs.
- [ ] Ajouter une API publique.
