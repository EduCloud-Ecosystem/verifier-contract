#!/usr/bin/env python3
"""
The conformance runner. Point it at an executable; it says whether that
executable is a conformant verifier.

    python conformance/runner.py                        # every profile + adversarial
    python conformance/runner.py --profile science
    python conformance/runner.py --profile code --exec "python3 path/to/code_profile.py"
    python conformance/runner.py --adversarial

This is the executable form of SPEC.md section 11. An implementation in any
language passes by satisfying it: nothing below imports a profile, and the only
interface used is "write a request document on the child's stdin, read a verdict
document off its stdout, look at its exit status".

THE CHECKS, and the SPEC.md clause each one is:

  request_schema             section 3   the request is a valid, closed document
  request_context_schema     section 3.1 the profile's own context shape
  exit_code                  section 1.1 exit 0 iff a verdict was reached
  stdout_json                section 1   exactly one JSON object on stdout
  verdict_schema             section 4   the verdict is a valid, closed document
  profile_echo               section 4   the verdict echoes the request's profile
  fail_has_reason_code       section 4   a fail carries a reason code
  reason_code_registered     section 7   the code is in schema/reason_codes.json
  reason_code_namespace      section 7   its namespace equals the profile
  evidence_non_reproduction  section 6   no evidence string reproduces candidate
  determinism                section 8   two invocations, identical verdicts
  network_isolation          section 5   no outbound connection was attempted
  golden_match               section 8   the verdict matches the golden document
  expected_error             section 1.1 a stub profile must fail as a JUDGE

A NON-ZERO EXIT IS NOT A FAILED VERDICT. The runner records it as
`kind="verifier_error"` with `verdict=None`, and every report distinguishes the
two columns. Conflating them is the defect SPEC.md section 1.1 exists to
prevent, so the runner refuses to represent them the same way even internally.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import platform
import re
import shlex
import subprocess
import sys
import tempfile

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - the runner's one dependency
    print(
        "conformance: jsonschema is required to run the suite "
        "(`uv sync` or `pip install jsonschema`)",
        file=sys.stderr,
    )
    raise

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFORMANCE = ROOT / "conformance"
GUARD_DIR = CONFORMANCE / "guard"
SCHEMA_DIR = ROOT / "schema"

TIMEOUT_SECONDS = 600

# SPEC.md section 6: the operationalised threshold. Forty is a threshold, not the
# rule; a profile that games it is out of conformance even if this passes it.
EVIDENCE_RUN_LENGTH = 40

SANDBOX_EXEC = pathlib.Path("/usr/bin/sandbox-exec")
# macOS Seatbelt profile: everything permitted except the network. `sandbox-exec`
# is deprecated by Apple and still present and functional on Darwin; the runner
# probes it at start-up rather than assuming, and degrades loudly.
SANDBOX_PROFILE = "(version 1)(allow default)(deny network-outbound)(deny network-bind)"


# ── the contract's own documents ─────────────────────────────────────────────


def _schema(*parts: str) -> dict:
    return json.loads(SCHEMA_DIR.joinpath(*parts).read_text(encoding="utf-8"))


REQUEST_VALIDATOR = Draft202012Validator(_schema("request.schema.json"))
VERDICT_VALIDATOR = Draft202012Validator(_schema("verdict.schema.json"))
REASON_CODES = _schema("reason_codes.json")["codes"]


def _context_validator(profile: str) -> Draft202012Validator | None:
    path = SCHEMA_DIR / "context" / f"{profile}.context.schema.json"
    if not path.is_file():
        return None
    return Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))


# ── evidence non-reproduction (SPEC.md section 6) ────────────────────────────


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).lower()


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value)


def reproduces_candidate(evidence, candidate: str, n: int = EVIDENCE_RUN_LENGTH):
    """Return the first evidence string sharing an n-char run with candidate."""
    haystack = _normalise(candidate)
    if len(haystack) < n:
        return None
    windows = {haystack[i : i + n] for i in range(len(haystack) - n + 1)}
    for value in _strings(evidence):
        needle = _normalise(value)
        if len(needle) < n:
            continue
        if any(needle[i : i + n] in windows for i in range(len(needle) - n + 1)):
            return value
    return None


# ── invocation ───────────────────────────────────────────────────────────────


class Sandbox:
    """The kernel-level half of the network mechanism, probed not assumed."""

    def __init__(self) -> None:
        self.available = False
        self.reason = "not attempted"
        if platform.system() != "Darwin":
            self.reason = f"sandbox-exec is macOS-only; this is {platform.system()}"
            return
        if not SANDBOX_EXEC.is_file():
            self.reason = f"{SANDBOX_EXEC} not present"
            return
        # Probe: does a denied connect actually fail under this profile on this
        # machine? A mechanism claimed but not verified is worse than none.
        probe = (
            "import socket,sys\n"
            "try:\n"
            "    socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(('192.0.2.1', 80))\n"
            "except PermissionError:\n"
            "    sys.exit(0)\n"
            "except OSError:\n"
            "    sys.exit(3)\n"
            "sys.exit(1)\n"
        )
        try:
            proc = subprocess.run(
                [str(SANDBOX_EXEC), "-p", SANDBOX_PROFILE, sys.executable, "-c", probe],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as err:
            self.reason = f"probe failed to run: {err}"
            return
        if proc.returncode == 0:
            self.available = True
            self.reason = "verified by probe: connect(2) denied with EPERM"
        else:
            self.reason = f"probe did not observe a denial (exit {proc.returncode})"

    def wrap(self, argv: list[str]) -> list[str]:
        if not self.available:
            return argv
        return [str(SANDBOX_EXEC), "-p", SANDBOX_PROFILE, *argv]


class Invocation:
    __slots__ = ("returncode", "stdout", "stderr", "network_attempts")

    def __init__(self, returncode, stdout, stderr, network_attempts):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.network_attempts = network_attempts


def invoke(argv: list[str], request: dict, cwd: str | None, sandbox: Sandbox) -> Invocation:
    """One verifier invocation, under both network layers."""
    with tempfile.TemporaryDirectory(prefix="verifier-conformance-") as tmp:
        netlog = pathlib.Path(tmp) / "netlog"
        env = dict(os.environ)
        # The guard rides on PYTHONPATH, which `site` consults before any
        # verifier code runs. The VERIFIER is still invoked with no arguments
        # and reads no environment variable of its own (SPEC.md section 1).
        env["PYTHONPATH"] = os.pathsep.join(
            [str(GUARD_DIR)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
        )
        env["VERIFIER_NETGUARD_LOG"] = str(netlog)
        env.pop("PYTHONDONTWRITEBYTECODE", None)
        try:
            proc = subprocess.run(
                sandbox.wrap(argv),
                input=json.dumps(request),
                capture_output=True,
                text=True,
                cwd=cwd,
                env=env,
                timeout=TIMEOUT_SECONDS,
            )
            returncode, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired:
            returncode, stdout, stderr = 124, "", f"timed out after {TIMEOUT_SECONDS}s"
        except OSError as err:
            returncode, stdout, stderr = 127, "", f"could not execute {argv!r}: {err}"
        attempts = (
            [ln for ln in netlog.read_text(encoding="utf-8").splitlines() if ln.strip()]
            if netlog.is_file()
            else []
        )
    return Invocation(returncode, stdout, stderr, attempts)


# ── a single case ────────────────────────────────────────────────────────────


class CaseResult:
    def __init__(self, name: str, profile: str):
        self.name = name
        self.profile = profile
        self.failures: list[str] = []
        self.notes: list[str] = []
        self.invoked = False
        # "conformant" | "verifier_error" | "not_invoked" | "verdict"
        self.kind = "not_invoked"
        # Deliberately None whenever no verdict was reached. A verifier error is
        # NOT a fail verdict, and this object refuses to store it as one.
        self.verdict: dict | None = None

    @property
    def ok(self) -> bool:
        return not self.failures

    def fail(self, check: str, note: str = "") -> None:
        self.failures.append(check)
        if note:
            self.notes.append(f"{check}: {note}")


def run_case(case: dict, argv: list[str], cwd: str | None, sandbox: Sandbox) -> CaseResult:
    profile = case["request"].get("profile", "?")
    result = CaseResult(case.get("name", case.get("id", "?")), profile)
    request = case["request"]

    # 1. The request is validated BEFORE the verifier is invoked. A malformed
    #    request is the caller's defect, and running a verifier against one
    #    would test nothing about the verifier (SPEC.md section 3).
    errors = sorted(REQUEST_VALIDATOR.iter_errors(request), key=lambda e: list(e.path))
    if errors:
        result.fail("request_schema", "; ".join(e.message for e in errors))
        return result
    context_validator = _context_validator(profile)
    if context_validator is not None:
        errors = sorted(
            context_validator.iter_errors(request.get("context", {})),
            key=lambda e: list(e.path),
        )
        if errors:
            result.fail("request_context_schema", "; ".join(e.message for e in errors))
            return result

    # 2. Two invocations, always: determinism (SPEC.md section 8) is not an
    #    optional check and cannot be tested from one run.
    first = invoke(argv, request, cwd, sandbox)
    second = invoke(argv, request, cwd, sandbox)
    result.invoked = True

    attempts = first.network_attempts + second.network_attempts
    if attempts:
        result.fail("network_isolation", "; ".join(attempts[:3]))

    if case.get("expect_verifier_error"):
        # A declared `not_implemented` stub. It must fail as a JUDGE, not emit a
        # verdict about the candidate.
        result.kind = "verifier_error"
        if first.returncode == 0:
            result.fail("expected_error", "exited 0; a stub must reach no verdict")
        if first.stdout.strip():
            result.fail("expected_error", "wrote to stdout while reaching no verdict")
        return result

    if first.returncode != 0 or second.returncode != 0:
        # SPEC.md section 1.1. Recorded as a verifier error and NOT as a fail
        # verdict; result.verdict stays None on purpose.
        result.kind = "verifier_error"
        result.fail(
            "exit_code",
            f"exit {first.returncode}: {(first.stderr or '').strip()[:160]}",
        )
        return result

    try:
        verdict = json.loads(first.stdout)
        other = json.loads(second.stdout)
    except ValueError as err:
        result.kind = "verifier_error"
        result.fail("stdout_json", f"stdout is not one JSON object: {err}")
        return result
    if not isinstance(verdict, dict):
        result.fail("stdout_json", "stdout is JSON but not an object")
        return result

    result.kind = "verdict"
    result.verdict = verdict

    errors = sorted(VERDICT_VALIDATOR.iter_errors(verdict), key=lambda e: list(e.path))
    if errors:
        result.fail("verdict_schema", "; ".join(e.message for e in errors))

    if verdict.get("profile") != request["profile"]:
        result.fail(
            "profile_echo",
            f"verdict profile {verdict.get('profile')!r} != request {request['profile']!r}",
        )

    if verdict.get("verdict") == "fail":
        code = verdict.get("reason_code")
        if not code:
            result.fail("fail_has_reason_code", "a fail verdict carries no reason_code")
        else:
            if code not in REASON_CODES:
                result.fail("reason_code_registered", f"{code} is not in schema/reason_codes.json")
            # SPEC.md section 7: the namespace must equal `profile`. This is the
            # cross-field constraint draft 2020-12 cannot express, which is why
            # it is checked here and not in the schema.
            if code.split(".", 1)[0] != verdict.get("profile"):
                result.fail(
                    "reason_code_namespace",
                    f"{code} is not namespaced by profile {verdict.get('profile')!r}",
                )

    echoed = reproduces_candidate(verdict.get("evidence", []), request["candidate"])
    if echoed is not None:
        result.fail(
            "evidence_non_reproduction",
            f"evidence reproduces >= {EVIDENCE_RUN_LENGTH} chars of the candidate: {echoed[:80]!r}",
        )

    if verdict != other:
        result.fail("determinism", "two invocations on identical input disagreed")

    if "expect" in case and verdict != case["expect"]:
        result.fail("golden_match", "verdict does not match the golden document")

    return result


# ── suites ───────────────────────────────────────────────────────────────────


def load_golden(profile: str) -> list[dict]:
    directory = CONFORMANCE / "golden" / profile
    if not directory.is_dir():
        return []
    return [
        json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*.json"))
    ]


def resolve_manifest() -> dict:
    """Profile -> {argv, cwd}, with sibling-repo placeholders expanded.

    `leak` lives in Belay and `code` in Portage, because the predicate belongs to
    the caller that owns it. A checkout without those siblings runs the profiles
    it has and says so; it does not silently report a smaller suite as green.
    """
    manifest = json.loads((CONFORMANCE / "profiles.json").read_text(encoding="utf-8"))
    dev = ROOT.parent
    values = {
        "CONTRACT": str(ROOT),
        "BELAY": os.environ.get("BELAY_DIR", str(dev / "belay")),
        "PORTAGE": os.environ.get("PORTAGE_DIR", str(dev / "portage")),
        "PYTHON": sys.executable,
    }
    resolved = {}
    for profile, spec in manifest.items():
        if profile.startswith("$"):
            continue
        argv = [_expand(part, values) for part in spec["argv"]]
        cwd = _expand(spec["cwd"], values) if spec.get("cwd") else None
        if argv[0].startswith("${"):
            resolved[profile] = {"argv": argv, "cwd": cwd, "missing": argv[0]}
            continue
        target = pathlib.Path(argv[0])
        missing = None
        if spec.get("requires"):
            required = pathlib.Path(_expand(spec["requires"], values))
            if not required.exists():
                missing = str(required)
        if not target.exists() and "/" in argv[0]:
            missing = argv[0]
        resolved[profile] = {"argv": argv, "cwd": cwd, "missing": missing}
    return resolved


def _expand(text: str, values: dict) -> str:
    if "${BELAY_PYTHON}" in text:
        text = text.replace("${BELAY_PYTHON}", _belay_python(values["BELAY"]))
    for key, value in values.items():
        text = text.replace("${" + key + "}", value)
    return text


def _belay_python(belay: str) -> str:
    """Belay's checked-in virtualenv interpreter, whichever minor version it is."""
    candidates = sorted(pathlib.Path(belay, "backend", ".venv", "bin").glob("python3.*"))
    return str(candidates[-1]) if candidates else "python3"


