# The verifier contract, v1

A verifier is an executable that decides one question about one candidate
artifact, deterministically and offline, and says so in a document.

This specification defines the wire format, the invocation convention, the
reason-code registry, and the four invariants that make an implementation
conformant. It says nothing about how a verifier reaches its decision. That is
deliberate: the point of the contract is that Belay's Python leak gate, Portage's
Python code gate, and a future Go implementation in
`github.com/EduCloud-Ecosystem/cairn` can all be the same kind of thing to a
caller.

> **Repository status.** This repository is private and its Apache-2.0 grant is
> not yet in force; see `LICENSING.md`. The contract is stable for internal use
> and is written to be published unchanged.

> **Cairn module path.** The rename in `CC-C4-cairn-rename.md` has **not** run.
> Cairn's `go.mod` still reads `module github.com/quad/quad`. Every reference in
> this document uses the post-rename path
> `github.com/EduCloud-Ecosystem/cairn`, which is the path as it will be, not as
> it is today.

---

## 1. The invocation convention

A verifier is any executable that:

1. reads a **request document** — one JSON object, UTF-8, on `stdin`;
2. writes a **verdict document** — one JSON object, UTF-8, on `stdout`;
3. exits `0` if it ran and reached a verdict, non-zero if it did not.

`stderr` is unconstrained and is for diagnostics. Nothing on `stderr` is part of
the contract; a caller must never parse it to recover a verdict.

There is no other invocation mode in v1. No arguments are read, no environment
variables are read, no files are opened except those named in the request's
`context`. A verifier that requires a flag to behave correctly is not conformant,
because the conformance runner invokes it with none.

### 1.1 The exit code is not the verdict

This is the single most load-bearing rule in the document.

| Exit code | Meaning | `stdout` |
|---|---|---|
| `0` | The verifier ran and reached a verdict. The verdict may be `pass` or `fail`. | A valid verdict document. |
| non-zero | **The verifier itself failed.** It reached no verdict. | Undefined. Callers must not parse it. |

A non-zero exit is *not* a `fail` verdict and must never be treated as one. A
caller that collapses the two turns every crashed verifier into a universal
failure signal, which in a fail-up ladder means every task silently escalates to
the most expensive tier, and in a benchmark means the win-tier distribution
records capability failures that never happened.

The converse is equally binding: a verifier that catches its own crash and emits
`{"verdict": "fail", ...}` to keep its exit code at `0` has destroyed the
distinction from the inside. If a verifier cannot decide, it must exit non-zero
and say why on `stderr`.

### 1.2 Which non-zero code (informative, not normative)

**Every non-zero exit means the same thing to a conformant caller:** no verdict
was reached. The contract does not grade failures and a caller must not branch
on the value. The shipped profiles nevertheless use one convention, because a
human reading a log deserves to know whether the judge crashed or was never
built:

| Code | Meaning |
|---|---|
| `2` | The request document could not be read or parsed. |
| `3` | The verifier ran and failed — a missing tool, an unusable `context`, an unregistered resolver. |
| `4` | The profile is a declared `not_implemented` stub (`verifier.design`). |

A second implementation is free to ignore this table entirely. It is here so
that the four shipped profiles agree with each other rather than each inventing
a scheme, and `conformance/` asserts nothing about the value.

---

## 2. The two failure kinds, and why they stay apart

There are two ways a verification can fail to produce a capability judgement, and
they are different failures with different owners. This section exists because a
reader who does not see *why* they are separate will collapse them, and because
one of them is deliberately implemented outside this contract.

### 2.1 The subject was unreachable — not the contract's business

The model or runner that produced the candidate failed for availability reasons:
rate limits, gateway errors, connection refused, timeouts. The candidate is
absent or empty not because the subject lacked the capability but because the
subject was never really tried.

**This is detected upstream of the verifier, by the caller, before a request
document is ever constructed.** Portage implements it in
`src/portage/failup.py::runner_availability_failure()`, which scans the runner's
own stdout and stderr for `AVAILABILITY_MARKERS` before the deterministic gate
runs. Its reasoning, quoted verbatim from the source, is why this must not move
into the contract:

