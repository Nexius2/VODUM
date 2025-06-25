from flask import Flask, g, render_template_string
import os
import json

app = Flask(__name__)

def load_translations(lang_code):
    path = os.path.join(os.path.dirname(__file__), "..", "lang", f"{lang_code}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ Erreur de chargement des traductions ({lang_code}): {e}")
        return {}

@app.before_request
def load_lang():
    g.translations = load_translations("fr")

@app.context_processor
def inject_translation():
    def _(key):
        return g.get("translations", {}).get(key, f"[{key}]")
    return dict(_=_)

@app.route("/")
def index():
    return render_template_string("""
    <html>
    <body>
        <h1>{{ _('settings') }}</h1>
        <p>{{ _('smtp_gmail') }}</p>
        <p>{{ _('smtp_choose') }}</p>
        <p>{{ _('yes') }} / {{ _('no') }}</p>
    </body>
    </html>
    """)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
