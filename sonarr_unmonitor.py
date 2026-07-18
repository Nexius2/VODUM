# -*- coding: utf-8 -*-

"""
#########################################################
# Media Management Tools (MMT) - Sonarr Unmonitor
# Auteur       : Nexius2
# Description  : Script permettant de désactiver le monitoring
#                des épisodes dans Sonarr en fonction des critères
#                définis dans `multi_services_config.json`.
# Licence      : MIT
#########################################################


🛠 Sonarr Unmonitor - Désactivation automatique des épisodes dans Sonarr

=============================================================
📌 DESCRIPTION
-------------------------------------------------------------
Sonarr Unmonitor est un script Python permettant de **désactiver le monitoring**
des épisodes dans Sonarr en fonction des critères définis dans `config.json`.
Il permet d'éviter que des épisodes déjà récupérés soient à nouveau téléchargés.

📂 Fonctionnalités :
- Analyse les séries et leurs **épisodes monitorés avec un fichier**.
- Vérifie si le **nom du fichier** correspond aux critères de désactivation.
- Désactive automatiquement le monitoring des épisodes concernés.
- **Mode simulation (DRY_RUN)** pour tester sans effectuer de modifications.
- **Logs détaillés** des épisodes traités et des erreurs éventuelles.

=============================================================
📜 FONCTIONNEMENT
-------------------------------------------------------------
1. **Connexion à Sonarr** via son API.
2. **Récupération de la liste des séries et épisodes monitorés** ayant un fichier.
3. **Analyse du nom du fichier** et comparaison avec les critères définis.
4. **Désactivation du monitoring** pour les épisodes correspondants.
5. **Gestion du mode simulation** (`dry_run` activé/désactivé).
6. **Gestion avancée des erreurs et des logs**.

=============================================================
⚙️ CONFIGURATION (config.json)
-------------------------------------------------------------
Le script utilise un fichier de configuration JSON contenant les paramètres suivants :

{
    "services": {
        "sonarr": {
            "url": "http://192.168.1.100:8989",
            "api_key": "VOTRE_CLE_API_SONARR"
        }
    },
    "sonarr_unmonitor": {
        "log_file": "sonarr_unmonitor.log",
        "log_level": "INFO",
        "dry_run": true,
        "search_terms": [
            ["1080", "FR", "MULTI"],
            ["4K", "FR", "MULTI"]
        ]
    }
}

| Clé                           | Description |
|--------------------------------|-------------|
| `services.sonarr.url`         | URL de l'instance Sonarr |
| `services.sonarr.api_key`     | Clé API pour Sonarr |
| `sonarr_unmonitor.log_file`   | Nom du fichier de log |
| `sonarr_unmonitor.log_level`  | Niveau de logs (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `sonarr_unmonitor.dry_run`    | `true` = simulation, `false` = modifications réelles |
| `sonarr_unmonitor.search_terms` | Liste des groupes de critères pour la désactivation |

📌 **Critères de désactivation (`search_terms`)**
- Chaque groupe de termes doit être **présent simultanément** dans le nom du fichier.
- Exemple :
  - `["1080", "FR", "MULTI"]` ➝ Désactive si les trois termes sont présents.
  - `["4K", "FR", "MULTI"]` ➝ Désactive si ces trois termes sont présents.

=============================================================
🚀 UTILISATION
-------------------------------------------------------------
1. **Installez les dépendances requises** :
   pip install requests

2. **Créez/modifiez le fichier `config.json`** avec vos paramètres.

3. **Lancez le script en mode simulation (DRY_RUN activé)** :
   python sonarr_unmonitor.py
   - Aucun épisode ne sera désactivé, mais le script affichera ceux qui le seraient.

4. **Exécutez le script avec modifications réelles** (après avoir mis `dry_run` sur `false` dans `config.json`) :
   python sonarr_unmonitor.py
   - Les épisodes correspondant aux critères seront réellement désactivés.

=============================================================
📄 LOGS ET DEBUG
-------------------------------------------------------------
Le script génère des logs détaillés :
- Les logs sont enregistrés dans le fichier spécifié (`sonarr_unmonitor.log`).
- En mode `DEBUG`, toutes les analyses et modifications sont enregistrées.
- Les erreurs de connexion ou de requête API sont également loguées.

=============================================================
🛑 PRÉCAUTIONS
-------------------------------------------------------------
- **Aucun fichier n'est supprimé**, seule la surveillance est désactivée.
- **Le monitoring peut être réactivé** manuellement dans Sonarr si nécessaire.
- **Vérifiez les logs avant de désactiver `dry_run`**, pour éviter des désactivations indésirables.

=============================================================
🔥 EXEMPLE D'EXÉCUTION EN MODE `DRY_RUN`
-------------------------------------------------------------
python sonarr_unmonitor.py

📝 **Exemple de sortie :**
🚀 Début du traitement des séries dans Sonarr...
📥 500 séries récupérées depuis Sonarr.
✅ 480 séries avec épisodes monitorés et téléchargés.
📋 25 épisodes détectés correspondant aux critères de désactivation.
🔧 Mode DRY RUN activé. Aucun épisode ne sera modifié.

=============================================================
🗑 EXEMPLE D'EXÉCUTION AVEC MODIFICATIONS EFFECTIVES
-------------------------------------------------------------
Après avoir mis `dry_run` sur `false` dans `config.json` :

python sonarr_unmonitor.py

📝 **Exemple de sortie :**
🚀 Début du traitement des séries dans Sonarr...
📥 500 séries récupérées depuis Sonarr.
✅ 480 séries avec épisodes monitorés et téléchargés.
📋 25 épisodes détectés correspondant aux critères de désactivation.
📝 Épisode "Breaking Bad S02E05" marqué comme NON MONITORÉ.
📝 Épisode "Game of Thrones S04E03" marqué comme NON MONITORÉ.
✅ Fin du traitement. 25 épisodes ont été désactivés.

=============================================================
💡 ASTUCE
-------------------------------------------------------------
Vous pouvez programmer l'exécution automatique de ce script 
via un **cron job** ou une **tâche planifiée Windows**.

"""

