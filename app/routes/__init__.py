def register_routes(app):
    """
    Enregistre toutes les routes de l'application.
    Chaque module expose une fonction register(app).
    """

    from . import (
        about,
        auth,
        backup,
        communications,
        dashboard,
        logs,
        monitoring_api,
        monitoring_overview,
        monitoring_user,
        servers,
        settings,
        subscriptions_page,
        tasks,
        tasks_api,
        users_actions,
        users_detail,
        users_list,
    )

    modules = [
        about,
        auth,
        backup,
        communications,
        dashboard,
        logs,
        monitoring_api,
        monitoring_overview,
        monitoring_user,
        servers,
        settings,
        subscriptions_page,
        tasks,
        tasks_api,
        users_actions,
        users_detail,
        users_list,
    ]

    for module in modules:
        if hasattr(module, "register"):
            module.register(app)