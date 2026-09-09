# VODUM — audit fonctionnel et couverture Plex / Jellyfin

Date : 6 septembre 2026. Périmètre : administration des serveurs, utilisateurs, accès et sécurité, avec inventaire des autres modules VODUM.

**Cadrage après revue avec le mainteneur — 6 septembre 2026**

Le [TODO](C:/Users/sylva/OneDrive/Documents/Dev/VODUM-dev/TODO.md) porte les suites à étudier et prévaut sur l'ordre initial proposé ci-dessous. Le retrait des bibliothèques sans désactivation du compte Jellyfin est intentionnel, pas un défaut : désactiver et supprimer seront des choix supplémentaires, en respectant les modes existants de fin d'abonnement et de suppression. La coupure de lecture Jellyfin est signalée comme non fonctionnelle par le mainteneur : sa reproduction et sa correction sont prioritaires, indépendamment de la future révocation des appareils. La promesse de changement obligatoire du mot de passe reste à corriger.

La recherche d'une disparition complète de l'utilisateur côté Plex a déjà été menée sans succès : les retraits de partage, d'amitié ou de Home ne constituent pas une garantie de purge de toutes les références. Le ZIP autonome avec sa clé est conservé pour la restauration sur une nouvelle instance ; vérifier sa protection locale et clarifier sa sensibilité, sans imposer son chiffrement comme correction prioritaire. La vue invitations sera propre à Plex et masquée sans serveur Plex. Le point 7 signifie seulement que le scan Jellyfin actuel concerne tout le serveur, même déclenché depuis une bibliothèque.

**Conclusion**

VODUM est déjà une console de gestion des abonnements, des identités et des droits sur plusieurs serveurs, avec surveillance des lectures et automatisations. Il ne remplace pas encore les consoles d’administration Plex et Jellyfin. Le principal manque est la gestion des politiques natives, des appareils, des paramètres serveur et des opérations de sécurité de bout en bout.

Jellyfin permet d’aller beaucoup plus loin dans la gestion des comptes locaux. Pour Plex, il faut séparer le serveur PMS, le compte propriétaire plex.tv, les partages et Plex Home. Administrer un serveur Plex ne donne pas le contrôle des comptes personnels des utilisateurs invités.

**Méthode et limites**

- Analyse statique du dossier de travail, y compris ses modifications non commitées ; il ne s’agit donc pas d’un audit de la dernière version publiée.
- Lecture des routes, services, fournisseurs, tâches, modèles de pages, schémas et tests pertinents. Recherche transversale des appels API et champs de politiques.
- Comparaison avec le code officiel Jellyfin, son SDK, le support Plex et les sources du client Python PlexAPI. Les sources Jellyfin `master` et PlexAPI `latest` sont évolutives : les signatures doivent être vérifiées contre les versions réellement déployées avant implémentation.
- Le portail officiel PMS existe, mais sa page dépasse la limite de récupération du navigateur de recherche. L’index api.jellyfin.org renvoie 403 à cet outil. Les sources primaires alternatives sont citées ci-dessous ; la couverture complète de ces deux portails n’est pas revendiquée.
- Aucun serveur réel n’a été interrogé, aucun compte ni réglage distant modifié. Pas de parcours visuel de l’interface et pas de test d’intrusion. Les tests existants ont été consultés, pas exécutés ; `python` n’est pas disponible dans le PATH de cette session.
- « Présent » signifie implémenté dans le code observé, pas validé en production. « Manquant » signifie qu’aucun parcours ou appel correspondant n’a été identifié dans ce périmètre. Aucun pourcentage de couverture arbitraire n’est attribué.

**Tour fonctionnel de VODUM**