VERSION = "26.07.16"
import requests
import json
import logging
from logging.handlers import RotatingFileHandler
import re
import time
from pathlib import Path
from collections import defaultdict
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Chargement de la configuration
CONFIG_FILE = "multi_services_config.json"
LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)

global_stats = defaultdict(lambda: {
    "series_processed": 0,
    "episodes_processed": 0,
    "episodes_matching": 0,
    "episodes_unmonitored": 0,
    "episodes_already_unmonitored": 0,
    "seasons_unmonitored": 0,
    "series_deleted": 0
})


try:
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
except FileNotFoundError:
    print(f"❌ Erreur : fichier de configuration '{CONFIG_FILE}' introuvable.")
    exit(1)

_sonarr_instances = config["services"].get("sonarr", [])
# Robustesse : permet de gérer à la fois un dict (ancienne config) ou une liste
if isinstance(_sonarr_instances, dict):
    SONARR_INSTANCES = [_sonarr_instances]
else:
    SONARR_INSTANCES = list(_sonarr_instances)

UNMONITOR_CONFIG = config.get("sonarr_unmonitor", {})

LOG_FILE = LOGS_DIR / Path(UNMONITOR_CONFIG.get("log_file", "sonarr_unmonitor.log")).name
LOG_LEVEL = UNMONITOR_CONFIG.get("log_level", "INFO").upper()
DRY_RUN = UNMONITOR_CONFIG.get("dry_run", True)
SEARCH_TERMS = UNMONITOR_CONFIG.get("search_terms", [["1080", "FR", "MULTI"]])
REQUEST_TIMEOUT = UNMONITOR_CONFIG.get("request_timeout", 30)
ADD_IMPORT_LIST_EXCLUSION = UNMONITOR_CONFIG.get("add_import_list_exclusion", True)

