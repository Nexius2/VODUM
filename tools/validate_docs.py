"""Validate MkDocs navigation, internal links and deployment references."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = ROOT / "vodum-docs"
DOCS = DOCS_ROOT / "docs"
config = (DOCS_ROOT / "mkdocs.yml").read_text(encoding="utf-8")
pages = sorted(DOCS.glob("*.md"))
assert pages

nav_pages = set(re.findall(r":\s+([a-z0-9-]+\.md)\s*$", config, flags=re.MULTILINE))
for required in (
    "index.md", "getting-started.md", "dashboard.md", "monitoring.md",
    "users.md", "servers-libraries.md", "subscriptions.md",
    "communications.md", "migrations.md", "backup.md", "settings.md",
    "logs.md", "tasks.md", "configuration.md", "architecture.md",
    "security.md", "troubleshooting.md", "faq.md", "about.md",
):
    assert required in nav_pages, f"Page missing from MkDocs navigation: {required}"

corpus = []
for page in pages:
    text = page.read_text(encoding="utf-8")
    corpus.append(text)
    assert len(re.findall(r"^# ", text, flags=re.MULTILINE)) == 1, f"Expected one H1: {page.name}"
    for mojibake in ("ðŸ", "Ã©", "â†", "/app/data"):
        assert mojibake not in text, f"Obsolete or broken text in {page.name}: {mojibake}"
    for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        local = target.split("#", 1)[0]
        assert (page.parent / local).exists(), f"Broken link in {page.name}: {target}"
    for target in re.findall(r'<img[^>]+src="([^"#:?]+)"', text):
        assert (page.parent / target).exists(), f"Broken image in {page.name}: {target}"

all_text = "\n".join(corpus)
for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        key = line.split("=", 1)[0]
        assert key in all_text, f"Deployment variable missing from docs: {key}"

print(f"OK - {len(pages)} documentation pages, navigation, links and variables validated.")
