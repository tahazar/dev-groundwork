; pr-map tags query for Python (docs/specs/pr-map/design.md).
;
; Adapted from the tags query of tree-sitter-python
; (https://github.com/tree-sitter/tree-sitter-python, queries/tags.scm,
; research.md C26, C26b), MIT licensed, Copyright (c) 2016 Max Brunsfeld.
; Module-level constants (C26c) are left out: version 1 maps functions,
; methods and classes (research.md, answers to open questions).
;
; Captures follow the tags convention, @role.kind with an inner @name
; (research.md C19). A function directly inside a class is reported as a
; method by constructs.py. Every identifier is a reference site:
; @reference.call marks the callee of a call, @reference.name any other use.

(class_definition
  name: (identifier) @name) @definition.class

(function_definition
  name: (identifier) @name) @definition.function

(call
  function: [
    (identifier) @reference.call
    (attribute
      attribute: (identifier) @reference.call)
  ])

(identifier) @reference.name
