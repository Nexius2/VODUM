# Collections : premier moteur Memoria

Le moteur reprend le principe de l'application Memoria voisine : détecter les décès récents sur Wikidata, confirmer l'identité et la date dans TMDb, puis construire un hommage avec la filmographie présente dans la bibliothèque choisie. Une configuration peut cibler une bibliothèque ou une paire films/séries. Chaque bibliothèque conserve ses objets distants et son historique séparément ; les réglages et les actions restent communs.

## Premier essai

1. Reconstruire et redémarrer VODUM avec ce code. Le démarrage crée les tables et ajoute la tâche `run_collections` sans réinitialiser les tâches existantes.
2. Dans **Collections → Configuration**, enregistrer une clé API TMDb (ou un jeton de lecture) commune à tous les moteurs. La clé est chiffrée dans la base et jamais renvoyée par l’API. Les anciennes clés sont reprises automatiquement si elles sont identiques ; des clés différentes imposent de choisir une clé commune dans cet onglet.
3. Cliquer sur **Memoria**, choisir une bibliothèque ou une paire films/séries et enregistrer. Le nom est imposé selon la langue, par exemple « En hommage à … ». Le nombre de médias peut être limité ou réglé sur **Tous les médias**. L’ordre **Aléatoire** est disponible. Utiliser **Aperçu** : cette exécution consulte les sources et les inventaires, mais ne crée pas de collection et ne demande pas de téléchargement.
4. Consulter **Historique**, puis utiliser **Exécuter** pour appliquer la configuration. Le mode privé désactive la mise en avant Plex ; le mode publié l'active. Les demandes ARR restent optionnelles et nécessitent les routes et profils déjà configurés dans VODUM.

## Exécution et échéances

La tâche `run_collections` est créée activée avec un passage quotidien à **05:15** selon le fuseau du planificateur VODUM. Elle est également déclenchée par une demande manuelle ou lorsqu'une configuration atteint sa propre échéance. Le contrôle utilise le planificateur existant ; aucune seconde boucle indépendante n'est lancée.

Chaque configuration possède sa fréquence, éventuellement une expression cron à cinq champs. Le fuseau est celui des paramètres généraux VODUM. **Désactiver la collection** arrête les synchronisations et acquisitions et demande immédiatement le retrait de tous ses hommages, sur les deux bibliothèques le cas échéant. Les aperçus restent disponibles. Les erreurs de retrait sont visibles et réessayées ; si la tâche globale ou le planificateur est arrêté, le retrait reste en attente jusqu’à sa reprise.

La durée de conservation part de la première détection. Une nouvelle exécution ne repousse pas l'expiration. La détection quotidienne garde en interne un rattrapage de sept jours pour les décès renseignés tardivement ; ce réglage n’est pas exposé dans le formulaire. Aucun hommage vide n'est créé ; les médias arrivés plus tard peuvent compléter l'hommage jusqu'à son échéance.

## Personnalités et limite des hommages

À la limite configurée, une nouvelle détection validée remplace l’hommage le plus ancien (date de première détection). La popularité sert de seuil et de départage pour les détections simultanées, pas à maintenir indéfiniment les anciens hommages. La date d’expiration reste inchangée. Seule la collection est retirée ; aucun média ne l’est.


Le champ **Nombre maximal de personnalités** vaut **4 par défaut**, y compris pour les anciennes configurations qui ne possèdent pas encore ce réglage. Il est distinct du nombre de médias dans chaque hommage. Avec les bibliothèques films et séries, les mêmes quatre personnes peuvent produire jusqu’à quatre hommages par bibliothèque, donc huit objets distants au total. Réduire la limite retire d’abord les hommages VODUM excédentaires avant d’en créer d’autres.

Dans **Mes collections**, l’action **Personnalités** affiche les personnes détectées ou ajoutées, leur portrait, leur score web, leur origine, leur statut, leur échéance et les personnes exclues. **Retirer** demande le retrait de l’hommage et conserve une exclusion persistante : la détection du lendemain ne le recrée pas. **Réinclure** lève cette exclusion ; les personnes dont la durée est déjà écoulée restent expirées.

La recherche TMDb affiche le nom, l’identifiant et quelques titres connus pour choisir le bon résultat. L’ajout est vérifié côté serveur à partir de cet identifiant. Un ajout manuel est prioritaire sur les découvertes automatiques, peut concerner une personne vivante, respecte le plafond et la durée d’hommage, et s’applique aux deux bibliothèques. Ajouter plusieurs fois la même personne active ne prolonge pas son échéance ; ajouter explicitement une personne expirée démarre un nouvel hommage. Les modifications sont prises en charge par `run_collections` et leur attente est visible.

