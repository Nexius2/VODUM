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

    # --------------------------------------------------
    # Cache en mémoire
    # --------------------------------------------------
    if lang_code in _I18N_CACHE:
        return _I18N_CACHE[lang_code]

    translations: dict[str, str] = {}

    # --------------------------------------------------
    # Chargement fichiers JSON
    # --------------------------------------------------
    lang_dir = os.path.join(current_app.root_path, "lang")
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

    # --------------------------------------------------
    # Mise en cache
    # --------------------------------------------------
    _I18N_CACHE[lang_code] = translations
    return translations


def get_available_languages():
    lang_dir = os.path.join(current_app.root_path, "lang")
    languages = {}

    for filename in os.listdir(lang_dir):
        if filename.endswith(".json"):
            code = filename[:-5]  # fr.json → fr

            # lire le "language_name" dans le JSON
            try:
                with open(os.path.join(lang_dir, filename), "r", encoding="utf-8") as f:
                    data = json.load(f)
                    name = data.get("language_name", code.upper())
            except:
                name = code.upper()

            languages[code] = name

    return languages


def get_translator():
    logger = get_logger("i18n")

    available_langs = tuple(get_available_languages().keys())

    # --------------------------------------------------
    # 1) Déterminer la langue active (READ ONLY)
    # --------------------------------------------------
    lang = session.get("lang")

    # Si pas de langue en session -> fallback stable (PAS accept-language ici)
    if not lang:
        lang = "en"

    # Sécurité : langue inconnue / invalide
    if lang not in available_langs:
        logger.warning(f"[i18n] Langue invalide '{lang}', fallback en")
        lang = "en"

    # --------------------------------------------------
    # 2) Charger le dictionnaire
    # --------------------------------------------------
    try:
        translations = load_language_dict(lang)
    except Exception as e:
        logger.error(
            f"[i18n] Erreur chargement dictionnaire langue '{lang}': {e}",
            exc_info=True,
        )
        translations = {}

    # --------------------------------------------------
    # 3) Fonction traducteur
    # --------------------------------------------------
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
    # Injecte "t" dans tous les templates Jinja
    @app.context_processor
    def inject_globals():
        """
        Variables globales injectées dans tous les templates Jinja.

        - settings : paramètres globaux
        - t        : fonction de traduction

        Compatible DBManager
        Aucun cursor
        Aucun execute+fetch
        Aucun commit
        """
        db = get_db()

        # READ ONLY via DBManager
        row = db.query_one("SELECT * FROM settings WHERE id = 1")

        # Toujours un dict pour un comportement homogène
        settings = dict(row) if row else {}

        # -----------------------------
        # Sync langue session <- settings (si session vide)
        # -----------------------------
        available_langs = tuple(get_available_languages().keys())

        if not session.get("lang"):
            default_lang = settings.get("default_language")
            if default_lang in available_langs:
                session["lang"] = default_lang

        # Sécurité : si langue invalide, fallback en
        if session.get("lang") not in available_langs:
            session["lang"] = "en"

        return {
            "t": get_translator(),  # <= pas d'argument
            "settings": settings,
        }

    @app.route("/set_language/<lang>")
    def set_language(lang):
        session["lang"] = lang
        return redirect(request.referrer or url_for("dashboard"))