> ```
> # Substrings that mark a runner failure as UNAVAILABILITY (network/rate-limit/
> # gateway trouble) rather than the tier lacking the capability to do the task.
> # Checked case-insensitively against the runner's own stdout+stderr, BEFORE the
> # deterministic gate runs — an unreachable model also produces an empty diff,
> # and misfiling that as "empty-diff" (a capability verdict) would poison
> # measure.py's win-tier distribution and the steward's training signal
> # (PLATFORM.md §9) with attempts that were never really tried.
> ```

The verifier cannot make this call, and the structural invariant (§5) is the
reason: the request carries no endpoint, no credential and no model handle, so a
verifier has no way to distinguish "the model produced an empty diff because it
could not do the task" from "the model produced an empty diff because it was
rate-limited". Only the caller, which holds the runner's transcript, can tell
those apart. An empty diff arriving at a verifier is *already* a capability
question by the time it gets there, because the caller has already filtered out
the availability case.

**Implementers: do not add an availability mechanism to this contract.** There is
no `unavailable` verdict, no `availability` reason-code namespace, and no
`error` verdict value. Adding one creates a second implementation of a
distinction that already works, and two mechanisms for one distinction is a
defect whether or not they agree today.

### 2.2 The judge was unreachable — the contract's business

The verifier process itself broke: it crashed, it could not parse the request, a
tool it shells out to is missing, a path in `context` does not exist. No verdict
was reached about the candidate.

**This is a non-zero exit**, per §1.1. It is the only failure kind the contract
represents, and it is represented by the exit code rather than by a document,
precisely so that a caller cannot accidentally read it as a verdict by looking at
a field.

### 2.3 The two, side by side

| | Subject unreachable | Judge unreachable |
|---|---|---|
| What broke | The model/runner that produced the candidate | The verifier process |
| Who detects it | The caller, upstream | The operating system, via exit status |
| Where | `failup.py::runner_availability_failure()` and its equivalents | This contract, §1.1 |
| Signal | Caller-defined (`unavailable:<marker>` in Portage) | Non-zero exit code |
| In the contract? | **No, on purpose** | Yes |
| Misfiled as | `code.empty_diff` | any `fail` verdict |

Both misfilings produce the same damage — a capability verdict recorded for an
attempt that was never really judged — which is why the same rationale covers
both and why the two sites must cross-reference each other and this section.

### 2.4 Detecting subject-unreachability is half the caller's job; the other half is not aggregating over it

§2.1 says the caller owns the distinction. That is a statement about who
*detects* it, and detecting it is worth nothing on its own. A caller that
records "this tier was never reached" and then computes statistics as though it
had been has implemented the distinction and thrown it away, and the resulting
numbers are worse than if it had never made the distinction at all — because
they now look like they were checked.

**The rule for callers that aggregate.** If you fan a candidate out across a
ladder of subjects, cheapest first, taking the first that earns a `pass`, then a
run is admissible capability evidence only if every rung below the winning rung
produced a *verdict*. A rung that was never reached produced no verdict, so the
run cannot say whether that rung would have sufficed, and it must not contribute
to any capability statistic or to any training label derived from "the cheapest
rung that passed".

Note what this is not. It is not "drop the unreachable attempts and reconstruct
from the rest". That removes the visible error and leaves a quieter one of the
same sign: with the unreachable attempt gone, the run is indistinguishable from
one that legitimately started at the higher rung, so it still lands in the
win-rung distribution as a task that *needed* that rung, and still becomes a
routing label pointing at a rung whose cheaper alternative was never tested.
Admissibility is a judgement about the run. It is not a filter on records, and
the unreachable attempts should stay in the run so that reports can count them.

Inadmissible runs are excluded and **counted**. A capability statistic computed
over a filtered population that does not say it was filtered is a worse defect
than the one being fixed here.

