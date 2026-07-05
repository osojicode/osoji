"""__all__ as a plain list, including a private name."""

__all__ = ["exported_one", "_private_but_listed"]


def exported_one():
    return "one-result"


def _private_but_listed():
    return "two-result"


def not_in_all():
    return "three-result"
