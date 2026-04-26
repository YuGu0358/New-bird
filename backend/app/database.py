"""Backward-compat shim. New code should import from app.db directly."""
from app.db import *  # noqa: F401, F403
from app.db import __all__  # noqa: F401
