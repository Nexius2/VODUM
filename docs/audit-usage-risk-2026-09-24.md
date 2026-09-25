# Audit de la détection Usage Risk — 24 septembre 2026

## Ajustement demandé : distinguer les transitions normales

La logique a ensuite été affinée : les appareils distincts restent présents dans les sessions, mais un dépassement plausible de transition est différé pendant cinq minutes. Cela couvre notamment TV → téléphone, y compris sur un autre réseau, et les mêmes modèles/produits sur une même IP avec le même compte. Le démarrage récent de la nouvelle lecture sert de signal ; une simple date de collecte récente ne suffit pas. Les limites de flux par utilisateur, de flux par IP et d'IP sont prises en compte.

Les contrôles suivants réévaluent les lectures présentes. Si l'ancienne disparaît, il n'y a pas de dépassement à sanctionner. Si le chevauchement persiste après le délai, toutes les lectures restantes sont comptées et les règles configurées s'appliquent. Les identifiants matériels identiques et les contenus cohérents ne justifient plus une fusion permanente. Changer de média ne renouvelle pas le délai d'un chevauchement continuellement observé.

La tolérance de changement de lecteur porte sur un dépassement d'une unité ; elle ne contourne pas une limite à zéro ni un dépassement plus important. Les doublons de lecture sur un même appareil ont également leur délai borné. Deux TV sur deux IP lisant des contenus distincts n'obtiennent pas une tolérance sur la seule ressemblance de modèle. Des comptes distincts sur la même IP ne sont pas assimilés à un changement de lecteur du même utilisateur.

Pendant la tolérance, aucun événement de dépassement n'est produit pour ce cas : il ne provoque donc pas une nouvelle alerte Usage Risk. Cela ne supprime pas le risque historique éventuel du compte. Les caches de tolérance restent en mémoire et ne sont pas persistés lors d'un redémarrage.

Validation supplémentaire : neuf tests de transition (avec plusieurs appareils/règles en sous-cas) et les 82 tests ciblés précédents passent, soit 91 tests. Les constats de déduplication de l'audit initial ci-dessous sont à lire avec cet ajustement.

## Conclusion et périmètre

L'absence d'alertes ne prouve pas l'absence de partage. Plusieurs défauts du code pouvaient empêcher un dépassement de remonter jusqu'au rapport. Ils ont été reproduits et corrigés dans le dépôt de développement. Aucun déploiement, blocage de lecture réel ni envoi de message n'a été effectué.

Audit réalisé sur le code actuel, avec ses modifications locales préexistantes. La base et les journaux de production n'ont pas été consultés : l'impact sur des comptes réels et la date de déploiement responsable ne sont donc pas établis.

Les mécanismes de fusion permissive et de grâce renouvelée apparaissent déjà dans le commit `ed6b353` du 10 juin 2026 (« streams usage fix »). Cette chronologie est compatible avec la disparition des alertes au début de l'été, sans constituer une preuve de causalité en production.

## Chaîne examinée

1. `monitor_enqueue_refresh` programme la collecte ; `media_jobs_worker` appelle le collecteur et peut demander une exécution du contrôleur après une collecte contenant des lectures.
2. Le fournisseur Plex lit `/status/sessions` : utilisateur, IP, appareil, lecteur et données brutes. Le collecteur associe le compte au serveur et enregistre `media_sessions` puis l'historique.
3. Le contrôleur sélectionne les sessions récentes, présentes, suffisamment stables et sur des serveurs disponibles. Il charge les règles activées, résout leur portée et l'héritage des abonnements, puis applique les dérogations, la déduplication et les délais de tolérance.
4. Les avertissements et blocages sont enregistrés dans `stream_enforcements`, avec un instantané des sessions et des IP. La terminaison Plex utilise l'identifiant de session Plex et vérifie la disparition de la session.
5. Usage Risk analyse les événements de contrôle, leurs appareils et leurs IP, puis calcule un score et éventuellement une recommandation d'abonnement.
6. Le tableau de bord, le monitoring et la fiche utilisateur consomment ce rapport. Les notifications de recommandation nécessitent aussi leurs réglages, un modèle actif, un nombre de blocages suffisant et le respect du délai entre notifications.

## Défauts corrigés

### Appareils distincts fusionnés

L'ancien score de rapprochement atteignait son seuil avec le même produit client (+2) et des dates de dernière collecte proches (+3). Les lectures collectées simultanément ont naturellement des dates proches. Deux TV sur deux IP pouvaient ainsi devenir une seule session avant le comptage. Une même IP suffisait également à fusionner des appareils distincts, ce qui rendait les limites de flux par IP inopérantes dans ces cas.

Le rapprochement repose désormais sur l'identifiant matériel, ou sur un même point de lecture avec un contenu et une transition temporelle cohérents. Des noms de produits communs, un sous-réseau commun ou une collecte simultanée ne suffisent plus.

### Identifiant matériel Plex ignoré

Le fournisseur conserve l'identifiant sous `raw_json.Player.machineIdentifier`, alors que l'extracteur cherchait seulement des champs à la racine. Le format réellement enregistré par Plex est maintenant pris en charge, sous forme JSON ou dictionnaire ; les identifiants Jellyfin restent reconnus.

### Tolérance IP sans expiration effective

Le nettoyage supprimait l'entrée de grâce au moment où elle devait expirer. L'appel suivant créait une nouvelle grâce. Un partage de contenu cohérent pouvait donc rester toléré indéfiniment.

Le délai reste maintenant expiré tant que le même dépassement est observé régulièrement, y compris pendant la revérification. Un changement d'épisode ou de clé de session ne le renouvelle plus. Une absence d'observation supérieure au délai permet une nouvelle transition. Ce cache demeure en mémoire : un redémarrage du processus le réinitialise.