**First instance found in practice.** Portage. `failup.py` has recorded
`category: "ok" | "capability" | "availability"` on every attempt since before
this contract existed, and the comment §2.1 quotes states exactly why. Nothing
downstream read the field: `measure.py` and `distill.py` reconstructed runs from
`ok` and `tier` alone, so an unreachable tier 0 followed by a pass at tier 1 was
recorded as "this task needs tier 1" across four independent readers — the
headline escalation and floor-pass rates, the win-tier distribution, the
counterfactual that decides whether a paid subscription lane can be cancelled,
and the routing training labels. The discriminator was written and never read
for the whole life of the instrument. The fix is one shared reconstruction
(`src/portage/runlog.py::reconstruct`) applying the rule above, imported by both
consumers, because three independent copies of the same reconstruction is how
the defect survived in the first place.

**Implementers: this is the failure mode to expect.** A second implementation
gets the exit-code rule from §1.1 and the caller-side detection from §2.1 and
will reproduce this defect exactly, because both of those can be satisfied
completely while the aggregation stays wrong. The detection is the easy half and
it is the half the spec was previously alone in describing.

---

## 3. The request document

```json
{
  "profile":   "leak",
  "task":      "Compute the mean amount per category from a CSV into `result`.",
  "candidate": "You've read the CSV — what single number should each category collapse to?",
  "context":   { "exercise": { "id": "ds-foundations" }, "stance": "peer" }
}
```

| Field | Type | Required | Meaning |
|---|---|---|---|
| `profile` | string | yes | Which question is being asked. Matches `^[a-z][a-z0-9_]*$`. Also the reason-code namespace (§7). |
| `task` | string | yes | What the candidate was supposed to do, in the task's own words. A verifier may ignore it; it must not be absent. |
| `candidate` | string | yes | The artifact being judged. May be empty — an empty candidate is a legitimate subject, not an error. |
| `context` | object | yes | Everything else the profile needs. Profile-specific, and the only extension point. May be `{}`. |

`additionalProperties: false` at the top level. There are exactly four fields and
there will never be a fifth. New profile needs go in `context`, which is where
the schema deliberately stops constraining.

`candidate` is a string because the thing being judged is always a produced
artifact — a message, a diff, a passage, a manuscript. Structured inputs that
*describe* the candidate (a working directory, an exercise record, a rubric) are
context, not candidate. Keeping `candidate` a scalar is what makes the evidence
non-reproduction rule (§6) mechanically checkable: the runner has exactly one
string to look for in the evidence.

### 3.1 The `context` object is profile-defined and closed at the profile

The top-level schema constrains `context` only to `type: object`. Each profile
defines its own context shape and each profile SHOULD close that shape with
`additionalProperties: false` in its own schema. The contract does not do it for
them, because the contract does not know what a profile needs.

Contexts defined so far. The two that have a schema carry it in
`schema/context/`, and the conformance runner validates a request's `context`
against it when one exists:

| Profile | `context` fields | Schema |
|---|---|---|
| `leak` | `exercise` (object — the full exercise record), `stance` (string), `subject_id` (string, optional — see §6.2) | — |
| `code` | `working_dir` (string), `commands` (object with optional `lint`, `typecheck`, `test`, each an argv array) | `schema/context/code.context.schema.json` |
| `science` | `rubric` (object), `resolver` (string: `inline` \| `live`), `sources` (object, optional — the fixture records the `inline` resolver reads) | `schema/context/science.context.schema.json` |
| `design` | not defined; the profile is an explicit `not_implemented` stub | — |

`leak` has no context schema because its `exercise` is an entire domain record
whose shape belongs to Belay, and closing it here would make the contract the
owner of a value type it does not define. That is a deliberate exception to the
SHOULD above, not an omission.

`science.sources` is the shape the injected resolver reads when the request
names the `inline` resolver, which is the only resolver a shipped build
registers (§5). It is `context` rather than a new top-level field precisely
because §3's four fields never grow.

---

## 4. The verdict document

```json
{
  "verdict":     "fail",
  "profile":     "leak",
  "reason_code": "leak.is_solution",
  "detail":      "candidate contains code that independently meets the exercise goal",
  "evidence":    [{"signal": "is_solution", "subject_id": null, "snippet_count": 1}]
}
```

