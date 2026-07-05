; String literals feeding the usage taxonomy (produced/checked/defined).
; Concatenated strings are handled at the concatenation node; f-strings are
; string nodes whose prefix makes literal_eval fail, mirroring the ast
; JoinedStr skip.
(string) @string
(concatenated_string) @concat