### Deux TV du même modèle sous-comptées dans le risque

Le rapport comptait les libellés distincts, pas les appareils. Deux TV portant les mêmes descriptions étaient comptées comme une seule. Les identifiants matériels servent maintenant au comptage ; à défaut, le couple description/IP distingue les points de lecture. Les libellés lisibles restent utilisés dans les preuves affichées.

### Limite de risque différente des règles appliquées

Le rapport lisait seulement le JSON du modèle d'abonnement. Il pouvait manquer une règle globale/manuelle, ou diverger de l'instantané effectivement appliqué à l'utilisateur.

Il utilise maintenant les règles activées de `stream_policies` et le même résolveur de portée et d'héritage que le contrôleur. Les dérogations utilisateur sont prises en compte. Aucun abonnement n'est identifié par son nom, aucun plafond commercial n'est imposé, aucun modèle existant n'est modifié.

### Erreurs présentées comme zéro risque

Une exception du calcul était silencieusement ignorée par le tableau de bord, qui conservait ses compteurs à zéro. L'erreur est maintenant journalisée et la carte affiche un état d'erreur à la place des compteurs.

### Désactivation non respectée

La conversion `int(value or default)` transformait le réglage `usage_risk_enabled=0` en valeur par défaut active. La conversion conserve maintenant le zéro, aussi bien pour le rapport que pour la tâche de notifications.

## Limites fonctionnelles à connaître

- Le rapport reste fondé sur les événements de contrôle, pas sur une analyse indépendante de toutes les lectures historiques. Sans avertissement/blocage, un partage peut rester absent du rapport. Le correctif ne reconstitue pas rétroactivement les événements manqués.
- Deux IP ne sont pas, à elles seules, une preuve de partage : déplacement, réseau mobile, changement d'adresse et usages explicitement autorisés doivent être considérés.
- `max_streams_per_ip` limite les lectures sur chaque IP ; `max_ips_per_user` limite le nombre d'IP. Un libellé « Same IP » n'ajoute aucune règle. Les règles choisies par l'administrateur sont seules déterminantes.
- Un abonnement sans plafond IP n'est pas automatiquement limité à une IP. L'héritage prévu par le contrôleur reste applicable ; un abonnement peut volontairement autoriser plusieurs lieux.
- Le score agrège des observations sur une période : il ne prouve pas que toutes les IP/appareils de cette période étaient simultanés. Les usages mobiles et navigateurs réduisent volontairement certains scores.
- Le rapport lit au plus 5 000 événements récents. Sur une instance très active, certains comptes peuvent être exclus de cette fenêtre. Les compteurs 7/30/90 jours et les preuves filtrées ne couvrent pas exactement le même périmètre.
- Pour plusieurs contextes serveur/fournisseur, le plafond agrégé est volontairement conservateur : la présence d'un contexte sans plafond neutralise les signaux fondés sur le seul nombre d'IP. Une analyse séparée par contexte serait plus précise.
- Les compteurs de blocages dédupliquent sur la clé de session seule ; des collisions entre serveurs ou des réutilisations peuvent sous-compter les incidents. Les identités externes non associées à un utilisateur VODUM et les comptes liés à plusieurs fournisseurs méritent aussi une vérification sur les données réelles.
- La courbe du tableau de bord représente l'historique des recommandations d'abonnement, pas l'historique exhaustif des partages détectés.

## Validation

82 tests ciblés passent dans 18 fichiers : contrôle des flux, règles et héritage, instantanés, stockage, terminaison Plex, monitoring, activation des tâches et Usage Risk.

11 tests nouveaux couvrent notamment les deux TV identiques sur deux IP, les appareils distincts sur une seule IP, TV/mobile, les identifiants Plex, l'expiration de la grâce et sa revérification, les règles administrateur personnalisées, la désactivation et les erreurs du tableau de bord.

Le scénario principal utilise une réponse XML Plex simulée, le vrai parseur, l'évaluation des règles, la construction de l'instantané, son enregistrement SQLite en mémoire et le calcul du rapport. Il produit un risque élevé avec une règle configurée à une IP. Aucun appel réseau réel n'est nécessaire.

Les sept premiers scénarios ont aussi été exécutés contre les trois modules d'origine : six échouaient avant correction. Certains tests préexistants de synchronisation génèrent des avertissements du journal Windows avec leurs horloges simulées proches de 1970 ; leurs assertions passent. La suite complète du dépôt n'a pas été exécutée.

## Vérifications restantes sur l'instance de production

Pour conclure sur la disparition réelle des alertes, relever en lecture seule :

- la version déployée et la date de mise à jour ;
- les réglages Usage Risk, la fenêtre d'analyse et les seuils ;
- les règles activées réellement appliquées aux utilisateurs concernés, leurs portées et dérogations ;
- l'état et la dernière exécution de `monitor_enqueue_refresh`, `media_jobs_worker`, `stream_enforcer` et, si souhaitée, `usage_risk_notifications` ;
- la fraîcheur des sessions, la présence des IP et le rattachement des comptes aux utilisateurs VODUM ;
- le volume mensuel d'événements avant/après le début de l'été et les erreurs de collecte/contrôle ;
- un échantillon de lectures réellement simultanées, en le confrontant aux règles configurées.

Une fois les correctifs déployés, contrôler avec un compte de test et ses propres plafonds que le dépassement génère bien l'événement attendu, puis son affichage. Les configurations multi-IP et les transitions légitimes doivent aussi être vérifiées.