# Session commune : réutilisation des connexions et nouvelles tentatives limitées
# sur les erreurs transitoires. Les méthodes utilisées ici sont idempotentes.
HTTP = requests.Session()
HTTP.mount(
    "http://",
    HTTPAdapter(max_retries=Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(("GET", "PUT", "DELETE")),
        respect_retry_after_header=True,
        raise_on_status=False,
    )),
)
HTTP.mount("https://", HTTP.adapters["http://"])


def api_request(method, url, **kwargs):
    """Effectue une requête Sonarr avec un timeout systématique."""
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)
    return HTTP.request(method, url, **kwargs)

# Initialisation du logging
log_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
file_handler.setFormatter(log_formatter)
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
logger = logging.getLogger()
logger.setLevel(getattr(logging, LOG_LEVEL, logging.DEBUG))
logger.handlers = []
logger.addHandler(file_handler)
logger.addHandler(console_handler)

logging.info("📝 Système de logs activé.")


def clean_filename(filename):
    filename = filename.lower()
    filename = filename.replace("1080p", "1080").replace("2160p", "4k")
    filename = re.sub(r"[\(\)\-_.]", " ", filename)
    filename = re.sub(r"\s+", " ", filename).strip()
    return filename


def match_criteria(term, filename):
    if term.isdigit():
        pattern = rf"(?:^|[\[\]\+\-&\s\._,]){re.escape(term)}(?:p|i|$|[\[\]\+\-&\s\._,])"
    else:
        pattern = rf"(?:^|[\[\]\+\-&\s\._,]){re.escape(term.lower())}(?:$|[\[\]\+\-&\s\._,])"
    match = re.search(pattern, filename)
    if match:
        logging.debug(f"✅ Terme '{term}' trouvé dans '{filename}'")
    else:
        logging.debug(f"❌ Terme '{term}' NON trouvé dans '{filename}'")
    return bool(match)

def has_any_token(text, tokens):
    return any(match_criteria(token, text) for token in tokens)


def is_quality_1080_or_more(relative_path):
    quality_tokens = ["1080", "1080p", "2160", "2160p", "4k", "uhd"]
    return has_any_token(relative_path, quality_tokens)


def has_french_language(relative_path):
    french_tokens = ["fr", "fra", "french"]
    return has_any_token(relative_path, french_tokens)


def get_original_language_tokens(series):
    original_language = series.get("originalLanguage") or {}
    lang = (
        original_language.get("name")
        or original_language.get("value")
        or original_language.get("twoLetterCode")
        or original_language.get("threeLetterCode")
        or ""
    ).strip().lower()

    language_map = {
        "french": ["fr", "fra", "french"],
        "français": ["fr", "fra", "french"],
        "francais": ["fr", "fra", "french"],
        "fr": ["fr", "fra", "french"],
        "fra": ["fr", "fra", "french"],

        "english": ["en", "eng", "english"],
        "anglais": ["en", "eng", "english"],
        "en": ["en", "eng", "english"],
        "eng": ["en", "eng", "english"],

        "japanese": ["jp", "jpn", "japanese"],
        "japonais": ["jp", "jpn", "japanese"],
        "ja": ["jp", "jpn", "japanese"],
        "jp": ["jp", "jpn", "japanese"],
        "jpn": ["jp", "jpn", "japanese"],

        "korean": ["ko", "kor", "korean"],
        "coréen": ["ko", "kor", "korean"],
        "coreen": ["ko", "kor", "korean"],
        "ko": ["ko", "kor", "korean"],
        "kor": ["ko", "kor", "korean"],

        "hindi": ["hi", "hin", "hindi"],
        "hi": ["hi", "hin", "hindi"],
        "hin": ["hi", "hin", "hindi"],

        "spanish": ["es", "spa", "spanish"],
        "espagnol": ["es", "spa", "spanish"],
        "es": ["es", "spa", "spanish"],
        "spa": ["es", "spa", "spanish"],

        "german": ["de", "ger", "deu", "german"],
        "allemand": ["de", "ger", "deu", "german"],
        "de": ["de", "ger", "deu", "german"],
        "ger": ["de", "ger", "deu", "german"],
        "deu": ["de", "ger", "deu", "german"],

        "italian": ["it", "ita", "italian"],
        "italien": ["it", "ita", "italian"],
        "it": ["it", "ita", "italian"],
        "ita": ["it", "ita", "italian"],

        "portuguese": ["pt", "por", "portuguese"],
        "portugais": ["pt", "por", "portuguese"],
        "pt": ["pt", "por", "portuguese"],
        "por": ["pt", "por", "portuguese"],

        "russian": ["ru", "rus", "russian"],
        "russe": ["ru", "rus", "russian"],
        "ru": ["ru", "rus", "russian"],
        "rus": ["ru", "rus", "russian"],

        "chinese": ["zh", "chi", "zho", "chinese"],
        "chinois": ["zh", "chi", "zho", "chinese"],
        "zh": ["zh", "chi", "zho", "chinese"],
        "chi": ["zh", "chi", "zho", "chinese"],
        "zho": ["zh", "chi", "zho", "chinese"],
    }

    if lang in language_map:
        return language_map[lang]

    two_letter = (original_language.get("twoLetterCode") or "").strip().lower()
    three_letter = (original_language.get("threeLetterCode") or "").strip().lower()

    fallback_tokens = []
    if two_letter:
        fallback_tokens.append(two_letter)
    if three_letter and three_letter not in fallback_tokens:
        fallback_tokens.append(three_letter)
    if lang and lang not in fallback_tokens:
        fallback_tokens.append(lang)

    return fallback_tokens

