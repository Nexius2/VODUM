"""Compatibility shim (refactor)

Some modules under app.core.* historically imported sibling helpers like:
  from ..logging_utils import get_logger
which resolves to app.core.logging_utils.

After the refactor, the canonical modules live at app.mailing_utils.
This shim keeps old relative imports working without changing behavior.
"""

from mailing_utils import *  # noqa: F401,F403
