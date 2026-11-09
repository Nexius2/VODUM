# Collection visibility

Collection activation (`enabled`) controls scheduled collection work. Publication destinations are saved independently in `visibility`, with boolean `home`, `shared` (Friends’ Home), and `recommended` fields.

The common creation/edit wizard exposes these three choices for every model. New UI configurations start with all destinations off. An enabled collection with all destinations off remains a normal library collection and continues updating. Private and Arr-only modes do not promote collections.

Legacy configurations without `visibility` retain their previous behavior: published mode enables all three destinations; private and Arr modes enable none. No migration changes remote collections automatically.

Every Plex sync applies the destinations independently, including explicit false values to unpin an existing collection. A saved visibility change queues an owned-object-only visibility job. It does not scan the inventory, discover titles, change membership, request Arr acquisitions, or move the next scheduled run. Plex ownership checks remain mandatory.

Jellyfin does not expose equivalent promotion controls. Requested promotion returns the existing unsupported-home warning; choosing no promotion does not produce that warning.


## Priorité et groupes de collections

Une valeur plus petite place la configuration plus haut parmi les collections VODUM de la même bibliothèque. Ce n’est pas un numéro de ligne Plex : Memoria et Franchise peuvent créer plusieurs collections, qui restent regroupées sous la priorité de leur configuration. À priorité égale, un identifiant de configuration stable assure un tri déterministe ; les titres ordonnent les collections à l’intérieur du groupe.

Enregistrer une priorité différente met en file une tâche légère de visibilité, comme pour un changement de destination. Elle applique les métadonnées de tri et l’ordre des recommandations sans découvrir de titres, changer les membres ou soumettre de requête Arr ; la prochaine exécution planifiée reste inchangée.

Pour Plex, le titre de tri contient la priorité et l’identifiant du groupe, ce qui permet aussi de regrouper les franchises dans la grille Collections lorsque celle-ci est triée par titre. Les recommandations appartenant à VODUM sont ordonnées ensemble avant les autres rangées. Les hubs externes ne sont pas édités ni déplacés explicitement et conservent leur ordre relatif. Le périmètre est l’identifiant de bibliothèque VODUM, distinct du numéro de section Plex. Une synchronisation normale réconcilie aussi les collections VODUM existantes de la bibliothèque.

Jellyfin reçoit également le nom de tri contenant la priorité. La prise en charge des rangées d’accueil reste limitée comme auparavant.
