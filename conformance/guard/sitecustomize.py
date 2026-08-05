"""Socket-level network guard for the conformance runner. Python children only.

SPEC.md section 5 makes "a verifier opens no outbound connection during
verification" a conformance requirement, and section 11 item 8 lists it. This
file is one of the two mechanisms that enforce it; `conformance/README.md`
states exactly what each one covers and what neither does.

HOW IT IS INSTALLED. The runner puts this directory on the child's `PYTHONPATH`.
CPython's `site` module imports `sitecustomize` at interpreter start-up, before
any verifier code runs, so the patches below are in place before `main()` is
reached. The verifier reads no environment variable and takes no argument to
make this happen — the invocation convention in SPEC.md section 1 is untouched.
The runner sets `VERIFIER_NETGUARD_LOG`, and THIS FILE reads it; the verifier
never does.

WHAT IT DOES. `socket.socket.connect`, `.connect_ex`, `socket.create_connection`
and `socket.getaddrinfo` are wrapped. An AF_INET/AF_INET6 attempt is appended to
the log file and then raises `PermissionError`. AF_UNIX is left alone: a unix
socket is not an outbound connection, and blocking it would break unrelated
machinery (multiprocessing, some loggers) for no gain. DNS resolution is treated
as an outbound attempt in its own right, because it is one, and because a
verifier that resolves a name has already told a nameserver what it is doing.

WHY IT LOGS RATHER THAN ONLY RAISING. A verifier that catches the
`PermissionError` and carries on would otherwise look conformant. The log file
is written before the exception is raised, so the attempt is recorded whether or
not the verifier admits to it — the runner rejects on the log, not on the
verifier's behaviour afterwards.

LIMITS, STATED PLAINLY. This is a Python-level guard. It binds Python children
only, it can be defeated by a verifier that calls the `connect(2)` syscall
through `ctypes` or a C extension, and it says nothing about a verifier written
in Go or Rust. The kernel-level layer (`sandbox-exec`) is what covers those; see
`conformance/README.md`.
"""

import os
import socket

_LOG_PATH = os.environ.get("VERIFIER_NETGUARD_LOG")
_INET_FAMILIES = {socket.AF_INET, socket.AF_INET6}
_MESSAGE = (
    "outbound network access is blocked during verification "
    "(verifier contract SPEC.md section 5)"
)


def _record(attempt):
    if not _LOG_PATH:
        return
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(attempt + "\n")
            handle.flush()
    except OSError:
        # Never let the guard's own bookkeeping crash the child: a failed write
        # here would be indistinguishable from a verifier defect.
        pass


def _blocked(attempt):
    _record(attempt)
    raise PermissionError(_MESSAGE)


_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
_real_create_connection = socket.create_connection
_real_getaddrinfo = socket.getaddrinfo


def _connect(self, address):
    if self.family in _INET_FAMILIES:
        _blocked(f"socket.connect {address!r}")
    return _real_connect(self, address)


def _connect_ex(self, address):
    if self.family in _INET_FAMILIES:
        _blocked(f"socket.connect_ex {address!r}")
    return _real_connect_ex(self, address)


def _create_connection(address, *args, **kwargs):
    _blocked(f"socket.create_connection {address!r}")


def _getaddrinfo(host, port, *args, **kwargs):
    _blocked(f"socket.getaddrinfo {host!r}:{port!r}")


socket.socket.connect = _connect
socket.socket.connect_ex = _connect_ex
socket.create_connection = _create_connection
socket.getaddrinfo = _getaddrinfo
