from .module_aliases import install_module_aliases


def create_app(*args, **kwargs):
    install_module_aliases()
    from .app import create_app as _create_app
    return _create_app(*args, **kwargs)