| Field | Type | Required | Meaning |
|---|---|---|---|
| `verdict` | `"pass"` \| `"fail"` | yes | The decision. Two values, no third. |
| `profile` | string | yes | Echoes the request's `profile`. A mismatch is a conformance failure. |
| `reason_code` | string | **when `verdict` is `fail`** | A registered code from §7, namespaced by `profile`. |
| `detail` | string | yes | Human-readable. Never parsed. May be empty on a `pass`. |
| `evidence` | array of objects | yes | Profile-defined. May be empty. Subject to §6. |

`additionalProperties: false`.

**A `fail` must carry a `reason_code`.** This is enforced in the schema by an
`if`/`then`, not by prose, because a `fail` without a code is a verdict a
consumer cannot route on, and routing on verdicts is what the whole contract is
for.

**A `pass` may carry evidence**, and often should — a `pass` with evidence is how
a profile reports what it checked and found clean, which is what makes coverage
measurable rather than assumed. A `pass` may also carry a `reason_code`, though
no shipped profile does; if it does, the code must still be registered, and a
consumer must never infer failure from the presence of a code.

### 4.1 `reason_code` is singular; `evidence` is plural

A verdict names exactly one reason code. Real predicates can have several
independent signals true at once — Belay's leak gate is exactly such a case, with
`is_solution` and `prose_disclosure` able to fire on the same candidate.

The rule is:

- `reason_code` names the **primary** reason, chosen by a precedence the profile
  documents and never varies (determinism, §8).
- `evidence` carries **every** signal that fired, so nothing is lost.

A caller that needs the full signal set reads `evidence`; a caller that needs to
route reads `reason_code`. Widening `reason_code` into an array was considered
and rejected: every consumer would then have to decide what "the" reason is, and
they would decide differently.

The `leak` profile's documented precedence is `leak.is_solution` before
`leak.prose_disclosure`, matching `governance.py::screen_passages`'s existing
`"is_solution" if ev.is_solution else "prose_disclosure"`.

---

## 5. The structural invariant

**A request carries no model handle, no credential, no endpoint, and no
conversation history.**

The four fields in §3 are the whole of it, `additionalProperties: false` is the
whole of the enforcement, and there is no field in which a base URL, an API key,
a model name, a session id, or a transcript could legitimately travel.

The consequence is the point: **a verifier cannot consult the model that produced
the candidate, because it has no way to reach it.** Not "must not" — *cannot*.
A verifier that wanted to ask an LLM whether the candidate is good would have to
carry its own credentials, and the conformance suite's network-isolation case
(Step 4) fails any verifier that opens an outbound connection during
verification.

This is enforced by the schema and by the conformance test, **never by policy
prose**. A rule that lives only in a document is a rule that a second
implementation will violate without noticing. `additionalProperties: false` and a
blocked socket are rules that fail loudly.

A profile that genuinely needs the network — `verifier.science` must resolve
citations — takes a **resolver dependency** rather than reaching out itself. The
resolver is injected, tests inject a fixture, and the live resolver ships behind
a flag. No test in any repository reaches the network.

---

## 6. Evidence identifies and characterises; it does not reproduce

Evidence exists so a human or a downstream tool can understand *why* a verdict
came out the way it did. It does not exist to carry the candidate around.

**Normative rule.** No string value anywhere in `evidence` may reproduce content
from `candidate`. Evidence may carry:

- **identifiers** — passage ids, file paths, line numbers, citation keys,
  rubric keys;
- **characterisations** — booleans, counts, rates, categories, signal names;
- **profile vocabulary** — fixed strings the profile itself defines.

Evidence may not carry the candidate's text, a substring of it, a redacted or
paraphrased form of it, or any transformation from which it can be recovered.

**Operationalisation.** The conformance runner rejects a verdict if any string
value reachable in `evidence` shares a contiguous run of **40 or more
characters** with `candidate`, comparing case-insensitively with runs of
whitespace normalised to a single space. Forty is a threshold, not the rule; the
rule is the paragraph above, and a profile that games the threshold is out of
conformance even if the runner passes it.

### 6.1 Why this is load-bearing, not hygiene

For the `leak` profile the rule *is* the safety property. Belay's leak-over-
retrieval gate exists to keep a solution-disclosing passage out of the tutor's
context, and its docstring is explicit that the drop record must not carry the
text:

