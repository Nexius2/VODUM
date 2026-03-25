# /app/run.py
import os

from app import create_app, _log_ip_filter_status
from tasks_engine import start_scheduler


app = create_app()

# Evite le double démarrage du scheduler avec le reloader Werkzeug
if (not app.debug) or (os.environ.get("WERKZEUG_RUN_MAIN") == "true"):
    with app.app_context():
        start_scheduler()


if __name__ == "__main__":
    _log_ip_filter_status()
    app.run(host="0.0.0.0", port=5000, use_reloader=False)