"""Gate 3: `verifier.science` with an injected resolver. No network, no model.

The gate's own wording: "a fixture where a citation fails to resolve produces
`science.citation_unresolved` with the offending citation in the evidence
array". That is `test_unresolved_citation_names_the_offending_key`, and the
three tests around it are the ways that could be satisfied dishonestly — by
reaching the network anyway, by putting the candidate's text in evidence, or by
reporting a rate over an empty denominator as if it were a clean result.
"""

import json
import pathlib
import re
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCIENCE_PY = ROOT / "profiles" / "science.py"

TASK = "Write a results section that sources every claim and every number."

MANUSCRIPT = """## Results

The effect size was 0.42 in the replication [@smith2024].

The sample size was 120 participants [@jones2025].

[@smith2024]: A Replication of the Effect
"""

RUBRIC = {
    "effect_size": {"pattern": "effect size"},
    "sample_size": {"pattern": "sample size"},
}

SOURCES = {"smith2024": {"title": "A Replication of the Effect", "numbers": ["0.42", "120"]}}


def fixture_resolver(key):
    """The injected dependency (SPEC.md §5). Resolves from a dict, never a socket."""
    return dict(SOURCES[key]) if key in SOURCES else None


def _request(science, candidate=MANUSCRIPT, rubric=None, resolver="inline", sources=None):
    return science.build_request(
        candidate=candidate,
        task=TASK,
        rubric=RUBRIC if rubric is None else rubric,
        resolver=resolver,
        sources=SOURCES if sources is None else sources,
    )


# ── the gate ─────────────────────────────────────────────────────────────────


def test_unresolved_citation_names_the_offending_key(science):
    verdict = science.verify(_request(science), resolver=fixture_resolver)
    assert verdict["verdict"] == "fail"
    assert verdict["reason_code"] == "science.citation_unresolved"
    citations = verdict["evidence"][0]
    assert citations["unresolved"] == ["jones2025"]
    assert citations["citation_resolvability"] == 0.5
    assert citations["hallucinated_citation_rate"] == 0.5


def test_resolver_is_injected_and_the_profile_never_opens_a_socket(science, monkeypatch):
    """SPEC.md §5. Not "must not" — cannot: there is nothing to reach out with."""
    import socket

    def explode(*args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("the science profile touched the network")

    monkeypatch.setattr(socket, "create_connection", explode)
    monkeypatch.setattr(socket, "getaddrinfo", explode)
    monkeypatch.setattr(socket.socket, "connect", explode)

    verdict = science.verify(_request(science), resolver=fixture_resolver)
    assert verdict["profile"] == "science"


def test_a_title_mismatch_is_not_a_resolution(science):
    candidate = "The effect was large [@smith2024].\n\n[@smith2024]: Another Paper Entirely\n"
    verdict = science.verify(
        _request(science, candidate=candidate, rubric={}), resolver=fixture_resolver
    )
    assert verdict["reason_code"] == "science.citation_unresolved"
    assert verdict["evidence"][0]["unresolved"] == ["smith2024"]


def test_rubric_key_absent_and_rubric_key_unsourced_are_the_same_code(science):
    candidate = (
        "## Results\n\nThe effect size was 0.42 [@smith2024].\n\n"
        "The method was a within-subjects design with no source.\n"
    )
    rubric = {"effect_size": {"pattern": "effect size"},
              "sample_size": {"pattern": "sample size"},
              "method": {"pattern": "method"}}
    verdict = science.verify(
        _request(science, candidate=candidate, rubric=rubric), resolver=fixture_resolver
    )
    assert verdict["reason_code"] == "science.rubric_key_missing"
    rubric_evidence = verdict["evidence"][1]
    assert rubric_evidence["missing"] == ["sample_size"]
    assert rubric_evidence["unsourced"] == ["method"]


def test_numbers_trace_to_a_source_or_to_included_code(science):
    candidate = (
        "## Results\n\nThe effect size was 0.42 [@smith2024].\n\n"
        "```python\nthreshold = 7\n```\n\nWe removed 999 outliers.\n"
    )
    verdict = science.verify(
        _request(science, candidate=candidate, rubric={}), resolver=fixture_resolver
    )
    assert verdict["reason_code"] == "science.number_untraceable"
    numbers = verdict["evidence"][2]
    # 0.42 traces to the source; 7 is inside included code and is not checked;
    # 999 traces to neither.
    assert numbers["untraceable_count"] == 1
    assert numbers["untraceable"] == [{"line": 9, "ordinal": 0}]


def test_untraceable_numbers_are_reported_by_position_never_by_value(science):
    candidate = "We removed 999 outliers and kept 31415926535 rows.\n"
    verdict = science.verify(
        _request(science, candidate=candidate, rubric={}, sources={}),
        resolver=fixture_resolver,
    )
    blob = json.dumps(verdict["evidence"])
    assert "999" not in blob
    assert "31415926535" not in blob
    assert verdict["evidence"][2]["untraceable_count"] == 2


def test_precedence_is_fixed_when_several_signals_fire(science):
    """SPEC.md §4.1: `reason_code` names the primary reason; evidence keeps all."""
    candidate = "The effect was 999 [@nobody2020].\n"
    verdict = science.verify(
        _request(science, candidate=candidate, rubric={"sample_size": {}}),
        resolver=fixture_resolver,
    )
    assert [e["fired"] for e in verdict["evidence"]] == [True, True, True]
    assert verdict["reason_code"] == "science.citation_unresolved"


def test_rates_over_an_empty_denominator_are_null_not_one(science):
    verdict = science.verify(
        _request(science, candidate="Nothing is cited here.\n", rubric={}),
        resolver=fixture_resolver,
    )
    assert verdict["verdict"] == "pass"
    citations = verdict["evidence"][0]
    assert citations["citation_resolvability"] is None
    assert citations["hallucinated_citation_rate"] is None


def test_a_pass_reports_every_signal_it_evaluated(science):
    candidate = (
        "## Results\n\nThe effect size was 0.42 [@smith2024].\n\n"
        "The sample size was 120 [@smith2024].\n"
    )
    verdict = science.verify(
        _request(science, candidate=candidate), resolver=fixture_resolver
    )
    assert verdict["verdict"] == "pass"
    assert [e["signal"] for e in verdict["evidence"]] == ["citations", "rubric_keys", "numbers"]
    assert all(e["fired"] is False for e in verdict["evidence"])


# ── the live resolver ships behind a flag ────────────────────────────────────


def test_live_resolver_is_not_installed_and_science_cannot_reach_it(science):
    assert science.registered_resolvers() == ("inline",)
    assert not any("science_live" in name for name in sys.modules)


def test_requesting_the_live_resolver_in_a_build_without_it_is_a_judge_failure(science):
    """Not a `fail` verdict: nothing was decided about the manuscript. A resolver
    that silently resolved nothing would turn every citation into
    `science.citation_unresolved` and report a wiring problem as a quality one."""
    with pytest.raises(science.VerifierError):
        science.verify(_request(science, resolver="live"))


def test_installing_the_live_resolver_is_an_explicit_call(science):
    """The flag exists and works — it is just never flipped by default. This test
    installs a stand-in rather than the real one, so the network client is still
    never imported."""
    science.register_resolver("live", lambda ctx: fixture_resolver)
    assert set(science.registered_resolvers()) == {"inline", "live"}
    verdict = science.verify(_request(science, resolver="live"))
    assert verdict["reason_code"] == "science.citation_unresolved"


def test_science_live_module_imports_urllib_and_nothing_else_does():
    """The flag is an import-graph property, which is why it is checkable."""
    source = (ROOT / "profiles" / "science.py").read_text(encoding="utf-8")
    for network_module in ("urllib", "http.client", "requests", "socket"):
        assert f"import {network_module}" not in source
    live = (ROOT / "profiles" / "science_live.py").read_text(encoding="utf-8")
    assert "import urllib.request" in live
    package = (ROOT / "profiles" / "__init__.py").read_text(encoding="utf-8")
    assert "import science_live" not in package
    assert "from . import science_live" not in package


# ── evidence, determinism, the executable boundary ───────────────────────────


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value)


