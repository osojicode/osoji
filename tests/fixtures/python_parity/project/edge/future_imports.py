"""Future imports and multi-alias import statements."""

from __future__ import annotations

import json, collections
import xml.etree.ElementTree as ET
from json import dumps as to_json, loads


def roundtrip(payload):
    text = to_json(payload)
    return loads(text)
