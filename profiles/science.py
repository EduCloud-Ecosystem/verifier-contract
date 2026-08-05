#!/usr/bin/env python3
"""
Reference implementation of the `science` profile.

WHY THIS LIVES IN THE CONTRACT REPO. The contract is `SPEC.md`, `schema/` and
`conformance/`; it decides nothing. Profiles belong in the repository of the
caller that owns the predicate — `leak` lives in Belay because the predicate is
Belay's pack oracle, `code` lives in Portage because the predicate is the fail-up
guard's deterministic gate. `science` has no host repository yet: the science
lane's first consumer does not exist, and the profile is being built ahead of it
so the Perplexity citation-resolvability subscription has something to be
retired against. It ships here as a REFERENCE IMPLEMENTATION and moves to its
host the day one exists. Nothing in `conformance/` imports it.

WHAT IT DECIDES (SPEC.md section 7.1, three registered codes):

  science.citation_unresolved  a citation does not resolve to a document whose
                               title matches the one the candidate asserts
  science.rubric_key_missing   a rubric key from `context` is absent from the
                               candidate, or present with no citation near it
  science.number_untraceable   a number traces to neither a resolved source nor
                               to code included in the candidate

PRECEDENCE (SPEC.md section 4.1). `reason_code` is singular and names the
primary reason under this fixed order:

    citation_unresolved  >  rubric_key_missing  >  number_untraceable

Rationale, and it is not arbitrary: an unresolved citation invalidates the
sourcing of everything downstream of it, so reporting "a number is untraceable"
as the primary reason when the source it would trace to does not exist names a
symptom over a cause. `evidence` still carries all three signals, always.

THE RESOLVER IS INJECTED (SPEC.md section 5). This module opens no socket and
imports no network library. `context.resolver` names a resolver:

  "inline"  resolves from `context.sources`, i.e. from the request itself.
            Offline by construction. Every test and every golden case uses it.
  "live"    registered ONLY by a build that has called
            `profiles.science_live.install()`. A build that has not exits
            non-zero (a judge failure, SPEC.md section 2.2) rather than
            resolving nothing, because a resolver that silently resolves
            nothing turns every citation into `science.citation_unresolved`
            and reports a manuscript-quality verdict about its own wiring.

A Python caller can bypass the name entirely: `verify(request, resolver=fn)`.
That is the injection point the tests use.

EVIDENCE (SPEC.md section 6). Citation keys and rubric keys are identifiers and
are named in evidence explicitly — SPEC.md section 6 lists both as permitted.
Untraceable NUMBERS are not: a number's value is candidate text, and section 6's
permitted list is identifiers, characterisations and profile vocabulary, none of
which a numeric literal lifted out of the manuscript is. They are therefore
reported by LINE and ORDINAL, which are identifiers, and never by value. This
costs some debuggability and is the correct trade: the rule is that evidence
identifies and characterises without reproducing, not that it stays under a
forty-character threshold.

`citation_resolvability` and `hallucinated_citation_rate` are emitted as
evidence fields because they are the instrumentation the stewardship paper
needs. Both are `null` when the candidate cites nothing — a rate over an empty
denominator is undefined, and reporting 1.0 there would let an uncited
manuscript read as perfectly sourced.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable
from typing import Any

PROFILE = "science"

EXIT_BAD_STDIN = 2
EXIT_JUDGE_FAILED = 3

# `[@key]` inline. Reference definitions (`[@key]: Title`) are stripped before
# citations are extracted, so a definition is not also counted as a citation.
_CITATION = re.compile(r"\[@([A-Za-z][A-Za-z0-9_:.\-]*)\]")
_REFERENCE = re.compile(r"^\[@([A-Za-z][A-Za-z0-9_:.\-]*)\]:[ \t]*(.+?)[ \t]*$", re.MULTILINE)
_FENCE = re.compile(r"```.*?```", re.DOTALL)
# Numeric literals, optionally with a percent sign. The lookbehind keeps version
# strings and identifiers (`utf8`, `v2`, `1.2.3`) from fragmenting into numbers.
_NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?%?(?![\w.])")

_SIGNALS: tuple[tuple[str, str], ...] = (
    ("citations", "science.citation_unresolved"),
    ("rubric_keys", "science.rubric_key_missing"),
    ("numbers", "science.number_untraceable"),
)

_DETAIL = {
    "science.citation_unresolved": "one or more citations do not resolve to a document whose title matches",  # noqa: E501
    "science.rubric_key_missing": "one or more rubric keys are absent from the candidate or carry no source",  # noqa: E501
    "science.number_untraceable": "one or more numbers trace to neither a resolved source nor included code",  # noqa: E501
}

Resolver = Callable[[str], "dict[str, Any] | None"]


class VerifierError(RuntimeError):
    """The judge could not decide. Becomes a non-zero exit, never a `fail`."""


# ── resolvers ────────────────────────────────────────────────────────────────


def inline_resolver(sources: dict[str, Any]) -> Resolver:
    """Resolve citations from records carried in the request itself.

    This is a real resolver, not a mock: it is what makes the profile runnable
    as a conformant executable with no network and no host service, and it is
    what the golden conformance cases use.
    """

    def resolve(key: str) -> dict[str, Any] | None:
        record = sources.get(key)
        return dict(record) if isinstance(record, dict) else None

    return resolve


_RESOLVER_FACTORIES: dict[str, Callable[[dict[str, Any]], Resolver]] = {
    "inline": lambda context: inline_resolver(context.get("sources") or {}),
}


def register_resolver(name: str, factory: Callable[[dict[str, Any]], Resolver]) -> None:
    """Install a named resolver. The flag behind which the live resolver ships.

    `profiles/science_live.py` calls this from `install()`. Nothing else does,
    and nothing imports `science_live` by default — which is what makes "no test
    reaches the network" a property of the import graph rather than a promise.
    """
    _RESOLVER_FACTORIES[name] = factory


def registered_resolvers() -> tuple[str, ...]:
    return tuple(sorted(_RESOLVER_FACTORIES))


# ── parsing ──────────────────────────────────────────────────────────────────


def _normalise_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def _parse(candidate: str) -> dict[str, Any]:
    """Split a candidate into the four things the three checks need."""
    asserted = {m.group(1): m.group(2) for m in _REFERENCE.finditer(candidate)}
    body = _REFERENCE.sub("", candidate)

    keys: list[str] = []
    for m in _CITATION.finditer(body):
        if m.group(1) not in keys:
            keys.append(m.group(1))

    code_numbers = {n for block in _FENCE.findall(body) for n in _NUMBER.findall(block)}

    prose = _FENCE.sub(lambda m: "\n" * m.group(0).count("\n"), body)
    numbers: list[dict[str, Any]] = []
    for line_no, line in enumerate(prose.splitlines(), start=1):
        for ordinal, m in enumerate(_NUMBER.finditer(line)):
            numbers.append({"line": line_no, "ordinal": ordinal, "_value": m.group(0)})

    return {
        "asserted_titles": asserted,
        "body": body,
        "prose": prose,
        "citations": keys,
        "code_numbers": code_numbers,
        "numbers": numbers,
    }


def _paragraph_of(text: str, index: int) -> str:
    start = text.rfind("\n\n", 0, index)
    start = 0 if start < 0 else start + 2
    end = text.find("\n\n", index)
    end = len(text) if end < 0 else end
    return text[start:end]


# ── the three checks ─────────────────────────────────────────────────────────


def _check_citations(parsed: dict[str, Any], resolve: Resolver) -> tuple[dict[str, Any], dict]:
    unresolved: list[str] = []
    resolved_records: dict[str, dict[str, Any]] = {}
    for key in parsed["citations"]:
        record = resolve(key)
        if not isinstance(record, dict) or not record.get("title"):
            unresolved.append(key)
            continue
        asserted = parsed["asserted_titles"].get(key)
        if asserted is not None and _normalise_title(asserted) != _normalise_title(record["title"]):
            unresolved.append(key)
            continue
        resolved_records[key] = record

    total = len(parsed["citations"])
    ok = total - len(unresolved)
    evidence = {
        "signal": "citations",
        "fired": bool(unresolved),
        "citations_total": total,
        "citations_resolved": ok,
        # Undefined over an empty denominator; see the module docstring.
        "citation_resolvability": round(ok / total, 4) if total else None,
        "hallucinated_citation_rate": round(len(unresolved) / total, 4) if total else None,
        "unresolved": unresolved,
    }
    return evidence, resolved_records


def _check_rubric(parsed: dict[str, Any], rubric: dict[str, Any]) -> dict[str, Any]:
    missing: list[str] = []
    unsourced: list[str] = []
    body = parsed["body"]
    for key, spec in rubric.items():
        pattern = (spec or {}).get("pattern") or re.escape(key)
        try:
            match = re.search(pattern, body, re.IGNORECASE)
        except re.error as err:
            raise VerifierError(f"rubric key {key!r} has an invalid pattern: {err}") from err
        if match is None:
            missing.append(key)
            continue
        if not _CITATION.search(_paragraph_of(body, match.start())):
            unsourced.append(key)
    return {
        "signal": "rubric_keys",
        "fired": bool(missing or unsourced),
        "rubric_keys_total": len(rubric),
        "missing": missing,
        "unsourced": unsourced,
    }


def _check_numbers(
    parsed: dict[str, Any], resolved_records: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    supported = set(parsed["code_numbers"])
    for record in resolved_records.values():
        for n in record.get("numbers") or []:
            supported.add(str(n))

    untraceable = [
        {"line": n["line"], "ordinal": n["ordinal"]}
        for n in parsed["numbers"]
        if n["_value"] not in supported and n["_value"].rstrip("%") not in supported
    ]
    return {
        "signal": "numbers",
        "fired": bool(untraceable),
        "numbers_total": len(parsed["numbers"]),
        "untraceable_count": len(untraceable),
        # By line and ordinal, never by value: a numeric literal is candidate
        # text, and evidence identifies without reproducing (SPEC.md section 6).
        "untraceable": untraceable,
    }


# ── the profile ──────────────────────────────────────────────────────────────


def build_request(
    candidate: str,
    task: str,
    rubric: dict[str, Any] | None = None,
    resolver: str = "inline",
    sources: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble a contract request document for the science profile."""
    context: dict[str, Any] = {"rubric": rubric or {}, "resolver": resolver}
    if sources is not None:
        context["sources"] = sources
    return {"profile": PROFILE, "task": task, "candidate": candidate, "context": context}


