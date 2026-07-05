"""__all__ with augmented assignment — unresolvable, falls back to underscore rule."""

__all__ = ["base_func"]
__all__ += ["extra_func"]


def base_func():
    return "base-result"


def extra_func():
    return "extra-result"


def _private_func():
    return "private-result"