Le seuil **Popularité minimale (score web)** reprend celui de Memoria : **25 par défaut**, réglable par configuration ; **0** désactive ce filtre. Il s’agit du nombre de liens vers les projets Wikimedia renseigné sur Wikidata. Les ajouts manuels passent en premier et ignorent ce seuil, puis les détections sont classées par score décroissant et date de décès la plus récente. Le plafond reste de quatre personnes par défaut. Les portraits TMDb passent par une route locale à destination fixe ; une silhouette remplace une image absente.

Après expiration, les fiches et crédits sont purgés une fois les hommages distants retirés. Un marqueur temporaire réduit aux identifiants empêche leur recréation pendant la fenêtre de détection. Une exclusion conserve seulement les identifiants et le choix d’exclusion après expiration. En cas d’échec de retrait distant, les informations nécessaires à sa reprise restent disponibles. Les comptes rendus historiques sont conservés pour l’audit.

## Édition et arrêt d’une exécution

**Modifier** reste accessible pour consulter la configuration. Une exécution qui détient encore son verrou interdit l’enregistrement et les modifications de personnalités ; un avertissement propose **Arrêter l’exécution**. L’arrêt est coopératif : la requête externe déjà partie peut finir, puis le traitement s’arrête avant l’action suivante. Les actions déjà appliquées ne sont pas annulées. Les traitements de cette configuration encore en attente sont déprogrammés ; la prochaine échéance normale reste prévue.

Une configuration simplement en file d’attente peut être modifiée avant sa prise en charge. Un verrou expiré après une interruption ne bloque plus indéfiniment l’édition : l’exécution est marquée interrompue et le verrou est libéré. Les annulations et erreurs apparaissent dans l’historique et les journaux.

## Résultat de l’enregistrement

La fenêtre se ferme après la tentative. Un message persistant indique le succès, le refus ou l’impossibilité de confirmer la réponse du serveur. En cas de refus, **Reprendre la configuration** restaure les choix sans ressaisie ; si la clé commune manque, un bouton ouvre directement son réglage. Les choix en attente restent en mémoire dans la page jusqu’à son rechargement.

Une panne de réveil du planificateur après validation n’annule pas l’enregistrement : la réponse confirme la sauvegarde et signale le problème séparément. L’erreur est journalisée.

## Erreurs et protection des collections

Chaque exécution possède un état et un résultat dans l'historique, avec les médias présents, absents et les éventuelles erreurs ou restrictions. Les détails techniques sont journalisés. Une configuration en échec n'empêche pas les suivantes de passer. Une panne d'identification d'un média conserve l'hommage correspondant sans changement.

VODUM ne gère que les objets dont il a enregistré l'identifiant et vérifié le marqueur de propriété. Une collection externe portant le même titre provoque un conflit visible. L'expiration supprime les métadonnées de l'hommage ; elle ne supprime aucun film, série ou téléchargement ARR.

Les nouvelles erreurs ARR indiquent le titre, le serveur, l’étape, le statut HTTP et les noms des champs de validation refusés, sans exposer la clé ou la réponse brute. Un identifiant TVDB absent ou un titre absent du catalogue ARR produit un avertissement visible. Les refus HTTP définitifs ne déclenchent plus une reprise toutes les quinze minutes ; les pannes transitoires restent réessayables. Les anciens comptes rendus incomplets ne permettent pas de reconstruire rétroactivement leur cause.

## Limites de cette première version

- Memoria et Sélection du moment disposent chacun d’un moteur. Voir aussi `collections-spotlight.md`. Les autres cartes restent en préparation.
- L'identité et la date du décès doivent être confirmées dans les deux sources ; une information absente ou contradictoire est signalée et ignorée.
- La priorité Plex détermine la position du bandeau dans les recommandations de sa bibliothèque. Le portrait TMDb est appliqué comme affiche de l’hommage lorsqu’il est disponible.
- Jellyfin : la mise en avant sur l'accueil et l'ordre personnalisé ne sont pas pris en charge ; ces restrictions apparaissent dans le résultat.
- Les essais automatisés utilisent des adaptateurs simulés et une base isolée. La création réelle et les permissions de tes serveurs restent à tester.

## Validation