def _resolver_for(context: dict[str, Any]) -> Resolver:
    name = context.get("resolver")
    if not isinstance(name, str):
        raise VerifierError("context.resolver is required and must be a string")
    factory = _RESOLVER_FACTORIES.get(name)
    if factory is None:
        raise VerifierError(
            f"resolver {name!r} is not registered in this build "
            f"(registered: {', '.join(registered_resolvers())}). "
            "The live resolver ships behind profiles/science_live.install()."
        )
    return factory(context)


def verify(request: dict[str, Any], resolver: Resolver | None = None) -> dict[str, Any]:
    """Request document in, verdict document out. One candidate per call.

    `resolver` is the injection point (SPEC.md section 5). When it is None the
    resolver named in `context.resolver` is used, which for every shipped build
    is the offline `inline` one.
    """
    context = request.get("context")
    if not isinstance(context, dict):
        raise VerifierError("request.context is required and must be an object")
    rubric = context.get("rubric")
    if not isinstance(rubric, dict):
        raise VerifierError("context.rubric is required and must be an object")
    candidate = request.get("candidate")
    if not isinstance(candidate, str):
        raise VerifierError("request.candidate is required and must be a string")

    resolve = resolver if resolver is not None else _resolver_for(context)

    parsed = _parse(candidate)
    citations, resolved_records = _check_citations(parsed, resolve)
    evidence = [
        citations,
        _check_rubric(parsed, rubric),
        _check_numbers(parsed, resolved_records),
    ]
    fired = {e["signal"]: e["fired"] for e in evidence}

    hits = [code for signal, code in _SIGNALS if fired[signal]]
    if not hits:
        return {
            "verdict": "pass",
            "profile": PROFILE,
            "detail": "citations resolve, rubric keys are present and sourced, numbers trace",
            "evidence": evidence,
        }
    return {
        "verdict": "fail",
        "profile": PROFILE,
        "reason_code": hits[0],
        "detail": "; ".join(_DETAIL[code] for code in hits),
        "evidence": evidence,
    }


def main(argv: list[str] | None = None) -> int:
    """Executable form: stdin -> stdout, exit 0 iff a verdict was reached."""
    try:
        request = json.loads(sys.stdin.read())
    except (ValueError, OSError) as err:
        print(f"science: cannot read a request document on stdin: {err}", file=sys.stderr)
        return EXIT_BAD_STDIN
    try:
        verdict = verify(request)
    except Exception as err:  # noqa: BLE001 — any failure here is a JUDGE failure
        print(f"science: the verifier failed and reached no verdict: {err!r}", file=sys.stderr)
        return EXIT_JUDGE_FAILED
    json.dump(verdict, sys.stdout, sort_keys=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
