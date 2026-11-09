import os
from pathlib import Path
from zoneinfo import ZoneInfo
from datetime import time
import yaml


def load(path):
    c = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    for env, section, key in [("PLEX_URL", "plex", "url"), ("PLEX_TOKEN", "plex", "token"),
                              ("PLEX_LIBRARY", "plex", "library"), ("TMDB_API_KEY", "tmdb", "api_key"),
                              ("DATABASE_PATH", "database", "path")]:
        if env in os.environ:
            c[section][key] = os.environ[env]
    if not c['plex']['url'] or not c['plex']['token']:
        raise ValueError('PLEX_URL et PLEX_TOKEN obligatoires')
    for key in ('retention_days', 'release_window_days'):
        if not isinstance(c['collection'][key], int) or c['collection'][key] < 1:
            raise ValueError(f'{key} doit être un entier positif')
    if c['exclusions']['manual_removal_cooldown_days'] < 0:
        raise ValueError('Délai exclusion invalide')
    ZoneInfo(c['scheduler']['timezone'])
    schedule = c['scheduler']['daily_time']
    if len(schedule) != 5 or schedule[2] != ':':
        raise ValueError('Horaire attendu au format HH:MM')
    time.fromisoformat(schedule)
    if not isinstance(c['execution']['dry_run'], bool):
        raise ValueError('dry_run doit être un booléen')
    s = c['scoring']
    if s['minimum_votes'] <= 0 or not 0 <= s['high_rating_threshold'] <= 10:
        raise ValueError('Paramètres de notes invalides')
    if any(value < 0 for value in s['weights'].values()) or sum(s['weights'].values()) <= 0:
        raise ValueError('Pondérations invalides')
    if not 0 <= s['min_score'] <= sum(s['weights'].values()):
        raise ValueError('Score minimal invalide')
    if any(value < 0 for value in s['profiles'].values()):
        raise ValueError('Seuils de profils invalides')
    if not 0 <= s['profiles']['trend_strength'] <= 1:
        raise ValueError('Force tendance hors intervalle 0..1')
    if c['logging']['retention_days'] < 1:
        raise ValueError('Rétention journaux invalide')
    return c