83 tests couvrent le moteur, les identités, l'expiration, les aperçus sans mutation, l'isolation, les horaires, la reprise et la propriété des collections. Les tests ciblés du planificateur, du catalogue de tâches, du chiffrement et des demandes de médias passent également (50 tests supplémentaires).

Références : [filmographie TMDb](https://developer.themoviedb.org/reference/person-combined-credits), [identifiants TMDb](https://developer.themoviedb.org/docs/finding-data), [collections PlexAPI](https://python-plexapi.readthedocs.io/en/latest/modules/collection.html), [contrôleur officiel Jellyfin](https://github.com/jellyfin/jellyfin/blob/master/Jellyfin.Api/Controllers/CollectionController.cs).

Références pour la gestion manuelle : [recherche de personnes TMDb](https://developer.themoviedb.org/reference/search-person), [fiche d’une personne TMDb](https://developer.themoviedb.org/reference/person-details).

## Historique lisible

Les nouvelles exécutions regroupent films et séries par configuration et passage du moteur. Chaque hommage affiche ses titres et le statut ARR de chacun : ajouté, déjà connu, présent en bibliothèque, non ajouté ou échec. Les identifiants et diagnostics complets ne sont affichés que lorsque le mode debug VODUM est activé. Les anciens résultats ne permettent pas de reconstruire les statuts par titre absents de leur enregistrement.

Les recherches d’identifiants alternatifs ne concernent que les médias sans identifiant TMDb dans l’inventaire, ce qui évite des appels TMDb inutiles pour chaque crédit manquant. Un échec d’identification conserve les hommages existants et apparaît dans le listing.

Le bouton **Ajouter la collection** dans Personnalités valide une personne détectée comme choix manuel prioritaire et demande une synchronisation. Il ne confirme pas une publication distante : celle-ci doit finir avec succès. La vue normale de l’historique conserve les hommages validés ou publiés et affiche cinq titres avant **Afficher la suite**. Les erreurs restent signalées sous forme compacte.

Un titre dont l’identification échoue est isolé sans bloquer les titres identifiés. Lorsqu’un inventaire est incertain, les mises à jour conservent les anciens membres de la collection et ajoutent les titres confirmés ; aucune suppression fondée sur cet inventaire incomplet n’est effectuée. Les réponses TMDb 404 sont signalées comme titres indisponibles. Les comptes rendus complets restent en base pour le debug ; les logs courants ne répètent plus toute la filmographie.

## Worker collections et priorité

Les collections disposent d’un worker sériel dédié au sein du processus VODUM, avec son propre verrou. Le worker général continue donc le monitoring et les autres tâches pendant les attentes réseau des collections. Les deux workers partagent les ressources du processus et la base ; ce n’est pas une isolation CPU ou mémoire. Le planificateur et la tâche quotidienne restent communs.

Les hommages utilisant les médias déjà présents sont publiés avant les demandes ARR. Après une erreur de connexion ou un ajout non confirmé, les demandes restantes du passage sont suspendues et signalées, sans répéter un POST incertain. Une lecture de l’inventaire ARR tente de confirmer un ajout dont la réponse a été perdue.

La priorité est saisissable à la création et à l’édition ; 1 déplace le bandeau Plex de l’hommage en tête de sa bibliothèque en mode publié. L’action d’une personnalité est unique : Ajouter tant qu’aucun hommage n’est publié, Retirer ensuite.

## Historique des publications et respect du planning

L’historique présente les dix derniers passages avec leur résultat, puis au maximum les trois dernières publications distinctes par type de moteur. Les synchronisations répétées du même hommage sont regroupées ; aperçus, traitements en cours et erreurs sans publication restent dans les journaux et l’état de la configuration. Les anciens résultats dépourvus de confirmation explicite ne sont pas présentés comme publiés.

Les erreurs ne déclenchent plus de reprise globale ni de relance de collection toutes les quinze minutes. Le prochain passage suit le planning de la configuration ; les demandes manuelles restent possibles. Le nettoyage en échec attend le prochain planning ou, pour une configuration sans planning, au moins un jour.

Les titres de tri des hommages sont préfixés par `_` (Plex `titleSort`, Jellyfin `SortName` et `ForcedSortName`) ; le nom visible reste inchangé. Le préfixe est appliqué à la prochaine synchronisation. Les lignes dépliées conservent les couleurs de statut et le bouton devient Afficher moins. L’indicateur global des tâches tient compte des verrous actifs des collections, sans double comptage, et se rafraîchit lors des changements d’état.

## Filmographie locale et affiche

La sélection combine les identifiants de la filmographie TMDb, les crédits acteur/réalisateur exposés par Plex pour la personnalité et ses alias, et une correspondance exacte titre ou titre original avec année pour les entrées locales. Les résultats sont dédupliqués par identifiant du média serveur avant le plafond configuré. Cette recherche locale reprend les voies de recherche de Memoria qui manquaient à VODUM ; une comparaison des inventaires réels reste nécessaire pour confirmer une égalité de comptage sur chaque serveur.

Le portrait TMDb est appliqué à la collection Plex via son URL fixe en taille w500 et à Jellyfin via un envoi borné de l’image. Un échec de récupération ou d’application produit un avertissement et conserve les médias publiés.

## Collections vides

Dans Configuration, **Ne pas publier les collections vides** est activé par défaut, y compris pour les bases existantes. Sans média disponible, aucun nouvel hommage vide n’est créé ; un hommage VODUM existant devenu vide est retiré à la prochaine synchronisation. Décocher permet de conserver un hommage existant même vide. Une identification incertaine ne provoque pas un retrait. Les médias et les collections externes restent protégés. Le changement du réglage ne déclenche pas de traitement distant immédiat.

### Execution bounds

Each library execution has a cooperative 15-minute deadline, checked before external requests. An in-flight request finishes or reaches its HTTP timeout first. On expiry, the lease is released and the normal schedule is preserved; no immediate retry is queued. Changes already applied remain in place. Plex synchronization only moves items whose position changed. Ownership checks reload missing labels once and still require the stored identifier, library and VODUM marker. Ownership conflicts prevent ARR acquisition for that tribute.


## Diagnostic des lenteurs et reprise (22 octobre 2026)

L’inventaire Plex lit les métadonnées déjà retournées, sans déclencher le rechargement automatique de PlexAPI pour un GUID, une année ou un titre original absent. Ce rechargement pouvait produire une requête par média et atteindre la limite de quinze minutes avec le débit partagé d’une requête par seconde. Les résultats des recherches par personnalité utilisent la même lecture sans rechargement implicite.

La correspondance exacte titre/année est indexée et consultée avant les identifiants alternatifs TMDb. Les hommages sélectionnés d’une bibliothèque sont tous publiés avant les acquisitions ARR ; la bibliothèque suivante conserve son passage sériel. Les appels ARR vérifient l’arrêt et la limite de durée entre les étapes de consultation et d’ajout.

L’identifiant d’une création distante est enregistré avant de vérifier un arrêt survenu pendant la requête. En cas d’annulation ou de dépassement de durée, le compte rendu conserve les publications confirmées, les compteurs et la dernière étape atteinte. Les journaux indiquent les étapes `discovery`, `verify_people`, `inventory`, `match`, `publish`, `acquisition` et `complete`, leur durée écoulée et leurs compteurs. L’erreur de dépassement de durée est conservée explicitement sur la configuration.

Les tests utilisent notamment 1 000 vrais objets PlexAPI partiels avec interdiction de rechargement, ainsi que des interruptions après création distante et après publication. Ces validations locales ne remplacent pas une mesure sur les bibliothèques du serveur déployé.


## Complément de diagnostic commun aux moteurs

Les étapes et compteurs sont maintenant enregistrés pendant le traitement et affichés dans l’historique, même en cas d’échec ou sans publication. La date affichée dans la configuration correspond à la fin du passage ; le début et la durée figurent dans l’historique. Les résultats anciens ne permettent pas de reconstruire les diagnostics qui n’avaient pas été enregistrés.

Les vérifications ARR (profils, dossiers et inventaire) ne commencent qu’après les publications locales de la bibliothèque. Le catalogue ARR est lu une fois au début de cette phase, puis une nouvelle lecture complète est réservée aux anciennes demandes à réconcilier et aux réponses d’ajout incertaines ou conflictuelles. Les nouvelles demandes utilisent cet inventaire et les ajouts confirmés du passage. Une ancienne demande incertaine est toujours réconciliée avant tout nouvel envoi.


## Inventaire partagé

Les moteurs utilisent désormais l’inventaire local partagé, alimenté par `refresh_collection_inventory`, et ne relisent plus toute la bibliothèque distante à chaque passage. Voir [Inventaire des collections](collections-inventory.md) pour le premier remplissage, les durées, le planning à 12 heures après la fin et la gestion des pannes.
