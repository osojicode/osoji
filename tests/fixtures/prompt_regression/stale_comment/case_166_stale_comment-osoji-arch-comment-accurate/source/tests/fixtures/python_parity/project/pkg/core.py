"""Core module: functions, classes, constants, member writes."""

import json
import os.path as osp
from collections import OrderedDict

MAX_RETRIES = 3
default_timeout = 30.5
NAME_A = NAME_B = "chained-value"
first, second = "tuple-a", "tuple-b"


def api_func(arg, mode="strict-mode"):
    """Docstring with 'quoted words' inside."""
    payload = json.dumps({"key-one": "value-one", "outer": arg})
    if mode == "strict-mode":
        return "strict-result"
    return payload


async def async_api(items):
    for item in items:
        yield item


def helper():
    def nested_inner():
        return "nested-return"

    return nested_inner()


def _internal():
    return osp.join("dir-part", "file-part")


class Service:
    """A class with methods one level deep."""

    registry = OrderedDict()

    def __init__(self, name):
        self.name = name
        self.status = "created"

    def start(self):
        self.status = "running"
        return self.status

    async def stop(self):
        self.status = "stopped"

    def _private_method(self):
        return None

    class Inner:
        def inner_method(self):
            return "inner-result"


class Derived(Service):
    def start(self):
        result = super().start()
        Service.registry["derived-key"] = result
        return result


Service.class_attr = "attached-value"
module_state = {}
module_state["config-key"] = "config-value"
