# Project rules

The design review checks every design against these rules. An exception
needs a written justification in the design's "Project rules check".

1. **Reuse before building.** Use or extend existing code before adding a
   new module, helper or abstraction. Research lists what exists.
2. **Simplest design that meets the criteria.** No layer, option or
   extension point that no criterion needs.
3. **Use frameworks and libraries directly.** Do not wrap them unless the
   wrapper removes real duplication.
4. **One representation per concept.** No parallel models of the same data.
5. **Tests come from acceptance criteria.** Every criterion has a test,
   written and reviewed before the code. Tests use real code and fakes of
   process boundaries, not mocks of the unit under test.
6. **Never weaken a check to pass it.** No skipped tests, suppressions,
   loosened assertions or lowered thresholds without a written reason.
7. **Errors are specific.** A failure is never reported as "not found" or
   "empty". A rethrown error keeps its cause.
8. **Sources are tiered.** A decision rests on a Tier 1 source, or a
   Tier 2 source with the gap stated. "Unverified" is an acceptable answer;
   a made-up source is not.

<Add project-specific rules below: boundaries, licensing, performance limits.>