| Domaine | Ce que le code couvre | Limite principale |
|---|---|---|
| Tableau de bord | Serveurs, lectures en cours, abonnements, tâches et indicateurs de risque | Agrège les informations disponibles ; ne constitue pas un diagnostic complet de l’hôte |
| Serveurs | Ajout Plex/Jellyfin, URL locale/publique, secrets, découverte Plex, synchronisation, état, intégration Tautulli | Enregistre et surveille les serveurs ; ne configure pas l’ensemble de leurs paramètres natifs |
| Bibliothèques | Inventaire, attribution/retrait individuel et en masse, synchronisation et demande de scan | Pas de console complète de création, chemins, agents, paramètres et suppression des bibliothèques natives |
| Utilisateurs | Identités par fournisseur et serveur, regroupement/fusion, coordonnées, propriétaire/admin, invitations Plex, création Jellyfin | La suppression de la fiche reste locale ; contrôle natif Jellyfin incomplet |
| Abonnements | Échéances, modèles, droits, politiques, parrainage, cadeaux et automatisations associées | Une échéance VODUM ne représente pas à elle seule l’état d’authentification natif |
| Monitoring | Sessions, historique, activité par utilisateur/serveur/bibliothèque, transcodage, statistiques | Les lectures observées ne recensent pas tous les jetons et appareils autorisés |
| Politiques de lecture | Limites de flux/IP, sélection des sessions à couper, délais de grâce, avertissements et traces des interventions | Exécution externe dépendant du collecteur, du worker et des capacités du fournisseur |
| Communications | Modèles, campagnes, historique, configuration email/Discord, messagerie du portail | Les notifications de session ne sont pas identiques entre fournisseurs |
| Portail utilisateur | Profil, abonnement, accès, monitoring personnel, support, méthodes de connexion et confidentialité | Les permissions du portail ne remplacent pas celles du serveur média |
| Paiements | Liens et instructions, méthodes configurables, association à des offres | Ce module ne prouve pas un encaissement ni une réconciliation bancaire automatique |
| Migrations | Analyse, mapping des bibliothèques, création/invitation destination, bascule des accès, suivi et rollback de droits | Pas une migration complète des installations, fichiers médias et de tous les états personnels |
| Sauvegardes | Base VODUM, pièces jointes, clé, restauration, rétention ; import Tautulli | Pas une sauvegarde complète de Plex/Jellyfin ; ZIP externe non chiffré |
| Exploitation | Tâches planifiées, séquences, files de travaux, logs et diagnostics | Les tâches VODUM et les tâches natives PMS/Jellyfin sont deux périmètres distincts |
| Sécurité VODUM | Connexion admin locale/Plex, TOTP, sessions serveur, CSRF, séparation portail/admin, chiffrement des secrets, contrôles HTTP | Pas de délégation fine à plusieurs administrateurs et pas d’audit central de toutes les mutations natives |

Points d’entrée : [routes serveurs](C:/Users/sylva/OneDrive/Documents/Dev/VODUM-dev/app/routes/servers.py), [actions utilisateurs](C:/Users/sylva/OneDrive/Documents/Dev/VODUM-dev/app/routes/users_actions.py), [provisionnement](C:/Users/sylva/OneDrive/Documents/Dev/VODUM-dev/app/core/user_provider_provisioning.py), [capacités de migration](C:/Users/sylva/OneDrive/Documents/Dev/VODUM-dev/app/core/migrations/capabilities.py), [liens de paiement](C:/Users/sylva/OneDrive/Documents/Dev/VODUM-dev/app/core/payment_links.py).

**Écarts concrets à traiter en premier**

