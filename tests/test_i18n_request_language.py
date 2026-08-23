import importlib
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

os.environ.setdefault("VODUM_LOG_DIR", tempfile.mkdtemp(prefix="vodum-test-logs-"))

from flask import Flask
sys.modules.pop("core.i18n", None)
sys.modules.pop("core", None)
i18n = importlib.import_module("core.i18n")


class I18nRequestLanguageTests(unittest.TestCase):
    def setUp(self):
        i18n._I18N_CACHE.clear()
        i18n._AVAILABLE_LANGUAGES_CACHE = None
        self.app = Flask(__name__)
        self.app.secret_key = "test"
        self.app.config["LANG_DIR"] = str(ROOT / "translations" / "ui")

    def test_translator_without_settings_uses_ui_language_before_browser_language(self):
        class FakeDB:
            def query_one(self, *_args, **_kwargs):
                return {"default_language": "en"}

        helpers = types.ModuleType("web.helpers")
        helpers.get_db = lambda: FakeDB()

        with self.app.test_request_context("/communications/configuration/action", headers={"Accept-Language": "fr"}):
            with patch.dict(sys.modules, {"web.helpers": helpers}):
                self.assertEqual(i18n.get_translator()("comm_retry_scheduled_success"), "Retry scheduled.")

    def test_missing_active_language_key_falls_back_to_english(self):
        english = {"fallback.only": "English fallback"}
        spanish = {}

        with self.app.test_request_context("/"):
            with patch.object(
                i18n,
                "load_language_dict",
                side_effect=lambda language: english if language == "en" else spanish,
            ):
                translator = i18n.get_translator({"default_language": "es"})
            self.assertEqual("English fallback", translator("fallback.only"))
            self.assertEqual("unknown.translation.key", translator("unknown.translation.key"))


if __name__ == "__main__":
    unittest.main()