def should_unmonitor(episode, series):
    filename = episode.get("episodeFile", {}).get("relativePath", "")
    episode_id = episode.get("id")
    title = episode.get("title", "Titre inconnu")

    if not filename:
        logging.debug(f"🚫 Aucun fichier associé à l'épisode {episode_id}")
        return False

    normalized_filename = clean_filename(filename)
    logging.debug(f"🔍 Vérification des critères pour : {normalized_filename}")

    quality_ok = is_quality_1080_or_more(normalized_filename)
    french_ok = has_french_language(normalized_filename)

    original_language_tokens = get_original_language_tokens(series)
    original_language_ok = has_any_token(normalized_filename, original_language_tokens) if original_language_tokens else False

    if quality_ok and french_ok and original_language_ok:
        original_language = series.get("originalLanguage") or {}
        original_language_name = (
            original_language.get("name")
            or original_language.get("value")
            or original_language.get("twoLetterCode")
            or original_language.get("threeLetterCode")
            or "inconnue"
        )

        logging.info(
            f"🎯 Épisode détecté : {title} | "
            f"quality>=1080=oui | french=oui | original_language={original_language_name} | "
            f"tokens_originaux={original_language_tokens} | fichier={filename}"
        )
        return True

    # Compatibilité avec l'ancien fonctionnement basé sur SEARCH_TERMS
    for group in SEARCH_TERMS:
        if all(match_criteria(term, normalized_filename) for term in group):
            logging.info(f"🎯 Épisode détecté via SEARCH_TERMS : {filename} - Correspondance: {group}")
            return True

    logging.debug(
        f"🚫 Épisode ignoré : {title} | "
        f"quality>=1080={quality_ok} | french={french_ok} | "
        f"original_language_tokens={original_language_tokens} | original_language_match={original_language_ok} | "
        f"fichier={filename}"
    )
    return False


def get_episodes(sonarr_url, headers, series_id):
    episodes_url = f"{sonarr_url.rstrip('/')}/api/v3/episode?seriesId={series_id}&includeEpisodeFile=true"

    try:
        response = api_request("GET", episodes_url, headers=headers)
    except requests.exceptions.Timeout:
        logging.error(f"❌ Timeout lors de la récupération des épisodes pour la série {series_id}")
        return []
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ Erreur réseau lors de la récupération des épisodes pour la série {series_id} - {e}")
        return []

    if response.status_code != 200:
        logging.error(f"❌ Erreur lors de la récupération des épisodes pour la série {series_id}: {response.status_code} - {response.text}")
        return []

    episodes = response.json()
    logging.debug(f"📌 {len(episodes)} épisodes récupérés pour la série {series_id}")
    return episodes


