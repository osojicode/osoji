"""Relative imports across levels plus cross-file call sites."""

from . import sibling
from .sibling import sibling_func
from ..core import api_func, helper as h
from ..strings import classify
from pkg.core import Service
from mypkg.tool import tool_func
import pkg.decorated
from external_lib import missing_func
from ..core import *


def use_everything():
    first = api_func("payload-one")
    second = api_func("payload-two", mode="lenient-mode")
    h()
    sibling_func()
    sibling.sibling_func()
    classify("state-x", "kind-x", [])
    svc = Service("service-name")
    svc.start()
    tool_func()
    missing_func()
    unknown_local()
    return first, second
