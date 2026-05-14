import os

from .module_aliases import install_module_aliases


RESET_FILE = os.environ.get("VODUM_RESET_FILE", "/appdata/password.reset")
RESET_MAGIC = os.environ.get("VODUM_RESET_MAGIC", "RECOVER")


def create_app(*args, **kwargs):
    install_module_aliases()
    from .app import create_app as _create_app
    return _create_app(*args, **kwargs)


def _log_ip_filter_status():
    install_module_aliases()
    from .app import _log_ip_filter_status as _real_log_ip_filter_status
    return _real_log_ip_filter_status()