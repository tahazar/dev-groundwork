# Requirements: pr-map

- Status: draft
- Requested by: the owner, 2026-10-07: "adding a GitHub action to generate a
  visual in our PRs to enable quick code reviews", inspired by Etchpad
  ("every wire a reference that actually exists ... never hallucinated").

## Problem

A reviewer reads a pull request as a list of changed lines. The diff does
not show where a change sits: what calls the changed code, and what it
calls in turn. An experienced reviewer fills that in from memory; someone
new to the codebase cannot, and most changes are now written by an agent,
so the person reviewing often did not write the code either. A diagram
helps only if it is right: a picture with an invented call is worse than
none, because the reader trusts it.

## Acceptance criteria

The map: one Mermaid diagram of the changed functions and their nearest
neighbours, computed from the source code, posted on the pull request.

What goes on the map

- **AC-1** When a pull request changes the body or signature of a function,
  method or class, the map shall show that construct as a box marked
  "changed".
- **AC-2** When a pull request adds a function, method or class, the map
  shall show it as a box marked "added".
- **AC-3** When a pull request deletes a function, method or class, the map
  shall show it as a box marked "removed", with an arrow from each
  construct in the head commit that still references it.
- **AC-4** The map shall draw an arrow from A to B for each construct A that
  calls or references a changed, added or removed construct B, and for
  each construct B that a changed or added construct A calls or references
  (one step in each direction, not further).
- **AC-5** The map shall draw an arrow as solid only when the language's
  own tooling resolves the reference to that exact definition (the
  TypeScript compiler for TypeScript; Python's parser and import
  resolution for Python).
- **AC-6** If a reference cannot be resolved to exactly one definition
  (for example a Python call on a value of unknown type), then the map
  shall draw it as a dashed arrow labelled "possible", and shall not draw
  it as solid.
- **AC-7** The map shall not draw an arrow that does not correspond to a
  reference in the source. (Test: every arrow on the map for a fixture
  repository is checked against a hand-written list of its real
  references.)
- **AC-8** The map shall label each box with the construct's name and its
  file path relative to the repository root.
- **AC-9** The map shall support TypeScript (`.ts`, `.tsx`) and Python
  (`.py`) files, including a pull request that changes both.
- **AC-10** When a pull request changes only files in other languages or no
  functions (for example documentation only), the map shall say "No
  function-level changes to map" instead of a diagram.

Size

- **AC-11** The map shall include every changed, added and removed
  construct and every one-step neighbour of each, with no limit on their
  number. Nothing is left out to keep the map small.
- **AC-12** If one diagram would be too large for GitHub to render, then
  the map shall split it into several diagrams, one per group of connected
  boxes, so that each renders and every box and arrow appears in one of
  them.
- **AC-13** The map shall also list every box and arrow as text, in a
  collapsed section under the diagram, so a reviewer can search for a
  name and follow a change that is hard to see in the picture.
- **AC-14** If the map is too long for one pull request comment, then the
  comment shall hold the diagrams that fit and a link to the complete map
  in the workflow run's summary, and shall say how much was moved there.

On the pull request

- **AC-15** When a pull request is opened, or a commit is pushed to it, the
  workflow shall post the map as one comment on the pull request.
- **AC-16** When the workflow runs again on the same pull request, it shall
  update its existing comment in place and shall not post a second one.
- **AC-17** The comment shall state the base and head commits the map was
  computed from.
- **AC-18** If the workflow cannot post a comment (for example a pull
  request from a fork, where the token is read-only), then it shall write
  the map to the workflow run's job summary instead and say why.

Failure

- **AC-19** If a changed file cannot be parsed, then the map shall be
  built from the files that can be, and the comment shall name each file
  that was skipped and the parser's reason.
- **AC-20** If building the map fails entirely, then the comment shall say
  so with the error, and the workflow's check shall still pass.
- **AC-21** The workflow shall never fail a pull request's checks because
  of the map. (The map is a reading aid, not a gate.)

Setup

- **AC-22** When `/dev-groundwork:setup` runs in a project, it shall add the
  map's workflow and script to the project alongside the existing
  Groundwork checks. (deferred until the map works in one project)

## Out of scope

- AI-written explanations or walkthroughs. That is version 2, a separate
  feature, and its claims will be checked against this map.
- File-level and package-level views (the other zoom levels).
- Languages other than TypeScript and Python.
- Following references more than one step away. (Every changed construct
  is shown; only the depth is limited.)
- An interactive or zoomable view; the output is a static Mermaid diagram.
- Blocking merges or reporting anything as a failure.

## Open questions

- Should the comment also show a small package-level line ("touches: core,
  cli") above the diagram? Cheap, but it is a second zoom level. (owner:
  the owner, after seeing version 1)
- Which construct kinds count for Python: also module-level constants and
  decorators? Research will check what the parser gives for free. (owner:
  research stage, then the owner)
- GitHub's exact limits on Mermaid diagram size and comment length, which
  set where AC-12 and AC-14 split. (owner: research stage)
