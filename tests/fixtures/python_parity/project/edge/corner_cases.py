"""Walrus, match, lambda, nested class methods, aug-assign, conditional defs."""

counter = 0
counter += 1
flag = True


def scope_probe(data):
    handler = lambda item: transform(item)
    if (size := len(data)) > 10:
        record("size-large")
    match data:
        case {"type-key": kind}:
            record(kind)
        case [first_item, *rest]:
            record("list-shape")
        case _:
            record("fallback-shape")
    return handler, size


def transform(item):
    return item


def record(event):
    return event


if flag:
    def conditional_func():
        return "conditional-result"


class Outer:
    class Middle:
        def middle_method(self):
            return "middle-result"

    def outer_method(self):
        def local_helper():
            return "local-result"

        return local_helper()


try:
    import optional_dep
except ImportError:
    optional_dep = None