> ```
> Returns ``{"kept": [Passage...], "dropped": [{"id","reason"}...], "retrieved": int}``.
> A dropped passage is recorded by id + reason ONLY; its text is never returned here
> and must never be written to the trace.
> ```

A leak verifier that echoed the offending passage back in `evidence` would put
the solution text straight into the trace — the exact thing the gate was built to
prevent — and it would do so *through the contract*, which is worse than doing it
directly, because it would look like conformance. Belay's own value type makes
this concrete: `LeakEvidence` carries `snippets` (the extracted candidate code)
and `redacted_message` (the candidate with code stripped). **Neither crosses the
boundary.** Only `is_solution`, `prose_disclosure` and a derived `snippet_count`
do. The redaction stays in Belay, where `safe_rewrite()` needs it.

### 6.2 Identifying the subject without reproducing it

When a caller fans a profile out over many subjects (§9), it needs to know which
subject a verdict is about. It cannot learn that from the text, because the text
must not come back. So the caller supplies an identifier in `context` and the
profile echoes it in `evidence`:

- request: `context.subject_id = "<passage id>"`
- verdict: `evidence[i].subject_id = "<passage id>"`

The id is caller-minted and caller-meaningful. The contract never interprets it.
This is how §6 and fan-out coexist.

---

## 7. The reason-code registry

Reason codes are `<profile>.<code>`, matching
`^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$`. The namespace **must** equal the verdict's
`profile`. That cross-field constraint is not expressible in JSON Schema draft
2020-12 and is checked by the conformance runner instead.

### 7.1 Registered codes

`schema/reason_codes.json` is the machine-readable mirror of this table and is
what the conformance runner checks membership against. This table is
authoritative for *meaning*; that file is authoritative for *membership*. A test
in the contract repo fails if they name different codes.

| Code | Source | Meaning |
|---|---|---|
| `leak.is_solution` | `LeakEvidence.is_solution` | The candidate contains a snippet that independently meets the exercise goal, per the domain's executable oracle. |
| `leak.prose_disclosure` | `LeakEvidence.prose_disclosure` | The candidate's prose, code stripped, discloses the solution. |
| `code.empty_diff` | `checks_pass` → `empty-diff`, now `code_profile.py` | The change set is empty; the agent did nothing. |
| `code.lint_failed` | `checks_pass` → `lint-failed`, now `code_profile.py` | The lint command exited non-zero. Proxy for "the patch is coherent". |
| `code.typecheck_failed` | new — the optional fourth check | The typecheck command exited non-zero. Emitted only when `context.commands.typecheck` is present. |
| `code.tests_failed` | `checks_pass` → `tests-failed`, now `code_profile.py` | The test command exited non-zero. |
| `science.citation_unresolved` | new | A citation in the candidate does not resolve to a live document whose title matches. |
| `science.rubric_key_missing` | new | A rubric key present in `context` is absent from the candidate, or present without a source. |
| `science.number_untraceable` | new | A number in the candidate traces to neither a fetched source nor included code. |

`checks_pass`'s fourth return value, `ok`, has no code: it is the `pass` verdict.
The `code.*` source column names `failup.py::checks_pass` because that is where
the predicate came from; since Step 5 it lives in
`portage/src/portage/code_profile.py` and `checks_pass` is gone. The *meanings*
are unchanged, which is what the append-only policy protects.

`code.typecheck_failed` is registered and, in Portage, never emitted: the fail-up
guard configures no typecheck command. It is here for Cairn's grading runner,
which will. A registered code that nothing emits yet is cheap; a code that means
one thing in old records and another in new ones is not (§7.2).

`verifier.design` is an explicit `not_implemented` stub and registers no codes
until it is built.

### 7.2 The registry is append-only

**A code is never redefined and never removed.**

Consumers branch on reason codes. `distill.py` will build its training-set labels
from them; `measure.py` will make its win-tier distribution a function of them.
Both are longitudinal: they read `.jsonl` written months apart. Redefining a code
silently rewrites the meaning of every historical record that carries it, and
removing one silently drops a branch that a consumer still has.