def unmonitor_episode(episode, sonarr_url, headers, instance_name):
    episode_id = episode["id"]
    title = episode.get("title", "Titre inconnu")
    season = episode.get("seasonNumber", "?")
    episode_number = episode.get("episodeNumber", "?")

    logging.info(f"🛠️ Traitement de l'épisode '{title}' (S{season}E{episode_number}, ID: {episode_id})...")

    if DRY_RUN:
        logging.info(f"[DRY_RUN] 🚀 L'épisode '{title}' (S{season}E{episode_number}, ID: {episode_id}) aurait été marqué comme NON MONITORÉ ✅")
        return

    url = f"{sonarr_url}/api/v3/episode/{episode_id}"
    data = {"monitored": False}

    max_retries = 5
    for attempt in range(max_retries):
        response = api_request("PUT", url, headers=headers, json=data)

        if response.status_code == 200:
            logging.info(f"✅ Épisode '{title}' (S{season}E{episode_number}, ID: {episode_id}) marqué comme NON MONITORÉ avec succès.")
            global_stats[instance_name]["episodes_unmonitored"] += 1
            break
        elif response.status_code == 202:
            logging.warning(f"⚠️ Sonarr est lent à traiter '{title}' (ID: {episode_id}). Vérification après 3s...")
            time.sleep(3)
            check = api_request("GET", url, headers=headers)
            if check.status_code == 200 and not check.json().get("monitored", True):
                logging.info(f"✅ Vérification OK : Épisode '{title}' bien NON MONITORÉ.")
                global_stats[instance_name]["episodes_unmonitored"] += 1
                break
        else:
            logging.error(f"❌ Erreur lors de la mise à jour de l'épisode {episode_id}: {response.status_code} - {response.text}")
            break


def get_series(sonarr_url, headers):
    url = f"{sonarr_url.rstrip('/')}/api/v3/series"

    try:
        response = api_request("GET", url, headers=headers)
    except requests.exceptions.Timeout:
        logging.error(f"❌ Timeout lors de la récupération des séries : {url}")
        return []
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ Erreur réseau lors de la récupération des séries : {url} - {e}")
        return []

    if response.status_code != 200:
        logging.error(f"❌ Erreur lors de la récupération des séries : {response.status_code} - {response.text}")
        return []

    series_list = response.json()
    logging.info(f"📥 {len(series_list)} séries récupérées depuis Sonarr.")
    return series_list


