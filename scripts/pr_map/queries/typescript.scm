; pr-map tags query for TypeScript and TSX (docs/specs/pr-map/design.md).
;
; Adapted from the tags queries of tree-sitter-typescript and
; tree-sitter-javascript (https://github.com/tree-sitter), and from
; Etchpad's fork of tree-sitter-typescript
; (https://github.com/etchpad/tree-sitter-typescript, queries/tags.scm).
; All three are MIT licensed: Copyright (c) 2017 Max Brunsfeld
; (tree-sitter-typescript and the fork) and Copyright (c) 2014 Max
; Brunsfeld (tree-sitter-javascript). The grammar's own tags.scm has
; no function or class declarations (research.md C21), so this file
; carries both.
;
; Captures follow the tags convention, @role.kind with an inner @name
; (research.md C19). The kind after "definition." is the construct kind
; constructs.py reports; "interface" is reported as a class. Every
; identifier is a reference site: @reference.call marks the callee of a
; call or `new`, @reference.name any other use.

; Functions
(function_declaration
  name: (identifier) @name) @definition.function

(generator_function_declaration
  name: (identifier) @name) @definition.function

(function_signature
  name: (identifier) @name) @definition.function

(variable_declarator
  name: (identifier) @name
  value: [(arrow_function) (function_expression) (generator_function)]) @definition.function

; Classes and interfaces
(class_declaration
  name: (type_identifier) @name) @definition.class

(abstract_class_declaration
  name: (type_identifier) @name) @definition.class

(interface_declaration
  name: (type_identifier) @name) @definition.interface

; Methods, including methods and function-valued keys of object literals
(method_definition
  name: [(property_identifier) (private_property_identifier)] @name) @definition.method

(pair
  key: (property_identifier) @name
  value: [(arrow_function) (function_expression) (generator_function)]) @definition.method

; Members: signatures, and class fields that hold a function
(method_signature
  name: [(property_identifier) (private_property_identifier)] @name) @definition.member

(abstract_method_signature
  name: [(property_identifier) (private_property_identifier)] @name) @definition.member

(property_signature
  name: [(property_identifier) (private_property_identifier)] @name) @definition.member

(public_field_definition
  name: [(property_identifier) (private_property_identifier)] @name
  value: [(arrow_function) (function_expression) (generator_function)]) @definition.member

; Reference sites
(call_expression
  function: (identifier) @reference.call)

(call_expression
  function: (member_expression
    property: [(property_identifier) (private_property_identifier)] @reference.call))

(call_expression
  function: (super) @reference.call)

(new_expression
  constructor: (identifier) @reference.call)

(new_expression
  constructor: (member_expression
    property: (property_identifier) @reference.call))

(new_expression
  constructor: (this) @reference.call)

(identifier) @reference.name
(property_identifier) @reference.name
(private_property_identifier) @reference.name
(shorthand_property_identifier) @reference.name
(type_identifier) @reference.name
