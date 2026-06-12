from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"

legacy_workers = (
    "send_mail_campaigns",
    "send_campaign_discord",
    "send_expiration_discord",
)

for worker in legacy_workers:
    assert not (APP / "tasks" / f"{worker}.py").exists(), f"legacy worker still exists: {worker}"

bootstrap = (APP / "db_bootstrap.py").read_text(encoding="utf-8")
check_status = (APP / "tasks" / "check_mailing_status.py").read_text(encoding="utf-8")
tasks_route = (APP / "routes" / "tasks.py").read_text(encoding="utf-8")

assert "DELETE FROM tasks" in bootstrap
for worker in legacy_workers:
    assert f"'name': '{worker}'" not in bootstrap
    assert f'"name": "{worker}"' not in bootstrap
    assert f'"{worker}":' not in check_status
    assert worker not in check_status
    assert f'"{worker}"' not in tasks_route

assert '"send_expiration_emails": 1 if (email_ok or discord_ok) else 0' in check_status
assert '"send_comm_campaigns": 1 if (email_ok or discord_ok) else 0' in check_status

print("OK - Communications uses only the unified scheduled and campaign workers.")