def _shares_long_run(a, b, n=40):
    norm = lambda s: re.sub(r"\s+", " ", s).lower()  # noqa: E731
    a, b = norm(a), norm(b)
    if len(a) < n or len(b) < n:
        return False
    windows = {a[i : i + n] for i in range(len(a) - n + 1)}
    return any(b[i : i + n] in windows for i in range(len(b) - n + 1))


@pytest.mark.parametrize(
    "candidate",
    [MANUSCRIPT, "Nothing cited.\n", "", "We removed 999 outliers [@nobody2020].\n"],
)
def test_evidence_never_reproduces_the_candidate(science, candidate):
    verdict = science.verify(
        _request(science, candidate=candidate, rubric={"effect_size": {}}),
        resolver=fixture_resolver,
    )
    for value in _strings(verdict["evidence"]):
        assert not _shares_long_run(candidate, value)
    assert not _shares_long_run(candidate, verdict["detail"])


def test_determinism(science):
    request = _request(science)
    first = json.dumps(science.verify(request, resolver=fixture_resolver))
    second = json.dumps(science.verify(request, resolver=fixture_resolver))
    assert first == second


def test_executable_form_round_trips_on_stdin_stdout(science):
    request = _request(science)
    proc = subprocess.run(
        [sys.executable, str(SCIENCE_PY)],
        input=json.dumps(request), capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    # The executable uses the request's own named resolver, not the injected one.
    assert json.loads(proc.stdout) == science.verify(request)


@pytest.mark.parametrize(
    "payload",
    [
        "{ not json",
        json.dumps({"profile": "science", "task": "", "candidate": "x", "context": {}}),
        json.dumps({"profile": "science", "task": "", "candidate": "x",
                    "context": {"rubric": {}, "resolver": "live"}}),
    ],
    ids=["unparseable", "context-missing-rubric", "resolver-not-in-this-build"],
)
def test_a_broken_verifier_exits_non_zero_and_emits_no_verdict(payload):
    proc = subprocess.run(
        [sys.executable, str(SCIENCE_PY)],
        input=payload, capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode != 0
    assert proc.stdout.strip() == ""
