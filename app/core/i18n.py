# app/core/i18n.py
from __future__ import annotations

import json
import os
from typing import Callable, Dict, Optional

from flask import session, redirect, url_for, request, current_app
from logging_utils import get_logger


# Cache global pour éviter de relire les JSON à chaque requête
_I18N_CACHE: Dict[str, Dict] = {}


# ======================
#   MULTILINGUAL SYSTEM
# ======================
def load_language_dict(lang_code: str) -> dict:
    """
    Charge le dictionnaire de traduction pour une langue donnée.

    - Source unique : fichiers JSON du dossier lang/
    - Mise en cache en mémoire par langue
    """
    logger = get_logger("i18n")

    if lang_code in _I18N_CACHE:
        return _I18N_CACHE[lang_code]

    translations: dict[str, str] = {}

    lang_dir = current_app.config.get("LANG_DIR") or os.path.join(current_app.root_path, "lang")
    json_path = os.path.join(lang_dir, f"{lang_code}.json")

    if not os.path.exists(json_path):
        logger.warning(f"[i18n] Fichier de langue introuvable: {json_path}")
        _I18N_CACHE[lang_code] = translations
        return translations

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            translations.update(data)
            logger.debug(
                f"[i18n] {len(translations)} traductions chargées depuis fichier ({lang_code})"
            )

    except Exception as e:
        logger.error(
            f"[i18n] Erreur lecture fichier langue {json_path}: {e}",
            exc_info=True,
        )

    _I18N_CACHE[lang_code] = translations
    return translations


def get_available_languages():
    logger = get_logger("i18n")
    lang_dir = current_app.config.get("LANG_DIR") or os.path.join(current_app.root_path, "lang")
    languages = {}

    if not os.path.isdir(lang_dir):
        logger.warning(f"[i18n] Dossier de langues introuvable: {lang_dir}")
        return {"en": "English"}

    for filename in os.listdir(lang_dir):
        if filename.endswith(".json"):
            code = filename[:-5]  # fr.json → fr

            try:
                with open(os.path.join(lang_dir, filename), "r", encoding="utf-8") as f:
                    data = json.load(f)
                    name = data.get("language_name", code.upper())
            except Exception as e:
                logger.warning(
                    f"[i18n] Impossible de lire le nom de langue pour {filename}: {e}",
                    exc_info=True,
                )
                name = code.upper()

            languages[code] = name

    if not languages:
        languages["en"] = "English"

    return languages


def _resolve_active_language(settings: Optional[dict] = None) -> str:
    """
    Priorité :
    1. session["lang"]
    2. langue du navigateur (Accept-Language)
    3. settings.default_language
    4. en
    """
    logger = get_logger("i18n")
    available_langs = tuple(get_available_languages().keys())

    session_lang = session.get("lang")
    if session_lang in available_langs:
        return session_lang

    browser_lang = None
    try:
        browser_lang = request.accept_languages.best_match(available_langs)
    except Exception as e:
        logger.warning(f"[i18n] Impossible de lire Accept-Language: {e}", exc_info=True)

    if browser_lang in available_langs:
        return browser_lang

    default_lang = (settings or {}).get("default_language")
    if default_lang in available_langs:
        return default_lang

    if "en" in available_langs:
        return "en"

    return available_langs[0]


def get_translator(settings: Optional[dict] = None):
    logger = get_logger("i18n")

    lang = _resolve_active_language(settings)

    try:
        translations = load_language_dict(lang)
    except Exception as e:
        logger.error(
            f"[i18n] Erreur chargement dictionnaire langue '{lang}': {e}",
            exc_info=True,
        )
        translations = {}

    def _translate(key: str):
        if not key:
            return ""
        return translations.get(key, key)

    return _translate


def init_i18n(app, get_db: Callable[[], object]) -> None:
    """
    Initialise l'i18n pour l'app Flask:
    - injecte t() et settings dans tous les templates
    - expose la route /set_language/<lang>
    """
    @app.context_processor
    def inject_globals():
        """
        Variables globales injectées dans tous les templates Jinja.

        - settings : paramètres globaux
        - t        : fonction de traduction
        """
        db = get_db()

        row = db.query_one("SELECT * FROM settings WHERE id = 1")
        settings = dict(row) if row else {}

        lang = _resolve_active_language(settings)
        session["lang"] = lang

        return {
            "t": get_translator(settings),
            "settings": settings,
        }

    @app.route("/set_language/<lang>")
    def set_language(lang):
        available_langs = tuple(get_available_languages().keys())

        if lang in available_langs:
            session["lang"] = lang
        else:
            get_logger("i18n").warning(f"[i18n] Tentative de langue invalide: {lang}")

        return redirect(request.referrer or url_for("dashboard"))