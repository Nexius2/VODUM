# 🍿 La Sélection du Moment

Gestionnaire autonome de collection Plex : suivi SQLite des entrées manuelles,
expiration après 30 jours calendaires et sélection de sorties numériques récentes.
Python 3.11+, PlexAPI, TMDB, sans interface web ni dépendance à Kometa ou Radarr.
Aucune opération de suppression de média ou de fichier n'est utilisée.

## Démarrage

### Lanceur quotidien Linux / Unraid

Depuis le terminal Unraid, lancer une première simulation :

```bash
cd "/mnt/user/Dev/Selection du moment"
bash run.sh --dry-run
```

Puis utiliser chaque jour (ou dans Unraid User Scripts) :

```bash
bash "/mnt/user/Dev/Selection du moment/run.sh"
```

Le lanceur exige Python 3.11+ avec `venv` et `pip`, crée `.venv` et installe
automatiquement `requirements.txt` au premier lancement. Les lancements suivants
réutilisent cet environnement ; une modification des exigences, un module manquant
ou une incohérence détectée déclenche une nouvelle installation. Internet est
nécessaire pour installer les dépendances et accéder aux services.
Le lanceur se place dans le dossier du projet et exécute **un seul cycle**,
même si le planificateur interne est activé. Les options sont transmises à Python
(`--dry-run`, `--cleanup-only`, `--populate-only`, `--config ...`) et son code de
sortie est conservé. Pour choisir un interpréteur : `PYTHON=/chemin/python3 bash run.sh`.

Préparer `config/config.yaml` et les identifiants comme indiqué ci-dessous.
Utiliser des chemins locaux pour la base et les journaux (voir ci-dessous).
Le lanceur respecte `execution.dry_run` : passer cette valeur à `false` après
validation de la simulation pour autoriser les modifications Plex.

### Préparation de la configuration et lancement manuel

1. Copier `config/config.example.yaml` vers `config/config.yaml`.
2. Fournir `PLEX_URL`, `PLEX_TOKEN`, `TMDB_API_KEY` par variables d'environnement.
   `TMDB_API_KEY` attend une clé API v3, pas un jeton Bearer v4.
3. Vérifier le nom de bibliothèque et de collection. Une collection standard est
   requise ; une collection intelligente ou un nom ambigu est refusé.
