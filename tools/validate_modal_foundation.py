"""Validate the shared modal lifecycle and accessibility foundation."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
manager = (ROOT / "static" / "js" / "modal_manager.js").read_text(encoding="utf-8")
base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
base_embed = (ROOT / "templates" / "base_embed.html").read_text(encoding="utf-8")

for required in (
    '".fixed.inset-0.z-50"',
    'setAttribute("role"',
    'setAttribute("aria-modal", "true")',
    'setAttribute("aria-hidden"',
    '"overflow-hidden"',
    'focus({ preventScroll: true })',
    'event.key !== "Escape"',
    "MutationObserver",
    '"htmx:load"',
    "window.VodumModal",
):
    assert required in manager, f"modal manager is missing {required}"

for name, source in (("base", base), ("base_embed", base_embed)):
    assert "js/modal_manager.js" in source, f"{name} does not load modal manager"

modal_roots = []
pattern = re.compile(r'class="[^"]*fixed[^"]*inset-0[^"]*z-50[^"]*"')
for path in sorted((ROOT / "templates").rglob("*.html")):
    count = len(pattern.findall(path.read_text(encoding="utf-8")))
    if count:
        modal_roots.extend([str(path.relative_to(ROOT))] * count)

assert len(modal_roots) >= 15, "modal inventory unexpectedly small"

print(
    "OK - shared modal lifecycle covers "
    f"{len(modal_roots)} full-screen modal roots across {len(set(modal_roots))} templates."
)