def process_instance(instance):
    url = instance["url"].rstrip("/")
    api_key = instance["api_key"]
    name = instance.get("name", url)
    headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}

    logging.info(f"🚀 Début du traitement des séries dans Sonarr : {name} ({url})")
    series_list = get_series(url, headers)

    if not series_list:
        logging.warning(f"⚠️ Aucune série récupérée pour l'instance {name}. Instance ignorée.")
        return

    for series in series_list:
        series_id = series["id"]
        series_url = f"{url}/api/v3/series/{series_id}"

        global_stats[name]["series_processed"] += 1

        # --- PHASE 1 : Unmonitor des épisodes ---
        episodes = get_episodes(url, headers, series_id)

        for ep in episodes:
            global_stats[name]["episodes_processed"] += 1

            if ep.get("episodeFile") and should_unmonitor(ep, series):
                global_stats[name]["episodes_matching"] += 1

                if ep.get("monitored"):
                    unmonitor_episode(ep, url, headers, name)
                else:
                    global_stats[name]["episodes_already_unmonitored"] += 1

        # --- PHASE 2 : désactivation des saisons ---
        if UNMONITOR_CONFIG.get("unmonitor_season", False):
            episodes = get_episodes(url, headers, series_id)

            try:
                series_resp = api_request(
                    "GET",
                    series_url,
                    headers=headers
                )

                if series_resp.status_code != 200:
                    logging.error(
                        f"❌ Erreur lors de la récupération de la série {series_id} "
                        f"pour la phase saison : {series_resp.status_code} - {series_resp.text}"
                    )
                    continue

                series_updated = series_resp.json()

            except Exception as e:
                logging.error(
                    f"❌ Erreur lors du décodage de la série {series_id} "
                    f"pour la phase saison : {e}"
                )
                continue

            for season in series_updated.get("seasons", []):
                snum = season.get("seasonNumber")

                if snum == 0:
                    continue

                season_episodes = [
                    ep for ep in episodes
                    if ep.get("seasonNumber") == snum
                ]

                if not season_episodes:
                    continue

                if season.get("monitored", True) and all(
                    not ep.get("monitored", True) for ep in season_episodes
                ):
                    unmonitor_season_if_all_episodes_unmonitored(
                        url,
                        headers,
                        series_id,
                        snum,
                        season_episodes,
                        DRY_RUN,
                        name
                    )

        # --- PHASE 3 : suppression de la série si toutes saisons unmonitorées et status Ended ---
        if UNMONITOR_CONFIG.get("delete_ended_and_unmonitored_series", False):
            try:
                refresh_resp = api_request(
                    "GET",
                    series_url,
                    headers=headers
                )

                if refresh_resp.status_code != 200:
                    logging.error(
                        f"❌ Impossible de recharger la série {series_id} "
                        f"pour la phase suppression : {refresh_resp.status_code} - {refresh_resp.text}"
                    )
                    continue

                series_updated = refresh_resp.json()

            except Exception as e:
                logging.error(
                    f"❌ Erreur lors du rechargement de la série {series_id} "
                    f"pour la phase suppression : {e}"
                )
                continue

            updated_seasons = series_updated.get("seasons", [])

            all_seasons_unmonitored = all(
                not s.get("monitored", True)
                for s in updated_seasons
                if s.get("seasonNumber") != 0
            )

            if (
                series_updated.get("status", "").lower() == "ended"
                and all_seasons_unmonitored
            ):
                delete_series_if_ended_and_all_seasons_unmonitored(
                    series_updated,
                    url,
                    headers,
                    DRY_RUN,
                    name
                )





def unmonitor_season_if_all_episodes_unmonitored(
    sonarr_url, headers, series_id, season_number, episodes_in_season, dry_run, instance_name
):
    # On ne le fait que si tous les épisodes de la saison sont unmonitorés
    if not episodes_in_season or not all(not ep.get("monitored", True) for ep in episodes_in_season):
        return

    series_url = f"{sonarr_url}/api/v3/series/{series_id}"
    resp = api_request("GET", series_url, headers=headers)
    if resp.status_code != 200:
        logging.error(
            f"❌ Erreur lors de la récupération de la série {series_id} : "
            f"{resp.status_code} - {resp.text}"
        )
        return

    series_obj = resp.json()

    found = False
    for season in series_obj.get("seasons", []):
        if season.get("seasonNumber") == season_number:
            if not season.get("monitored", True):
                logging.debug(
                    f"ℹ️ Saison {season_number} de la série {series_id} déjà non monitorée."
                )
                return
            season["monitored"] = False
            found = True
            break

    if not found:
        logging.warning(
            f"⚠️ Saison {season_number} introuvable dans la série {series_id}."
        )
        return

    if dry_run:
        logging.info(
            f"[DRY_RUN] 🚀 La saison {season_number} de la série {series_id} "
            f"serait passée en NON MONITORÉE (tous les épisodes sont unmonitorés)"
        )
        global_stats[instance_name]["seasons_unmonitored"] += 1
        return

    put_url = f"{sonarr_url}/api/v3/series/{series_id}"

    max_retries = 5
    for attempt in range(1, max_retries + 1):
        resp2 = api_request("PUT", put_url, headers=headers, json=series_obj)

        if resp2.status_code in (200, 202):
            # Vérification réelle côté Sonarr
            time.sleep(2)

            verify = api_request("GET", series_url, headers=headers)
            if verify.status_code == 200:
                verify_obj = verify.json()
                verified = False

                for season in verify_obj.get("seasons", []):
                    if season.get("seasonNumber") == season_number:
                        verified = not season.get("monitored", True)
                        break

                if verified:
                    logging.info(
                        f"✅ Saison {season_number} (série {series_id}) marquée comme NON MONITORÉE."
                    )
                    global_stats[instance_name]["seasons_unmonitored"] += 1
                    return

            logging.warning(
                f"⚠️ Tentative {attempt}/{max_retries} : la saison {season_number} "
                f"de la série {series_id} n'est pas encore confirmée NON MONITORÉE."
            )
            time.sleep(2)
            continue

        log_api_error(
            f"❌ Erreur lors du unmonitor de la saison {season_number} (série {series_id})",
            resp2
        )
        return

    logging.error(
        f"❌ Impossible de confirmer le passage en NON MONITORÉ de la saison "
        f"{season_number} (série {series_id}) après {max_retries} tentatives."
    )



