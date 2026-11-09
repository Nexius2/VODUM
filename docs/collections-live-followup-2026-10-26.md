# Deuxième contrôle VODUM / Plex — 26 octobre 2026

Contrôle de l’instance déployée `26.10.26 b1454`, des états des 13 configurations, des historiques et des erreurs récentes. Les chiffres ci-dessous distinguent les candidats sélectionnés des membres effectivement visibles dans Plex.

## Interface corrigée dans le dépôt

* Confirmation de suppression intégrée au thème Collections : fenêtre sombre, nom injecté comme texte, boutons Annuler/Supprimer, fermeture sans action par Échap, croix ou clic extérieur. Le focus initial est sur Annuler. Le formulaire `method=dialog` est exclu du chargeur de navigation et du boost HTMX. Les brouillons locaux utilisent la même confirmation, sans requête distante.
* Le lancement d’une synchronisation et la demande de suppression restent dans l’onglet courant. Seul l’aperçu conserve son ouverture de l’historique.
* Une publication avec des membres ou un ordre encore en attente s’affiche comme **Mise à jour partielle**, avec l’avertissement correspondant. Un compteur de sélection n’est pas une preuve que tous les anciens membres ont déjà été retirés de Plex.
* Le libellé d’aide du pays, momentanément affiché comme `country_hint`, est de nouveau inclus dans les traductions JavaScript.

## Résultats vérifiés

| Configuration | Contrôle |
|---|---|
| Famille | Publication précédente réussie, 30 membres visibles dans Plex ; l’ancien délai de sélection ne se reproduit plus. |
| Top Country Media Inde | 29 présents, 1 absent ; les 29 membres sont visibles dans Plex. |
| TMDb populaire | Aperçu : 250 candidats lus, 12 présents et 8 absents pour la limite de 20. Synchronisation réelle `174` réussie avec avertissement Arr. Les 12 films sont visibles dans Plex. |
| Top mondial | Aperçus puis synchronisations réelles `175` (séries) et `176` (films) terminés sans erreur de publication. Sélection : 15 séries présentes / 5 absentes et 4 films présents / 3 absents. Quatre ajouts Arr ont été effectués par les routes déjà configurées. Plex conserve aussi les anciens membres autorisés par la politique de conservation lors d’une source partielle ; la collection films affiche 8 membres. |
| Dernières sorties | Aperçu `168` terminé en 20 secondes, 30 sélectionnés. Publication `172` terminée sans erreur mais avec `membership_pending`. Trois médias restent sans langue originale vérifiable et sont exclus de la nouvelle sélection. Le retrait des anciens membres n’est pas achevé : 1376 membres encore observés dans Plex. |
| Saisons / Halloween | La configuration actuellement enregistrée demande **200** médias, pas 30 ni tous les médias. Publication `173` sélectionne 200 médias et termine sans erreur mais avec `membership_pending`. 2875 anciens membres sont encore observés dans Plex. |
| Récemment ajoutés / Kids / Spotlight / Asie | États réussis ou attendus ; compteurs Plex films : 20 récemment ajoutés, 3 Kids, 7 Spotlight, 20 Asie. Les affiches Family, Kids, Recently Added, Spotlight et les affiches streaming sont visibles. Les collections externes portant des noms proches sont conservées. |
| Memoria | Avertissements historiques de source/identification et d’acquisition, publication existante conservée. Pas de nouvelle suppression ou modification des collections externes d’hommage. |
| Streaming France | Configuration prête après modification, résultats historiques publiés visibles dans Plex. Des services utilisent le repli JustWatch quand la source directe échoue. |

## Retraits trop lents : correction supplémentaire

L’ancien chemin de PlexAPI effectue un retrait d’association par requête. Le limiteur global VODUM reste à une requête par seconde et par serveur, partagée avec le monitoring, ce qui laisse parfois seulement quelques dizaines de retraits par passage.

La correction locale utilise désormais l’[API officielle de modification des métadonnées Plex](https://developer.plex.tv/pms/) : retrait du seul tag `collection[].tag.tag-` sur une liste explicite d’identifiants, par lots de 100. Le code vérifie d’abord l’appartenance VODUM par UUID et la bibliothèque. Il ne remplace pas les autres tags et ne modifie pas leur verrouillage. L’encodage suit PlexAPI ; un nom contenant une virgule conserve le chemin individuel pour éviter toute ambiguïté. Un refus de modification par lots reprend sur les seuls lots restants, avec le même budget de temps.

Cette amélioration n’est **pas encore déployée** sur l’instance contrôlée. Après le prochain déploiement Docker, relancer Dernières sorties puis Saisons pour terminer les retraits et contrôler respectivement les limites 30 et 200. Aucun fichier média n’est supprimé par cette opération.

## Blocages externes et réglages restants

* **IMDb** : la source du serveur répond HTTP 202 sans classement exploitable, y compris les listes saisonnières. Le classement public s’affiche dans le navigateur : ce sont donc bien les requêtes du serveur VODUM qui restent bloquées. Aucun contournement ni classement de substitution n’a été mis en place.
* **FlixPatrol** : les six sources mondiales directes renvoient HTTP 403. Le repli TMDb vérifie la disponibilité streaming et publie une sélection partielle signalée comme telle.
* **Jellyfin** : les serveurs 6 et 7 sont inaccessibles lors du rafraîchissement des inventaires. Les anciennes copies sont préservées et le moteur ne les traite pas comme des bibliothèques vides. Le code ne peut pas remettre ces services en ligne.
* **Arr** : Radarr multi manque de valeurs par défaut enregistrées pour les demandes. Aucune qualité ni destination n’a été choisie arbitrairement. Les erreurs Arr restent des avertissements et ne bloquent pas la publication.
* Un échec ponctuel de rafraîchissement de l’indicateur des tâches apparaît aussi dans les logs du navigateur (`app.js:533`). La trace ne prouve pas une erreur dans la collection ; aucune cause réseau supplémentaire n’est inventée et cette erreur n’a pas été masquée.

Les sessions VODUM/Plex ont été laissées ouvertes. Le remplacement du code distant reste assuré par l’utilisateur via Docker.
