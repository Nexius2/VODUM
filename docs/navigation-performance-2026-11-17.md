# Audit de navigation — 17 novembre 2026

## Périmètre et méthode

Audit local du code et essais sur une base SQLite temporaire, sans connexion aux
serveurs de production. Les mesures HTTP utilisent le client Flask : elles
incluent les contrôles d’accès et le rendu, mais pas un trajet réseau réel.
Les temps répétés sont la médiane de trois requêtes après une première ouverture.
Les valeurs ci-dessous sont des observations locales, pas des objectifs garantis.

Premier jeu : 3 000 utilisateurs, 6 000 comptes média, 2 serveurs, 100 bibliothèques
et 300 000 relations d’accès. Les jeux avant/après ont les mêmes données synthétiques.
Second jeu : ajout de 100 000 lectures réparties sur les 29 derniers jours.
Les appels réseau externes sont bloqués dans les essais ; le scénario de découverte
Plex utilise séparément un délai et une panne simulés.

## Résultats et corrections

| Accès HTTP répété, premier jeu | Avant | Après |
| --- | ---: | ---: |
| Utilisateurs, tri par défaut | 369 ms | 18 ms |
| Utilisateurs, tri par nom | 360 ms | 19 ms |
| Utilisateurs, tri par nombre de bibliothèques | 366 ms | 102 ms |
| Serveurs, sans découverte réseau | 82 ms | 12 ms |

### Utilisateurs et serveurs

La [liste utilisateurs](../app/core/user_list_queries.py) ne joint plus tous les
accès pour compter les utilisateurs. Pour les tris sur un champ utilisateur, elle
sélectionne d’abord la page puis charge ses rôles et compteurs. Les tris portant
sur l’abonnement ou les compteurs continuent à considérer tous les candidats avant
pagination. Des sous-requêtes indexées séparent la recherche des rôles et le
comptage des accès, sans recalculer les rôles pour chaque bibliothèque.
Les priorités de statut, les valeurs absentes et la priorité Owner sur Admin
restent celles de l’ancien comportement.

Les [compteurs serveurs](../app/core/server_page_queries.py) sont calculés
indépendamment : les bibliothèques et comptes média ne sont plus multipliés
par une jointure croisée avant leur décompte distinct.

La [page Serveurs](../app/routes/servers.py) ne récupère plus de jeton et ne lance
plus de découverte Plex avant son premier rendu. Un fragment HTMX protégé charge
les suggestions ensuite. Une panne propose une relance ; les jetons restent côté
serveur et les formulaires de sélection conservent leur protection CSRF.

### Blocages communs à toutes les pages

Le [contrôle d’accès](../app/core/global_access_guard.py) lisait les réglages
d’authentification même pour les CSS, les scripts et `/health`. Ces routes étaient
déjà publiques ; elles sont maintenant reconnues avant la lecture de la base,
après le contrôle IP. Aucun accès protégé n’est ajouté à cette exception.

Avec le verrou Python de la connexion partagée volontairement occupé 400 ms,
la première réponse CSS est passée de 453 à 52 ms dans l’essai local. Le test de
non-régression vérifie aussi que les routes publiques ne lisent aucun réglage
d’authentification. Ce changement ne supprime pas une éventuelle attente dans
la file du serveur HTTP si tous ses workers sont déjà occupés.

Les réglages d’authentification et les [sessions admin](../app/core/admin_sessions.py)
sont lus par des connexions de lecture isolées, sans cache d’autorisation.
Chaque requête protégée continue à vérifier l’état actuel de la session ; une
révocation est visible dès la lecture suivante. Le renouvellement périodique de
session conserve sa voie d’écriture. Ces ouvertures de connexion ajoutent quelques
millisecondes aux petites pages dans ce test, mais évitent leur attente derrière
un calcul sur la connexion partagée. Le modèle transactionnel général ne change pas.

La copie défensive des résultats du [cache d’agrégats](../app/core/aggregate_cache.py)
se fait hors de son verrou global. Copier un gros rapport ne bloque donc plus les
lectures de clés indépendantes. Les résultats stockés restent immuables pour leurs
appelants et les calculs simultanés d’une même clé restent regroupés.

### Premier affichage du monitoring

Sur le second jeu, l’aperçu du monitoring demandait environ 2 703 ms à cache froid,
contre 21–22 ms avec les agrégats déjà présents. Les classements historiques
retardaient le premier document et sa navigation.

L’[aperçu](../app/routes/monitoring_overview.py) affiche désormais sa structure,
les serveurs et les compteurs live avant de demander ses statistiques historiques
par HTMX. Le navigateur local a rendu la structure en 94 ms ; les statistiques
étaient complètes après environ 3 004 ms. Le temps de calcul historique n’est donc
pas annoncé comme supprimé. Les chargements sont signalés explicitement, sans
présenter des zéros comme résultats définitifs. L’actualisation périodique reste
active et une relance manuelle est disponible. Les variantes page/fragment portent
`Vary: HX-Request` et `Cache-Control: no-store`.

Autres observations sur ce jeu : historique 24–25 ms en chargement répété,
monitoring utilisateurs 279–289 ms, bibliothèques 43–45 ms et fiche utilisateur
20–21 ms. Les calculs de classement à froid et l’onglet utilisateurs du monitoring
restent des pistes de travail si les captures de l’instance réelle les confirment.

## Vérifications

- Non-régression des rôles, compteurs, regroupements de statut, recherches,
  filtres vides, pagination et lectures concurrentes dans
  `tests/test_navigation_performance_regressions.py`.
- Comparaison locale de 168 combinaisons tri/sens/recherche/page avec la route
  précédant les changements : mêmes lignes et mêmes totaux.
- Tests du contrôle d’accès, des sessions admin, du cache concurrent et de la
  découverte Plex ; scénario de routes réel avec bootstrap, rendu différé,
  variantes HTMX, panne de découverte et refus des accès non authentifiés.
- Essai navigateur avec vraie exécution HTMX : page Serveurs disponible avant la
  fin de la découverte, panne puis relance réussie, sélection et champ CSRF présent,
  aperçu du monitoring chargé ensuite ; aucune exception JavaScript observée.
- Deux fixtures devenues obsolètes ont été actualisées : le monitoring utilisateurs
  nécessite l’identifiant d’historique, et le test du monitoring personnel appelle
  son constructeur public, désormais séparé du lecteur isolé. Les 36 tests de
  lectures isolées et les 6 tests du monitoring utilisateurs passent ensuite.
- Au total, 102 tests ciblés passent dans les suites exécutées séparément ; cette
  vérification ne prétend pas couvrir l’intégralité des tests du dépôt.

## Déploiement et limites

Aucune migration et aucun nouvel index. Déployer ensemble le code Python et les
templates, puis redémarrer le processus applicatif. Aucun changement d’INFO ou
annonce de validation en production pour cet audit.

Les attentes réseau Plex, l’attente de workers HTTP saturés, le stockage et les
volumes réels peuvent différer des essais locaux. Pour une mesure sur l’instance,
utiliser les journaux `route_timing` existants et le
[rapport de temps](../app/route_timing_report.py), notamment `--by-view`, avec les
mesures optionnelles SQLite, fournisseurs et file Waitress. Comparer avant/après
sur les mêmes écrans et volumes, sans assimiler les chiffres de ce rapport à des
mesures de production.
