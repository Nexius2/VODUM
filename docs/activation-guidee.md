# Activation guidée des utilisateurs

## Fonctionnement

Portail désactivé : la création existante est conservée, avec provisionnement Plex/Jellyfin immédiat et notifications habituelles.

Portail activé : les accès sélectionnés sont enregistrés dans `user_activations` et `user_activation_servers`. Les bibliothèques de serveurs Plex liés sont réparties par serveur réel. Les invitations Plex attendent la vérification de l'identité ; Jellyfin conserve la création de comptes existante. Le mode e-mail utilise l'activation locale et sa politique de mot de passe.

Le lien personnel ouvre `/portal/access`. Plex utilise les PIN et la vérification d'identité existants. L'adresse Plex doit correspondre à l'adresse invitée lors de la première association ; les reprises vérifient ensuite l'identifiant Plex stable. Un autre compte, une association concurrente ou une adresse Apple masquée incompatible sont refusés explicitement. L'administrateur peut corriger l'adresse VODUM et renvoyer l'activation ; une identité déjà associée n'est pas remplacée.

Chaque serveur est traité séparément par POST protégé par CSRF. Un verrou temporaire évite les traitements concurrents. Les partages sont recherchés avant écriture et mis à jour s'ils existent. L'acceptation automatique ne concerne que les identifiants de partages du serveur sélectionné, jamais toutes les invitations reçues. L'accès est déclaré prêt seulement quand le serveur apparaît dans les ressources du compte utilisateur. Un échec partiel permet une reprise sans retraitement des serveurs prêts.

## E-mails : modèles existants

L'envoi passe par `select_comm_templates_for_user`, avec `trigger_event=user_creation` et le fournisseur réel (`plex` pour les accès Plex), puis `comm_scheduled` et la tâche existante `send_expiration_emails`.

Les règles existantes choisissent un modèle par créneau `days_after`, selon l'abonnement et la cible média ; la cible générique `all` reste le recours prévu par ce moteur. Les cibles Jellyfin ne sont pas utilisées pour Plex. Les modèles désactivés sont exclus. Sans modèle applicable, une erreur est remontée dans l'admin et aucun e-mail distinct n'est envoyé. Les délais, traductions, pièces jointes, tentatives et historique sont conservés.

L'objet et le texte du modèle configuré sont utilisés, y compris s'il s'agit d'un modèle par défaut personnalisé. Les ancres existantes deviennent du texte et un unique bouton « Activer mon accès » est ajouté. Le texte personnalisé reste sous le contrôle de l'administrateur : ses éventuelles anciennes consignes de connexion ne sont pas réécrites. L'envoi d'activation utilise exclusivement le canal e-mail. Le bouton de renvoi sur la fiche utilisateur utilise les mêmes modèles et délais.

Le jeton n'est généré qu'au traitement effectif de la file. Plusieurs tentatives de livraison utilisent le même lien tant qu'il est valide. Le renvoi explicite invalide l'ancienne génération et ses parcours en cours. Les anciens messages en file sont refusés à l'envoi. Un modèle dont le déclencheur ou la cible a changé est également refusé.

## Sécurité et durée de vie

- Lien aléatoire de 256 bits, validation par empreinte SHA-256, durée de 7 jours à partir de sa génération pour livraison.
- Copie du jeton d'e-mail chiffrée avec le stockage de secrets existant pour permettre les tentatives de livraison ; aucun jeton brut dans la file ni dans l'historique de communication ajouté par ce parcours.
- Paramètre personnel retiré de l'URL avant affichage ; `Cache-Control: no-store` et `Referrer-Policy: no-referrer`.
- État OAuth à usage unique lié au navigateur, à l'activation et à sa génération. Aucun mot de passe Plex demandé.
- Jeton Plex chiffré, utilisable 15 minutes, supprimé à l'achèvement ou au nettoyage après expiration. Il n'est placé ni dans le cookie ni dans le HTML.
- Lien consommé après activation complète ; reprise dans le navigateur autorisé jusqu'à expiration. Le portail habituel reste accessible.
- Suspension, révocation, réinitialisation et effacement du portail invalident aussi l'activation.

## Vérification Plex et Wizarr

Code public consulté les 27–28 septembre 2026 :

