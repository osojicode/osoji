; Import statements — one capture per statement kind.
; from __future__ import is a distinct node type in tree-sitter-python,
; while stdlib ast folds it into a plain ImportFrom.
(import_statement) @import
(import_from_statement) @import_from
(future_import_statement) @import_future
