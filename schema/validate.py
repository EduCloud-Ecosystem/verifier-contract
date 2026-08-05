#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema>=4.20"]
# ///
# SPDX-License-Identifier: Apache-2.0
"""Gate 1: both schemas validate against the JSON Schema draft 2020-12 metaschema.

Offline — `jsonschema` bundles the metaschema, so nothing here touches the network.
The behavioural cases (extra field rejected, `fail` without a reason code rejected,
and the rest of SPEC.md section 11) belong to the conformance suite, not here; this
script asserts only that the schema documents are themselves well-formed 2020-12.

    uv run schema/validate.py
"""

import json
import pathlib
import sys

from jsonschema.validators import Draft202012Validator, validator_for

HERE = pathlib.Path(__file__).parent
# The two wire-format schemas, plus every per-profile context schema. A profile
# SHOULD close its own context shape (SPEC.md §3.1); one that does so with a
# malformed schema has closed nothing.
SCHEMAS = tuple(
    p.relative_to(HERE).as_posix()
    for p in [HERE / "request.schema.json", HERE / "verdict.schema.json"]
    + sorted((HERE / "context").glob("*.json"))
)


def main() -> int:
    failed = False
    for name in SCHEMAS:
        doc = json.loads((HERE / name).read_text(encoding="utf-8"))
        cls = validator_for(doc)
        if cls is not Draft202012Validator:
            print(f"FAIL {name}: $schema is not draft 2020-12 ({cls.__name__})")
            failed = True
            continue
        errors = sorted(cls(cls.META_SCHEMA).iter_errors(doc), key=lambda e: list(e.path))
        for err in errors:
            print(f"FAIL {name}: {list(err.path)}: {err.message}")
            failed = True
        if not errors:
            print(f"ok   {name}: validates against the draft 2020-12 metaschema")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
