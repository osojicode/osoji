"""Has an invalid byte in a comment."""

# bad byte: ÿ
def survives():
    return "survived-result"
