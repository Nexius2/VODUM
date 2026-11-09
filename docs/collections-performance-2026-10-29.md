# Reprises longues des collections — 29 octobre 2026

## Diagnostic observé sur VODUM 26.10.28 b2230

La configuration plateformes des films a enchaîné des passages de 12 à 15
minutes, plutôt qu'une seule exécution bloquée toute la nuit. La bibliothèque
comptait environ 28 000 films. Le nombre de vérifications différées est passé
de 27 147 le 28 octobre à zéro le 29 octobre au matin. Les publications et
classements restaient ensuite partiels, avec plusieurs délais globaux dépassés.

L'API Collections renvoyait environ 19 Mo à chaque actualisation. L'historique
a pu être affiché lors du second contrôle ; le message d'erreur JavaScript
initial ne permet pas, à lui seul, d'identifier une exception persistante.

## Corrections locales

- Les curseurs d'analyse des plateformes et continents ne changent plus l'ordre
  de publication. Le classement conserve l'ordre stable de l'inventaire.
- Pendant une analyse encore différée, les appartenances sont publiées mais le
  classement personnalisé attend la fin de la découverte. Les données inconnues
  isolées n'empêchent pas ce classement final.
- Le classement conserve la plus longue sous-séquence déjà ordonnée. Une
  rotation d'une collection de 200 titres peut ainsi être réparée en un seul
  déplacement. Les membres préservés lors d'une analyse partielle restent présents.
- Le mode de tri Plex est établi avant la lecture de l'ordre et n'est pas réécrit
  lorsqu'il est déjà correct. La lecture utilise des pages de 1 000 membres, au
  lieu des pages de 100 par défaut. Le budget de mutation commence après cette
  lecture, sous réserve du délai global inchangé.
- Le renouvellement du bail est écrit au maximum toutes les 30 secondes. Les
  vérifications d'annulation et de délai restent effectuées à chaque heartbeat.
- L'interface utilise une réponse compacte : les 100 exécutions ne renvoient plus
  leurs listes de médias répétées. Les cartes conservent leurs totaux et cinq
  médias ; les listes complètes sont chargées à l'ouverture des détails, puis
  réutilisées tant que la publication n'a pas changé.
- La dernière publication de chaque objet est sélectionnée directement en base,
  y compris hors de la fenêtre des 100 exécutions récentes. Un objet jamais
  publié ne provoque plus la relecture de tout l'historique de ses voisins.
- Une collection en attente n'affiche plus la phase terminée de son ancien passage.

## Validation et limites

539 tests Python `test_collection*.py` réussis. Les suites JavaScript
`test_collection*.js` passent, notamment le chargement différé, les compteurs,
les états partiels, les sources dépliées et les interactions d'édition.
Le cas d'essai de dix passages contenant chacun 1 000 médias produit une réponse
compacte inférieure à 20 Ko, avec accès séparé aux 1 000 médias complets.

Les contrôles couvrent aussi les curseurs repris, les permutations d'ordre,
la pagination Plex, le budget après lecture et le renouvellement du bail.

Ces corrections ne sont pas déployées sur l'instance distante. Après
déploiement, mesurer le premier passage et la reprise suivante des plateformes,
continents et IMDb, puis vérifier que les avertissements de classement finissent
par disparaître. La première collecte de disponibilités reste dépendante des
services externes et de la taille de la bibliothèque. Les délais réseau et les
collisions avec des collections non gérées ne sont pas contournés.
