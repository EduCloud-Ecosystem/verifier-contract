#!/usr/bin/env python3
"""
`verifier.design` — an explicit `not_implemented` stub. Do not build it here.

SPEC.md section 3.1 lists no context shape for this profile and section 7.1
registers no reason codes for it, both on purpose. The registry is append-only
(SPEC.md section 7.2), so a code invented before there is a predicate to emit it
is a permanent piece of vocabulary bought with a guess. Two of the codes this
profile would plausibly want are named in the docstring below as candidates, in
prose, where they cost nothing and bind nothing.

WHY A STUB SHIPS AT ALL. A profile that exits non-zero for every request is the
honest form of "not implemented" under this contract, and it is a real
conformance case: the runner must report a verifier error rather than a `fail`
verdict (SPEC.md section 1.1), and a stub is the cheapest possible executable
that proves the runner does. `conformance/golden/design/` therefore contains
cases that expect an error, and they are the only golden cases in the suite that
do.

The failure mode this guards against is a stub that returns `{"verdict":
"fail"}` so its exit code can stay 0. That reads to every consumer as "the
candidate is bad" when what happened is "nobody has written this yet", and in a
fail-up ladder it escalates every design task to the top tier for free.

CANDIDATE CODES, when someone does build it (not registered, not binding):
`design.rubric_unmet`, `design.constraint_violated`. Neither is in
`schema/reason_codes.json` and neither should be added until a predicate emits
it.
"""

from __future__ import annotations

import sys

PROFILE = "design"

# A distinct non-zero code so a caller reading logs can tell "not built yet"
# from "crashed". The CONTRACT does not distinguish them — every non-zero exit
# means the same thing to a conformant caller, namely that no verdict was
# reached (SPEC.md section 1.1). This is a convention for humans.
EXIT_NOT_IMPLEMENTED = 4


def main(argv: list[str] | None = None) -> int:
    # stdin is drained but never parsed: whether the request is well-formed is
    # not knowable by a profile that has no predicate, and pretending to check
    # would be the first step toward pretending to decide.
    try:
        sys.stdin.read()
    except OSError:
        pass
    print(
        "design: not_implemented — the design profile is a declared stub with no "
        "predicate and no registered reason codes. It reaches no verdict, so it "
        "exits non-zero (SPEC.md sections 1.1 and 2.2) rather than emitting a `fail`.",
        file=sys.stderr,
    )
    return EXIT_NOT_IMPLEMENTED


if __name__ == "__main__":
    sys.exit(main())