def run_profile(profile: str, argv: list[str], cwd: str | None, sandbox: Sandbox):
    return [run_case(case, argv, cwd, sandbox) for case in load_golden(profile)]


def run_adversarial(sandbox: Sandbox):
    """Every case here MUST be rejected — except the control, which must pass.

    A suite that only proves it rejects bad verifiers has not shown it accepts
    good ones, and a runner that rejects everything would pass that half.
    """
    cases = json.loads((CONFORMANCE / "adversarial" / "cases.json").read_text(encoding="utf-8"))
    outcomes = []
    for case in cases:
        argv = [part.replace("${PYTHON}", sys.executable) for part in case["exec"]]
        result = run_case(case, argv, str(ROOT), sandbox)
        expected = case.get("must_be_caught_by")
        if expected is None:  # the control
            verdict = "ok" if result.ok else "REJECTED A CONFORMANT VERIFIER"
            passed = result.ok
        elif result.ok:
            verdict, passed = "NOT REJECTED", False
        elif expected not in result.failures:
            verdict = f"rejected for the wrong reason: {result.failures}"
            passed = False
        else:
            verdict, passed = f"rejected on {expected}", True
        # The non-zero-exit case additionally has to be classified correctly:
        # rejecting it as a `fail` verdict would be the very conflation
        # SPEC.md section 1.1 forbids.
        if case.get("must_be_kind") and result.kind != case["must_be_kind"]:
            verdict = f"kind was {result.kind!r}, expected {case['must_be_kind']!r}"
            passed = False
        if case.get("must_not_be_invoked") and result.invoked:
            verdict = "the verifier was invoked; a malformed request must be caught first"
            passed = False
        if case.get("must_have_no_verdict") and result.verdict is not None:
            verdict = "a verdict was recorded for a run that reached none"
            passed = False
        outcomes.append((case["id"], passed, verdict, case.get("why", "")))
    return outcomes


# ── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--profile", help="run one profile's golden set")
    parser.add_argument("--exec", dest="command", help="the executable to test, as a shell string")
    parser.add_argument("--cwd", help="working directory for the executable")
    parser.add_argument("--adversarial", action="store_true", help="run only the adversarial suite")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    sandbox = Sandbox()
    print(f"network isolation: python socket guard ON; sandbox-exec {sandbox.reason}")
    if not sandbox.available:
        print("  ! kernel-level isolation UNAVAILABLE — coverage is Python children only")

    failed = 0
    total = 0

    if not args.adversarial:
        if args.profile and args.command:
            targets = {args.profile: {"argv": shlex.split(args.command), "cwd": args.cwd,
                                      "missing": None}}
        else:
            targets = resolve_manifest()
            if args.profile:
                targets = {args.profile: targets[args.profile]}
        for profile, spec in targets.items():
            cases = load_golden(profile)
            if spec.get("missing"):
                print(f"\n{profile}: SKIPPED — {spec['missing']} not present "
                      f"({len(cases)} golden cases not run)")
                continue
            print(f"\n{profile}: {len(cases)} golden cases  [{' '.join(spec['argv'])}]")
            for result in run_profile(profile, spec["argv"], spec["cwd"], sandbox):
                total += 1
                if result.ok:
                    if not args.quiet:
                        print(f"  ok    {result.name}  ({result.kind})")
                else:
                    failed += 1
                    print(f"  FAIL  {result.name}  {result.failures}")
                    for note in result.notes:
                        print(f"          {note}")

    if args.adversarial or not args.profile:
        print("\nadversarial cases (every one must be rejected; the control must not be):")
        for case_id, passed, note, why in run_adversarial(sandbox):
            total += 1
            if passed:
                if not args.quiet:
                    print(f"  ok    {case_id}: {note}")
            else:
                failed += 1
                print(f"  FAIL  {case_id}: {note}")
                if why:
                    print(f"          {why}")

    print(f"\n{total - failed}/{total} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
