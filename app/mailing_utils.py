from datetime import datetime, date

# Variables autorisées dans les templates d'email.
# IMPORTANT: toute variable non listée ici est ignorée par render_mail().
ALLOWED_VARS = {
    # legacy
    "username",
    "email",
    "expiration_date",
    "days_left",

    # welcome / personnalisation
    "firstname",
    "lastname",
    "server_name",
    "server_url",
    "login_username",
    "temporary_password",
}


def build_user_context(user: dict):
    """Construit le contexte de variables pour un utilisateur.

    Accepte aussi des champs supplémentaires (firstname/lastname/server_*...),
    utilisés notamment par les emails de bienvenue.
    """
    today = date.today()

    expiration = user.get("expiration_date")
    days_left = ""

    if expiration:
        try:
            exp_date = datetime.fromisoformat(str(expiration)).date()
            days_left = str((exp_date - today).days)
        except Exception:
            days_left = ""

    return {
        "username": user.get("username", "") or "",
        "email": user.get("email", "") or "",
        "expiration_date": str(expiration) if expiration else "",
        "days_left": days_left,

        "firstname": user.get("firstname", "") or "",
        "lastname": user.get("lastname", "") or "",
        "server_name": user.get("server_name", "") or "",
        "server_url": user.get("server_url", "") or "",
        "login_username": user.get("login_username", "") or (user.get("username", "") or ""),
        "temporary_password": user.get("temporary_password", "") or "",
    }


def render_mail(text: str, context: dict) -> str:
    """Remplace proprement les variables {var}.

    - ignore les variables inconnues
    - ne plante jamais
    """
    if not text:
        return ""

    for key in ALLOWED_VARS:
        value = context.get(key, "")
        text = text.replace(f"{{{key}}}", str(value))

    return text