4. Lancer une simulation complète et examiner les journaux avant toute activation.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item config/config.example.yaml config/config.yaml
$env:PLEX_URL = "http://serveur:32400"
$env:PLEX_TOKEN = "votre-jeton"
$env:TMDB_API_KEY = "votre-cle"
python main.py --dry-run
```

Pour une exécution locale, adapter `database.path` à `./appdata/selection.db` et
`logging.path` à `./logs/selection.log`. Les chemins par défaut ciblent Docker.
Les identifiants peuvent aussi être écrits dans le YAML privé, ignoré par Git.
Ne pas versionner de secrets. Les erreurs HTTP sont résumées sans URL ni jeton.

**La configuration livrée utilise `execution.dry_run: true`.** Une fois les résultats
réels vérifiés, passer cette valeur à `false` pour autoriser les modifications.
L'option CLI `--dry-run` impose toujours une simulation.

## Commandes

```text
python main.py --dry-run         Simulation unique, données réelles, aucune écriture Plex
python main.py --cleanup-only    Synchronisation et expiration, sans appel TMDB
python main.py --populate-only   Synchronisation et découverte, sans expiration
python main.py --run-once        Cycle complet unique
python main.py                  Planification quotidienne si scheduler.enabled=true
python main.py --config chemin   Autre fichier YAML
```

Toutes les commandes respectent le mode simulation du YAML. Les deux modes
partiels sont mutuellement exclusifs. Le mode `populate-only` est destiné au
diagnostic ; le service quotidien doit conserver le cycle complet pour nettoyer.
Si la planification est désactivée, la commande sans options exécute un seul cycle.
Le service attend le prochain horaire local (12:30 Europe/Paris par défaut), sans
exécuter immédiatement au démarrage. Pour un rattrapage, utiliser `--run-once`.
Les codes de sortie d'une exécution unique sont 0 (réussite), 1 (échec ou résultat
partiel), 2 (configuration invalide). Le service journalise les échecs et reprend
au prochain horaire. SIGTERM/SIGINT interrompent l'attente ; un cycle engagé finit
ses opérations. Une interruption forcée reste récupérable via le journal SQLite.

## Suivi et nettoyage

Au premier cycle, les membres présents reçoivent une durée complète avec origine
`existing`. Ensuite, tout nouveau membre Plex reçoit l'origine `manual`. La date
`addedAt` de Plex n'est jamais utilisée. L'entrée et l'expiration sont enregistrées
en ISO 8601 avec décalage de fuseau ; les jours calendaires sont calculés dans le
fuseau configuré (une transition été/hiver peut donner une durée différente de 720 h).
Les dates restent inchangées tant que l'entrée est active.

Un retrait externe clôture l'entrée avec motif `manual` et bloque l'ajout automatique
pendant 30 jours configurables. Un réajout volontaire dans Plex crée une nouvelle
entrée, même pendant cette exclusion. La détection a lieu au prochain cycle : un
retrait et réajout entre deux observations ne peuvent pas être distingués.

Un film expiré est retiré avant tout appel TMDB. Les erreurs de retrait sont isolées
par film. Le nettoyage est enregistré avant le peuplement, et les deux résultats
figurent séparément dans `runs`. La collection peut donc se vider complètement.
Une popularité persistante ne réintroduit pas un film expiré : il faut une nouvelle
date de sortie numérique dans un pays quelconque, strictement postérieure au retrait et à
l'événement déjà traité. Les historiques sont rapprochés par clé Plex **et** TMDB.

Les écritures Plex sont précédées d'une opération SQLite persistante et confirmées
par une relecture. Chaque ajout automatique est déplacé **en tête de collection**,
en ordre personnalisé Plex ; l'ordre relatif des films déjà présents est conservé.
Lors de plusieurs ajouts, le dernier ajouté apparaît en premier. La position est
vérifiée après déplacement ; un échec reste en attente et sera repris au prochain
cycle. La simulation annonce le placement sans modifier l'ordre Plex.
Les écritures sont également confirmées
par une relecture des membres. Après interruption, les opérations en attente sont
réconciliées avec Plex avant la détection des ajouts manuels, en conservant les dates
initialement prévues. Un échec non confirmé est signalé, jamais annoncé comme réussi.
Un verrou fichier empêche les cycles concurrents partageant la même base.
Utiliser une seule base par serveur/bibliothèque/collection ; cette association est
contrôlée. Si Plex ou SQLite sont inaccessibles, aucune mutation non suivie n'est tentée.

En simulation, la base est copiée en mémoire : suivi, historique, opérations et bilan
de production restent intacts. Seuls les fichiers de journaux et de verrou peuvent
être créés. Le bilan final représente le résultat prévu, pas un nouvel état réel Plex.

## Découverte et scoring

La découverte pagine les sorties numériques TMDB (type 4), tous pays et fenêtre des
30 dates calendaires incluant aujourd'hui. La première page des tendances hebdomadaires
élargit les candidats. Pour chacun, les détails `release_dates` doivent confirmer
une date numérique dans au moins un pays dans la fenêtre, Canada compris.
La fenêtre numérique inclut aussi les sorties prévues dans les **30 prochains jours**.
Les dates cinéma, physiques, au-delà de ces 30 jours ou manquantes ne rendent pas un film éligible.
La présence dans la bibliothèque Plex reste obligatoire. Le pays de sortie ne
présume pas de la langue audio. Avant tout ajout automatique, le script recharge
les détails Plex et exige une **piste audio française** (VF seule ou VO + VF,
français canadien compris). Une VO seule, quelle que soit sa langue, ou des
sous-titres français seuls ne suffisent pas. Une langue audio inconnue est refusée.
Pour un film en plusieurs parties, chaque partie d'une même version doit avoir
du français. Parmi plusieurs éditions, la première édition éligible avec du français
est choisie. Un échec de lecture des pistes bloque l'ajout et signale un résultat partiel.
Ce filtre ne retire pas les films ajoutés manuellement ; leur expiration reste inchangée.
`tmdb.language: fr-FR` conserve les métadonnées en français. L'ancien paramètre
`tmdb.region` est ignoré : aucune modification du YAML existant n'est nécessaire.
Aucun quota n'est appliqué.
Le film doit également avoir sa première sortie connue **depuis le début du mois précédent
et jusqu'à 30 jours dans le futur**.
Au 12 octobre 2026, la période autorisée va du 1er septembre au 11 novembre 2026 inclus.
La date de sortie Plex (`originallyAvailableAt`) doit elle aussi appartenir à cette
période. Une date Plex inconnue entraîne un rejet de l'ajout automatique.
L'ancien paramètre `collection.max_movie_age_days` est ignoré : la règle s'applique
immédiatement aux configurations existantes, même si elles contiennent encore 365.
La date retenue est la plus ancienne parmi `release_date` et les sorties de tous les
pays, avant-premières comprises. Une date initiale inconnue ou hors période entraîne un rejet.
Un film disponible en avance dans Plex avec de l'audio français peut donc être ajouté.
La fraîcheur des sorties futures est plafonnée à 25 points, sans bonus supplémentaire.
Une réédition numérique récente de *Shutter Island* (2010) reste donc exclue,
quel que soit son score ou sa popularité. Ce filtre concerne les ajouts automatiques ;
les membres existants et les ajouts manuels conservent leur suivi et expiration habituels.
Les journaux de sélection affichent à côté du titre la date Plex, la première date
TMDB et la date numérique retenue ; les simulations d'ajout affichent la date Plex.
La limite API de 500 pages est technique et signalée si atteinte.

Un candidat doit franchir le score minimal **et** au moins un profil configurable :

| Profil | Seuil initial |
|---|---|
| Film événement | Popularité ≥ 50, sans seuil de note |
| Très bons avis | ≥ 100 votes, note pondérée ≥ 7, popularité ≥ 5 |
| Franchise | Appartenance à une collection TMDB et popularité ≥ 20 |
| Tendance | Signal tendance ≥ 0,5 et popularité ≥ 15 |

La note pondérée vaut `(votes × note + 100 × 6) / (votes + 100)`.
Le score est la somme des signaux normalisés : fraîcheur 25 points, popularité 35,
note 25, tendance 10, franchise 5. Le seuil initial est 65/100.
Fraîcheur : `1 - âge / fenêtre`. Popularité : `log(1+p)/log(101)`, plafonné à 1.
Note : `(note pondérée - 5)/3`, borné entre 0 et 1. Tendance : rang normalisé dans
la première page hebdomadaire. Franchise : 0 ou 1. Tous les poids et seuils de profils
sont exposés dans `scoring`.

Exemples synthétiques à la date de sortie, 1 000 votes :

| Exemple | Popularité | Note | Tendance | Score approximatif | Résultat |
|---|---:|---:|---:|---:|---|
| Gros film d'action | 100 | 6,2 | 0 | 69,8 | Retenu |
| Film très bien reçu | 15 | 8 | 0 | 69,5 | Retenu |
| Film confidentiel, 5 votes | 1 | 9 | 0 | 39,7 | Rejeté |

Ce sont des valeurs de départ, pas une calibration empirique sur votre bibliothèque.
Examiner les décisions `SELECT`/`REJECT` lors de simulations avant d'ajuster les poids.
Le signal de tendance est un rang actuel, pas une mesure de croissance historique.
L'appartenance à une franchise ne mesure pas le succès de ses épisodes précédents.

Seuls les GUID `tmdb://...` non ambigus permettent un rapprochement automatique.
Sans identifiant, le repli prudent est l'abstention avec journalisation : aucun
rapprochement par titre. Ces films restent suivis et nettoyés s'ils sont ajoutés
manuellement. En présence de plusieurs éditions Plex, une seule est choisie de façon
déterministe. Aucun téléchargement ni demande externe n'est déclenché.

