# Seasonal : une collection par événement

Le modèle Seasonal est réservé aux **bibliothèques de films** Plex/Jellyfin.
L'API refuse une bibliothèque séries. Une configuration choisit un pays, une
langue de présentation, plusieurs événements, leur source de médias et une
priorité de base. Chaque événement actif crée sa propre collection appartenant
à VODUM, avec un nom traduit et son icône : Halloween 🎃, Noël 🎅, Pâques 🐰, etc.

## Calendrier et cycle de vie

Le formulaire affiche pour chaque événement sa prochaine date et sa fenêtre
d'affichage, calculées côté serveur dans le fuseau horaire global VODUM.
Les événements non définis pour le pays sont désactivés. Il n'est pas fait
d'hypothèse américaine par défaut pour une fête nationale absente.

Les événements proposés reprennent les 19 thèmes du catalogue saisonnier,
avec l'été ajouté par VODUM. Les dates locales et certaines fenêtres sont des
adaptations VODUM, et non une copie du calendrier américain :

- Fête nationale : France le 14 juillet, États-Unis le 4 juillet, Canada le
  1er juillet, Belgique le 21 juillet, Suisse le 1er août, Allemagne le
  3 octobre, Espagne le 12 octobre et Italie le 2 juin. Aucune date nationale
  unique n'est imposée au Royaume-Uni.
- Pâques est recalculé chaque année selon le calendrier occidental. Les fêtes
  des mères/pères suivent les conventions du pays ; en France, une fête des
  mères coïncidant avec Pentecôte est reportée au premier dimanche de juin.
- Thanksgiving : quatrième jeudi de novembre aux États-Unis, deuxième lundi
  d'octobre au Canada ; non proposé pour les autres pays.
- Noël et Halloween occupent respectivement décembre et octobre ; le Nouvel An
  couvre le 26 décembre au 4 janvier de l'année suivante. Les mois culturels
  suivent les thèmes du catalogue ; Black History Month est placé en octobre au
  Royaume-Uni et en février ailleurs. L'été est la fenêtre météorologique de
  l'hémisphère Nord, du 1er juin au 31 août.

Ce calendrier de collections utilise les dates de célébration et non les
reports administratifs des jours fériés. Des traditions régionales, religieuses
ou familiales peuvent avoir d'autres dates ; les périodes retenues sont visibles
dans le formulaire avant enregistrement.

Les mises à jour sont quotidiennes par défaut. La fréquence est configurable,
y compris mensuellement (le 1er du mois, selon le fuseau de VODUM). Une collection est créée/actualisée lors
de la synchronisation dans sa période d'affichage et retirée après celle-ci.
Le journal `collection_seasonal_windows` enregistre l'échéance avant toute
publication, afin que le worker puisse aussi réveiller un nettoyage à échéance.
La suppression d'une fête dans la configuration retire sa collection à la
synchronisation suivante. Désactiver/supprimer la configuration retire ses
collections. **Aucun fichier média n'est supprimé.**

## Trois modes de sélection

| Mode | Sélection | Arr |
| --- | --- | --- |
| Listes web | Listes thématiques publiques | Facultatif pour les films manquants |
| Bibliothèque uniquement | Genres, labels, titres et résumés locaux | Aucun |
| Les deux | Union des listes web et de la sélection locale | Uniquement pour les titres web manquants |

Le mode local ne requiert ni clé TMDb ni accès aux listes web. Il réutilise
l'inventaire partagé. Les nouvelles métadonnées de thème sont récupérées au
prochain inventaire ; un inventaire antérieur est signalé comme incomplet et
ne justifie pas le retrait des membres existants. Pour une sélection manuelle
explicite, un label/tag `seasonal:halloween`, `seasonal:christmas`, etc. permet
d'associer un film à l'événement. Une fête nationale peut être ciblée avec
`seasonal:independence:FR`, par exemple. La détection automatique reste une
heuristique thématique, pas une reproduction des listes web.

Le mode web utilise les références de `app/data/seasonal_sources.json` : listes IMDb, collections et films TMDb, listes MDBList et Letterboxd. L'été utilise les thèmes `summer vacation` et `summer camp`. Les listes Independence Day sont américaines et ne s'appliquent qu'aux États-Unis ; les autres fêtes nationales disposent de leurs propres thèmes.

La provenance des données est conservée dans `docs/third-party/collection-sources-provenance.json`. Les notices MIT sont fournies dans `app/data/seasonal-sources-LICENSE.txt` et `docs/third-party/seasonal-sources-LICENSE.txt`.

## Classement et échecs

Par défaut, l'ordre aléatoire est stable au cours d'une même journée locale,
pour un événement et une configuration donnés. Le tri par date de sortie ou
popularité reste possible. La limite s'applique par événement. Les événements
simultanés occupent des positions successives à partir de la priorité de base.

Une liste refusée/incomplète n'est pas considérée comme une liste vide valide.
IMDb peut notamment répondre HTTP 202 sans contenu, ce qui est signalé comme
un échec. Les sources refusées ne sont pas contournées. Une source en échec
produit une erreur dans les logs VODUM ; les autres sources continuent et les
anciens membres restent conservés lors d'une sélection partielle. Un événement
en échec n'empêche pas les autres événements d'être traités. Le nettoyage hors
période ne dépend ni des listes web ni de TMDb.

Les aperçus ne publient rien et ne demandent aucun téléchargement réel. Les
protections de propriété, délais, annulation et acquisitions Arr sont ceux du
moteur commun des collections.

## Références des règles de calendrier

- [Élysée : fête nationale du 14 juillet](https://www.elysee.fr/la-presidence/la-fete-nationale-du-14-juillet)
- [USAGov : dates des fêtes américaines](https://www.usa.gov/holidays)
- [Canada : dates des jours fériés](https://www.canada.ca/en/library-archives/services/public/visit/holiday-closures.html)
- [Légifrance : règle française de la fête des mères](https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000006905391)
- [English Heritage : Mothering Sunday](https://www.english-heritage.org.uk/visit/familydaysout/mothers-day/)

## Latest releases by country

Ce modèle reste distinct de Seasonal : uniquement les médias des bibliothèques,
aucun Arr. Son formulaire et ses récapitulatifs masquent le sélecteur et les
mentions Arr ; l'étape correspondante s'appelle simplement « Publication ».
