"""__all__ built dynamically — unresolvable, falls back to underscore rule."""

_names = ["dyn_func"]
__all__ = [name for name in _names]


def dyn_func():
    return "dyn-result"


def _hidden():
    return "hidden-result"
