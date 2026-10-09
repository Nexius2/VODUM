# Optimisations du 6 octobre 2026

Trois changements locaux, sans déploiement ni accès à la base de production :

- Cache des agrégats : une seule exécution par clé lors de requêtes simultanées ; les autres requêtes attendent le résultat. Les clés différentes restent indépendantes. Le TTL commence à la fin du calcul. Les résultats restent copiés pour éviter les mutations partagées. Le cache reste propre à chaque processus.
- DBManager.query_one : fetchone remplace le chargement de toutes les lignes ; verrouillage et déchiffrement des données de serveur sont conservés. Cela évite aussi le déchiffrement des lignes inutilisées.
- Deux index d'expression SQLite pour les filtres existants sur datetime(created_at) des actions et datetime(stopped_at) de l'historique. Ajout au schéma initial et au bootstrap des bases existantes. Les nouveaux index occupent de l'espace et ajoutent un coût aux écritures ; leur construction est faite au démarrage suivant avec cette version.

## Mesures

Base SQLite temporaire en mémoire avec 200 000 événements, dont 1 000 récents. Médiane de sept exécutions locales : filtre de dates 18,761 ms avant index, 0,023 ms après. Lecture de la première ligne sur une sélection de 200 000 lignes : 106,1 ms avec query + fetchall, 0,002 ms avec query_one + fetchone. Ces mesures isolent les opérations et ne prédisent pas le temps de chargement des pages en production. Les requêtes qui ont déjà LIMIT 1 n'obtiennent pas ce dernier gain.

## Validation

67 tests passent dans le groupe élargi (cache concurrent, accès SQL, dashboard, monitoring, migrations, secrets, contrôleur de streams). Deux contrôles statiques supplémentaires échouent sur des fichiers non modifiés par cette intervention : la règle d'usine unique de connexions vise diagnose_stream_policies.py ; la règle d'interpolation SQL vise le littéral JSON '{}' de db_bootstrap_activation.py. Le second signalement porte sur un littéral SQL voulu, pas sur une interpolation manquante.

Huit demandes concurrentes pour un même agrégat déclenchent un seul loader. Le test vérifie aussi qu'une autre clé peut être calculée pendant cette attente. La durée de calcul ne consomme plus le TTL. Le retry après erreur, l'indépendance des résultats, le déchiffrement de query_one et l'utilisation des index par EXPLAIN QUERY PLAN sont vérifiés.

## Limites et prochaines investigations

Pas de mesures CPU, disque, mémoire, taille d'historique ou temps de réponse sur l'instance. La cause principale des lenteurs ressenties reste à établir. Le premier calcul d'un agrégat demeure synchrone ; plusieurs processus peuvent encore calculer le même agrégat. Le verrou de connexion SQLite unique reste partagé entre pages et tâches de fond. Les attentes du contrôleur de streams retardent les autres tâches sur son worker, sans bloquer directement toutes les requêtes HTTP pendant le sleep. Aucune règle de kill n'a été modifiée.
