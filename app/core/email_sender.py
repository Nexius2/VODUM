"""Compatibility shim (refactor)

Some modules under app.core.* historically imported sibling helpers like:
  from ..logging_utils import get_logger
which resolves to app.core.logging_utils.

After the refactor, the canonical modules live at app.email_sender.
This shim keeps old relative imports working without changing behavior.
"""

from email_sender import *  # noqa: F401,F403
