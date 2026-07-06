"""__all__ as an annotated tuple assignment."""

__all__: tuple = ("visible_func",)


def visible_func():
    return "visible-result"


def hidden_func():
    return "hidden-result"
