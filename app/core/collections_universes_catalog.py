"""The curated movie franchises supported by VODUM."""
import json
from pathlib import Path

CATALOG = json.loads((Path(__file__).resolve().parents[1] / 'data' / 'franchise_universes.json').read_text(encoding='utf-8'))
UNIVERSES = CATALOG['universes']
