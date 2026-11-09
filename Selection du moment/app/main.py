import argparse
from datetime import datetime, timedelta
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
import signal
import threading
from zoneinfo import ZoneInfo
from filelock import FileLock, Timeout
from .config import load
from .database import Database
from .engine import Engine
from .plex_client import PlexClient
from .discovery import TMDB


def main():
    parser = argparse.ArgumentParser(description='La Sélection du Moment')
    parser.add_argument('--config', default='config/config.yaml')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--run-once', action='store_true')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--cleanup-only', action='store_true')
    modes.add_argument('--populate-only', action='store_true')
    args = parser.parse_args()
    try:
        c = load(args.config)
        logpath = Path(c['logging']['path'])
        logpath.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(level=c['logging']['level'], format='%(asctime)s [%(levelname)s] %(message)s',
            handlers=[logging.StreamHandler(), TimedRotatingFileHandler(logpath, when='midnight',
                       backupCount=c['logging']['retention_days'], encoding='utf-8')])
        # Prevent library HTTP debugging from exposing URLs or secrets.
        for name in ('urllib3', 'requests', 'plexapi'):
            logging.getLogger(name).setLevel(logging.CRITICAL)
        dry = args.dry_run or c['execution']['dry_run']
        mode = 'cleanup' if args.cleanup_only else 'populate' if args.populate_only else 'all'
        stop = threading.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stop.set())

        def cycle():
            path = c['database']['path']
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            try:
                with FileLock(path + '.lock', timeout=0):
                    db = Database(path, dry)
                    try:
                        plex = PlexClient(c['plex'])
                        scope = f"{plex.server.machineIdentifier}:{plex.section.key}:{c['plex']['collection']}"
                        previous = db.query("SELECT value FROM meta WHERE key='scope'")
                        if previous and previous[0]['value'] != scope:
                            raise ValueError('Base associée à une autre collection')
                        db.write("INSERT OR REPLACE INTO meta VALUES('scope',?)", (scope,))
                        result = Engine(c, db, plex, TMDB(c['tmdb']), dry).run(mode)
                        return 1 if any(result[k] in ('failed', 'partial') for k in ('cleanup', 'population')) else 0
                    finally:
                        db.close()
            except Timeout:
                logging.error('Une instance est déjà active')
                return 1
            except Exception:
                logging.error('Cycle impossible : vérifier configuration, Plex et SQLite')
                return 1

        if args.run_once or args.dry_run or args.cleanup_only or args.populate_only or not c['scheduler']['enabled']:
            return cycle()
        zone = ZoneInfo(c['scheduler']['timezone'])
        hour, minute = map(int, c['scheduler']['daily_time'].split(':'))
        while not stop.is_set():
            now = datetime.now(zone)
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            logging.info('Prochain cycle : %s', target.isoformat())
            if not stop.wait(target.timestamp() - now.timestamp()):
                cycle()
        return 0
    except Exception:
        print('Configuration invalide ou inaccessible ; vérifier les paramètres (secrets masqués).')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
