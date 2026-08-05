# The conformance suite

This is the executable form of `SPEC.md` §11, and it is the piece meant to be
published. Point the runner at any executable; it says whether that executable
is a conformant verifier. Nothing in here imports a profile — the only interface
used is "write a request document on the child's stdin, read a verdict document
off its stdout, look at its exit status" — so an implementation in any language
passes by satisfying it.

```
uv run python conformance/runner.py                     # every profile + adversarial
uv run python conformance/runner.py --profile science
uv run python conformance/runner.py --profile code --exec "python3 /path/to/verifier"
uv run python conformance/runner.py --adversarial
```

## Layout

| Path | What it is |
|---|---|
| `runner.py` | The runner. One check per `SPEC.md` clause; see its module docstring for the mapping. |
| `profiles.json` | Where each shipped profile's executable lives. |
| `golden/<profile>/*.json` | Golden request/verdict pairs: `name`, `why`, `request`, and either `expect` (the verdict, matched exactly) or `expect_verifier_error`. |
| `adversarial/verifiers.py` | Deliberately non-conformant verifiers, one violation each. |
| `adversarial/cases.json` | Which case must be caught by which check, and why it matters. |
| `guard/sitecustomize.py` | The Python-level network guard. |

Two of the four shipped profiles live in sibling repositories, because a profile
belongs to the repository of the caller that owns its predicate (`leak` in
Belay, `code` in Portage). The runner reports a missing sibling as **SKIPPED**
with the path it looked for; it never silently reports a smaller suite as green.
Override the locations with `BELAY_DIR` and `PORTAGE_DIR`.

## The control case

`adversarial/cases.json` opens with `control_conformant_verifier`, which must
**pass**. A suite that only demonstrates it rejects bad verifiers has not shown
it accepts good ones, and a runner that rejected everything would score full
marks on the other ten cases.

## Network isolation on macOS, and exactly what it covers

`SPEC.md` §5 says a verifier cannot consult the model that produced the
candidate, and §11 item 8 makes "opens no outbound connection during
verification" a conformance requirement. Linux network namespaces are not
available on macOS, and there is no `LD_PRELOAD` equivalent that survives
System Integrity Protection, so the runner uses **two layers**. Neither is
sufficient alone and the runner states at start-up which ones are live:

```
network isolation: python socket guard ON; sandbox-exec verified by probe: connect(2) denied with EPERM
```

**Layer 1 — a Python socket guard (`guard/sitecustomize.py`).** The runner puts
that directory on the child's `PYTHONPATH`; CPython's `site` module imports
`sitecustomize` before any verifier code runs. It wraps
`socket.socket.connect`, `.connect_ex`, `socket.create_connection` and
`socket.getaddrinfo`: an AF_INET/AF_INET6 attempt is **appended to a log file
and then raises `PermissionError`**. AF_UNIX is untouched, because a unix socket
is not an outbound connection.

Logging before raising is the load-bearing detail. The adversarial case
`verifier_opens_an_outbound_connection` catches its own `PermissionError` and
emits a perfectly clean `pass`, so nothing in the verdict, the exit code or
stdout gives it away. It is rejected because the *attempt* was recorded, not
because the verifier admitted to it.

- **Covers:** any Python child, including subprocesses it spawns (they inherit
  `PYTHONPATH`), with per-attempt attribution — the runner can say *what* was
  connected to.
- **Does not cover:** a verifier written in Go, Rust or C; a Python verifier
  that calls `connect(2)` through `ctypes` or a C extension; a Python
  interpreter started with `-S` or `-E`.

**Layer 2 — `sandbox-exec` (macOS Seatbelt).** Every invocation is wrapped in
`sandbox-exec -p '(version 1)(allow default)(deny network-outbound)(deny
network-bind)'`. This is kernel-level and language-independent.

It is **probed, not assumed**: at start-up the runner runs a child that attempts
a TCP connect under that profile and checks that it fails with `EPERM`. If the
probe does not observe a denial the runner prints

```
! kernel-level isolation UNAVAILABLE — coverage is Python children only
```

and carries on with layer 1. A mechanism claimed but not verified is worse than
no mechanism, so the probe result is printed on every run rather than inferred
from the platform name.

- **Covers:** arbitrary executables in any language, which is what makes the
  suite meaningful for the Go implementation in
  `github.com/EduCloud-Ecosystem/cairn`.
- **Does not cover:** attribution. A denied connect surfaces to the child as an
  ordinary `EPERM`, so a non-Python verifier that ignores the error and carries
  on is caught only if it *also* fails some other check. Against a non-Python
  verifier the honest claim is "it could not reach the network", not "we
  detected that it tried".
- **Caveats:** `sandbox-exec` is deprecated by Apple (still present and
  functional on Darwin 25). It is macOS-only; on Linux this layer is absent and
  the equivalent would be a network namespace, which the runner does not yet
  implement.

**What neither layer covers.** A verifier that reads a cached response written
to disk by an earlier networked process. That is not a network connection during
verification and the suite does not claim to catch it — `SPEC.md` §8's
determinism requirement is what makes it visible, because a cache that changes
makes two invocations disagree.
