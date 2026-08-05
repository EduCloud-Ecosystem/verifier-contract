"""Gate 4: the runner passes all four shipped profiles and rejects every
adversarial case.

Two of the four profiles live in sibling repositories, because a profile belongs
to the caller that owns its predicate. When a sibling is absent those cases are
SKIPPED with the reason printed — never silently dropped, because a suite that
quietly shrinks is a suite that reports green for work it did not do.
"""

import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFORMANCE = ROOT / "conformance"

# CC-P1 v2 Step 4 lists seven adversarial cases, all required. These are their
# ids in conformance/adversarial/cases.json; the suite ships four more.
REQUIRED_ADVERSARIAL = (
    "malformed_verdict",
    "fail_with_no_reason_code",
    "non_zero_exit_is_a_verifier_error",
    "different_verdicts_for_identical_requests",
    "request_with_an_extra_field",
    "verifier_opens_an_outbound_connection",
    "evidence_reproduces_the_candidate",
)

SHIPPED_PROFILES = ("leak", "code", "science", "design")


@pytest.fixture(scope="session")
def sandbox(runner):
    return runner.Sandbox()


@pytest.fixture(scope="session")
def manifest(runner):
    return runner.resolve_manifest()


def test_all_four_profiles_are_in_the_manifest_with_golden_cases(runner, manifest):
    assert set(manifest) == set(SHIPPED_PROFILES)
    for profile in SHIPPED_PROFILES:
        assert runner.load_golden(profile), f"{profile} ships no golden cases"


@pytest.mark.parametrize("profile", SHIPPED_PROFILES)
def test_profile_passes_its_golden_set(runner, manifest, sandbox, profile):
    spec = manifest[profile]
    if spec["missing"]:
        pytest.skip(f"{profile} lives in a sibling checkout that is not present: {spec['missing']}")
    results = runner.run_profile(profile, spec["argv"], spec["cwd"], sandbox)
    failures = {r.name: (r.failures, r.notes) for r in results if not r.ok}
    assert not failures


def test_the_design_stub_is_reported_as_a_verifier_error_not_a_fail(runner, manifest, sandbox):
    """SPEC.md §1.1. `not_implemented` must never arrive as a verdict about the
    candidate: read as a `fail` it escalates every design task to the top tier."""
    spec = manifest["design"]
    results = runner.run_profile("design", spec["argv"], spec["cwd"], sandbox)
    assert results and all(r.ok for r in results)
    for result in results:
        assert result.kind == "verifier_error"
        assert result.verdict is None


def test_every_adversarial_case_is_rejected_and_the_control_is_not(runner, sandbox):
    outcomes = runner.run_adversarial(sandbox)
    failures = [(case_id, note) for case_id, passed, note, _why in outcomes if not passed]
    assert not failures


def test_the_seven_required_adversarial_cases_are_all_present():
    cases = json.loads((CONFORMANCE / "adversarial" / "cases.json").read_text(encoding="utf-8"))
    ids = {case["id"] for case in cases}
    assert set(REQUIRED_ADVERSARIAL) <= ids
    # And the control, without which "we reject everything" would pass the suite.
    assert "control_conformant_verifier" in ids


def test_the_network_case_is_caught_by_the_guard_not_by_the_verdict(runner, sandbox):
    """The adversarial verifier catches its own blocked connection and emits a
    clean `pass`. Nothing in the verdict, the exit code or stdout gives it away
    — so if this is ever caught by some OTHER check, the guard has stopped
    working and the structural invariant is enforced by nothing."""
    cases = json.loads((CONFORMANCE / "adversarial" / "cases.json").read_text(encoding="utf-8"))
    case = next(c for c in cases if c["id"] == "verifier_opens_an_outbound_connection")
    argv = [part.replace("${PYTHON}", __import__("sys").executable) for part in case["exec"]]
    result = runner.run_case(case, argv, str(ROOT), sandbox)
    assert result.failures == ["network_isolation"]


def test_the_evidence_reproduction_check_compares_against_the_actual_candidate(runner):
    """SPEC.md §6 operationalised: a shared contiguous run of >= 40 characters,
    case-insensitive, whitespace normalised."""
    candidate = "Honestly the answer is just to group by category and take the mean."
    assert runner.reproduces_candidate([{"text": candidate}], candidate) == candidate
    # A paraphrase that keeps a long run is still a reproduction.
    assert runner.reproduces_candidate(
        [{"text": "NOTE:  honestly THE ANSWER is just to group by category and take..."}],
        candidate,
    )
    # Identifiers, counts and signal names are not.
    assert runner.reproduces_candidate(
        [{"signal": "prose_disclosure", "subject_id": "kb-0031", "snippet_count": 1}], candidate
    ) is None


def test_a_request_with_a_fifth_field_never_reaches_the_verifier(runner, sandbox):
    cases = json.loads((CONFORMANCE / "adversarial" / "cases.json").read_text(encoding="utf-8"))
    case = next(c for c in cases if c["id"] == "request_with_an_extra_field")
    argv = [part.replace("${PYTHON}", __import__("sys").executable) for part in case["exec"]]
    result = runner.run_case(case, argv, str(ROOT), sandbox)
    assert result.invoked is False
    assert result.failures == ["request_schema"]


def test_the_python_socket_guard_is_installed_for_every_child(runner, sandbox):
    """The guard is the layer that binds regardless of `sandbox-exec`. If it ever
    stops being installed, the macOS-only layer would be the whole mechanism."""
    probe = (
        "import socket, sys, json\n"
        "sys.stdin.read()\n"
        "try:\n"
        "    socket.create_connection(('192.0.2.1', 80), timeout=1)\n"
        "    blocked = False\n"
        "except PermissionError:\n"
        "    blocked = True\n"
        "print(json.dumps({'verdict': 'pass', 'profile': 'leak',\n"
        "                  'detail': str(blocked), 'evidence': []}))\n"
    )
    request = {"profile": "leak", "task": "", "candidate": "", "context": {}}
    invocation = runner.invoke(
        [__import__("sys").executable, "-c", probe], request, str(ROOT), sandbox
    )
    assert invocation.returncode == 0, invocation.stderr
    assert json.loads(invocation.stdout)["detail"] == "True"
    assert invocation.network_attempts, "the guard recorded no attempt"
