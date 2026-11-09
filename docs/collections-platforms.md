# By platform / Par plateforme

The secondary model creates one collection per selected platform and selected library.
The administrator chooses a country and any subset of Netflix, Prime Video, Disney+,
Apple TV+, Max, Paramount+ and Canal+. Regional availability is checked for movies
and/or series. Unavailable choices are disabled without losing the intended selection
when switching countries. Collection names include the country to distinguish catalogs.

Only media already present in the selected local library are classified. Availability
comes from JustWatch via TMDb's watch-provider endpoints, filtered by the selected
country and subscription (`flatrate`) offers. Rental, purchase and free offers do not
qualify. This classifies availability, not the studio that produced the work.
The default limit is unlimited. Optional Arr acquisition scans the selected regional
subscription catalogs, using the saved route for each library (Radarr for films,
Sonarr for series). Only titles absent from that library are submitted, by exact
TMDb/IMDb/TVDb identities. Unknown local identities are not treated as absence.
Existing Arr entries and previous confirmed requests are deduplicated. Preview
only plans requests. Catalog pages and acquisition offsets are persisted for
bounded runs and automatic continuation. Arr-only mode is supported as well.

Sources:
- https://developer.themoviedb.org/reference/movie-watch-providers
- https://developer.themoviedb.org/reference/tv-watch-providers
- https://developer.themoviedb.org/reference/watch-providers-movie-list
- https://developer.themoviedb.org/reference/watch-providers-tv-list

A shared TMDb API key is required. Successful availability responses are cached for
24 hours and shared across platform/country selections. IDs are resolved from local
TMDb, IMDb or TVDb metadata without title guessing. Large inventories are processed
within a time budget and resumed after successful progress. Unknown metadata keeps
existing members; complete metadata permits reconciliation. External collections
remain protected by ownership checks. Preview does not publish collections.

Posters are generated with `image_gen.imagegen`, stored in
`app/core/assets/collection_posters/platform-*-v1.png`; prompts are recorded in
`docs/platform-posters-v1-prompts.json`. They are original collection artwork,
not official platform posters.

Hidden gems, Returning shows and Rediscover are removed from the discovery choices.


## Disponibilité et nettoyage lors des reprises (29 octobre 2026)

La source utilisée par VODUM est l’API TMDb `/movie/{id}/watch/providers` ou `/tv/{id}/watch/providers`, alimentée par JustWatch. Ce n’est pas une lecture directe de la page catalogue JustWatch. Seules les offres `flatrate` du pays sélectionné sont acceptées ; les réponses par titre sont mises en cache 24 heures. Cela ne garantit pas une identité parfaite avec le catalogue web courant.

Une erreur sur un seul média rendait la passe partielle et bloquait toutes les suppressions. Les anciens membres pouvaient donc rester même après confirmation de leur indisponibilité. Les plateformes transmettent désormais les seuls identifiants non résolus ou différés : Plex et Jellyfin préservent ces membres s’ils étaient déjà dans la collection, mais retirent les membres dont l’absence a été confirmée. Un média inconnu ne devient pas un nouveau membre. Le nettoyage fonctionne également sans aucun résultat positif si certaines absences sont confirmées. Les autres modèles conservent leur politique de protection globale.

Contrôle visuel direct du 29 octobre : Plex affiche 3 090 médias dans Netflix · France. JustWatch affiche 6 359 films, triés par popularité, sur https://www.justwatch.com/fr/plateforme/netflix/films ; les premières positions diffèrent nettement de Plex. La page https://www.justwatch.com/fr/film/dhamaal-4 confirme toutefois une offre Netflix France lors du contrôle (mise à jour affichée : 29 octobre 2026, 17:08:52). Ce seul exemple ne valide pas les autres membres. Le nombre exact de membres obsolètes et l’équivalence complète entre TMDb et le catalogue JustWatch restent à établir sur les données de production.
