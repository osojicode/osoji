"""Package init exercising re-export detection."""

import pkg.sub
from os import path
from .core import api_func, helper as public_helper
from .core import _internal

CONSTANT_IN_INIT = "init-constant"
