# Contrôle des collections du 26 octobre 2026

## Vérifications sur l’instance

VODUM 26.10.26 b0914 et Plex MovieEmpire ont été consultés dans leurs interfaces, avec la session administrateur autorisée par l’utilisateur. Un aperçu du top Inde a été lancé, sans publication ni acquisition. Les logs anonymisés fournis ont également été analysés.

* Top streaming Inde : limite de 10 candidats, 4 présents et 6 absents. Le classement agrège les tops des fournisseurs disponibles dans le marché indien ; ce n’est pas une sélection par pays de production. Le nombre affiché dans Plex correspond aux médias présents, pas aux candidats absents.
* Häxan / La Sorcellerie à travers les âges est explicitement sélectionné sous ce titre dans l’historique, via GuideDoc, Cultpix, Bloodstream et Brew. Il n’y a pas d’indication d’une confusion avec un titre récent. Un classement de streaming peut inclure des films anciens.
* Les variantes d’abonnement et chaînes revendeuses donnent plusieurs votes au même service (ex. Lionsgate Play, sa chaîne Apple TV et sa chaîne Amazon ; Plex, Plex Channel et Plex Player). Ce biais est corrigé dans le score, tout en conservant le détail des fournisseurs.
* Les six acquisitions absentes sont bloquées au contrôle des valeurs par défaut de Radarr multi. L’interface confirme que les demandes ne sont pas configurées. Aucun profil qualité n’a été choisi arbitrairement et aucun réglage Arr n’a été modifié.
* Plusieurs fournisseurs refusent les requêtes HTTP (403). Le repli JustWatch reste visible dans les avertissements. Un titre impossible à identifier faisait aussi abandonner les autres titres du fournisseur.
* Le top TMDb échoue dans la validation des identifiants après pagination ; des pages de popularité qui évoluent peuvent contenir le même titre. Les doublons entre pages sont désormais dédupliqués, avec conservation de la première position et lecture de pages supplémentaires. Des doublons à l’intérieur d’une même page restent invalides.
* IMDb refuse une réponse vide ou un statut différent de 200, mais son statut HTTP n’était pas conservé dans le diagnostic. Il est maintenant disponible, y compris pour le cas 202 couvert par le test. Cela ne rétablit pas à lui seul un accès refusé par IMDb.
* Famille : limite de 30, nouveautés, audio français obligatoire. L’ancien parcours vérifiait l’audio de tous les candidats avant le tri et la limite. Il trie désormais les candidats d’abord et s’arrête dès que la sélection vérifiée est complète.
* Saisons et Dernières sorties dépassent le délai au stade publication. PlexAPI retire chaque association individuellement et déplace chaque membre individuellement. Les grandes collections convergent maintenant sur plusieurs passages avec un budget de 120 secondes pour ces opérations et des avertissements de synchronisation/ordre restant à terminer. Le prochain passage relit les membres réels ; aucun fichier média n’est supprimé.
* Le top mondial séries rencontre un `BadRequest` lors de `addItems` (run 153). La trace ne permet pas d’attribuer le refus à un ID précis. Les ajouts sont maintenant limités à des lots de 100 ; un lot rejeté est isolé par membre, journalisé et ne provoque pas le retrait des anciens membres. La validation du cas réel reste à faire après déploiement.
* Les deux serveurs Jellyfin sont signalés hors ligne dans VODUM. Ces erreurs de connexion ne sont pas réparées par les modifications du moteur.

## Acquisition indépendante de la publication

Les acquisitions ont lieu après la publication. Les refus Arr par média sont désormais des avertissements dans le bilan de collection, comme les échecs de précontrôle. Les statuts des médias et les détails d’erreur restent disponibles, et les échecs sont journalisés. Cette règle s’applique au moteur partagé streaming/IMDb/TMDb/Kids/Awards/Seasonal et à Memoria. Les erreurs de source ou de publication restent des erreurs de collection.

## Déploiement et validation restante

Les corrections sont dans le dépôt local. L’utilisateur assure le déploiement Docker ; aucun remplacement du code distant n’a été effectué. Après déploiement, relancer d’abord les aperçus Inde, TMDb et Famille, puis une synchronisation des collections concernées. Les anciennes grosses collections peuvent nécessiter plusieurs passages pour terminer retraits et ordre. Les avertissements Arr n’empêchent pas ces publications.

La disponibilité des sites externes, les valeurs par défaut Arr et la remise en ligne des serveurs Jellyfin restent des points distincts à traiter. Le film de 1922 ne fait l’objet d’aucune exclusion arbitraire par âge.
