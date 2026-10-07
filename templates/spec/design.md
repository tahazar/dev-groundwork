# Design: <feature>

- Status: draft | reviewed | approved (<date>, by <name>)
- Requirements: `requirements.md`; research: `research.md`

## Context

<What exists today and what has to change, in a few sentences.>

## Options

At least two options that differ in structure: different module
boundaries, data flow or ownership, not different names for the same idea.
Argue each one at its strongest. Every factual claim cites a C-id from
research.md.

### Option A: <name>

<How it works, which existing code it reuses, what it adds.>

### Option B: <name>

<How it works, which existing code it reuses, what it adds.>

## Comparison

| | Option A | Option B |
|---|---|---|
| Work for callers (interface simplicity) | | |
| Reuses existing code | | |
| New code and new abstractions | | |
| Fits project rules | | |
| Risk and unknowns | | |
| Criteria it cannot meet | | |

## Decision

<The chosen option and the reason, in terms of the comparison.>

## Rejected options

- <Option>: <why it lost, so nobody re-derives it later>

## Design

<Interfaces, data shapes, error handling. Enough that tasks.md follows from it.>

## Criteria coverage

| Criterion | How the design meets it |
|---|---|
| AC-1 | |

## Project rules check

<Each rule in the project's rules file that this design touches, and how it complies, or the justification for the exception.>