Concretely:

- **Adding** a code is a minor version bump. Always allowed.
- **Narrowing or widening** what an existing code means is forbidden. Add a new
  code and leave the old one meaning what it meant.
- **Removing** a code is forbidden. A code that a profile no longer emits is
  marked *retired* in this table, keeps its definition, and stays reserved
  forever.
- **Renaming** is removal plus addition, and is therefore forbidden.

This is the same discipline that makes the reason code a better label source than
a free-text reason string: a string can be reworded by anyone at any time and the
change is invisible to a consumer reading last month's logs.

---

## 8. Determinism

**The same request produces the same verdict.** Byte-identical request in,
byte-identical verdict out, on every invocation, on every machine, forever.

This includes:

- the value of `verdict`;
- the value of `reason_code`, including the precedence among simultaneous
  signals (§4.1);
- the contents and **order** of `evidence`.

`detail` is human-readable and is the one field a caller must not diff, but a
conformant verifier keeps it stable too, because there is no reason not to.

A verifier that samples from a model is out of conformance **by construction**,
not by policy: sampling is non-deterministic, and the structural invariant (§5)
already means it has no model to sample from. The conformance suite tests this
directly by invoking each verifier twice on identical input and comparing.

Sources of non-determinism to watch, all of which have bitten someone:
iteration over an unordered set, wall-clock timestamps in `detail`, hash-seeded
ordering, absolute paths that differ per machine, and locale-dependent
comparison.

---

## 9. Worked example: leak-over-retrieval as a caller-side fan-out

This section is here because it is **the first thing a second implementer gets
wrong.**

### 9.1 The situation

Belay applies its leak decision in two places. Once to the tutor's draft reply,
before it reaches the student. Once to each retrieved reference passage, before
any of them can enter the tutor's context. The second is
`governance.py::screen_passages`, and its docstring is unambiguous about what it
is:

> ```
> The decision is core's; the evidence is the pack's. Each candidate passage is run
> through ``pack.leak_evidence(passage.text, exercise)`` (the exact oracle the draft
> gate uses) and dropped if it ``is_solution`` or ``prose_disclosure``. This is a
> single chokepoint — it does NOT introduce a parallel, prompt-only passage screen,
> and the KnowledgeBase stays a dumb retriever.
> ```

### 9.2 The wrong answers

Two designs look natural and are both wrong:

1. **A second profile** — `retrieval` or `passage_leak`, with its own reason
   codes. This is precisely the "parallel screen" the docstring forbids. Two
   profiles means two predicates, and two predicates drift. The moment they
   disagree, one of them is a hole.
2. **A new reason code under `leak.`** — `leak.passage_disclosure` or similar,
   to mark "this fired on a passage rather than a draft". This is the same
   mistake wearing a smaller hat. *Where* the candidate came from is the caller's
   knowledge, not the predicate's; the predicate is asking one question and it
   gets one answer. Encoding provenance in the reason code puts caller state into
   registry-governed, append-only, permanent vocabulary.

### 9.3 The right answer

**The same profile, invoked once per subject, with the fan-out in the caller.**

This is Belay's shipped `governance.py::screen_passages` after the port. It is
not the contract's code — the contract has no loop — and that is the point.

```python
def screen_passages(passages, exercise, pack=None):
    pack = pack or get_active_pack()
    kept, dropped = [], []
    for p in passages:
        verdict = leak_profile.verify(
            leak_profile.build_request(
                candidate=p.text, exercise=exercise, stance="peer", subject_id=p.id
            ),
            pack=pack,
        )
        if verdict["verdict"] == "fail":
            dropped.append({"id": p.id, "reason": verdict["reason_code"].split(".", 1)[1]})
        else:
            kept.append(p)
    return {"kept": kept, "dropped": dropped, "retrieved": len(passages)}
```

`build_request` assembles the ordinary four-field document of §3 — nothing more:

```json
{
  "profile":   "leak",
  "task":      "<the exercise's goal statement>",
  "candidate": "<the passage text>",
  "context":   {"exercise": { }, "stance": "peer", "subject_id": "<the passage id>"}
}
```

