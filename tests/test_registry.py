# SPDX-License-Identifier: Apache-2.0
"""The contract's own documents: the schemas and the reason-code registry.

Gate 1 re-run as a test (both schemas validate against the draft 2020-12
metaschema), plus the invariants that keep `schema/reason_codes.json` and
SPEC.md §7.1 from drifting apart. They drift the moment someone adds a code to
one and not the other, and the machine-readable file is what the conformance
runner enforces membership with — so a code that exists only in the prose table
is a code the runner will reject in the field.
"""

import json
import pathlib
import re

from jsonschema.validators import Draft202012Validator, validator_for

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT / "schema"
SPEC = (ROOT / "SPEC.md").read_text(encoding="utf-8")

CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


def _schemas():
    return sorted(
        list(SCHEMA_DIR.glob("*.schema.json")) + list((SCHEMA_DIR / "context").glob("*.json"))
    )


def test_every_schema_validates_against_the_draft_2020_12_metaschema():
    for path in _schemas():
        document = json.loads(path.read_text(encoding="utf-8"))
        cls = validator_for(document)
        assert cls is Draft202012Validator, f"{path.name} is not draft 2020-12"
        errors = list(cls(cls.META_SCHEMA).iter_errors(document))
        assert not errors, f"{path.name}: {[e.message for e in errors]}"


def test_the_request_shape_is_closed_and_exactly_four_fields():
    """SPEC.md §5: `additionalProperties: false` IS the structural invariant."""
    request = json.loads((SCHEMA_DIR / "request.schema.json").read_text(encoding="utf-8"))
    assert request["additionalProperties"] is False
    assert set(request["properties"]) == {"profile", "task", "candidate", "context"}
    assert set(request["required"]) == {"profile", "task", "candidate", "context"}


def test_the_verdict_shape_is_closed_and_requires_a_code_on_a_fail():
    verdict = json.loads((SCHEMA_DIR / "verdict.schema.json").read_text(encoding="utf-8"))
    assert verdict["additionalProperties"] is False
    assert verdict["properties"]["verdict"]["enum"] == ["pass", "fail"]
    assert verdict["then"]["required"] == ["reason_code"]


def _registry():
    return json.loads((SCHEMA_DIR / "reason_codes.json").read_text(encoding="utf-8"))["codes"]


def test_every_registered_code_is_well_formed_and_self_consistent():
    for code, spec in _registry().items():
        assert CODE_PATTERN.match(code), code
        # SPEC.md §7: the namespace must equal the profile. Not expressible in
        # draft 2020-12; enforced by the conformance runner at verdict time and
        # here at registry time.
        assert code.split(".", 1)[0] == spec["profile"], code
        assert spec["status"] in {"active", "retired"}, code
        assert spec["meaning"].strip(), code


def test_the_registry_and_the_spec_table_name_the_same_codes():
    table = set(re.findall(r"^\| `([a-z0-9_]+\.[a-z0-9_]+)` \|", SPEC, re.MULTILINE))
    registry = set(_registry())
    assert table == registry, f"only in SPEC: {table - registry}; only in JSON: {registry - table}"


def test_the_three_code_codes_fixed_by_the_prompt_are_present():
    """CC-P1 v2 §0.3 fixes these one-to-one against `checks_pass`'s returns."""
    registry = _registry()
    for code in ("code.empty_diff", "code.lint_failed", "code.tests_failed"):
        assert registry[code]["profile"] == "code"


def test_design_registers_no_codes_until_it_has_a_predicate():
    assert not [c for c, s in _registry().items() if s["profile"] == "design"]


def test_the_append_only_policy_is_stated_in_both_places():
    assert "append-only" in json.loads(
        (SCHEMA_DIR / "reason_codes.json").read_text(encoding="utf-8")
    )["policy"]
    assert "never redefined and never removed" in SPEC
