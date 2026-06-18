import json
import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

base = (ROOT / "templates/base.html").read_text(encoding="utf-8")
assert base.index("url_for('logs_page')") < base.index("url_for('tasks_page')")

users = (ROOT / "templates/users/users.html").read_text(encoding="utf-8")
detail = (ROOT / "templates/users/partials/_user_general.html").read_text(encoding="utf-8")
actions = (ROOT / "app/routes/users_actions.py").read_text(encoding="utf-8")
presence = (ROOT / "app/core/provider_presence.py").read_text(encoding="utf-8")
assert "u.subscription_role_label or u.expiration_date" in users
assert "expiration_lock.role_label or expiration_lock.label" in detail
assert "get_user_deletion_protection" in actions
assert "plex_owner_cannot_be_deleted" in presence
assert "remove_admin_to_delete" in presence

monitoring = (ROOT / "app/routes/monitoring_overview.py").read_text(encoding="utf-8")
policies = (ROOT / "templates/monitoring/tabs/policies.html").read_text(encoding="utf-8")
assert 'request.args.get("enforcement_page"' in monitoring
assert "LIMIT ? OFFSET ?" in monitoring
assert "policy_enforcement_total_pages" in policies

backup_route = (ROOT / "app/routes/backup.py").read_text(encoding="utf-8")
setup_route = (ROOT / "app/routes/setup_wizard.py").read_text(encoding="utf-8")
restore_task = (ROOT / "app/tasks/restore_backup.py").read_text(encoding="utf-8")
assert 'Path("/appdata/imports")' not in backup_route
assert 'Path("/appdata/imports")' not in setup_route
assert 'Path("/appdata/imports/restore_request_path.txt")' not in restore_task

from core.app_paths import imports_dir  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    os.environ.pop("VODUM_IMPORTS_DIR", None)
    os.environ["DATABASE_PATH"] = str(Path(tmp) / "custom-data" / "database.db")
    assert imports_dir() == (Path(tmp) / "custom-data" / "imports").resolve()
    os.environ["VODUM_IMPORTS_DIR"] = str(Path(tmp) / "override-imports")
    assert imports_dir() == (Path(tmp) / "override-imports").resolve()

dashboard_route = (ROOT / "app/routes/dashboard.py").read_text(encoding="utf-8")
dashboard_live = (ROOT / "app/core/dashboard_now_playing.py").read_text(encoding="utf-8")
dashboard_card = (ROOT / "templates/dashboard/partials/_streams_killed_subscriptions.html").read_text(encoding="utf-8")
assert "load_dashboard_now_playing" in dashboard_route
assert "_task_queue_busy" in dashboard_live
assert '"-30 minutes"' in dashboard_live
assert "2xl:grid-cols" in dashboard_card

for path in sorted((ROOT / "lang").glob("*.json")):
    catalog = json.loads(path.read_text(encoding="utf-8"))
    assert "pseudonym" not in catalog["telemetry_modal_intro"].lower()
    assert "pseudon" not in catalog["telemetry_modal_intro"].lower()
    assert catalog["remove_admin_to_delete"]
    assert catalog["plex_owner_cannot_be_deleted"]
    assert catalog["now_playing_delayed"]
    assert catalog["now_playing_delayed_help"]

print("OK - focused UI/configuration TODO safeguards validated.")
