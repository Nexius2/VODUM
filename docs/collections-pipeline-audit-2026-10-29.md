# Audit du pipeline Collections — 29 octobre 2026

Suite de cet audit : [correctifs implémentés localement](collections-pipeline-fixes-2026-10-29.md).

## Conclusion

Le coût dominant identifié est l'orchestration et la multiplication des appels
Plex. Une requête locale sur 28 000 médias ne justifie pas des passages de dix
minutes. Les correctifs précédents sur le tri et la pagination ne suppriment pas
le recalcul global des recommandations effectué après chaque publication.

Cet audit ajoute des mesures et un scénario reproductible. Il ne constitue pas
une nouvelle optimisation du moteur ni un déploiement sur l'instance.

## État observé

L'interface affiche la version 26.10.28 b2230. Les logs montrent notamment :

- plateformes films : passage terminé à 10:12:07 en 624 secondes, 9 359 présents,
  zéro vérification différée, classement encore partiel ;
- plateformes séries : passage terminé à 10:27:15 en 315,9 secondes, 3 473 présents,
  zéro vérification différée, classement encore partiel ;
- modifications enregistrées entre 10:01 et 10:05 ; plusieurs configurations
  affichent ensuite leur fin de passage entre 10:13 et 10:22.

Le délai reste donc important après la fin de la première collecte externe.
La page affiche bien les paramètres « Collection off home » et « ARR disabled »
pour plusieurs configurations. Ces libellés décrivent les paramètres enregistrés,
pas un accusé d'application distant. Le compteur ARR 66 de Memoria provient du
dernier résultat affiché ; il ne prouve pas 66 nouveaux ajouts après désactivation.

Après actualisation de Plex, le navigateur demande de sélectionner un utilisateur.
L'état distant des recommandations n'a donc pas été confirmé par une vue fraîche.

## Mesures locales reproductibles

Commande : `python tools/benchmark_collections_pipeline.py` depuis la racine.
Le scénario utilise SQLite en mémoire, des données synthétiques et des objets
distants simulés. Il ne lit ni ne modifie les serveurs réels.

Première mesure sur cette machine, pour 28 000 films :

| Opération | Durée mesurée |
|---|---:|
| Lecture SQLite des lignes JSON | 0,0208 s |
| Décodage JSON | 0,2223 s |
| Filtre local par pays | 0,0061 s |
| Chargement complet avec reconstruction des objets PlexAPI | 3,3397 s |

Le dernier chemin n'ouvre aucune connexion. Ce sont des ordres de grandeur
locaux, pas des mesures du stockage ou du processeur de production.

Le scénario de publication de 20 objets déjà nommés et triés correctement compte
les opérations suivantes, avant même les modifications de membres ou de tri :

| Opération normalement distante | Nombre |
|---|---:|
| Revérifications des métadonnées des objets voisins | 380 |
| Lectures des recommandations | 420 |
| Écritures des destinations | 20 |
| Lectures des recommandations de la bibliothèque | 20 |
| Total | 840 |

Chaque opération correspond à un chemin HTTP du code de production. Le test
compte les appels aux méthodes, sans effectuer de requêtes HTTP. Avec la limite
actuelle d'une admission par seconde et par serveur, ce scénario représente un
plancher voisin de 14 minutes, hors attente dans la file, latence et appels
supplémentaires de validation. Ce n'est pas un comptage des appels de l'instance.

Le chemin séparé « masquer 20 objets » compte encore 81 opérations dans le même
scénario : 40 lectures de propriété, 20 lectures de recommandations, 20 écritures
et une lecture globale. Il évite le calcul des médias mais refait encore un
parcours de la bibliothèque.

## Causes identifiées dans le code

### 1. Recommandations recalculées après chaque objet

`PlexCollections.sync()` appelle `apply_visibility()`, qui appelle ensuite
`reorder_owned_collections()` quand une base est attachée à l'adaptateur.
Cette dernière méthode recharge les autres objets gérés et leurs recommandations.
Répéter cette opération pour N objets produit un coût quadratique. Même une
collection masquée reste vérifiée avant que sa visibilité soit testée.

L'écriture `updateVisibility()` est aussi envoyée sans comparer les destinations
actuelles aux destinations souhaitées.

### 2. Commandes administratives derrière le travail de fond

Les modifications de visibilité empruntent `run_collections`, dans le même
worker que l'inventaire. Le traitement utilise une liste initiale des candidats
et un ordre fondé sur la création, sans priorité spécifique pour la visibilité.
`wake_due_collections()` ne démarre pas une nouvelle exécution si la tâche tourne.

Une synchronisation déjà demandée est conservée lors d'une modification de
visibilité. Le worker applique alors la présentation au début de ce candidat,
puis poursuit son moteur complet. Le candidat peut lui-même attendre d'autres
configurations lentes. Le drapeau `priority_pending` ne préempte pas le travail
en cours.

