# Collection posters

Le catalogue Franchise contient désormais cinq affiches PNG originales : DC Universe,
Alien & Predator, Fast & Furious, Marvel Cinematic Universe et Star Trek.
Elles correspondent à `app/data/franchise_universes.json` et remplacent les anciennes
affiches des anciens univers. Voir `collections-franchises.md` pour la migration.

Audit du 27 octobre 2026 : les 14 modèles actifs sont couverts. Les 56 posters
préexistants sont complétés par `memoria-v1.png` et `franchises-v1.png` (58 au total).
Memoria conserve les portraits TMDb et Franchises les affiches TMDb ; lorsque le
chemin de cette image est absent ou invalide, le poster générique est proposé par
le mécanisme commun, qui préserve les images personnalisées existantes.
Un échec réseau sur une image TMDb valide conserve le comportement actuel et
produit un avertissement. Les nouveaux fichiers seront publiés après déploiement,
lors de la prochaine synchronisation normale ; aucun serveur distant n'a été
modifié par cet audit local.

Les deux images ont été créées avec l'outil intégré imagegen, en format portrait
1024 × 1536. Prompts utilisés :

```text
Use case: stylized-concept. Create a polished portrait 2:3 cinematic collection poster, 1024x1536. Match a premium media library poster series: deep midnight navy textured background, luminous gold cinematic illustration in upper two thirds, huge clean bold ivory uppercase sans-serif title in bottom third. Theme: respectful remembrance of cinema artists, an empty velvet director chair illuminated by a warm golden spotlight, elegant floating dust and a subtle film reel, quiet dignified atmosphere. Exact text: "MEMORIA". No other text, no people, no watermark. Full bleed.

Use case: stylized-concept. Create a polished portrait 2:3 cinematic collection poster, 1024x1536. Match a premium media library poster series: deep midnight navy textured background, luminous gold and amber cinematic illustration in upper two thirds, huge clean bold ivory uppercase sans-serif title in bottom third. Theme: cinema franchises and sagas, three elegant film reels connected by flowing film strips forming a coherent sweeping arc, luminous screen portals suggesting adventure and continuing stories, sophisticated theatrical lighting. Exact text: "FRANCHISES". Fit the full word with generous side margins. No other text, no recognizable characters, no logos, no watermark. Full bleed.
```

All four TMDb charts have distinct bundled `tmdb-<chart>-v1.png` posters:
popular_movies, popular_series, top_movies and top_series. The TMDb runner
passes the selected chart's poster key to normal publication. Existing
collections with generated mosaics receive it on their next successful sync;
custom posters are preserved. Preview and Arr-only runs do not upload posters.

Top streaming country uses the bundled poster `app/core/assets/collection_posters/top-streaming-country-v1.png`. It is shared across countries and movie/series libraries; the collection title retains the country and presentation-language information.

The streaming-country engine passes an allowlisted artwork key to publication. Plex uploads the local file if no manually selected poster exists (generated composites do not block it). Jellyfin uploads base64 PNG bytes when the collection has no Primary image tag. No public image-hosting URL is required. Existing custom artwork is preserved and upload failures become `collections.poster_failed` warnings.

New and existing VODUM-owned collections receive missing artwork during their next normal synchronization. Preview, visibility-only and Arr-only runs do not upload artwork. Country, worldwide and continental streaming collections receive this fallback; other collection posters are unchanged. Worldwide uses a purple/gold globe; Africa amber, Americas coral, Asia ruby, Europe ice blue and Oceania emerald, each with a separate bundled PNG and region label. The configured region selects the poster for both movie and series collections.


In the Spotlight uses `spotlight-v1.png` (gold spotlight and popcorn). Latest releases by country uses `latest-releases-country-v1.png` (mint clapperboard/calendar), shared across country and movie/series variants. Both use the same missing-artwork-only upload path. Spotlight also passes its poster during the final synchronization when membership has not changed. Existing custom posters remain untouched. Assets are bundled in the code; remote libraries receive them after deployment during their next successful normal synchronization.


All 20 Seasonal events have their own `seasonal-<event>-v1.png` poster. The Seasonal orchestrator passes an explicit poster key for each active event to the shared publication engine, keeping concurrent events separate. This works with web, local and mixed selection sources and reuses the same custom-artwork preservation and upload warnings. Previews and expired-event cleanup do not upload images. The posters contain English theme labels; collection names still follow the configured presentation language.


All 11 IMDb charts have distinct bundled posters, named imdb-<chart>-v1.png. The IMDb runner passes the chosen chart poster explicitly to the shared publication engine. Posters contain English chart labels; collection names remain localized. Existing custom artwork, preview behavior and cleanup safeguards remain unchanged.


Kids, Family and Recently added now have distinct bundled default posters, connected to their normal synchronization paths. Kids Top and Top latest share the Kids poster. All three posters deliberately omit movie/series wording, so each can be used by separate movie and TV library collections. Existing custom posters remain preserved; preview and cleanup do not upload them.

Top Country Media has two bundled defaults: `top-country-most-popular-v1.png` for `country_chart=popular`, and `top-country-top-rated-v1.png` for `country_chart=top`. The common resolver passes the selected poster to Plex/Jellyfin during normal synchronization. Both avoid country flags and movie/series labels, so they work for every supported country and library type. Generation prompts and integration details are in `collections-top-country-posters.md`.