def log_api_error(context, resp):
    if logger.level == logging.DEBUG:
        logging.error(f"{context}: {resp.status_code} - {resp.text}")
    else:
        logging.error(f"{context}: {resp.status_code} (détail disponible en mode DEBUG)")


def delete_series_if_ended_and_all_seasons_unmonitored(series, sonarr_url, headers, dry_run, instance_name):
    if series.get("status", "").lower() != "ended":
        return
    # Toutes les saisons non monitorées ?
    seasons = series.get("seasons", [])
    if not seasons:
        return
    regular_seasons = [s for s in seasons if s.get("seasonNumber") != 0]
    if not regular_seasons:
        return
    if all(not season.get("monitored", True) for season in regular_seasons):
        series_id = series["id"]
        title = series.get("title", f"ID:{series_id}")
        params = {
            "deleteFiles": "false",
            # Empêche une liste d'import (Trakt, IMDb, etc.) de rajouter la série.
            "addImportListExclusion": str(ADD_IMPORT_LIST_EXCLUSION).lower(),
        }
        if dry_run:
            exclusion = " et ajoutée aux exclusions des listes d'import" if ADD_IMPORT_LIST_EXCLUSION else ""
            logging.info(f"[DRY_RUN] 🚀 La série '{title}' (ID:{series_id}) serait SUPPRIMÉE{exclusion} car terminée et toutes saisons non monitorées.")
            return
        url = f"{sonarr_url}/api/v3/series/{series_id}"
        try:
            resp = api_request("DELETE", url, headers=headers, params=params)
        except requests.exceptions.RequestException as exc:
            logging.error(f"❌ Erreur réseau lors de la suppression de '{title}' (ID:{series_id}) : {exc}")
            return

        if resp.status_code in (200, 202, 204):
            exclusion = " ; exclusion des listes d'import demandée" if ADD_IMPORT_LIST_EXCLUSION else ""
            logging.info(f"🗑️ Série '{title}' (ID:{series_id}) supprimée{exclusion}.")
            global_stats[instance_name]["series_deleted"] += 1
        else:
            log_api_error(f"❌ Erreur lors de la suppression de la série '{title}' (ID:{series_id})", resp)


if __name__ == "__main__":
    for instance in SONARR_INSTANCES:
        process_instance(instance)

    logging.info(f"🛠️  Version de l'outil : {VERSION}")

    # ======= COMPTE RENDU FINAL =======

    print("\n\033[1;33m========= COMPTE RENDU FINAL =========\033[0m")

    for instance, stats in global_stats.items():
        print(f"\033[1;36m📺 Instance : {instance}\033[0m")
        print(f"    📚 Séries analysées                : {stats['series_processed']}")
        print(f"    🎞️  Épisodes analysés              : {stats['episodes_processed']}")
        print(f"    🎯 Épisodes correspondant critères : {stats['episodes_matching']}")
        print(f"    🔧 Épisodes unmonitorés            : {stats['episodes_unmonitored']}")
        print(f"    ℹ️  Déjà non monitorés              : {stats['episodes_already_unmonitored']}")
        print(f"    📦 Saisons unmonitorées            : {stats['seasons_unmonitored']}")
        print(f"    🗑️  Séries supprimées              : {stats['series_deleted']}")
        print()

    mode = "DRY_RUN (Simulation)" if DRY_RUN else "MODE ACTIF (Modifications réelles)"
    print(f"\033[1;35mMODE : {mode}\033[0m")
    print("========================================\n")



