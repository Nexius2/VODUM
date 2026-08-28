import ast
import json
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from flask import Flask, session
from werkzeug.security import generate_password_hash

APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from routes import plex_auth
from core.plex_auth_client import (
    PlexAuthorizationIncomplete,
    PlexPinExpired,
    PlexServiceUnavailable,
)
from core.plex_auth_flow import PlexFlowExpired, PlexFlowInvalid


class FakeDb:
    def __init__(self):
        self.executed = []
        self.require_totp = 0
        self.server_count = 0
        self.settings = {
            "admin_password_hash": generate_password_hash("local-password"),
            "admin_totp_enabled": 0,
            "admin_totp_secret": None,
        }

    def query_one(self, sql, params=()):
        if "COUNT(*) AS cnt FROM servers" in sql:
            return {"cnt": self.server_count}
        if "FROM settings" in sql:
            return self.settings
        if "FROM admin_accounts" in sql:
            return {
                "plex_client_identifier": "instance-id",
                "plex_require_vodum_totp": self.require_totp,
            }
        return None

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        if "wizard_state_json = ?" in sql:
            self.settings.update({
                "wizard_step": params[0],
                "wizard_state_json": params[1],
                "wizard_active": params[2],
                "wizard_completed": params[3],
            })
        return None


class FakeClient:
    def create_pin(self):
        return SimpleNamespace(id=42, code="strong-code")

    def build_authorization_url(self, pin, callback):
        return "https://app.plex.tv/auth#safe"

    def wait_for_token(self, pin_id):
        return "secret-token"

    def fetch_identity(self, token):
        return SimpleNamespace(
            subject="plex-42",
            username="owner",
            email="owner@example.test",
            display_name="Owner",
        )


class PlexAuthRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__, template_folder=str(APP_DIR.parent / "templates"))
        self.app.secret_key = "test-secret"
        self.app.add_url_rule("/login", "login", lambda: "login")
        self.app.add_url_rule("/settings", "settings_page", lambda: "settings")
        self.app.add_url_rule("/servers", "servers_list", lambda: "servers")
        self.app.add_url_rule("/", "dashboard", lambda: "dashboard")
        self.app.add_url_rule("/setup", "setup_wizard", lambda: "setup")
        plex_auth.register(self.app)
        self.db = FakeDb()

    def _login(self, client):
        with client.session_transaction() as browser_session:
            browser_session["vodum_logged_in"] = True

    def test_link_requires_authenticated_admin_session(self):
        client = self.app.test_client()
        with patch.object(plex_auth, "_client", return_value=FakeClient()) as plex_client:
            response = client.post("/auth/plex/link")
        self.assertEqual("/login", response.location)
        plex_client.assert_not_called()

    def test_authenticated_admin_can_open_plex_without_password_or_totp(self):
        client = self.app.test_client()
        self._login(client)
        with patch.object(plex_auth, "get_db", return_value=self.db), patch.object(
            plex_auth, "_client", return_value=FakeClient()
        ), patch.object(plex_auth, "get_admin_auth_identity", return_value=None), patch.object(
            plex_auth, "encrypt_secret", return_value="encrypted-token"
        ):
            response = client.post("/auth/plex/link")
        self.assertTrue(response.location.startswith("https://app.plex.tv/"))

    def test_rate_limit_blocks_before_calling_plex(self):
        linked = {"id": 7, "provider_subject": "plex-42", "is_active": 1}
        client = self.app.test_client()
        plex_client = FakeClient()
        with patch.object(plex_auth, "get_db", return_value=self.db), patch.object(
            plex_auth, "get_admin_auth_identity", return_value=linked
        ), patch.object(plex_auth, "_plex_locked", return_value=True), patch.object(
            plex_client, "create_pin", wraps=plex_client.create_pin
        ) as create_pin, patch.object(plex_auth, "_client", return_value=plex_client):
            response = client.post("/auth/plex/login")
        self.assertEqual("/login", response.location)
        create_pin.assert_not_called()

    def test_sensitive_rate_limit_scope_is_hashed(self):
        raw = "state-that-must-not-be-stored"
        scope = plex_auth._opaque_scope("plex-state", raw)
        self.assertTrue(scope.startswith("plex-state:"))
        self.assertNotIn(raw, scope)
        self.assertEqual(scope, plex_auth._opaque_scope("plex-state", raw))

    def test_existing_installation_recovers_discovery_token_only_from_same_identity(self):
        db = Mock()
        db.query.return_value = [{"token": "existing-server-token"}]
        linked = {"id": 7, "provider_subject": "plex-42", "is_active": 1}
        with patch.object(plex_auth, "get_admin_auth_discovery_token", return_value=""), patch.object(
            plex_auth, "_client", return_value=FakeClient()
        ), patch.object(plex_auth, "set_admin_auth_discovery_token") as store:
            token = plex_auth.get_or_recover_plex_discovery_token(db, linked)
        self.assertEqual("existing-server-token", token)
        store.assert_called_once_with(db, 7, "existing-server-token")

    def test_auth_route_has_no_media_server_or_provider_dependencies(self):
        source_path = APP_DIR / "routes" / "plex_auth.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported_modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported_modules.append(node.module or "")

        forbidden_fragments = (
            "jellyfin",
            "media_jobs",
            "providers",
            "server_sync",
            "server_admin",
            "plex_sync",
            "plex_connection",
        )
        for module_name in imported_modules:
            self.assertFalse(
                any(fragment in module_name for fragment in forbidden_fragments),
                module_name,
            )

        sql_text = "\n".join(
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        ).lower()
        # Discovery deliberately reads/writes media servers, but authentication
        # must remain independent from media users and background jobs.
        for forbidden_table in ("user_identities", "media_jobs"):
            self.assertNotIn(forbidden_table, sql_text)

    def test_identity_confirmation_is_an_accessible_responsive_modal(self):
        source = (APP_DIR.parent / "templates" / "auth" / "plex_link_confirm.html").read_text(
            encoding="utf-8"
        )
        self.assertIn('role="dialog"', source)
        self.assertIn('aria-modal="true"', source)
        self.assertIn("fixed inset-0", source)
        self.assertIn("sm:flex-row", source)
        self.assertIn("plex_auth_account_detected", source)

    def test_fresh_install_offers_plex_before_leaving_local_account_step(self):
        wizard = (APP_DIR.parent / "templates" / "setup" / "wizard.html").read_text(encoding="utf-8")
        setup_route = (APP_DIR / "routes" / "setup_wizard.py").read_text(encoding="utf-8")
        dockerfile = (APP_DIR.parent / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn('name="admin_auth_method"', wizard)
        self.assertIn('value="plex" checked', wizard)
        self.assertIn("wizard_admin_use_plex_help", wizard)
        self.assertIn('request.form.get("admin_auth_method")', setup_route)
        self.assertIn("return start_wizard_plex_link(db)", setup_route)
        self.assertIn("vodum_wizard_internal_redirect", setup_route)
        self.assertIn('_save(db, step=1, state=state, active=1)', setup_route)
        self.assertIn('name="admin_auth_method"', dockerfile)

    def test_settings_hides_plex_card_without_plex_server_but_wizard_is_unchanged(self):
        settings_route = (APP_DIR / "routes" / "settings.py").read_text(encoding="utf-8")
        settings_card = (APP_DIR.parent / "templates" / "settings" / "partials" / "_settings_system.html").read_text(encoding="utf-8")
        wizard = (APP_DIR.parent / "templates" / "setup" / "wizard.html").read_text(encoding="utf-8")
        self.assertIn("plex_server_configured", settings_route)
        self.assertIn("LOWER(TRIM(type))='plex'", settings_route)
        self.assertIn("{% if plex_server_configured %}", settings_card)
        self.assertIn('name="admin_auth_method"', wizard)
        self.assertNotIn("plex_server_configured", wizard)

    def test_global_auth_guard_does_not_intercept_fresh_wizard_plex_callback(self):
        auth_guard = (APP_DIR / "routes" / "tasks.py").read_text(encoding="utf-8")
        self.assertIn('"/auth/plex/wizard-link"', auth_guard)
        self.assertIn('"/auth/plex/link/callback"', auth_guard)
        self.assertIn('"/auth/plex/link/confirm"', auth_guard)
        self.assertIn("plex_auth_configured", auth_guard)
        self.assertIn("FROM admin_auth_identities", auth_guard)

    def test_all_plex_wizard_returns_use_explicit_resume_contract(self):
        route = (APP_DIR / "routes" / "plex_auth.py").read_text(encoding="utf-8")
        discovery_template = (APP_DIR.parent / "templates" / "servers" / "plex_discovery.html").read_text(encoding="utf-8")
        self.assertIn('url_for("setup_wizard", resume="wizard")', route)
        self.assertIn("wizard_resume_url", discovery_template)
        self.assertNotIn(
            'url_for("setup_wizard" if context.get("return_to") == "wizard" else "servers_list")',
            route,
        )

    def test_discovery_adds_only_confirmed_server_and_honors_preferred_url(self):
        client = self.app.test_client()
        self._login(client)
        with client.session_transaction() as browser_session:
            browser_session[plex_auth.DISCOVERY_SESSION_KEY] = {
                "id": "discovery-1", "nonce": "browser-nonce", "return_to": "servers",
                "expires_at": int(time.time()) + 600,
            }
        candidates = [
            {
                "id": "chosen", "provider_subject": "plex-42",
                "machine_identifier": "machine-1", "access_token": "resource-token",
                "connections": [
                    {"uri": "http://local.test:32400"},
                    {"uri": "https://public.test:32400"},
                ],
            },
            {
                "id": "not-chosen", "provider_subject": "plex-42",
                "machine_identifier": "machine-2", "access_token": "other-token",
                "connections": [{"uri": "https://other.test:32400"}],
            },
        ]
        linked = {"provider_subject": "plex-42", "is_active": 1}
        with patch.object(plex_auth, "get_db", return_value=self.db), patch.object(
            plex_auth, "load_discovery", return_value=candidates
        ), patch.object(plex_auth, "get_admin_auth_identity", return_value=linked), patch.object(
            plex_auth, "create_setup_media_server", return_value={"ok": True, "server_id": 9}
        ) as create, patch.object(plex_auth, "delete_discovery") as delete:
            response = client.post(
                "/auth/plex/discovery/add",
                data={
                    "candidate_id": "chosen",
                    "preferred_url_chosen": "https://public.test:32400",
                },
            )
        self.assertEqual("/servers", response.location)
        create.assert_called_once_with(
            self.db, server_type="plex", url="https://public.test:32400",
            token="resource-token", expected_identifier="machine-1"
        )
        delete.assert_called_once_with(self.db, "discovery-1")

    def test_wizard_discovery_add_resumes_server_step_instead_of_step_one(self):
        client = self.app.test_client()
        self._login(client)
        with client.session_transaction() as browser_session:
            browser_session[plex_auth.DISCOVERY_SESSION_KEY] = {
                "id": "wizard-discovery", "nonce": "browser-nonce", "return_to": "wizard",
                "expires_at": int(time.time()) + 600,
            }
        candidate = {
            "id": "chosen", "provider_subject": "plex-42",
            "machine_identifier": "machine-1", "access_token": "resource-token",
            "connections": [{"uri": "https://public.test:32400"}],
        }
        linked = {"provider_subject": "plex-42", "is_active": 1}
        with patch.object(plex_auth, "get_db", return_value=self.db), patch.object(
            plex_auth, "load_discovery", return_value=[candidate]
        ), patch.object(plex_auth, "get_admin_auth_identity", return_value=linked), patch.object(
            plex_auth, "create_setup_media_server", return_value={"ok": True, "server_id": 9}
        ), patch.object(plex_auth, "delete_discovery"), patch.object(
            plex_auth, "record_setup_media_servers"
        ) as record:
            response = client.post(
                "/auth/plex/discovery/add",
                data={"candidate_id": "chosen", "preferred_url_chosen": "https://public.test:32400"},
            )
        self.assertEqual("/setup?resume=wizard", response.location)
        record.assert_called_once_with(self.db, [9])

    def test_discovery_refuses_results_from_a_different_linked_identity(self):
        client = self.app.test_client()
        self._login(client)
        with client.session_transaction() as browser_session:
            browser_session[plex_auth.DISCOVERY_SESSION_KEY] = {
                "id": "discovery-1", "nonce": "browser-nonce", "return_to": "servers",
                "expires_at": int(time.time()) + 600,
            }
        candidates = [{
            "id": "chosen", "provider_subject": "old-plex-account",
            "machine_identifier": "machine-1", "access_token": "resource-token",
            "connections": [{"uri": "https://public.test:32400"}],
        }]
        linked = {"provider_subject": "new-plex-account", "is_active": 1}
        with patch.object(plex_auth, "get_db", return_value=self.db), patch.object(
            plex_auth, "load_discovery", return_value=candidates
        ), patch.object(plex_auth, "get_admin_auth_identity", return_value=linked), patch.object(
            plex_auth, "create_setup_media_server"
        ) as create, patch.object(
            plex_auth, "delete_discovery"
        ):
            client.post("/auth/plex/discovery/add", data={"candidate_id": "chosen"})
        create.assert_not_called()

    def test_expired_discovery_is_deleted_and_redirected_safely(self):
        client = self.app.test_client()
        self._login(client)
        with client.session_transaction() as browser_session:
            browser_session[plex_auth.DISCOVERY_SESSION_KEY] = {
                "id": "expired-search", "nonce": "browser-nonce",
                "return_to": "servers", "expires_at": 1,
            }
        with patch.object(plex_auth, "get_db", return_value=self.db), patch.object(
            plex_auth, "delete_discovery"
        ) as delete:
            response = client.get("/auth/plex/discovery/results")
        self.assertEqual("/servers", response.location)
        delete.assert_called_once_with(self.db, "expired-search")

    def test_discovery_continues_after_one_server_raises(self):
        client = self.app.test_client()
        self._login(client)
        with client.session_transaction() as browser_session:
            browser_session[plex_auth.DISCOVERY_SESSION_KEY] = {
                "id": "discovery-1", "nonce": "browser-nonce",
                "return_to": "servers", "expires_at": int(time.time()) + 600,
            }
        candidates = [
            {"id": "first", "provider_subject": "plex-42"},
            {"id": "second", "provider_subject": "plex-42"},
        ]
        linked = {"id": 7, "provider_subject": "plex-42", "is_active": 1}
        with patch.object(plex_auth, "get_db", return_value=self.db), patch.object(
            plex_auth, "load_discovery", return_value=candidates
        ), patch.object(plex_auth, "get_admin_auth_identity", return_value=linked), patch.object(
            plex_auth, "_add_discovered_server",
            side_effect=[RuntimeError("safe failure"), ("added", 9)],
        ) as add, patch.object(plex_auth, "delete_discovery"):
            response = client.post(
                "/auth/plex/discovery/add",
                data={"candidate_id": ["first", "second"]},
            )
        self.assertEqual("/servers", response.location)
        self.assertEqual(2, add.call_count)

    def test_callback_errors_have_specific_safe_messages(self):
        cases = (
            (PlexFlowExpired("expired"), "plex_auth_error_session_expired", 400),
            (PlexFlowInvalid("replay"), "plex_auth_error_session_invalid", 400),
            (PlexPinExpired("pin"), "plex_auth_error_pin_expired", 400),
            (PlexAuthorizationIncomplete("cancel"), "plex_auth_error_cancelled", 400),
            (PlexServiceUnavailable("network"), "plex_auth_error_network", 502),
        )
        for error, expected_key, expected_status in cases:
            with self.subTest(error=type(error).__name__):
                self.assertEqual(
                    (expected_key, expected_status),
                    plex_auth._plex_callback_error_key(error),
                )

    def test_fresh_wizard_plex_only_flow_opens_session_and_returns_to_wizard(self):
        client = self.app.test_client()
        self.db.settings.update({
            "wizard_active": 1,
            "wizard_step": 3,
            "wizard_state_json": '{"administrator":"plex_pending"}',
            "admin_email": "",
        })
        with patch.object(plex_auth, "get_db", return_value=self.db), patch.object(
            plex_auth, "_client", return_value=FakeClient()
        ), patch.object(plex_auth, "get_admin_auth_identity", return_value=None), patch.object(
            plex_auth, "encrypt_secret", return_value="encrypted-token"
        ):
            start = client.post("/auth/plex/wizard-link")
            self.assertTrue(start.location.startswith("https://app.plex.tv/"))
            with client.session_transaction() as browser_session:
                state = browser_session["vodum_plex_auth_flow"]["state"]
            with patch.object(plex_auth, "render_template", return_value="confirm"):
                callback = client.get(
                    "/auth/plex/link/callback", query_string={"state": state}
                )
            self.assertEqual(b"confirm", callback.data)
            with patch.object(
                plex_auth, "link_admin_auth_identity", return_value={"id": 9}
            ), patch.object(plex_auth, "decrypt_secret", return_value="secret-token"), patch.object(
                plex_auth, "set_admin_auth_discovery_token"
            ):
                confirmed = client.post("/auth/plex/link/confirm")
        self.assertEqual("/setup?resume=plex", confirmed.location)
        with client.session_transaction() as browser_session:
            self.assertEqual("admin", browser_session["vodum_principal"]["role"])
            self.assertEqual("owner@example.test", browser_session["vodum_principal"]["email"])

    def test_fresh_wizard_callback_survives_lost_browser_session(self):
        client = self.app.test_client()
        self.db.settings.update({
            "wizard_active": 1,
            "wizard_completed": 0,
            "wizard_step": 3,
            "wizard_state_json": '{"administrator":"plex_pending"}',
        })
        with patch.object(plex_auth, "get_db", return_value=self.db), patch.object(
            plex_auth, "_client", return_value=FakeClient()
        ), patch.object(plex_auth, "get_admin_auth_identity", return_value=None), patch.object(
            plex_auth, "encrypt_secret", return_value="encrypted-token"
        ):
            start = client.post("/auth/plex/wizard-link")
            self.assertTrue(start.location.startswith("https://app.plex.tv/"))
            stored_state = json.loads(self.db.settings["wizard_state_json"])["plex_link_flow"]
            with client.session_transaction() as browser_session:
                returned_state = browser_session["vodum_plex_auth_flow"]["state"]
                browser_session.clear()
            # The raw state remains only in Plex's callback URL; VODUM stores a hash.
            self.assertEqual(
                stored_state["state_hash"],
                plex_auth.hashlib.sha256(returned_state.encode()).hexdigest(),
            )
            with patch.object(plex_auth, "render_template", return_value="confirm"):
                callback = client.get(
                    "/auth/plex/link/callback", query_string={"state": returned_state}
                )
            self.assertEqual(b"confirm", callback.data)
            with client.session_transaction() as browser_session:
                self.assertEqual(
                    "plex-42",
                    browser_session[plex_auth.PENDING_IDENTITY_KEY]["subject"],
                )

    def test_callback_keeps_public_identity_but_not_token_in_session(self):
        client = self.app.test_client()
        self._login(client)
        with patch.object(plex_auth, "get_db", return_value=self.db), patch.object(
            plex_auth, "_client", return_value=FakeClient()
        ), patch.object(plex_auth, "encrypt_secret", return_value="encrypted-token"):
            start = client.post(
                "/auth/plex/link", data={"current_password": "local-password"}
            )
            self.assertTrue(start.location.startswith("https://app.plex.tv/"))
            with client.session_transaction() as browser_session:
                state = browser_session["vodum_plex_auth_flow"]["state"]
            with patch.object(plex_auth, "render_template", return_value="confirm"):
                callback = client.get(
                    "/auth/plex/link/callback", query_string={"state": state}
                )
        self.assertEqual(b"confirm", callback.data)
        with client.session_transaction() as browser_session:
            pending = browser_session[plex_auth.PENDING_IDENTITY_KEY]
            self.assertEqual("plex-42", pending["subject"])
            self.assertNotIn("secret-token", repr(dict(browser_session)))
        self.assertTrue(
            any(
                "DELETE FROM auth_login_attempts" in sql
                and params
                and str(params[-1]).startswith("plex-state:")
                for sql, params in self.db.executed
            )
        )

    def test_confirmation_is_one_shot(self):
        client = self.app.test_client()
        self._login(client)
        with client.session_transaction() as browser_session:
            browser_session[plex_auth.PENDING_IDENTITY_KEY] = {
                "subject": "plex-42", "display_name": "Owner", "email": ""
            }
        linked = {"id": 8}
        with patch.object(plex_auth, "get_db", return_value=self.db), patch.object(
            plex_auth, "link_admin_auth_identity", return_value=linked
        ) as link:
            first = client.post("/auth/plex/link/confirm")
            second = client.post("/auth/plex/link/confirm")
        self.assertEqual("/settings", first.location)
        self.assertEqual("/settings", second.location)
        link.assert_called_once()

    def test_authenticated_unlink_is_one_provider_only(self):
        client = self.app.test_client()
        self._login(client)
        with patch.object(plex_auth, "get_db", return_value=self.db), patch.object(
            plex_auth, "unlink_admin_auth_identity", return_value=True
        ) as unlink:
            response = client.post("/auth/plex/unlink")
        self.assertEqual("/settings", response.location)
        unlink.assert_called_once_with(self.db, provider="plex")
        self.assertTrue(
            all(
                forbidden not in sql.lower()
                for sql, _params in self.db.executed
                for forbidden in ("servers", "user_identities", "media_jobs")
            )
        )

    def test_plex_login_requires_exact_linked_subject_and_skips_vodum_totp(self):
        linked = {
            "id": 7,
            "provider_subject": "plex-42",
            "is_active": 1,
        }
        self.db.settings.update({"admin_email": "admin@example.test", "wizard_active": 0})
        client = self.app.test_client()
        with patch.object(plex_auth, "get_db", return_value=self.db), patch.object(
            plex_auth, "_client", return_value=FakeClient()
        ), patch.object(plex_auth, "get_admin_auth_identity", return_value=linked):
            start = client.post("/auth/plex/login")
            with client.session_transaction() as browser_session:
                state = browser_session["vodum_plex_auth_flow"]["state"]
            callback = client.get(
                "/auth/plex/login/callback", query_string={"state": state}
            )
        self.assertEqual("/", callback.location)
        with client.session_transaction() as browser_session:
            self.assertEqual("admin", browser_session["vodum_principal"]["role"])
            self.assertEqual("admin@example.test", browser_session["vodum_principal"]["email"])
            self.assertNotIn(plex_auth.PENDING_LOGIN_KEY, browser_session)

    def test_plex_login_repairs_stale_wizard_flag_on_configured_instance(self):
        linked = {"id": 7, "provider_subject": "plex-42", "is_active": 1}
        self.db.server_count = 1
        self.db.settings.update({
            "admin_email": "admin@example.test",
            "wizard_active": 1,
            "wizard_completed": 0,
        })
        client = self.app.test_client()
        with patch.object(plex_auth, "get_db", return_value=self.db), patch.object(
            plex_auth, "_client", return_value=FakeClient()
        ), patch.object(plex_auth, "get_admin_auth_identity", return_value=linked):
            client.post("/auth/plex/login")
            with client.session_transaction() as browser_session:
                state = browser_session["vodum_plex_auth_flow"]["state"]
            callback = client.get(
                "/auth/plex/login/callback", query_string={"state": state}
            )

        self.assertEqual("/", callback.location)
        self.assertTrue(any(
            "wizard_active = 0, wizard_completed = 1" in sql
            for sql, _params in self.db.executed
        ))

    def test_plex_login_rejects_another_plex_account(self):
        linked = {"id": 7, "provider_subject": "different", "is_active": 1}
        client = self.app.test_client()
        with patch.object(plex_auth, "get_db", return_value=self.db), patch.object(
            plex_auth, "_client", return_value=FakeClient()
        ), patch.object(plex_auth, "get_admin_auth_identity", return_value=linked):
            start = client.post("/auth/plex/login")
            with client.session_transaction() as browser_session:
                state = browser_session["vodum_plex_auth_flow"]["state"]
            with patch.object(plex_auth, "render_template", return_value="error"):
                callback = client.get(
                    "/auth/plex/login/callback", query_string={"state": state}
                )
        self.assertEqual(403, callback.status_code)
        self.assertEqual(b"error", callback.data)
        with client.session_transaction() as browser_session:
            self.assertNotIn("vodum_logged_in", browser_session)

    def test_optional_vodum_totp_delays_session_until_valid_code(self):
        linked = {"id": 7, "provider_subject": "plex-42", "is_active": 1}
        self.db.require_totp = 1
        self.db.settings.update({
            "admin_email": "admin@example.test",
            "wizard_active": 0,
            "admin_totp_enabled": 1,
            "admin_totp_secret": "secret",
        })
        client = self.app.test_client()
        with patch.object(plex_auth, "get_db", return_value=self.db), patch.object(
            plex_auth, "_client", return_value=FakeClient()
        ), patch.object(plex_auth, "get_admin_auth_identity", return_value=linked):
            client.post("/auth/plex/login")
            with client.session_transaction() as browser_session:
                state = browser_session["vodum_plex_auth_flow"]["state"]
            with patch.object(plex_auth, "render_template", return_value="totp"):
                callback = client.get(
                    "/auth/plex/login/callback", query_string={"state": state}
                )
            self.assertEqual(b"totp", callback.data)
            with client.session_transaction() as browser_session:
                self.assertNotIn("vodum_logged_in", browser_session)
            with patch.object(plex_auth, "verify_totp_code", return_value=True):
                completed = client.post(
                    "/auth/plex/login/totp", data={"totp_code": "123456"}
                )
        self.assertEqual("/", completed.location)
        with client.session_transaction() as browser_session:
            self.assertEqual("admin", browser_session["vodum_principal"]["role"])


if __name__ == "__main__":
    unittest.main()
