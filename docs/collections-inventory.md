# Inventaire partagé des collections

La tâche `refresh_collection_inventory` parcourt les bibliothèques films et séries connues de tous les serveurs Plex et Jellyfin enregistrés dans VODUM. Les bibliothèques musicales ne concernent pas les moteurs de collections actuels. La tâche est créée activée au démarrage et son premier passage est immédiatement dû. Les réglages globaux du planificateur restent applicables.

Le passage mesure et enregistre la durée de chaque bibliothèque et la durée totale. Il est planifié par défaut **12 heures après sa fin**, y compris lorsqu’une partie des serveurs a échoué. Ce n’est pas un cron fixé à minuit et midi. Il ne lance pas de reprise automatique rapprochée en cas d’erreur. Un inventaire interrompu par le redémarrage de VODUM redevient immédiatement dû à la reprise du planificateur.

La tâche utilise le worker des collections, partagé et sériel avec `run_collections`, sans monopoliser le worker général de monitoring. Un inventaire déjà en attente passe avant les collections en attente. Aucun worker supplémentaire ni boucle de synchronisation indépendante n’est créé.

## Utilisation

Dans **Collections → Configuration**, l’inventaire indique l’état, le nombre de médias, la date du dernier inventaire complet et la durée de lecture par bibliothèque, ainsi que la dernière durée globale et la prochaine échéance. **Actualiser l’inventaire** déclenche une demande manuelle avec les mêmes protections que la tâche planifiée. Les données complètes sont stockées dans la base VODUM, jamais dans le navigateur.

Memoria et Sélection du moment utilisent cet inventaire par défaut. Ils ne relancent pas de scan distant lorsqu’il manque : une erreur demande d’exécuter la tâche d’inventaire. Le premier passage doit donc terminer avant la première création de collection. Les appels aux sources TMDb/Wikidata, les lectures des membres d’une collection distante et les publications restent nécessaires.

Les identifiants Plex sont extraits des nœuds XML `Guid` déjà reçus. La date, l’année, les titres et les crédits locaux disponibles sont conservés. Les objets Plex nécessaires à une publication sont reconstruits localement et n’ouvrent une connexion qu’à la première opération distante. Les recherches locales de personnalités ne parcourent plus le serveur. Les vérifications audio sont réalisées à la demande, puis partagées entre configurations jusqu’au renouvellement de l’inventaire. Les bibliothèques et les générations de données sont isolées.

## Cohérence et pannes

Chaque bibliothèque est publiée dans la base en une transaction après la fin de sa lecture réseau. Un échec ou une pagination détectée comme incomplète ne remplace pas la dernière copie complète. Les autres bibliothèques continuent à être traitées. Une bibliothèque indisponible ne met pas en échec les inventaires réussis des autres serveurs.

Un moteur refuse un inventaire absent, incohérent, dont la dernière lecture a échoué, dont le serveur ou la bibliothèque cible a changé, ou dont la dernière lecture complète date de plus de 36 heures. Il ne considère pas ces cas comme une bibliothèque vide et ne retire pas des membres sur cette base. Les nettoyages explicitement demandés et les expirations continuent d’utiliser les identifiants distants dont VODUM est propriétaire.

Le remplacement réussi d’une bibliothèque retire de l’inventaire les médias réellement absents de cette lecture complète et invalide les résultats audio de l’ancienne génération. Une interruption de transaction restaure les données précédentes. Les instantanés ne stockent pas les clés des serveurs et n’adoptent aucune collection externe.

## Validation

Les tests couvrent les lectures partagées sans connexion, les objets Plex reconstruits, les bibliothèques Jellyfin, la lecture locale par les deux moteurs, le cache audio, son invalidation, l’isolation des sources, la conservation après panne ou transaction interrompue, les réponses incomplètes, le premier passage, le délai calculé à la fin, les erreurs partielles et l’isolation du worker général. Les tests de bootstrap vérifient également la création des tables et de la tâche sur une base complète.


## Connexions et diagnostic

Pour les lectures Jellyfin, les adresses HTTP/HTTPS explicitement enregistrées sont essayées dans l’ordre de préférence. Une adresse qui répond est réutilisée pour les pages suivantes. Les contrôles de certificat restent actifs selon le réglage existant du serveur. Une erreur TLS n’est pas contournée. Une requête de modification dont la réponse est perdue n’est jamais rejouée automatiquement sur une autre adresse.

Après épuisement des adresses et une erreur de connexion, le passage marque les bibliothèques suivantes de ce serveur en échec sans répéter les appels réseau pour chacune. Les autres serveurs continuent. Les données complètes précédentes sont conservées. Un serveur effectivement inaccessible reste une erreur à résoudre dans sa connexion ; les bibliothèques réussies des autres serveurs restent utilisables même si l’état global de la tâche indique une erreur partielle.

Les messages d’erreur indiquent désormais le serveur, la bibliothèque, l’étape, le type d’exception et le statut HTTP éventuel. Les causes connexion, authentification, TLS, adresse invalide et base locale sont distinguées dans Configuration. Les messages bruts des fournisseurs, les URL et les clés ne sont pas ajoutés aux logs de diagnostic. La pile technique sans valeurs sensibles est visible au niveau Error.
