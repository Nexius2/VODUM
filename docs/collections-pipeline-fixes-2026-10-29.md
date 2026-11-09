# Corrections du pipeline Collections — 29 octobre 2026

Implémentation locale de la suite de l'[audit du pipeline](collections-pipeline-audit-2026-10-29.md).
Les changements n'ont pas été déployés sur l'instance distante pendant ce travail.

## Commandes de présentation indépendantes

Les changements de visibilité et de priorité disposent d'une file durable
`collection_controls` et d'un worker distinct. Leur enregistrement réveille ce
worker directement ; le scheduler reprend les commandes en attente après un
redémarrage et les échecs après temporisation.

Chaque commande porte une révision, un bail et un accusé d'application. Une
ancienne révision ne peut pas acquitter une commande plus récente. Un échec
partiel conserve la demande. Les appels Plex de cette voie passent avant les
requêtes de fond en attente, sans augmenter le débit global autorisé.

Le mode visibilité seule ne consulte pas les médias, ne modifie pas les membres,
ne charge pas les affiches et ne réordonne pas les collections voisines. Les
destinations inchangées ne provoquent pas d'écriture. Le traitement normal ne
réexécute pas ces commandes dans sa file de synchronisation.

L'édition pendant un passage actif accepte les changements de visibilité et de
priorité, ainsi que la désactivation des ajouts ARR, en conservant son bail et son
horaire. Les changements de sélection restent refusés. Les indications de
l'interface distinguent l'application des paramètres du travail de publication
des médias.

## Suppression des parcours répétés

La publication d'un objet ne déclenche plus un parcours HTTP des objets voisins.
Le réordonnancement des recommandations relève des commandes de priorité et de
la finalisation d'un lot de créations. Les objets vérifiés pendant une commande
sont réutilisés pour son réordonnancement ; les collections masquées ne sont pas
relues pour ordonner les recommandations visibles.

Les traitements relisent les paramètres de présentation actuels avant de les
appliquer. Un verrou court par objet protège cette étape entre le worker normal
et le worker de commandes dans le processus. Il ne bloque pas toute la population.
Les contrôles existants de propriété et de bibliothèque restent en place.

## ARR

L'autorisation est relue en base avant la recherche d'un titre et juste avant
l'appel d'ajout. Une désactivation intervenue pendant la recherche empêche
l'envoi et libère la réservation correspondante. Une requête déjà envoyée reste
une opération en vol ; aucune suppression de contenu ARR n'est effectuée.

## Reprises et inventaire local

Les entrées de publication sont enregistrées dans `collection_publication_plans`.
Quand la découverte et l'acquisition nécessaires sont achevées, un lot de reprise
conserve aussi le résultat et la signature des paramètres de sélection.

Une continuation de population ou de classement valide exécute ce plan sans
appeler le moteur de découverte ni charger l'inventaire entier. Elle reconstruit
seulement les identités des médias du plan. Le plan est invalidé lors d'un
changement de sélection, de génération ou de serveur, d'un inventaire périmé ou
en erreur, ou quand une nouvelle échéance planifiée est atteinte. Une acquisition
ARR encore inachevée garde son moteur et son curseur ; un plan ne doit pas la
sauter. Une graine de tri aléatoire est conservée avec les entrées de publication.

Le chargement général conserve l'inventaire JSON existant, mais ne construit
plus systématiquement un objet PlexAPI complet par média. Les identités légères
fournissent les champs nécessaires aux ajouts et déplacements ; les méthodes
complètes sont chargées à la demande. Les échecs de disponibilité des plateformes
sont temporisés cinq minutes afin de ne pas relancer immédiatement les mêmes
requêtes à chaque reprise.

Les diagnostics des passages incluent les compteurs de lectures et écritures,
le temps des requêtes de publication et l'attente dans le limiteur. Le compteur
concerne les requêtes de l'adaptateur après sa connexion initiale.

## Mesures et validation

Scénario synthétique reproductible, sans appel aux serveurs réels :

| Mesure | Audit initial | Après correction |
|---|---:|---:|
| Opérations distantes simulées de présentation pour 20 publications | 840 | 40 |
| Parcours global des recommandations pendant ces publications | 20 | 0 |
| Masquage de 20 objets, voie dédiée | 81 | 60 |
| Chargement local de 28 000 médias avec identités de publication | 3,34 s | 0,35 s |

Ces résultats décrivent le scénario local et les méthodes appelées, pas une
latence mesurée sur Plex. Les 60 opérations de masquage comprennent la validation
des 20 objets, la lecture des 20 recommandations et leur mise à jour. Une
recommandation déjà masquée ne nécessite pas sa réécriture.

Validation : suites Python des collections, du scheduler et de Plex ; huit
suites JavaScript des collections. Les régressions vérifient notamment les
révisions concurrentes, les baux, la reprise des échecs, les migrations
idempotentes, la désactivation ARR pendant une recherche, la priorité des
commandes dans le limiteur, l'absence de parcours global et la reprise d'un plan
sans moteur ni inventaire complet.

Après déploiement, mesurer séparément un changement Home sur un objet existant,
une publication complète et sa continuation. Les durées distantes restent à
confirmer sur cette instance.