### Limites des données TMDB

TMDB est contributif : les dates numériques peuvent manquer, être erronées, ou
correspondre à une location plutôt qu'à un abonnement. Le type 4 ne distingue pas
précisément VOD, achat et arrivée sur une plateforme. Les fournisseurs de streaming
ne fournissent pas à eux seuls une date d'arrivée vérifiable. Cette version préfère
rejeter un film sans date numérique mondiale vérifiée plutôt que d'inventer une disponibilité. Une nouvelle
date saisie rétroactivement peut être interprétée comme un nouvel événement.
La qualité finale dépend des données et de vos simulations ; aucune source ne
permet de garantir à elle seule une sélection éditoriale parfaite.

Références : [TMDB Discover](https://developer.themoviedb.org/reference/discover-movie),
[types et régions TMDB](https://developer.themoviedb.org/docs/region-support),
[collections PlexAPI](https://python-plexapi.readthedocs.io/en/latest/modules/collection.html).

## Docker et Unraid

Créer les dossiers `appdata` et `logs`, ainsi que le vrai fichier `config/config.yaml`,
avant le lancement. Sous Linux, donner l'écriture sur ces deux dossiers à l'UID 10001
du conteneur. Le fichier YAML doit être lisible par cet utilisateur.

Créer un fichier `.env` privé à côté du Compose :

```dotenv
PLEX_URL=http://serveur:32400
PLEX_TOKEN=votre-jeton
TMDB_API_KEY=votre-cle
```

```bash
docker compose build
docker compose run --rm selection --dry-run
# Après vérification et passage du YAML à dry_run: false :
docker compose up -d
docker compose logs -f selection
```

Sur Unraid, construire l'image depuis ce dossier puis créer un conteneur avec les
mêmes variables, l'UID 10001 et ces chemins hôte persistants, par exemple :

| Hôte Unraid | Conteneur | Accès |
|---|---|---|
| /mnt/user/appdata/plex-selection/data | /appdata | Écriture |
| /mnt/user/appdata/plex-selection/logs | /logs | Écriture |
| /mnt/user/appdata/plex-selection/config.yaml | /app/config/config.yaml | Lecture |

Aucun port ni privilège supplémentaire n'est nécessaire. Utiliser le planificateur
intégré ou une tâche Unraid exécutant `--run-once` (dans ce cas, désactiver le
planificateur intégré et éviter une politique de redémarrage continu).
Les journaux fichiers sont tournés quotidiennement et conservés 30 rotations ;
l'historique SQLite est conservé sans purge automatique. Sauvegarder la base lorsque
le conteneur est arrêté. Éviter une base sur un montage réseau dont les verrous sont
incertains. Une modification manuelle simultanée dans Plex peut être observée au
cycle suivant ; le verrou protège les instances du script, pas l'interface Plex.

## Tests et architecture

```bash
python -m unittest discover -s tests -v
```

Tests sans serveur réel : initialisation, détection manuelle, expiration, panne TMDB,
anti-réintroduction, absence de Plex, ancienneté numérique, quinze candidats, reprise,
retrait manuel, simulation, opérations interrompues et erreur sur un retrait.
Le moteur `app.engine.Engine` reçoit des adaptateurs Plex/TMDB et une base ; il est
réutilisable indépendamment de la CLI et du planificateur. `app.discovery.score`
est également utilisable séparément. Aucun autre script Plex n'est modifié.

La validation avec votre serveur et la construction Docker doivent être effectuées
dans votre environnement avant l'activation réelle.
