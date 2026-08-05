#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
The live citation resolver for `verifier.science`. THE FLAG IT SHIPS BEHIND.

SPEC.md section 5: a profile that genuinely needs the network takes a resolver
DEPENDENCY rather than reaching out itself. This module is that dependency's
live implementation, and it is deliberately:

  * never imported by `profiles/science.py`,
  * never imported by any test,
  * never imported by the conformance runner,
  * not registered until something calls `install()` explicitly.

That is the flag. It is an import-graph property, not a runtime check and not a
promise in a docstring: `import profiles.science` cannot reach `urllib` through
this module, so "no test reaches the network" is checkable by looking at
`sys.modules` — and `tests/test_science.py::test_live_resolver_is_not_installed`
does exactly that.

WHAT IT WOULD DO. Crossref's REST API resolves a DOI to a work record with a
title, which is what `science.citation_unresolved` needs. This is a reference
implementation of the shape, not a hardened client: it has no cache, no retry
policy, no rate-limit courtesy beyond the polite User-Agent, and no offline
fallback. Before the science lane can retire Perplexity's citation-resolvability
role (docs/P1-report.md section 6), this needs all four, plus a recorded-fixture
mode so a verdict is reproducible after the fact.

DETERMINISM WARNING (SPEC.md section 8). A verifier using this resolver is
conformant only as long as the network agrees with itself. Crossref returning a
record today and a 503 tomorrow makes the same request produce two different
verdicts, which is exactly what section 8 forbids. That is not a defect in the
contract — it is the contract telling you that live resolution belongs behind a
cache with a recorded, replayable snapshot, and that the snapshot, not the
network, is what a conformant verifier reads.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

CROSSREF = "https://api.crossref.org/works/"
USER_AGENT = "verifier-contract/0.1 (https://github.com/EduCloud-Ecosystem/verifier-contract)"
TIMEOUT_SECONDS = 10


def live_resolver(_context: dict[str, Any] | None = None):
    """Return a resolver that asks Crossref to resolve a DOI-shaped citation key."""

    def resolve(key: str) -> dict[str, Any] | None:
        url = CROSSREF + urllib.parse.quote(key, safe="")
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:  # noqa: BLE001 — an unresolvable citation, not a judge failure
            return None
        message = payload.get("message") or {}
        titles = message.get("title") or []
        if not titles:
            return None
        return {"title": titles[0], "numbers": []}


    return resolve


def install() -> None:
    """Register the live resolver under the name `live`. The explicit flag flip."""
    from . import science

    science.register_resolver("live", live_resolver)
