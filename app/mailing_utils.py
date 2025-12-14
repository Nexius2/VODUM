from datetime import datetime, date

ALLOWED_VARS = {
    "username",
    "email",
    "expiration_date",
    "days_left",
}

def build_user_context(user: dict):
    """
    Construit le contexte de variables pour un utilisateur
    """
    today = date.today()

    expiration = user.get("expiration_date")
    days_left = ""

    if expiration:
        try:
            exp_date = datetime.strptime(expiration, "%Y-%m-%d").date()
            days_left = str((exp_date - today).days)
        except Exception:
            days_left = ""

    return {
        "username": user.get("username", ""),
        "email": user.get("email", ""),
        "expiration_date": expiration or "",
        "days_left": days_left,
    }


def render_mail(text: str, context: dict) -> str:
    """
    Remplace proprement les variables {var}
    - ignore les variables inconnues
    - ne plante jamais
    """
    if not text:
        return ""

    for key in ALLOWED_VARS:
        value = context.get(key, "")
        text = text.replace(f"{{{key}}}", value)

    return text
