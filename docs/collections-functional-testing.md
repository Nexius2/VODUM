# Recette fonctionnelle Collections / Lists

État du 2026-11-20. Cette recette décrit les fonctionnalités implémentées ; elle
ne signifie pas que les scénarios ont été validés sur des serveurs réels.

## Quand commencer

Les listes personnalisées sont testables après déploiement groupé du code et
redémarrage (schéma additif). Pour le parcours officiel et la migration, configurer
la clé TMDB existante dans Collections, activer les tâches et `run_collections`,
puis ouvrir Lists → Catalogue officiel → Préparer / continuer.

Le worker reprend automatiquement les lots qui atteignent leur budget. Actualiser
le suivi pour voir le résultat. L'état « Préparé — contenu à examiner » permet de
passer à l'examen ; « Préparation incomplète » indique des identités/métadonnées
non résolues qui bloquent l'activation. Vérifier ces entrées et corriger les sources
si nécessaire, puis reprendre. Le brouillon embarqué n'est jamais activé seul.
La préparation utilise TMDB pour les métadonnées ; elle ne prouve pas automatiquement
la couverture éditoriale de toutes les anciennes listes externes.

Pour tester l'ensemble des parcours officiels ci-dessous, attendre ce premier état,
examiner les six listes présentées et confirmer la migration. Le plan doit être
éligible (pas d'instance occupée ni de collision). La confirmation ne publie pas
directement sur Plex/Jellyfin : elle demande les synchronisations des instances
activées, traitées par le worker suivant. Les états et l'historique sont à contrôler.

## Scénarios de recette

1. Ajouter un serveur et des bibliothèques de test, puis vérifier leur inventaire.
   Configurer Franchises avec les cibles souhaitées et contrôler le mode privé ou
   publié, Home, fréquence, priorité et ordre.
2. Créer une liste personnalisée. Rechercher/ajouter un film puis une série ;
   vérifier titre, année, type, affiche, identité et prévention des doublons.
3. Associer la liste à un groupe Franchises films/séries, et à un second groupe
   pour couvrir plusieurs serveurs, ou choisir directement plusieurs bibliothèques
   dans un même groupe Franchises (maximum 50, mêmes types autorisés). Réouvrir
   la configuration et vérifier la conservation de toutes les sélections.
   Prévisualiser : aucune collection créée.
4. Synchroniser. Vérifier une collection par liste et bibliothèque compatible,
   limitée aux médias présents ; une liste custom peut publier un titre unique.
   Vérifier une bibliothèque sans correspondance : pas de collection vide.
5. Retirer un ajout, modifier le nom et resynchroniser. Vérifier la mise à jour
   sans perte de propriété distante. Désactiver puis réactiver ; détacher puis
   rattacher : les objets distants doivent être conservés hors nettoyage explicite.
6. Supprimer une liste custom après confirmation. Vérifier conservation des objets
   distants et apparition des cibles conservées. Prévisualiser leur nettoyage,
   confirmer puis contrôler le résultat du worker, les refus et les reprises.
   Les fichiers médias et les collections voisines restent présents.
7. Préparer et examiner le catalogue officiel. Avant activation, relever les clés,
   identifiants distants et paramètres des six univers existants. Confirmer le
   périmètre, puis la migration ; ne pas changer simplement le statut du JSON.
8. Vérifier les six listes officielles, leurs associations et les publications
   historiques : mêmes identifiants/paramètres, seuil de deux titres, affiches
   d'univers et acquisitions Arr conservés. Exclure puis réintégrer un média
   officiel ; ajouter un média personnel puis contrôler le contenu effectif.
9. Détacher une liste officielle, redémarrer et réexécuter l'activation : elle ne
   doit pas être rattachée de nouveau. Répéter une migration identique et une mise
   à jour de catalogue préparé : aucune duplication ni perte de personnalisations.
10. Vérifier collisions de titre, serveur indisponible, erreur TMDB, interruption
    de worker et annulation d'un nettoyage pendant. Les identités incertaines ne
    doivent pas provoquer de retraits destructifs. Confirmer l'historique et les
    messages dans les cinq langues.
11. Contrôler une collection dynamique et Seasonal local/web/both : leurs règles,
    calendrier et publications existants restent fonctionnels. L'internalisation
    des composantes statiques de Seasonal n'est pas encore livrée.

## Limites et déploiement de ce lot

Nouveau schéma `collection_catalog_preparation`, créé par le bootstrap. Sauvegarder
la base, déployer ensemble workflow, revue, routes, worker, service de données,
fragment, traductions et tables.sql ; redémarrer avant toute ouverture de Lists.
Aucun service/worker supplémentaire, aucune clé supplémentaire, aucun lancement
d'instance locale imposé. Préparation en lots de 25 appels maximum et budget
coopératif de 60 secondes entre appels ; un appel déjà en cours peut durer selon
les timeouts 10/30 s. Les retries HTTP sont désactivés pour ce travail. Les erreurs
permanentes arrêtent la reprise automatique et laissent le détail visible.

L'activation reste explicite et protégée admin/CSRF, avec contrôle d'empreinte et
nouvelle vérification des conflits par la migration transactionnelle. Les déclarations
de revue portent sur le contenu présenté ; aucun formulaire juridique supplémentaire
n'est requis. Les anciennes données de revue restent lisibles. L'activation
n'atteste pas une validation en production.
