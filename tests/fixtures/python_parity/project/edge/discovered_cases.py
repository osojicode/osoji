"""Cases discovered by the full-repo A/B, pinned so the golden covers them.

Each tripped the first driver iteration: multiline implicit concatenation,
conditional-expression visit order, annotated attribute assignment,
multi-element Literal subscripts, `not in` comparisons, and forward-reference
strings in type annotations.
"""

from typing import Literal

Verdict = Literal["confirmed-kind", "dismissed-kind", "uncertain-kind"]
Single = Literal["only-kind"]

_REGISTRY: dict[str, "LanguagePlugin"] = {}
forward_ref: "SoloForward" = None


class Holder:
    def __init__(self):
        self.plain_write = "written-value"
        self.annotated: dict = {}
        self.annotated_typed: list = []


def multiline_message():
    return (
        "first-part of a long message "
        "second-part continues here"
    )


def conditional(path, root):
    rel = path.relative_to(root) if path.is_absolute() else path
    label = "long-form" if len(str(path)) > 10 else "short-form"
    return rel, label


def membership(props, out):
    assert "required-key" in props
    assert "forbidden-key" not in props
    if "needle-text" not in out:
        return "missing-result"
    return "present-result"


def log_multiline(logger):
    logger.debug(
        "diagnostic part one, continuing with "
        "diagnostic part two"
    )
