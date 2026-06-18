from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

mailing = (ROOT / "app/mailing_utils.py").read_text(encoding="utf-8")
enforcer = (ROOT / "app/tasks/stream_enforcer.py").read_text(encoding="utf-8")
upgrade = (ROOT / "app/tasks/usage_risk_notifications.py").read_text(encoding="utf-8")
scheduled = (ROOT / "app/tasks/send_expiration_emails.py").read_text(encoding="utf-8")
history_route = (ROOT / "app/routes/communications.py").read_text(encoding="utf-8")
history_template = (ROOT / "templates/communications/communications_history.html").read_text(encoding="utf-8")

variables = (
    "stream_killed", "other_streams", "other_streams_count", "all_streams",
    "stream_count", "ip_count", "policy_limit", "policy_observed",
    "maximum_streams", "maximum_ips",
)
for variable in variables:
    assert f'"{variable}"' in mailing
    assert f'"{variable}"' in enforcer

assert "schedule_template_notification" in upgrade
assert "send_to_user" not in upgrade
assert 'enqueue_named_task(db, "send_expiration_emails")' in upgrade
assert 'trigger_event == "usage_risk_upgrade_suggestion"' in scheduled
assert "usage_risk_recommendations" in scheduled

assert "communication_summary" in history_route
assert "comm_summary_email" in history_template
assert "comm_summary_discord" in history_template

print("OK - policy context, upgrade retries and channel summary are unified.")
