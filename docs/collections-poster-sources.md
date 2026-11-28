# Affiches de franchises — compléments du 2026-11-21

## Hulu and Peacock posters — 2026-11-28

`app/core/assets/collection_posters/platform-hulu.png` and
`app/core/assets/collection_posters/platform-peacock.png` were generated with the
built-in ImageGen tool and visually checked. Both are portrait 1024 × 1536 PNGs,
shared by movie and series collections. Restart VODUM after updating; posters
are published on the next normal collection sync. No database migration.

Prompts:

```text
Create a premium cinematic streaming collection poster, portrait 2:3 1024x1536. Black background, fine gold border, antique gold cinema projector and reels in upper two thirds, sweeping luminous film strips with abstract cinema scenes, dramatic colored haze, polished realistic illustration. Match a coordinated luxury media library poster series. Dominant emerald green light, green film strips and reflections. Bottom quarter: huge crisp bold sans-serif exact text 'HULU' in luminous Hulu green, centered with generous margins. No other text or watermark. Full bleed.

Create a premium cinematic streaming collection poster, portrait 2:3 1024x1536. Black background, fine gold border, antique gold cinema projector and reels in upper two thirds, sweeping luminous film strips with abstract cinema scenes, dramatic colored haze, polished realistic illustration. Match a coordinated luxury media library poster series. Iridescent peacock palette: blue, cyan, purple, gold and green film strips and reflections. Bottom quarter: huge crisp bold sans-serif exact text 'PEACOCK' in white, centered with generous margins, six small colored dots beneath in yellow orange red purple blue green. No other text or watermark. Full bleed.
```


## Affiches des 23 listes supplémentaires

Les listes ajoutées le 2026-11-21 disposent de fichiers de collection dédiés
`universe-<clé>.png`, sélectionnés par l'allowlist existante au démarrage.
Les visuels créés avec ImageGen représentent l'univers de chaque franchise,
films et séries, avec un titre lisible et une composition cinématographique.
Les versions précédentes et le visuel générique sont conservés.

22 affiches actives sont des créations ImageGen depuis la refonte Jurassic du
2026-11-22. Les affiches Dune et Game of Thrones ont été régénérées le 2026-11-24.

`universe-jurassic.png` est une création ImageGen du 2026-11-22 : jungle
émeraude, T. rex, portail du parc, lumière ambrée et typographie dorée, au format
1024 × 1536. Elle remplace le visuel TMDB à fond de pierre pour harmoniser la
collection avec les autres franchises. Le JPEG v2 reste conservé comme archive
(source TMDB collection 328, image `jI2LDZAsDQP8iWSvt2zgT1YGspf.jpg`).

