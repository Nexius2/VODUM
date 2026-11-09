# Par continent

Le modèle « Par continent », dans « More ways to discover », produit les collections **Africa**, **Americas**, **Asia**, **Europe** et **Oceania** dans la bibliothèque sélectionnée. Une configuration peut réunir une bibliothèque films et une bibliothèque séries ; les collections restent séparées sur leurs bibliothèques respectives.

## Médias et pays

Seuls les éléments présents dans l’inventaire local sont candidats. Aucun classement externe, catalogue de streaming, recherche de nouveautés ou ajout Arr n’est utilisé. Le mode Arr et son activation sont refusés côté serveur et masqués dans l’éditeur.

Le classement utilise les pays de production/origine, jamais la langue, la nationalité d’un acteur ou le pays où une offre de streaming est disponible. Les pays Plex et les ProductionLocations Jellyfin sont conservés dans les instantanés d’inventaire. Quand ces métadonnées manquent, la clé TMDb partagée peut compléter uniquement les éléments locaux identifiés par TMDb, IMDb ou TVDb. Les résolutions et pays obtenus sont mis en cache 30 jours ; les résolutions vides ne sont pas mises en cache.

Les pays et territoires sont regroupés selon Unicode CLDR / UN M49, dans `app/data/continent_countries.json`. La notice correspondante est `app/data/continent-countries-LICENSE.txt`. Les noms de pays français, anglais, allemands, espagnols et italiens sont reconnus. Les Amériques réunissent nord, centre, sud et Caraïbes. Les territoires sont associés à leur région géographique ; par exemple la Guyane française est dans les Amériques et La Réunion en Afrique. La Russie est en Europe et la Turquie en Asie selon cette classification.

Une coproduction peut apparaître dans plusieurs collections. Un pays inconnu n’est pas deviné : le média est ignoré avec avertissement et les membres déjà publiés restent conservés. Le premier complément de métadonnées est borné à deux minutes par bibliothèque ; les réponses déjà en cache restent utilisables après expiration de ce budget. Les éléments reportés sont comptés séparément des pays réellement inconnus. Lorsqu’un lot a obtenu de nouvelles métadonnées, un lancement de continuation est mis en file automatiquement et reprend au premier média reporté ; la progression s’arrête automatiquement si aucune nouvelle métadonnée n’a pu être obtenue, pour éviter une boucle de requêtes infructueuses. Réactualiser l’inventaire après déploiement permet de disposer immédiatement des pays déjà connus du serveur.

## Publication

Le modèle utilise les mêmes règles de propriété Plex/Jellyfin, de priorité, de visibilité, d’aperçu et de planification que les autres collections. Par défaut, tous les médias identifiés sont inclus ; une limite choisie dans le formulaire s’applique à chaque continent. Les continents sans média suivent le réglage commun de suppression des collections vides. L’aperçu ne publie pas et le nettoyage n’effectue aucune recherche de pays.

Les cinq affiches PNG portrait 1024 × 1536 ont été créées avec l’outil intégré imagegen et sont embarquées dans `app/core/assets/collection_posters/continent-<continent>-v1.png`. Les prompts sont conservés dans `continent-posters-v1-prompts.json`, dans le même dossier.

## Noms et conflits

La comparaison des noms est exacte : « Africa test » ne bloque pas « Africa ». Seules les collections de la section Plex sélectionnée sont prises en compte. En cas de conflit réel avec une collection externe, ce continent est ignoré et les autres continuent ; aucune collection externe n’est adoptée ou modifiée. Les diagnostics indiquent le titre exact, le serveur, la bibliothèque et les identifiants distants en conflit. Une collection déjà marquée avec l’identifiant exact de l’objet VODUM peut retrouver son lien distant si celui-ci a été perdu ; sa bibliothèque et sa propriété sont vérifiées avant toute mise à jour.
