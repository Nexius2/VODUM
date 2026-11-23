# Affiches de franchises — compléments du 2026-11-21

## Affiches des 23 listes supplémentaires

Les listes ajoutées le 2026-11-21 disposent de fichiers de collection dédiés
`universe-<clé>-v2.png`, sélectionnés par l'allowlist existante au démarrage.
Les visuels créés avec ImageGen représentent l'univers de chaque franchise,
films et séries, avec un titre lisible et une composition cinématographique.
Les versions précédentes et le visuel générique sont conservés.

22 affiches actives sont des créations ImageGen depuis la refonte Jurassic du
2026-11-22. Game of Thrones conserve une affiche existante après refus de génération.

`universe-jurassic-v3.png` est une création ImageGen du 2026-11-22 : jungle
émeraude, T. rex, portail du parc, lumière ambrée et typographie dorée, au format
1024 × 1536. Elle remplace le visuel TMDB à fond de pierre pour harmoniser la
collection avec les autres franchises. Le JPEG v2 reste conservé comme archive
(source TMDB collection 328, image `jI2LDZAsDQP8iWSvt2zgT1YGspf.jpg`).

`universe-game_thrones-v2.jpg` est l’affiche de la série
[Game of Thrones, IMDb tt0944947](https://www.imdb.com/title/tt0944947/),
récupérée depuis son CDN d’images en format 500 pixels. Les deux propositions
ImageGen pour cet univers ont été refusées ; aucune méthode alternative de
génération par API/CLI n’a été utilisée.

| Liste | Fichier | Provenance |
| --- | --- | --- |
| Jurassic Park & Jurassic World | `universe-jurassic-v3.png` | ImageGen, 2026-11-22 |
| Terminator | `universe-terminator-v2.png` | ImageGen |
| The Matrix | `universe-matrix-v2.png` | ImageGen |
| James Bond 007 | `universe-james_bond-v2.png` | ImageGen |
| Mission: Impossible | `universe-mission_impossible-v2.png` | ImageGen |
| The Conjuring Universe | `universe-conjuring-v2.png` | ImageGen |
| Indiana Jones | `universe-indiana_jones-v2.png` | ImageGen |
| Pirates of the Caribbean | `universe-pirates_caribbean-v2.png` | ImageGen |
| Planet of the Apes | `universe-planet_apes-v2.png` | ImageGen |
| Ghostbusters | `universe-ghostbusters-v2.png` | ImageGen |
| Transformers | `universe-transformers-v2.png` | ImageGen |
| Rocky & Creed | `universe-rocky_creed-v2.png` | ImageGen |
| John Wick | `universe-john_wick-v2.png` | ImageGen |
| Resident Evil | `universe-resident_evil-v2.png` | ImageGen |
| Godzilla & Kong | `universe-godzilla_kong-v2.png` | ImageGen |
| The Chronicles of Narnia | `universe-narnia-v2.png` | ImageGen |
| Dune | `universe-dune-v2.png` | ImageGen |
| Shrek & Puss in Boots | `universe-shrek-v2.png` | ImageGen |
| The Walking Dead Universe | `universe-walking_dead-v2.png` | ImageGen |
| Game of Thrones Universe | `universe-game_thrones-v2.jpg` | IMDb tt0944947 |
| Yellowstone Universe | `universe-yellowstone-v2.png` | ImageGen |
| Doctor Who Universe | `universe-doctor_who-v2.png` | ImageGen |
| Dragon Ball Universe | `universe-dragon_ball-v2.png` | ImageGen |

La mise à jour des fichiers d'affiches nécessite un redémarrage de VODUM pour
recharger l'allowlist, puis la prochaine synchronisation des collections pour
republier les visuels dont le digest a changé. Aucune migration en base.

## Affiches actives Stargate et Terre du Milieu

- `universe-stargate-v2.png` et `universe-middle_earth-v2.png` : nouvelles affiches
  de collection générées avec ImageGen le 2026-11-21, dans une direction
  cinématographique cohérente avec Harry Potter / Fantastic Beasts.
- Les clés `universe_stargate` et `universe_middle_earth` pointent vers ces
  fichiers ; les anciennes affiches ci-dessous sont conservées pour historique.
- Les collections films et séries utilisent ces mêmes visuels. Le digest
  d’affiche existant déclenche leur remplacement à la prochaine synchronisation.

## Versions précédentes et affiche Harry Potter


- `universe-wizarding_world-v2.png` : visuel de collection généré avec ImageGen,
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