### 3. Réglages et application distante insuffisamment distingués

Le traitement lit une configuration au début du passage. Le heartbeat vérifie
l'annulation et le bail, pas une révision de configuration. L'édition est par
ailleurs refusée pendant un bail actif. Il n'existe donc pas de commande rapide
garantissant qu'une désactivation ARR soit relue juste avant chaque nouvel ajout.

`priority_pending` est effacé après `run_visibility()` même si le résultat contient
des échecs d'objets sous forme d'avertissements. Un changement peut être considéré
traité sans avoir réussi sur chaque objet.

### 4. L'inventaire local est un snapshot partiel, pas toute la connaissance métier

La table locale contient des lignes JSON de médias. Chaque moteur recharge
l'ensemble de sa bibliothèque et reconstruit un objet PlexAPI par média avant
sa sélection. Les correspondances ne sont donc pas toutes des requêtes SQL
ciblées et indexées.

Les disponibilités régionales par plateforme ne sont pas fournies par cet
inventaire : elles viennent de TMDb, avec un cache de 24 heures. Le moteur fait
une recherche de cache par média. Les erreurs de chargement ne sont pas mises
en cache, donc des identités ou disponibilités inconnues peuvent être redemandées
à chaque reprise. Les 52 inconnus films et 36 inconnus séries observés rendent
ce point pertinent, sans prouver le nombre de requêtes effectivement envoyées.

Les recherches complètes de personnes et certains contrôles audio peuvent aussi
consulter le serveur. Le cache audio est invalidé à chaque génération d'inventaire.

### 5. Limite de débit et observabilité

`plex_rate_limit.py` impose une admission par seconde. Ce choix amplifie le coût
des appels redondants. Il faut d'abord supprimer ces appels puis mesurer une
politique de débit et une concurrence bornée par serveur ; augmenter le débit
seul laisserait le coût quadratique intact.

Les résultats actuels n'isolent pas le temps d'attente dans la file, le temps
de sélection locale, les défauts de cache, le nombre d'appels HTTP et l'attente
imposée par le limiteur. Un total « Publishing » ne permet pas de les distinguer.

## Ordre de refonte recommandé

1. **Commandes rapides séparées.** Enregistrer une révision des paramètres et
   faire passer les commandes de visibilité avant les travaux de population.
   Aucun calcul de sélection, collecte externe, poster ou tri de membres pour
   masquer une recommandation. Relire l'autorisation ARR avant chaque ajout.
   Conserver un état « demandé / appliqué / échec » et ne lever le drapeau
   d'attente qu'après confirmation de toutes les opérations ciblées.
2. **Un seul rapprochement des recommandations par bibliothèque et par lot.**
   Charger une fois leur état, vérifier les objets ciblés, appliquer seulement
   les différences et réordonner uniquement si la priorité a changé. Ne pas
   relire toute la bibliothèque après chaque collection. Préserver les contrôles
   de propriété et ne pas adopter des objets externes par leur seul nom.
3. **Plan local persistant.** Séparer découverte, sélection et publication.
   Stocker le résultat de sélection, sa génération, sa révision de configuration
   et les opérations restantes. Une reprise de publication exécute le plan,
   sans recommencer la découverte ni reconstruire tout l'inventaire.
4. **Données locales interrogeables.** Indexer les identifiants, pays, dates,
   personnes et informations audio utiles. Charger seulement les médias retenus
   et construire les objets PlexAPI à la demande. Matérialiser les offres TMDb
   par région avec rafraîchissement incrémental et temporisation des erreurs.
5. **Publication différentielle et mesurée.** Calculer les ajouts/retraits,
   conserver les lots d'appartenance, limiter les déplacements individuels,
   éviter les réécritures de métadonnées inchangées. Mesurer ensuite le débit
   supporté par chaque serveur.

## Critères de validation

- Une désactivation Home sur une collection ne dépend pas des 28 000 médias et
  n'exécute aucune découverte ni modification d'appartenance.
- Le nombre d'appels pour une petite modification dépend des objets modifiés,
  sans parcours HTTP de tous leurs voisins.
- Deux passages identiques ne produisent aucune écriture distante superflue.
- Une reprise ne refait ni collecte externe ni sélection si leurs entrées n'ont
  pas changé ; une nouvelle révision invalide le plan devenu obsolète.
- ARR désactivé bloque les nouveaux ajouts dès l'enregistrement de la commande.
- Le suivi expose séparément attente, sélection locale, collecte externe,
  lectures distantes, écritures et temporisation du limiteur.

Ces critères doivent être vérifiés avec un comptage d'appels et un chronométrage
sur l'instance ; le succès des tests fonctionnels ne suffit pas à valider le gain.