`tools/archive/collection_posters/universe-game_thrones-v2.jpg` est l’ancienne affiche de la série
[Game of Thrones, IMDb tt0944947](https://www.imdb.com/title/tt0944947/),
récupérée depuis son CDN d’images en format 500 pixels. Les deux propositions
ImageGen pour cet univers ont été refusées ; aucune méthode alternative de
génération par API/CLI n’a été utilisée.

| Liste | Fichier | Provenance |
| --- | --- | --- |
| Jurassic Park & Jurassic World | `universe-jurassic.png` | ImageGen, 2026-11-22 |
| Terminator | `universe-terminator.png` | ImageGen |
| The Matrix | `universe-matrix.png` | ImageGen |
| James Bond 007 | `universe-james_bond.png` | ImageGen |
| Mission: Impossible | `universe-mission_impossible.png` | ImageGen |
| The Conjuring Universe | `universe-conjuring.png` | ImageGen |
| Indiana Jones | `universe-indiana_jones.png` | ImageGen |
| Pirates of the Caribbean | `universe-pirates_caribbean.png` | ImageGen |
| Planet of the Apes | `universe-planet_apes.png` | ImageGen |
| Ghostbusters | `universe-ghostbusters.png` | ImageGen |
| Transformers | `universe-transformers.png` | ImageGen |
| Rocky & Creed | `universe-rocky_creed.png` | ImageGen |
| John Wick | `universe-john_wick.png` | ImageGen |
| Resident Evil | `universe-resident_evil.png` | ImageGen |
| Godzilla & Kong | `universe-godzilla_kong.png` | ImageGen |
| The Chronicles of Narnia | `universe-narnia.png` | ImageGen |
| Dune | `universe-dune.png` | ImageGen, 2026-11-24 |
| Shrek & Puss in Boots | `universe-shrek.png` | ImageGen |
| The Walking Dead Universe | `universe-walking_dead.png` | ImageGen |
| Game of Thrones Universe | `universe-game_thrones.png` | ImageGen, 2026-11-24 |
| Yellowstone Universe | `universe-yellowstone.png` | ImageGen |
| Doctor Who Universe | `universe-doctor_who.png` | ImageGen |
| Dragon Ball Universe | `universe-dragon_ball.png` | ImageGen |

La mise à jour des fichiers d'affiches nécessite un redémarrage de VODUM pour
recharger l'allowlist, puis la prochaine synchronisation des collections pour
republier les visuels dont le digest a changé. Aucune migration en base.

## Affiches actives Stargate et Terre du Milieu

- `universe-stargate.png` et `universe-middle_earth.png` : nouvelles affiches
  de collection générées avec ImageGen le 2026-11-21, dans une direction
  cinématographique cohérente avec Harry Potter / Fantastic Beasts.
- Les clés `universe_stargate` et `universe_middle_earth` pointent vers ces
  fichiers ; les anciennes affiches ci-dessous sont conservées pour historique.
- Les collections films et séries utilisent ces mêmes visuels. Le digest
  d’affiche existant déclenche leur remplacement à la prochaine synchronisation.

## Versions précédentes et affiche Harry Potter


- `universe-wizarding_world.png` : visuel de collection généré avec ImageGen,
  spécifique à Harry Potter et Fantastic Beasts, ajouté sans remplacer l'ancienne
  affiche `universe-wizard-v1.jpg`.
- `universe-middle-v1.jpg` : visuel Middle-earth Collection déjà présent dans le
  projet, anciennement associé à la clé `universe_middle_earth`.
- `universe-stargate-v1.jpg` : affiche du film *Stargate* (1994), identifiée par
  [IMDb tt0111282](https://www.imdb.com/title/tt0111282/) et téléchargée via son
  CDN d'images en miniature de 500 pixels. Elle servait de visuel spécifique de
  secours pour la franchise films/séries ; ce n'est pas une nouvelle création
  générée. Une des générations supplémentaires demandées à ImageGen a été
  refusée par le filtre de sortie ; aucun contournement n'a été utilisé.

Les fichiers sont dans `app/core/assets/collection_posters/`. Leur sélection
passe par l'allowlist de `app/core/collections_posters.py`. Le contrôle de digest
existant republie une affiche modifiée lors d'une synchronisation VODUM.

## Prompt Jurassic v3 — outil intégré ImageGen

Use case: stylized-concept. Create a finished portrait 2:3 collection poster for Jurassic Park & Jurassic World, matching an illustrated premium movie-universe poster series: rich emerald jungle, teal mist, dramatic amber sunlight, intricate cinematic painterly detail, thin subtle gold border, polished embossed gold serif title in the lower quarter. Scene: a majestic realistic Tyrannosaurus rex emerging above dense tropical foliage, ancient jungle park gates in the middle distance, volcanic island mountains and a few distant pterosaurs silhouetted in a luminous sky. Strong readable composition at thumbnail size, dramatic depth, saturated jewel colors, elegant adventurous mood. Exact title text: 'JURASSIC PARK' with '& JURASSIC WORLD' below in smaller gold type. Full bleed art with generous safe margins around lettering. Avoid a flat logo on cracked stone, avoid circular dinosaur emblem, avoid black empty background, avoid actors, credits, additional text, watermarks. Produce only the poster artwork.

Chaque affiche active a un seul fichier canonique, sans suffixe de version, dans `app/core/assets/collection_posters/`. Une nouvelle version remplace ce fichier ; Plex et Jellyfin la reçoivent au prochain passage grâce à la comparaison d'empreinte. Les anciennes versions citées ci-dessus (`universe-wizard-v1.jpg`, `universe-middle-v1.jpg`, `universe-stargate-v1.jpg`, etc.) sont conservées hors dépôt publié dans `tools/archive/collection_posters/` (ignoré par Git et par l'image Docker).

Le 2026-11-26, les affiches ImageGen du 2026-11-24 de Dune et de Game of Thrones sont devenues les fichiers canoniques `universe-dune.png` et `universe-game_thrones.png`. Les précédentes sont dans `tools/archive/collection_posters/` (`universe-dune-v2.png`, `universe-game_thrones-v2.jpg`).
