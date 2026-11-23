# Listes de franchises ajoutées le 2026-11-21

23 listes supplémentaires portent le catalogue livré à 32 listes. Les 307
identifiants IMDb ajoutés ont été vérifiés directement auprès d'IMDb le
2026-11-21 (titre, année et type). Le catalogue contient les identités typées,
les titres et les années ; les affiches sont récupérées via le mécanisme de
métadonnées et le cache local existants.

| Liste | Clé stable | Films, téléfilms et courts | Séries / mini-séries | Référence IMDb |
| --- | --- | ---: | ---: | --- |
| Jurassic Park & Jurassic World | `jurassic` | 8 | 2 | [IMDb](https://www.imdb.com/title/tt0107290/) |
| Terminator | `terminator` | 6 | 2 | [IMDb](https://www.imdb.com/title/tt0088247/) |
| The Matrix | `matrix` | 5 | 0 | [IMDb](https://www.imdb.com/title/tt0133093/) |
| James Bond 007 | `james_bond` | 27 | 0 | [IMDb](https://www.imdb.com/title/tt0055928/) |
| Mission: Impossible | `mission_impossible` | 8 | 2 | [IMDb](https://www.imdb.com/title/tt0117060/) |
| The Conjuring Universe | `conjuring` | 10 | 0 | [IMDb](https://www.imdb.com/title/tt1457767/) |
| Indiana Jones | `indiana_jones` | 5 | 1 | [IMDb](https://www.imdb.com/title/tt0082971/) |
| Pirates of the Caribbean | `pirates_caribbean` | 5 | 0 | [IMDb](https://www.imdb.com/title/tt0325980/) |
| Planet of the Apes | `planet_apes` | 10 | 2 | [IMDb](https://www.imdb.com/title/tt0063442/) |
| Ghostbusters | `ghostbusters` | 5 | 2 | [IMDb](https://www.imdb.com/title/tt0087332/) |
| Transformers | `transformers` | 10 | 24 | [IMDb](https://www.imdb.com/title/tt0092106/) |
| Rocky & Creed | `rocky_creed` | 9 | 0 | [IMDb](https://www.imdb.com/title/tt0075148/) |
| John Wick | `john_wick` | 5 | 1 | [IMDb](https://www.imdb.com/title/tt2911666/) |
| Resident Evil | `resident_evil` | 12 | 2 | [IMDb](https://www.imdb.com/title/tt0120804/) |
| Godzilla & Kong | `godzilla_kong` | 46 | 8 | [IMDb](https://www.imdb.com/title/tt0047034/) |
| The Chronicles of Narnia | `narnia` | 4 | 3 | [IMDb](https://www.imdb.com/title/tt0363771/) |
| Dune | `dune` | 3 | 3 | [IMDb](https://www.imdb.com/title/tt0087182/) |
| Shrek & Puss in Boots | `shrek` | 16 | 1 | [IMDb](https://www.imdb.com/title/tt0126029/) |
| The Walking Dead Universe | `walking_dead` | 0 | 7 | [IMDb](https://www.imdb.com/title/tt1520211/) |
| Game of Thrones Universe | `game_thrones` | 0 | 3 | [IMDb](https://www.imdb.com/title/tt0944947/) |
| Yellowstone Universe | `yellowstone` | 0 | 5 | [IMDb](https://www.imdb.com/title/tt4236770/) |
| Doctor Who Universe | `doctor_who` | 4 | 8 | [IMDb](https://www.imdb.com/title/tt0056751/) |
| Dragon Ball Universe | `dragon_ball` | 26 | 7 | [IMDb](https://www.imdb.com/title/tt0088509/) |

## Périmètre

- Sélection éditoriale des films, séries, principaux spin-offs et des courts
  explicitement retenus, sans jeux vidéo, making-of, podcasts ou entrées
  annoncées après le 2026-11-21. Ce n'est pas un inventaire de chaque publicité,
  épisode, compilation ou court promotionnel jamais produit.
- James Bond inclut les 25 films EON, ainsi que *Casino Royale* (1967) et
  *Never Say Never Again* (1983). The Matrix inclut *The Animatrix* comme un film
  d'anthologie, sans dupliquer ses segments.
- Godzilla & Kong regroupe les productions japonaises, les différentes versions
  de King Kong et le MonsterVerse : elles ne forment pas toutes une continuité
  narrative unique. Transformers et Dragon Ball réunissent films et animations.
- Doctor Who distingue les séries de 1963, 2005 et 2023 ; le téléfilm de 1996 et
  le pilote *K-9 and Company* sont classés comme films, pas comme séries.
- Yellowstone inclut Yellowstone, 1883, 1923, Marshals et Dutton Ranch.
  The Madison et les autres séries de Taylor Sheridan sans lien narratif ne
  sont pas ajoutées automatiquement à cet univers.
- Ghostbusters inclut The Real Ghostbusters et Extreme Ghostbusters. La série
  homonyme de Filmation (1986), issue d’une autre propriété, est exclue.
- Conjuring inclut La Llorona comme film connexe ; son rattachement au canon
  principal est discuté.
- Les courts et téléfilms suivent le type de bibliothèque « film » dans VODUM.
  Leur présence dans IMDb ne garantit pas une correspondance TMDB ; les règles
  existantes de découverte partielle et de conservation des membres restent
  applicables.

## Installation et associations

Le démarrage ajoute les listes et leurs entrées avec `INSERT OR IGNORE`, sans
écraser les noms modifiés, les exclusions ou les ajouts personnels. Aucun
changement de schéma n'est requis.

Les associations explicites des configurations Franchise existantes sont
conservées. Pour les compléter, ouvrir **Listes → Collections et bibliothèques
associées → Gérer les liens Franchise**. Les nouvelles configurations Franchise
utilisent les listes VODUM comme sélection initiale ; une configuration
historique sans sélection explicite utilise également les listes VODUM.
