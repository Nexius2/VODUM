# Auto-split from app.py (keep URLs/endpoints intact)
import platform
from importlib.metadata import version

from flask import render_template

from web.helpers import get_db, scheduler_db_provider, table_exists

def register(app):
    @app.route("/about")
    def about_page():
        flask_version = version("flask")
        python_version = platform.python_version()
        os_info = f"{platform.system()} {platform.release()}-{platform.version()}"
        
        return render_template(
            "about/about.html",
            flask_version=flask_version,
            python_version=python_version,
            os_info=os_info,
            active_page="about"
        )




    # Expose helpers pour d’éventuels scripts internes
    app.get_db = get_db
    app.table_exists = table_exists
    app.scheduler_db_provider = scheduler_db_provider


    return app