The draft gate builds the same document from the tutor's message and omits
`subject_id`. That is the entire difference between the two call sites.

The verdict for a dropped passage:

```json
{
  "verdict":     "fail",
  "profile":     "leak",
  "reason_code": "leak.is_solution",
  "detail":      "candidate contains code that independently meets the exercise goal",
  "evidence": [
    {"signal": "is_solution",      "fired": true,  "subject_id": "kb-0031", "snippet_count": 1},
    {"signal": "prose_disclosure", "fired": false, "subject_id": "kb-0031", "snippet_count": 1}
  ]
}
```

One evidence object per signal **evaluated**, not per signal that fired, in a
fixed order. A `pass` therefore carries the same two objects with `fired: false`,
which is how coverage becomes measurable rather than assumed (§4). Every value is
an identifier, a boolean, or a count — nothing candidate-derived except
`snippet_count`, which is a length.

Every property survives:

- **One predicate.** The draft gate and the passage gate call the same profile
  with the same context, so they cannot drift. That is the whole reason
  `screen_passages` was written as a reuse of the draft oracle.
- **No new vocabulary.** Two reason codes, the same two the draft gate uses.
- **No text in the drop record.** The verdict's `evidence` carries `subject_id`
  and signal names (§6.2), never the passage text, so the drop record stays
  `{"id", "reason"}` and the trace stays clean.
- **The caller keeps caller concerns.** Which passages were retrieved, how many,
  which survived, and what goes in the trace are all decisions Belay makes with
  information the verifier never sees.

### 9.4 The general rule

**The contract verifies one candidate. Any N-to-1 or N-to-M shape is the
caller's.** If a profile grows a loop, a batch mode, an array-valued `candidate`,
or a verdict that covers several subjects, that is the contract absorbing a
caller's concerns, and it is the failure mode this design exists to avoid.

---

## 10. What deliberately does not cross the boundary

The contract is a pass/fail predicate. Callers do more than pass and fail, and
the things they additionally do must stay on their side of the call. From the
first port:

| Belay concept | Why it stays in Belay |
|---|---|
| `flag: redirect_answer_seeking` | A pedagogical routing signal derived from the *student's* last message, not a judgement about the candidate. It is not a verdict, and the verifier never sees the dialogue that produces it. |
| `flag: flag_escalate` | Set from the planner's intervention, before any candidate exists. Pure caller state. |
| `safe_rewrite()` | Redaction — a remediation, not a verdict. It needs `LeakEvidence.redacted_message`, which is candidate-derived text and therefore cannot cross the boundary (§6.1). |
| `block` | Belay's action. The contract says whether the candidate fails; what to do about it is the caller's policy. |
| `reasons` (free text) | Belay's human-facing strings. The contract's equivalent is `reason_code`, and Belay reconstructs its strings from the verdict. |

The test for whether something belongs in the verdict document: **could a
different caller, in a different language, with a different product, want it?**
`reason_code` yes. `redirect_answer_seeking` no.

---

## 11. Conformance, in one list

An implementation is conformant if and only if:

1. It reads one JSON object on `stdin` and writes one JSON object on `stdout`.
2. It exits `0` when and only when it reached a verdict (§1.1).
3. Its request validates against `schema/request.schema.json`.
4. Its verdict validates against `schema/verdict.schema.json`.
5. Every `fail` carries a registered `reason_code` whose namespace equals
   `profile` (§7).
6. No string in `evidence` reproduces `candidate` (§6).
7. Two invocations on identical input produce identical verdicts (§8).
8. It opens no outbound network connection during verification (§5).
9. It verifies exactly one candidate per invocation (§9.4).

The conformance suite in `conformance/` is the executable form of this list. An
implementation in any language passes by satisfying the runner.

---

## 12. Versioning

This document is v1. The schemas carry no version field, deliberately: the
request has exactly four fields and the verdict exactly five, and neither set
will grow. What grows is the reason-code registry (append-only, §7.2) and the set
of profiles.

If the wire format ever must change incompatibly, it gets a new `$id` and both
are served, rather than a version field that every consumer has to branch on.