1. **Suppression locale et suppression native sont différentes.** `_delete_vodum_user_everywhere()` annonce explicitement une suppression locale. Un compte encore présent peut revenir à la synchronisation. Ajouter des actions séparées : retirer de VODUM, suspendre, révoquer un partage Plex, supprimer un compte Jellyfin. La suppression native Jellyfin est possible par `DELETE /Users/{userId}` ; le contrôleur consulté révoque aussi ses jetons. Une suppression globale d’un compte personnel plex.tv n’est pas une fonction d’administration d’un serveur partagé. [Code VODUM](C:/Users/sylva/OneDrive/Documents/Dev/VODUM-dev/app/routes/users_actions.py:24), [contrôleur officiel Jellyfin](https://github.com/jellyfin/jellyfin/blob/master/Jellyfin.Api/Controllers/UserController.cs).

2. **Retirer les bibliothèques Jellyfin ne désactive pas le compte.** Le worker écrit `EnableAllFolders=False` et `EnabledFolders`, sans écrire `IsDisabled`. L’utilisateur peut conserver un compte authentifiable ; les autres droits doivent être examinés séparément. Ajouter une suspension native explicite, avec mémorisation du motif et de l’état précédent. Ne pas réactiver automatiquement un compte déjà bloqué manuellement par un administrateur. [Worker](C:/Users/sylva/OneDrive/Documents/Dev/VODUM-dev/app/tasks/apply_jellyfin_access_updates.py:163), [application des dossiers](C:/Users/sylva/OneDrive/Documents/Dev/VODUM-dev/app/core/providers/jellyfin_users.py:228), [UserPolicy officiel](https://github.com/jellyfin/jellyfin/blob/master/MediaBrowser.Model/Users/UserPolicy.cs).

3. **Le changement obligatoire de mot de passe Jellyfin n’est pas établi.** VODUM envoie `RequirePasswordChange` dans `Policy`, alors que ce champ n’existe ni dans le modèle officiel ni dans le SDK consultés. La fonction ignore les erreurs et le provisionnement mémorise malgré tout l’intention. Un HTTP 2xx peut aussi ne pas prouver l’application d’un champ inconnu. Retirer la promesse tant qu’un mécanisme réellement compatible n’est pas validé ; un mot de passe temporaire ou une activation de portail ne force pas, à lui seul, le client Jellyfin à changer le mot de passe. [Implémentation](C:/Users/sylva/OneDrive/Documents/Dev/VODUM-dev/app/core/providers/jellyfin_users.py:186), [SDK officiel](https://typescript-sdk.jellyfin.org/interfaces/generated-client.UserPolicy.html).

4. **Couper une lecture Jellyfin n’est pas déconnecter l’appareil.** `terminate_session()` envoie `Playing/Stop`, puis vérifie l’absence de `NowPlayingItem`. Ce contrôle est utile pour la lecture, mais ne révoque pas le jeton. Ajouter une opération distincte de déconnexion/révocation, puis tester qu’un ancien jeton ne peut plus accéder au serveur. [Fournisseur](C:/Users/sylva/OneDrive/Documents/Dev/VODUM-dev/app/core/providers/jellyfin.py:100), [API sessions](https://github.com/jellyfin/jellyfin/blob/master/Jellyfin.Api/Controllers/SessionController.cs), [API appareils](https://github.com/jellyfin/jellyfin/blob/master/Jellyfin.Api/Controllers/DevicesController.cs).

5. **La sauvegarde complète est déchiffrable par son détenteur.** `create_backup_file()` place `database.db` et `vodum.encryption_key` dans le même ZIP standard. Le chiffrement des colonnes ne protège donc pas cette archive si elle est volée. Prévoir une enveloppe chiffrée avec un secret externe à l’archive, ou un stockage de sauvegarde chiffré avec clés séparées. Clarifier la présentation « sauvegardes chiffrées » du README. [Sauvegarde](C:/Users/sylva/OneDrive/Documents/Dev/VODUM-dev/app/core/backup.py:50).

6. **Les politiques natives Jellyfin sont principalement affichées.** La fiche montre admin, désactivé, masqué, dernière connexion et autres informations importées, avec un lien vers Jellyfin. Les changements natifs identifiés portent surtout sur les dossiers, le mot de passe et le nom via le portail. Transformer cette fiche en éditeur de politiques par serveur. [Fiche](C:/Users/sylva/OneDrive/Documents/Dev/VODUM-dev/templates/users/partials/_user_jellyfin.html), [renommage](C:/Users/sylva/OneDrive/Documents/Dev/VODUM-dev/app/core/portal_provider_profile.py).

7. **Le rafraîchissement Jellyfin est global.** Le fournisseur ignore le `section_id` et appelle `/Library/Refresh`. L’interface doit préciser cette portée. Une actualisation ciblée des métadonnées existe dans `POST /Items/{itemId}/Refresh`, mais ce n’est pas automatiquement l’équivalent d’un scan de bibliothèque : le mapping des identifiants et le comportement doivent être validés. [Code](C:/Users/sylva/OneDrive/Documents/Dev/VODUM-dev/app/core/providers/jellyfin.py:84), [contrôleur officiel](https://github.com/jellyfin/jellyfin/blob/master/Jellyfin.Api/Controllers/ItemRefreshController.cs).

**Plex : ce qu’il reste à ajouter**

Plex publie une documentation officielle PMS. Les opérations de compte et de partage utilisées par VODUM passent néanmoins aussi par plex.tv et des endpoints historiques. Les méthodes Python PlexAPI citées ci-dessous constituent une source primaire sur ce client communautaire, pas une garantie contractuelle de Plex. [Annonce officielle](https://www.plex.tv/en-gb/blog/plex-pro-week-25-api-unlocked/).

| Fonction | État VODUM | Accès technique / proposition |
|---|---|---|
| Connexion, découverte, inventaire | Présent | Consolider le diagnostic propriétaire, token, version, capacités et connectivité |
| Invitation et partage de bibliothèques | Présent | Le code utilise notamment `/api/servers/{machineId}/shared_servers` sur plex.tv |
| Retrait d’un partage sur un serveur | Présent dans les jobs | Le worker possède une action `revoke` explicite ; l’exposer clairement comme révocation de partage |
| Filtres films/séries/musique, options de partage | Présent | Améliorer l’éditeur et vérifier les options réellement applicables au compte et à la version |
| Cycle des invitations | Partiel | Ajouter une vue centralisée des invitations, ancienneté, annulation et erreurs de synchronisation |
| Plex Home et utilisateurs gérés | Détection, pas de console complète identifiée | Création/retrait de profils gérés et gestion du PIN selon l’identité propriétaire ; tester séparément des invités |
| Paramètres PMS | Manquant | Lecture/écriture de `/:/prefs`, avec formulaire typé et valeurs annoncées par le serveur |
| Audit réseau et authentification PMS | Manquant | Examiner les accès sans authentification, connexions sécurisées et réglages réseau exposés |
| Bibliothèques natives | Accès et scan présents, administration partielle | Ajouter création/modification, emplacements et paramètres ; séparer suppression de bibliothèque et effacement de médias |
| Maintenance PMS | Manquant | Tâches Butler, activité, logs, diagnostic et vérification de mises à jour selon plateforme |
| Appareils autorisés | Monitoring de lecture seulement | Distinguer historique des appareils ayant lu et appareils autorisés sur le compte connecté ; portée à afficher |
| Accès à des médias individuels | Aucun parcours identifié | Plex propose cette fonction ; faisabilité API à qualifier avant engagement |
| Comptes personnels des invités | Hors contrôle propriétaire du serveur | Ne pas promettre de gérer leurs mots de passe, leur MFA ou tous leurs appareils |

Références : [PlexAPI comptes/Home/invitations](https://python-plexapi.readthedocs.io/en/latest/modules/myplex.html), [sources des endpoints plex.tv](https://python-plexapi.readthedocs.io/en/latest/_modules/plexapi/myplex.html), [PlexAPI paramètres PMS](https://python-plexapi.readthedocs.io/en/latest/modules/settings.html), [PlexAPI serveur et maintenance](https://python-plexapi.readthedocs.io/en/latest/modules/server.html), [accès aux médias individuels](https://support.plex.tv/articles/shared-media/).

Les restrictions de partage peuvent dépendre de Plex Pass. L’interface doit montrer « non disponible pour ce compte » plutôt qu’un bouton qui échoue. Les noms historiques `allowCameraUpload`, `allowChannels`, `allowSync` présents dans VODUM doivent faire l’objet d’une qualification fonctionnelle ; leur présence dans une bibliothèque cliente ne démontre pas qu’ils correspondent tous à des fonctions actuelles utilisables. [Restrictions Plex](https://support.plex.tv/articles/201105738-creating-and-managing-server-shares/).

L’accès PMS sans authentification mérite un contrôle dédié : Plex documente une liste d’IP/réseaux autorisés sans connexion. VODUM pourrait signaler une exception trop large et expliquer sa portée. La vérification TLS configurée dans VODUM protège son propre client HTTP ; elle ne prouve pas que PMS impose des connexions sûres à tous les lecteurs. [Documentation Plex](https://support.plex.tv/articles/200890058-authentication-for-local-network-access/), [client HTTP VODUM](C:/Users/sylva/OneDrive/Documents/Dev/VODUM-dev/app/core/http_security.py).

**Jellyfin : ce qu’il reste à ajouter**

L’API fournit des comptes locaux et une politique native riche. Il faut exposer des formulaires adaptés à la version, pas un éditeur JSON libre par défaut. Les propriétés doivent être lues avant modification pour conserver celles que VODUM ne gère pas.

| Groupe de permissions | Réglages à proposer |
|---|---|
| Compte | Activation/désactivation, visibilité, statut administrateur ; protection du dernier administrateur |
| Connexion | Accès distant, seuil de verrouillage, diagnostic et remise à zéro des tentatives sous contrôle |
| Lecture | Lecture autorisée, transcodage audio/vidéo, remuxage et débit distant |
| Contenus | Téléchargement, suppression globale ou par dossier, gestion des collections/sous-titres/paroles selon version |
| Contrôle parental | Classification, contenus non classés, tags autorisés/interdits et horaires |
| Appareils | Autoriser tous les appareils ou une liste définie |
| TV et commandes | Accès/gestion TV, chaînes, contrôle d’autres utilisateurs et appareils partagés, SyncPlay |
| Sessions | Limite native de sessions actives ; vérifier sa sémantique avant de l’assimiler aux flux simultanés VODUM |

Source des champs : [UserPolicy du SDK officiel](https://typescript-sdk.jellyfin.org/interfaces/generated-client.UserPolicy.html). Leur présence dans le modèle ne garantit pas que chaque fonction soit opérationnelle sur toute installation ; les politiques de connexion dépendent aussi des fournisseurs d’authentification installés.

| Fonction API | État VODUM | Endpoint / capacité à intégrer |
|---|---|---|
| Lister, créer, renommer, changer mot de passe | Présent, avec parcours différents | `/Users`, `/Users/New`, `/Users/{id}`, `/Users/{id}/Password` |
| Modifier les politiques | Dossiers principalement | `POST /Users/{id}/Policy` ; conserver les champs non modifiés |
| Supprimer un compte natif | Manquant | `DELETE /Users/{id}` ; montrer aussi les conséquences sur les données personnelles natives |
| Lister/déconnecter les appareils | Manquant | `GET /Devices`, `DELETE /Devices` avec identifiants ; signature selon version |
| Gérer les clés API | Manquant | `GET/POST /Auth/Keys`, `DELETE /Auth/Keys/{key}` |
| Lire/modifier configuration serveur | Manquant | `GET/POST /System/Configuration` et configurations nommées |
| Diagnostic natif | Partiel | `/System/Info`, `/System/Logs`, logs individuels selon version |
| Redémarrer/arrêter | Manquant | `POST /System/Restart`, `POST /System/Shutdown` ; possibilité effective selon hébergement |
| Tâches natives | Manquant | `/ScheduledTasks` : liste, lancement, arrêt, déclencheurs |
| Bibliothèques natives | Inventaire/accès présents | `/Library/VirtualFolders` et sous-routes de gestion |
| Plugins et dépôts | Aucun parcours identifié | Lot ultérieur à qualifier sur API/version ; intérêt pour diagnostic et surface de sécurité |

Sources : [utilisateurs](https://github.com/jellyfin/jellyfin/blob/master/Jellyfin.Api/Controllers/UserController.cs), [appareils](https://github.com/jellyfin/jellyfin/blob/master/Jellyfin.Api/Controllers/DevicesController.cs), [clés API](https://github.com/jellyfin/jellyfin/blob/master/Jellyfin.Api/Controllers/ApiKeyController.cs), [configuration](https://github.com/jellyfin/jellyfin/blob/master/Jellyfin.Api/Controllers/ConfigurationController.cs), [système](https://github.com/jellyfin/jellyfin/blob/master/Jellyfin.Api/Controllers/SystemController.cs), [tâches](https://github.com/jellyfin/jellyfin/blob/master/Jellyfin.Api/Controllers/ScheduledTasksController.cs), [bibliothèques](https://github.com/jellyfin/jellyfin/blob/master/Jellyfin.Api/Controllers/LibraryStructureController.cs).

Plusieurs endpoints officiels consultés exigent une politique d’élévation. Il faut tester la capacité du jeton configuré, distinguer 401 et 403, et éviter de promettre des clés finement limitées à une bibliothèque si le fournisseur n’offre pas ce mécanisme. Pour une rotation de clé : créer, enregistrer chiffré, tester la nouvelle clé puis révoquer l’ancienne ; ne jamais révoquer d’abord la seule clé fonctionnelle. Masquer les secrets jusque dans les URL d’erreur de révocation.

**Sécurité et architecture à compléter dans VODUM**

Les protections existantes sont substantielles : garde globale des routes, distinction portail/admin, CSRF, sessions révocables, TOTP, secrets chiffrés et restrictions des origines HTTP. Leur existence ne vaut pas certification de sécurité ; ce rapport ne remplace pas les audits spécialisés déjà présents dans `docs`.

| Besoin | Constat | Évolution proposée |
|---|---|---|
| Plusieurs administrateurs | `admin_accounts` impose `CHECK(id = 1)` ; les identités se rattachent au même administrateur | Comptes nominatifs et rôles : lecture, support, gestion des accès, administration serveur, propriétaire |
| Permissions par serveur | Contrat principal admin/portail ; pas de délégation fine identifiée | Limiter un opérateur aux serveurs et actions autorisés, contrôles backend inclus |
| Journal d’administration | Logs, audit portail et interventions existent séparément | Journal commun : auteur, cible, avant/après expurgé, motif, résultat natif, identifiant d’opération |
| Cohérence des changements | Files de jobs et mécanismes de reprise déjà présents | Étendre à tous les réglages ; distinguer souhaité, envoyé, confirmé et échec |
| Conflits avec les consoles natives | Synchronisations existantes | Détecter les changements externes ; choisir explicitement l’autorité champ par champ |
| Vérification des résultats | Variable selon les opérations | Relire la ressource après écriture ; un succès HTTP ne suffit pas à prouver l’état souhaité |
| Inventaire des capacités | Contrat explicite limité aux migrations ; BaseProvider très réduit | Registre global par fournisseur/version/identité : supporté, interdit, non disponible, non testé |
| Secrets | Chiffrement déjà en place | Inventaire de portée, date de contrôle, rotation, révocation, erreurs sans fuite et sauvegardes protégées |
| Provisionnement Jellyfin | Création puis mot de passe puis droits, par appels successifs | Tester les échecs intermédiaires ; prévoir désactivation/compensation d’un compte créé mais incomplet |
| Réponse à un incident | Coupure de lecture et règles disponibles | Action orchestrée : suspendre, couper, révoquer ce qui est possible, vérifier, alerter et tracer |

Preuves : [schéma admin](C:/Users/sylva/OneDrive/Documents/Dev/VODUM-dev/app/core/db_bootstrap_admin_auth.py:6), [garde globale](C:/Users/sylva/OneDrive/Documents/Dev/VODUM-dev/app/core/global_access_guard.py), [CSRF](C:/Users/sylva/OneDrive/Documents/Dev/VODUM-dev/app/core/csrf_security.py), [contrat fournisseur](C:/Users/sylva/OneDrive/Documents/Dev/VODUM-dev/app/core/providers/base.py), [audit portail](C:/Users/sylva/OneDrive/Documents/Dev/VODUM-dev/app/core/portal_audit.py).

Le provisionnement partiel est un risque à tester, pas une exploitation démontrée : une séquence de plusieurs appels distants n’est pas transactionnelle. Un nouvel utilisateur ne doit pas rester avec des droits par défaut imprévus si l’attribution des restrictions échoue.

**Organisation proposée dans l’interface**

- Fiche serveur : résumé, connexion/capacités, utilisateurs, bibliothèques, réglages, sécurité, tâches natives, journal.
- Fiche utilisateur : identités par serveur, accès effectifs, politiques natives, appareils, sessions, abonnement, historique des changements.
- Centre sécurité : comptes privilégiés, comptes désactivés/verrouillés, appareils, jetons configurés, anomalies réseau/TLS, sauvegardes et interventions.
- Vue comparaison : état VODUM souhaité et état natif observé, date de lecture et action de réconciliation.

Les commandes doivent nommer leur portée : « arrêter la lecture », « déconnecter cet appareil », « désactiver ce compte Jellyfin », « retirer ce partage Plex » et « supprimer la fiche VODUM ». Une commande générique « bannir » serait trompeuse sans résultat détaillé par fournisseur.

**Feuille de route recommandée**

| Ordre | Lot | Résultat attendu | Critère de validation |
|---|---|---|---|
| 1 | Corriger les promesses et états ambigus | Mot de passe obligatoire, sauvegardes, suppression locale et scan global clairement qualifiés | Les messages correspondent aux effets réels et aux capacités vérifiées |
| 2 | Suspension et gestion complète Jellyfin | Politiques natives, désactivation/réactivation, suppression et appareils | État relu ; ancien accès refusé après révocation ; dernier admin protégé |
| 3 | Registre de capacités et opérations communes | Contrats distincts pour comptes, partages, sessions, configuration, clés | Une action non supportée ne peut pas être présentée comme exécutée |
| 4 | Console serveur et diagnostic sécurité | Paramètres PMS/Jellyfin, audit réseau, logs, bibliothèques et tâches natives | Modifications bornées, confirmation de l’état et récupération documentée |
| 5 | Délégation et audit unifié | Administrateurs nominatifs, droits par serveur, historique des mutations | Un opérateur ne peut ni voir ni modifier un serveur hors périmètre |
| 6 | Plex avancé | Invitations, Home, profils gérés, PIN, appareils du compte autorisé | Portée du compte explicite ; pas d’effet sur des partages hors sélection |
| 7 | Réconciliation et réponse à incident | Détection de dérive, modèles de politiques, suspension multi-serveur | Résultat partiel visible, reprises idempotentes et absence de réactivation abusive |

Le registre de capacités et le journal doivent être introduits dès les premiers ajouts, même si leur généralisation est un lot séparé. Réutiliser les jobs, les identités et le stockage des secrets déjà présents plutôt que reconstruire un second système.

**Validation à prévoir avant mise en production**

Tester sur des comptes et serveurs de validation : versions PMS/Jellyfin réellement prises en charge, token propriétaire/admin et insuffisant, serveur indisponible, timeout après écriture, réponse partielle, modification concurrente depuis l’interface native et reprise d’un job. Vérifier spécialement un compte Jellyfin suspendu avec une session déjà ouverte, un jeton d’appareil révoqué, un échec pendant la création et un utilisateur Plex partagé sur plusieurs serveurs du même propriétaire.

Les tests unitaires actuels simulant le fournisseur ne prouvent pas le comportement d’un serveur réel. Exemple : le test de provisionnement vérifie l’appel à `jellyfin_reset_password_required`, sans démontrer que Jellyfin applique cette contrainte. Ajouter des tests de contrat sur des versions ciblées, puis des tests d’intégration pour les opérations critiques.

**Frontière de l’objectif « tout faire »**

Objectif réaliste : centraliser toutes les opérations administratives exposées et autorisées par les fournisseurs, avec une couverture et des limites explicites. L’API média ne suffit pas à administrer le système d’exploitation, le pare-feu, le reverse proxy, les certificats externes, Docker/NAS ou la restauration de tous les volumes. Ces fonctions exigeraient une intégration d’infrastructure distincte. De même, une politique MFA de VODUM ne rend pas automatiquement obligatoire la MFA dans Plex ou Jellyfin.

La meilleure prochaine étape est un lot **politiques natives Jellyfin + suspension/révocation vérifiée + correction des garanties de sécurité**, suivi de la console de configuration serveur Plex/Jellyfin. C’est ce qui rapproche le plus VODUM d’une administration complète sans attribuer aux API des pouvoirs qu’elles n’ont pas.