- [Wizarr : acceptation v2](https://github.com/wizarrrr/wizarr/blob/main/app/services/media/plex_custom.py) : recherche des invitations reçues et POST `/api/v2/shared_servers/{id}/accept` avec le jeton utilisateur.
- [Wizarr : service Plex](https://github.com/wizarrrr/wizarr/blob/main/app/services/media/plex.py) : provisionnement et appel de l'acceptation après connexion.
- [Python PlexAPI : code MyPlexAccount](https://python-plexapi.readthedocs.io/en/latest/_modules/plexapi/myplex.html) : partages et invitations historiques.
- [Documentation Plex : gestion des accès](https://support.plex.tv/articles/201105738-creating-and-managing-server-shares/) : création du compte et acceptation possible directement dans Plex Web, sans rechercher un autre e-mail.

Les API internes Plex peuvent évoluer. Une acceptation refusée conserve l'état « invitation à accepter », avec un lien vers Plex et une action de vérification. Créer le compte Plex, se connecter et autoriser VODUM restent des actions de l'utilisateur. Si l'autorisation expire pendant une interruption, il faut continuer à nouveau avec Plex.

## Fichiers du changement

- Métier et migration : `app/core/user_activation.py`, `plex_activation.py`, `activation_email.py`, `db_bootstrap_activation.py`, `db_bootstrap_portal.py`, `tables.sql`.
- Raccordements : `app/blueprints/users.py`, `app/routes/portal_activation.py`, `portal_auth.py`, `portal_admin.py`, `__init__.py`, `app/tasks/send_expiration_emails.py`.
- Sécurité et cycle de vie : `app/core/plex_auth_flow.py`, `route_access_policy.py`, `portal_admin_data.py`, `portal_privacy.py`.
- Interface : `templates/portal/access.html`, `access_invalid.html`, `templates/users/partials/_user_general.html`, `static/js/pages/portal-activation.js`.
- Traductions : catalogues `lang`, `translations/ui` et `translations/communication`, en français, anglais, allemand, espagnol et italien.
- Tests : `tests/test_user_activation.py`, `test_plex_activation.py`, `test_portal_translation_catalogs.py`.

## Validation

21 tests dédiés : création admin avec/sans portail, choix des modèles et délais, rendu réel de la file de communications, retour Plex, CSRF et rejeu, comptes incompatibles/Apple, deux serveurs, échec partiel, reprise, invitation déjà reçue/acceptée, expiration, renvoi, révocation, Jellyfin et activation e-mail complète. Tests exécutés avec une base SQLite temporaire issue du schéma et des migrations réels ; appels Plex, Jellyfin et SMTP simulés.

La suite ciblée élargie passe : **245 tests réussis**, couvrant également le portail, Plex, les communications, les migrations du portail, le provisionnement, les routes et CSRF. La syntaxe Python/JavaScript et les espaces du diff sont vérifiés. Aucune invitation réelle, aucun accès serveur réel ni aucun e-mail réel n'ont été envoyés pour ces tests ; une validation avec des comptes Plex de test reste nécessaire pour confirmer le comportement du service distant dans l'installation cible.


## Contrôle du parcours mobile — 29 septembre 2026

- Première activation Plex : ajout de `signUp=true&skipLanding=true` au flux PIN existant, sans perdre le callback signé. Les reconnexions après association conservent le flux habituel. Paramètres vérifiés dans le [formulaire actuellement servi par Plex](https://app.plex.tv/auth-form/), version 4.161.0, puis dans le navigateur avec un PIN de test : champs « Adresse de courriel », « Créer un mot de passe », bouton « Créer un compte » et alternative « Déjà un compte ? Se connecter ». Aucun compte créé ni autorisé pendant ce contrôle.
- Page finale : titre « Votre accès est prêt », explication adaptée, ouverture de Plex dans le même onglet. Les étapes d'inscription ne sont plus affichées après succès.
- Page de création du mot de passe local : thème VODUM ajouté, champs et boutons adaptés au tactile.
- Un échec réseau ou HTTP 500 sur un serveur ne bloque plus la tentative sur le suivant. Les erreurs de session et la limitation de débit arrêtent la boucle.
- Validation du 29 septembre : 171 tests Python réussis (activation, portail, authentification Plex, partages Plex et historique), 5 scénarios JavaScript de poursuite/arrêt de la boucle réussis. `node --check` et `git diff --check` passent.
- Contrôle navigateur sur les templates réels avec données fictives : écran final et formulaire local à 390 px, préparation à 320 px ; thème chargé, aucun débordement horizontal constaté. Cela ne remplace pas un essai complet sur Safari/iOS ou Chrome/Android avec un compte de test et les serveurs réels.
- Fichiers de ce dernier contrôle : `app/core/plex_auth_client.py`, `app/routes/portal_activation.py`, `templates/portal/access.html`, `templates/portal/activate.html`, `static/js/pages/portal-activation.js`, catalogues UI des cinq langues et tests d'activation/authentification Plex.
