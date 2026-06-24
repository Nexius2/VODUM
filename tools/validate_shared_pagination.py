"""Validate adoption of the shared server-rendered pagination component."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "templates" / "partials" / "_pagination.html"

shared = SHARED.read_text(encoding="utf-8")
for required in (
    'pagination.first_url',
    'pagination.prev_url',
    'pagination.next_url',
    'pagination.last_url',
    'pagination.unit_label',
    'aria-label=',
):
    assert required in shared, f"shared pagination is missing {required}"

monitoring = (ROOT / "templates" / "monitoring" / "partials" / "_pagination.html").read_text(
    encoding="utf-8"
)
communications = (
    ROOT / "templates" / "communications" / "communications_history.html"
).read_text(encoding="utf-8")
applications = (
    ROOT / "templates" / "subscriptions" / "_applications.html"
).read_text(encoding="utf-8")
users = (ROOT / "templates" / "users" / "users.html").read_text(encoding="utf-8")
logs = (ROOT / "templates" / "logs" / "logs.html").read_text(encoding="utf-8")

for name, source in (
    ("monitoring", monitoring),
    ("communications history", communications),
    ("subscription applications", applications),
    ("user lists", users),
    ("logs", logs),
):
    assert 'partials/_pagination.html' in source, f"{name} bypasses shared pagination"

assert "pagination.first_url" not in monitoring, "monitoring wrapper duplicates pagination markup"
assert "applications_page > 1" not in applications, "applications retains manual pagination"
assert "page > 1" not in communications, "communications retains manual pagination"
assert users.count('partials/_pagination.html') == 2, "both user lists must share pagination"
assert "Page {{ page }}" not in users, "user lists retain manual pagination summary"
assert "page_window_start" in logs, "logs must preserve their numbered page window"
assert "numbered_pages" in shared, "shared pagination must support numbered windows"
assert 'href="?page=' not in logs, "logs retain manual pagination links"

print("OK - shared pagination covers monitoring, communications, subscriptions, users and logs.")
