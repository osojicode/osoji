"""Module docstring — must be suppressed from string extraction."""

STATUS_ACTIVE = "status-active"
threshold: str = "annotated-defined"
short = "x"


def classify(state, kind, tags):
    """Function docstring — suppressed too."""
    if state == "state-running":
        return "verdict-running"
    if "special-tag" in tags:
        return "verdict-special"
    if kind != "kind-basic":
        return "verdict-other"
    if state in ("state-a", "state-b"):
        return "verdict-ab"
    return "verdict-none"


def produce(callback):
    callback("callback-arg", retries="retry-value")
    options = ["opt-one", "opt-two"]
    pair = ("pair-left", "pair-right")
    unique = {"set-member"}
    mapping = {"map-key": "map-value", "other-key": produce_name()}
    return options, pair, unique, mapping


def produce_name(label="default-label"):
    return label


def formatted(value):
    plain = f"prefix-{value}-suffix"
    joined = "concat-first" "concat-second"
    raw = r"raw\path\segment"
    escaped = "line-one\nline-two\ttabbed"
    multi = """multi-line
literal-content"""
    return plain, joined, raw, escaped, multi


class Labeled:
    """Class docstring — suppressed."""

    label = "class-level-label"

    def compare(self, other):
        return other == "comparison-target"


"standalone expression string is skipped"
