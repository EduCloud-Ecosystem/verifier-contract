#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
Deliberately non-conformant verifiers. Each one violates exactly one clause of
SPEC.md section 11, and the conformance runner has to catch it for the right
reason — a runner that rejects everything would pass a suite that only checked
that bad verifiers are rejected, which is why `reference_pass` is here too and
why the suite fails if that one is rejected.

Every mode is one file so the failure modes sit side by side and stay readable.
Selected by `argv[1]`, which is the only place in this repository an argument is
read: these are not verifiers under test, they are fixtures the runner drives,
and the runner still supplies the request on stdin the way it does for a real
one.

  reference_pass       conformant. THE CONTROL.
  unparseable_stdout   writes something that is not JSON              -> stdout_json
  invalid_verdict      writes a JSON object the verdict schema rejects -> verdict_schema
  fail_without_reason  a `fail` carrying no reason_code                -> fail_has_reason_code
  unregistered_code    a `fail` whose code is not in the registry      -> reason_code_registered
  foreign_namespace    a `fail` whose code names another profile       -> reason_code_namespace
  crashes              exits non-zero                                  -> exit_code (verifier_error)
  nondeterministic     alternates verdicts across invocations          -> determinism
  phones_home          opens an outbound connection mid-verification   -> network_isolation
  echoes_candidate     puts the candidate's text into evidence         -> evidence_non_reproduction
"""

import json
import pathlib
import sys
import tempfile


def _request():
    return json.loads(sys.stdin.read())


def _emit(doc):
    json.dump(doc, sys.stdout)
    sys.stdout.write("\n")
    return 0


def _pass(request, evidence=None):
    return {
        "verdict": "pass",
        "profile": request["profile"],
        "detail": "reference verifier: nothing was actually checked",
        "evidence": evidence if evidence is not None else [],
    }


def reference_pass():
    return _emit(_pass(_request()))


def unparseable_stdout():
    _request()
    sys.stdout.write("VERDICT: pass\n")
    return 0


def invalid_verdict():
    request = _request()
    # Two violations at once: a third verdict value, and an extra property under
    # `additionalProperties: false`. Either alone is enough.
    return _emit(
        {
            "verdict": "error",
            "profile": request["profile"],
            "detail": "the candidate could not be assessed",
            "evidence": [],
            "confidence": 0.4,
        }
    )


def fail_without_reason():
    request = _request()
    return _emit(
        {
            "verdict": "fail",
            "profile": request["profile"],
            "detail": "it was bad",
            "evidence": [],
        }
    )


def unregistered_code():
    request = _request()
    return _emit(
        {
            "verdict": "fail",
            "profile": request["profile"],
            "reason_code": f"{request['profile']}.vibes_off",
            "detail": "a code nobody registered",
            "evidence": [],
        }
    )


def foreign_namespace():
    request = _request()
    # A real registered code — from the wrong profile. The namespace rule is the
    # cross-field constraint JSON Schema draft 2020-12 cannot express, so this
    # case is the only thing standing between the registry and a namespace that
    # means nothing.
    return _emit(
        {
            "verdict": "fail",
            "profile": request["profile"],
            "reason_code": "code.tests_failed",
            "detail": "borrowed someone else's vocabulary",
            "evidence": [],
        }
    )


def crashes():
    _request()
    print("adversarial: the judge broke and reached no verdict", file=sys.stderr)
    return 9


def nondeterministic():
    """Alternates pass/fail across invocations on identical input.

    The counter lives in the system temp directory because the contract gives a
    verifier no state channel — which is the point: a verifier that needs one is
    already outside SPEC.md section 8.
    """
    request = _request()
    counter = pathlib.Path(tempfile.gettempdir()) / "verifier-conformance-nondeterministic"
    n = int(counter.read_text()) if counter.is_file() else 0
    counter.write_text(str(n + 1))
    if n % 2 == 0:
        return _emit(_pass(request))
    return _emit(
        {
            "verdict": "fail",
            "profile": request["profile"],
            "reason_code": "leak.is_solution",
            "detail": "the mood changed",
            "evidence": [],
        }
    )


def phones_home():
    """Opens an outbound connection, then behaves impeccably.

    It catches its own failure and emits a clean `pass`, so the runner cannot
    detect it from the verdict, the exit code, or anything on stdout. The only
    reason it is caught is that the guard records the attempt before raising —
    which is exactly the case SPEC.md section 5 says must not be enforceable by
    policy prose.
    """
    request = _request()
    try:
        import socket

        socket.create_connection(("192.0.2.1", 80), timeout=2).close()
    except Exception:  # noqa: BLE001 — the point is that it hides the failure
        pass
    return _emit(_pass(request))


def echoes_candidate():
    """Reproduces the candidate in evidence. SPEC.md section 6 / section 0.2.

    For the leak profile this is the safety property itself: a dropped passage
    that came back as text would put the solution into the trace THROUGH the
    contract, which is worse than doing it directly because it would look like
    conformance.
    """
    request = _request()
    return _emit(
        {
            "verdict": "fail",
            "profile": request["profile"],
            "reason_code": "leak.is_solution",
            "detail": "candidate contains a solution",
            "evidence": [
                {
                    "signal": "is_solution",
                    "fired": True,
                    "offending_text": request["candidate"],
                }
            ],
        }
    )


MODES = {
    "reference_pass": reference_pass,
    "unparseable_stdout": unparseable_stdout,
    "invalid_verdict": invalid_verdict,
    "fail_without_reason": fail_without_reason,
    "unregistered_code": unregistered_code,
    "foreign_namespace": foreign_namespace,
    "crashes": crashes,
    "nondeterministic": nondeterministic,
    "phones_home": phones_home,
    "echoes_candidate": echoes_candidate,
}


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in MODES:
        print(f"usage: verifiers.py [{'|'.join(MODES)}]", file=sys.stderr)
        sys.exit(64)
    sys.exit(MODES[sys.argv[1]]())
