# /app/run.py
import os

from app import create_app, _log_ip_filter_status
from tasks_engine import start_scheduler


"""
Chaîne réelle de démarrage VODUM

1. entrypoint.sh
   - crée la DB si absente via tables.sql
   - détecte une éventuelle ancienne DB V1
   - applique la migration V1 -> V2 si nécessaire
   - applique le fix FK legacy si nécessaire
   - lance db_bootstrap.py (idempotent)

2. run.py
   - crée l'application Flask via create_app()
   - démarre le scheduler UNE seule fois
   - démarre ensuite le serveur Flask

3. app/app.py -> create_app()
   - configure Flask, templates, static, i18n, csrf, trust proxy
   - enregistre blueprints et routes
   - exécute ensuite les boot fixes via _run_startup_boot_fixes(app)

4. _run_startup_boot_fixes(app)
   - startup_admin_recover_if_requested(app)
   - _reset_maintenance_on_startup(app)
   - run_repair_if_needed(...)
"""

app = create_app()

# Évite le double démarrage du scheduler avec le reloader Werkzeug
if (not app.debug) or (os.environ.get("WERKZEUG_RUN_MAIN") == "true"):
    with app.app_context():
        start_scheduler()


if __name__ == "__main__":
    _log_ip_filter_status()
    app.run(host="0.0.0.0", port=5000, use_reloader=False)