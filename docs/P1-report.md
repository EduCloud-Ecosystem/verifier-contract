# CC-P1 build report — the verifier contract

Against `CC-P1-v2-verifier-contract.md` (Cowork, 2026-08-05). Written 2026-08-04
against the state of `~/dev/verifier-contract`, `~/dev/belay` and `~/dev/portage`
at the end of Step 7.

**Status of the eight gates.**

| Gate | Result |
|---|---|
| 0 — repo exists, visibility matches the licence decision | private; `LICENSING.md` states the conditional Apache-2.0 grant; recorded in `educloud/EDUCLOUD-STATUS.md` §5 |
| 1 — schemas validate against the draft 2020-12 metaschema | 4/4 (`request`, `verdict`, and the two profile context schemas) |
| 2 — every governance case passes through the boundary, zero verdict changes | Belay: **380 passed, 1 skipped**; ruff and mypy clean |
| 3 — profiles green, no network, no model calls | contract repo: **42 passed**; Portage: **73 passed** |
| 4 — runner passes all four profiles, rejects every adversarial case | **29/29** (18 golden cases across four profiles, 11 adversarial including the control) |
| 5 — escalation tests pass with the guard reading verdict documents | Portage: **73 passed**, ruff clean; Belay unchanged at 380/1 |
| 7 — HB-0 reconciliation | null result; see §7 |
| 8 — this document | — |

Commands, all offline:

```
cd ~/dev/verifier-contract && uv run pytest && uv run python schema/validate.py \
    && uv run python conformance/runner.py
cd ~/dev/portage         && uv run pytest && uv run ruff check .
cd ~/dev/belay/backend   && .venv/bin/python3.14 -m pytest      # stale-shebang venv
```

---

## 1. Every change the leak port forced on the contract

The port was done before any other profile precisely so the contract would be
shaped by a real predicate. Five changes came out of it, and three more came out
of Steps 3–5. Each is a case where the design sketch was wrong or silent.

### From Step 2 (the leak port)

**1.1 `reason_code` is singular, and singular is not obviously right.**
Belay's gate can have `is_solution` and `prose_disclosure` true on the same
draft. Widening `reason_code` to an array was considered and rejected: every
consumer would then have to decide what "the" reason is, and they would decide
differently. Resolution (§4.1): `reason_code` names the **primary** signal under
a precedence the profile documents and never varies, and `evidence` carries
**every** signal that fired. The leak precedence is `leak.is_solution` before
`leak.prose_disclosure`, which is the precedence `screen_passages` already had
inline as `"is_solution" if ev.is_solution else "prose_disclosure"` — so the
contract adopted an existing decision rather than inventing one.

Belay loses nothing: `governance.check` rebuilds its two human-readable
`reasons` strings from `evidence`, not from the code, so the both-signals case
still returns both strings in the original order.

**1.2 Evidence must not reproduce its subject (§6, and §6.1 for the why).**
`LeakEvidence` carries `snippets` (the extracted candidate code) and
`redacted_message` (the candidate with code stripped). **Neither crosses the
boundary.** Only `is_solution`, `prose_disclosure` and a derived `snippet_count`
do, and the redaction stays with `safe_rewrite()`, its only caller, because a
redaction is a remediation rather than a verdict. Without this rule the contract
would have been a legitimate-looking channel for putting solution text into the
trace — which is worse than doing it directly, because it would look like
conformance.

**1.3 `context.subject_id` (§6.2).** §6 creates a problem it has to solve: if
the text cannot come back, a caller fanning the profile out over many subjects
cannot tell which verdict is about which subject. So the caller mints an opaque
identifier, puts it in `context.subject_id`, and the profile echoes it in every
evidence object. The contract never interprets it. This is what lets
`screen_passages` keep returning `{"id", "reason"}` drop records.

**1.4 A `pass` carries one evidence object per signal *evaluated*, not per
signal that fired (§4).** A clean pass therefore documents its own coverage:
`[{is_solution, fired: false}, {prose_disclosure, fired: false}]` says *both
checks ran and both were clean*, which an empty array does not. The same
decision propagated to `code` (four checks, always four evidence objects, with
`not_configured` distinguished from `not_run` and from `passed`) and to
`science` (three signals, always three).

**1.5 The namespace rule is not expressible in JSON Schema draft 2020-12.**
`reason_code`'s namespace must equal `profile`, and there is no way in
draft 2020-12 to reference a sibling field's value inside a pattern. §7 delegates
it to the conformance runner. Step 4 discharges that: `reason_code_namespace` is
a runner check, and `reason_code_from_another_profile` is an adversarial case
that emits a real registered code (`code.tests_failed`) under `profile: "leak"`
and must be rejected for exactly that reason. Without that case the namespace
would be decoration.

### From Steps 3–5 (the other profiles and the callers)

**1.6 §1.2, an informative exit-code convention.** Every non-zero exit means the
same thing to a conformant caller — no verdict was reached — and the contract
still says so. But four profiles each inventing a scheme would be silly, so §1.2
records the one they share (`2` unreadable request, `3` the verifier failed, `4`
a declared stub) and states plainly that it is not normative and that
`conformance/` asserts nothing about the value.

**1.7 §3.1 gained real context schemas, and one deliberate exception.**
`schema/context/code.context.schema.json` and
`schema/context/science.context.schema.json` close those two shapes with
`additionalProperties: false`, and the runner validates a request's `context`
against one when it exists. `leak` deliberately has none: its `exercise` is an
entire domain record whose shape belongs to Belay, and closing it here would
make the contract the owner of a value type it does not define. `science` also
gained `context.sources` — the fixture records the injected `inline` resolver
reads — which is in `context` precisely because §3's four top-level fields never
grow.

**1.8 §7.1 gained `code.typecheck_failed` and a membership authority.** The
optional fourth check was taken, so the code is registered. It is registered and
never emitted in Portage today, because the fail-up guard configures no
typecheck command; it exists for Cairn's grading runner. Separately,
`schema/reason_codes.json` was added as the machine-readable mirror of the §7.1
table — the runner needs to check membership mechanically — and
`tests/test_registry.py` fails if the two ever name different codes. The `code.*`
"Source" column still names `failup.py::checks_pass` because that is where the
predicate came from; the predicate now lives in
`portage/src/portage/code_profile.py` and `checks_pass` is gone. The *meanings*
did not change, which is the thing the append-only policy protects.

---

## 2. Leak-over-retrieval shipped as a caller-side fan-out, and it survived

It shipped as the same profile, invoked once per passage, with the loop in
Belay. Not a second profile, not a second reason code — either would be the
"parallel screen" `screen_passages`'s own docstring forbids. `SPEC.md` §9 records
it as the worked example, with §9.2 naming both wrong answers, because it is the
first thing a second implementer will get wrong.

It survived contact with the tests, in four independent places:

1. `belay/backend/tests/test_verifier_contract_leak.py::test_screen_passages_is_one_profile_fanned_out_by_the_caller`
   — four passages in, the drop record is still `{"id", "reason"}` only, and no
   passage's text shares a 40-character run with the serialised drop record.
2. `::test_no_second_profile_and_no_passage_reason_code` — the passage screen
   emits the same `profile` and the same two codes the draft gate emits, and
   nothing else. This is the test that would fail the moment someone adds
   `leak.passage_disclosure`.
3. `::test_subject_id_identifies_without_reproducing` — the id round-trips into
   every evidence object; a draft-gate request omits it and gets `null`.
4. `conformance/golden/leak/30-passage-fan-out-subject-id.json` — the fan-out
   shape is pinned as a golden case, so a second implementation of the `leak`
   profile has to reproduce it byte for byte at the wire level.

The whole of Belay's suite is unchanged at **380 passed, 1 skipped**, and the
Step 2 pre/post capture of 270 cases was byte-identical. Zero verdict changes.

One thing did *not* survive, and it is worth naming: the golden corpus contains
no `leak.is_solution` case. Producing one means carrying a working solution to a
shipped Belay exercise — an answer key — in a repository whose entire purpose is
to be published. Belay's own suite covers that path (including the
both-signals-at-once precedence case), and the golden corpus covers
`leak.prose_disclosure` plus three passes. Publishing the answer key to
demonstrate that a verifier withholds answer keys is the joke §6 exists to
prevent. `conformance/golden/leak/10-prose-disclosure-fail.json` records the
reasoning in its `why` field.

---

## 3. The network-isolation mechanism on macOS

Linux network namespaces are unavailable on macOS and there is no `LD_PRELOAD`
equivalent that survives System Integrity Protection. The runner therefore uses
**two layers**, and prints which ones are live on every run:

```
network isolation: python socket guard ON; sandbox-exec verified by probe: connect(2) denied with EPERM
```

**Layer 1 — a Python socket guard** (`conformance/guard/sitecustomize.py`). The
runner puts that directory on the child's `PYTHONPATH`; CPython's `site` module
imports `sitecustomize` before any verifier code runs, so no argument and no
environment variable is read *by the verifier* and the invocation convention in
§1 is untouched. It wraps `socket.socket.connect`, `.connect_ex`,
`socket.create_connection` and `socket.getaddrinfo`. An AF_INET/AF_INET6 attempt
is **appended to a log file and then raises `PermissionError`**. AF_UNIX is left
alone: a unix socket is not an outbound connection.

Logging *before* raising is the load-bearing detail, and the adversarial case is
built to prove it matters. `phones_home` opens a connection, **catches its own
`PermissionError`, and emits a perfectly clean `pass`** — nothing in the verdict,
the exit code or stdout gives it away. It is rejected because the attempt was
recorded, not because the verifier admitted to it.
`tests/test_conformance.py::test_the_network_case_is_caught_by_the_guard_not_by_the_verdict`
asserts the failure list is *exactly* `["network_isolation"]`, so if the guard
ever stops working and some other check happens to catch the case, that test
fails rather than passing for the wrong reason.

- **Covers:** any Python child and any subprocess it spawns (they inherit
  `PYTHONPATH`), with per-attempt attribution — the runner can name the address.
- **Does not cover:** verifiers in Go, Rust or C; a Python verifier calling
  `connect(2)` through `ctypes` or a C extension; an interpreter started with
  `-S` or `-E`.

**Layer 2 — `sandbox-exec` (macOS Seatbelt), kernel-level and
language-independent.** Every invocation is wrapped in
`sandbox-exec -p '(version 1)(allow default)(deny network-outbound)(deny network-bind)'`.

It is **probed, not assumed.** At start-up the runner runs a child that attempts
a TCP connect under that profile and checks it fails with `EPERM`; the result is
printed every run. On this machine (Darwin 25.5.0) the probe observes the denial
and the layer is live. If it ever does not, the runner prints
`! kernel-level isolation UNAVAILABLE — coverage is Python children only` and
continues with layer 1 rather than silently claiming isolation it does not have.

- **Covers:** arbitrary executables in any language — which is what makes the
  suite meaningful for the Go implementation in §5.
- **Does not cover:** attribution. A denied connect reaches the child as an
  ordinary `EPERM`, so against a non-Python verifier the honest claim is "it
  could not reach the network", not "we detected that it tried".
- **Caveats:** `sandbox-exec` is deprecated by Apple (present and functional on
  Darwin 25); it is macOS-only, and on Linux this layer is simply absent — the
  equivalent would be a network namespace, which the runner does not implement.

**What neither layer covers**, stated so nobody has to discover it: a verifier
reading a cached response written to disk by an earlier networked process. That
is not a connection during verification. §8's determinism requirement is what
makes it visible, because a cache that changes makes two invocations disagree.

`conformance/README.md` carries the same account for anyone running the suite
without reading this report.

---

## 4. How the evidence non-reproduction rule was tested

The rule (§6) is that evidence *identifies and characterises* and does not
reproduce. The operationalisation is mechanical: **a verdict is rejected if any
string reachable in `evidence` shares a contiguous run of 40 or more characters
with the request's `candidate`, compared case-insensitively with runs of
whitespace normalised to a single space.** Forty is a threshold, not the rule.

It is tested at four levels, deliberately, because a rule enforced in one place
is a rule that a second implementation violates without noticing.

1. **A runner check on every golden case of every profile.**
   `runner.reproduces_candidate()` runs against all 18 golden cases — including
   the passes, because a `pass` carries evidence too.
2. **An adversarial verifier that does exactly the forbidden thing.**
   `echoes_candidate` emits an otherwise-flawless `fail` whose evidence carries
   `{"offending_text": <the candidate>}`. `evidence_reproduces_the_candidate` in
   `adversarial/cases.json` requires the runner to reject it *on that check*.
3. **Unit tests of the comparison itself**
   (`test_the_evidence_reproduction_check_compares_against_the_actual_candidate`):
   a verbatim copy is caught; a paraphrase that keeps a long run is caught; and
   `{"signal": "prose_disclosure", "subject_id": "kb-0031", "snippet_count": 1}`
   is *not* — which is the shape every shipped profile actually emits.
4. **Per-profile tests in all three repositories**, each aimed at that profile's
   specific temptation:
   - Belay: `test_evidence_carries_no_leak_evidence_text_surfaces` asserts the
     pack really did produce `snippets` and `redacted_message` and that neither
     appears in the verdict, only `snippet_count`.
   - Portage: `test_evidence_carries_no_command_output` — lint and test output
     quotes source lines, and source lines are candidate content, so the `code`
     profile carries a check name, a status and an exit code and nothing else.
   - Contract: `test_untraceable_numbers_are_reported_by_position_never_by_value`
     — the `science` profile reports untraceable numbers by **line and ordinal**,
     never by value. A numeric literal lifted out of a manuscript is candidate
     text; §6's permitted list is identifiers, characterisations and profile
     vocabulary, and a number is none of them. Citation *keys* and rubric *keys*
     do appear, because §6 names both as permitted identifiers. This costs some
     debuggability and is the right trade: the rule is not "stay under forty
     characters".

The fifth level is the golden corpus's own composition — see the answer-key
decision in §2.

---

## 5. What a Go implementation would need (Cairn)

**`CC-C4-cairn-rename.md` has not run.** Cairn's `go.mod` still reads
`module github.com/quad/quad`. Everything below uses the post-rename path
`github.com/EduCloud-Ecosystem/cairn`, which is the path as it will be, not as it
is today. Cairn's grading runner was left alone, per Step 5.

Cairn is the first cross-language consumer and the real test of whether the wire
format was the right call. It would implement `verifier.code` — its grading
runner already does what that profile decides — as
`github.com/EduCloud-Ecosystem/cairn/cmd/verify`, reading a request on stdin and
writing a verdict on stdout.

**What is easy.** `encoding/json`, `os/exec` with an argv vector (never a shell
string), and `os.Exit`. There is no framework to adopt: the contract is two
schemas and an exit code.

**The four traps, all of which the conformance suite catches:**

1. **A nil slice marshals as `null`, not `[]`.** `evidence` is
   `type: array`, so a Go verifier that returns a nil `[]Evidence` emits
   `"evidence": null` and fails `verdict_schema`. The
   `leak/20-oracle-stance-pass` golden case has `"evidence": []` exactly, so a
   Go `leak` implementation would hit this on its first run. Initialise the
   slice.
2. **A `pass` must OMIT `reason_code`, not send an empty one.** The schema
   pattern rejects `""`. `ReasonCode string \`json:"reason_code,omitempty"\`` is
   correct; a struct without `omitempty` fails on every pass.
3. **`null` is not the same as absent for `subject_id`.** The `leak` evidence
   objects carry `"subject_id": null` when the caller minted none, and the golden
   verdicts pin that. That needs `*string` with no `omitempty` — a plain `string`
   with `omitempty` drops the key and fails `golden_match`.
4. **Field order is not part of the contract, and must not be relied on.** The
   runner compares *decoded* documents, not bytes. This matters in both
   directions: Go marshals struct fields in declaration order and would produce a
   stable but different byte string, and Go renders `1.0` as `1` while Python
   renders `1.0`. Both decode to the same value and both pass. A future runner
   that compared bytes would break every non-Python implementation, so it must
   not.

**What it should not do:** re-declare the reason codes as Go constants. Embed
`schema/reason_codes.json` with `go:embed` and look up membership, so an
append-only addition to the registry propagates without a Cairn release.

**How it proves conformance:** `go build -o /tmp/cairn-verify ./cmd/verify` then
`uv run python conformance/runner.py --profile code --exec /tmp/cairn-verify`.
Under `sandbox-exec` the binary is covered by the kernel-level network layer;
the Python guard does not bind it, so a network violation would surface as a
`verifier_error` without attribution (§3).

---

## 6. The three downstream consumers (notes only — nothing was built)

### 6.1 `distill.py`

**A correction to the prompt's premise first.** The prompt says distill's labels
"currently come from failup's ad-hoc reason strings". They do not.
`grep -n "category\|reason" src/portage/{measure,distill}.py` returns **nothing**:
`distill.tasks()` reads only `run_id`, `task`, `tier`, `model` and `ok` from
`failup-log.jsonl`. The routing label is `win_model`; `reason` and `category` are
written by the guard and read by nobody. So the change is not "swap the label
source" — it is "start reading a field that already exists, in its new
registry-governed form".

Concretely:

- **The guard must log `reason_code` alongside `reason`.** It does not today, on
  purpose: adding a field was Step 6 work and Step 6 says do not build. The
  guard currently translates the verdict back to the legacy strings
  (`_LEGACY_REASON` in `failup.py`) so that months of existing records keep their
  meaning. The additive field is the first line of the next prompt.
- **`build_routing`** — the label (`win_model`) does not change. What changes is
  the *filter*: it should skip runs whose only sub-ceiling failures were
  `category == "availability"`, because "tier 0 was rate-limited, tier 1 passed"
  is currently recorded as "this task needs tier 1". That is a capability claim
  from an attempt that was never really tried — the exact poisoning
  `runner_availability_failure()` exists to prevent, caught at the guard and then
  discarded one layer down. This is the highest-value change in Step 6 and it is
  a data-quality bug that exists today.
- **`build_triage`** — unaffected by the contract. Its split comes from
  `triage-log.jsonl`'s `clarify` flag, not from verdicts. Worth noting only so
  nobody rewrites it for symmetry.
- **`build_adapt`** — its `verified` boolean in `adapt-log.jsonl` is a verdict in
  disguise. It should become the verdict document's `verdict` field, and the
  preference pairs should be reportable per `reason_code`: "template A fails
  `code.lint_failed` twice as often as template B" is an actionable finding that
  a boolean cannot express.
- **Why `reason_code` and not `reason`:** distill reads `.jsonl` written months
  apart. A free-text reason can be reworded by anyone at any time and the change
  is invisible to a consumer reading last month's logs. The registry is
  append-only (§7.2) precisely so that cannot happen.

### 6.2 Parity Bench / `measure.py`

`measure.py` today derives everything from one boolean: `summarize()` and
`tasks_in()` read `a["ok"]`, and the win-tier distribution is
`min(tier for attempts where ok)`. That boolean used to be a process exit code.

The interface it would need:

- **Read the verdict document, not `ok`.** `win_tier` becomes the cheapest tier
  whose verdict was `pass`. Mechanically similar; the gain is what comes with it.
- **Exclude verifier errors from the denominator, structurally.** `ok == False`
  today covers three different things: the candidate failed, the runner was
  unavailable, and (once verifiers are separate processes) the verifier itself
  broke. The first is a capability datum; the other two are not. `measure.py`
  needs three states where it has two, and the contract already distinguishes
  them: `pass`, `fail` + `reason_code`, and non-zero exit. Today it reads
  `category == "availability"` for none of this.
- **Score without an LLM judge — which is the whole point.** The scoring function
  *is* the verdict document. A Parity Bench task ships with a profile name and a
  context, the harness builds a request, and the win tier is the cheapest tier
  whose verdict passed. No judge, no rubric prompt, no sampling.
- **Report the distribution over `reason_code`, not just over tiers.** "40% of
  floor failures are `code.empty_diff`" (the model produced nothing) and "40% are
  `code.tests_failed`" (the model produced something wrong) are completely
  different findings about a tier, and the current win-tier histogram cannot tell
  them apart.
- **The preregistration will need `evidence` to be stable**, since a
  preregistered analysis that reads `evidence[i]` is committing to the profile's
  evidence shape. §8 makes evidence order part of determinism, which is the
  guarantee that makes such a preregistration possible; nothing yet makes the
  *shape* append-only the way reason codes are. See §8.5 below.

### 6.3 The science lane and Perplexity

Perplexity (`sonar-deep-research`, the `proprietary_research` alias in the HB-0
registry) is currently trusted for exactly one thing that `verifier.science`
would replace: **citation resolvability** — the claim that a cited work exists
and says what the manuscript says it says. The subscription decision has a dated
cutover in **lineP S3**; treat that as the named milestone, not as a date this
report invents.

What has to be true before the cancellation is defensible:

1. **A live resolver, not a fixture.** `profiles/science_live.py` exists and is
   registered only by an explicit `install()` call — no test can reach it, which
   is currently a feature and would then be the blocker. It needs a cache, a
   retry policy, rate-limit courtesy, and a **recorded, replayable snapshot**,
   because §8 says the same request produces the same verdict and a network
   round-trip does not. The snapshot, not the network, is what a conformant
   verifier reads.
2. **Coverage measured, not assumed.** `citation_resolvability` and
   `hallucinated_citation_rate` already ship as evidence fields for exactly this
   reason. Both are `null` when nothing is cited — a rate over an empty
   denominator is undefined, and reporting 1.0 there would let an uncited
   manuscript read as perfectly sourced. The number that justifies the
   cancellation is agreement with Perplexity on a shared corpus, per identifier
   type: DOIs are nearly free, arXiv ids are easy, and books, preprints, grey
   literature and URLs are where a resolver-based approach loses. The honest
   version of the decision is "retire Perplexity for the identifier classes where
   agreement is measured and high, keep it for the rest", not "retire
   Perplexity".
3. **The title-match predicate has to survive real bibliographies.** The profile
   today compares normalised titles for exact equality after stripping
   punctuation. That will produce false `science.citation_unresolved` on
   subtitles, translations and preprint-to-published title drift. A verdict that
   is wrong in the direction of "your citation is fake" is expensive.
4. **Citation syntax has to stop being ours.** The profile parses `[@key]` plus
   a reference block, a convention invented here. A manuscript in BibTeX, CSL-JSON
   or plain numeric style produces different verdicts. See §8.3.

Until 1–4, `verifier.science` is a real profile with a real predicate and a
fixture resolver — enough to build the instrumentation against, not enough to
cancel a subscription on.

---

## 7. HB-0 reconciliation — a null result

**The reconciliation found no coupling in either direction.** Nothing in
`SPEC.md`, `schema/`, `conformance/` or any of the four profiles reads or writes
any field of `portage-local/registry.yaml`: a grep across `SPEC.md`, `schema/`,
`conformance/` and `profiles/` for `registry.yaml`, `bfclv3`, `ifeval`,
`license_family`, `open_weight` and `license` returns nothing (this report is the
only file in the repository that mentions any of them), and the same grep across
the three profile
implementations returns only Belay's `from ..core.registry import get_active_pack`
— which is Belay's *domain-pack* registry, an unrelated object that happens to
share a word. Both specifically-flagged facts are confirmed clean.
`bfclv3` and `ifeval` are `null` throughout with `TODO(native)` and are read by
exactly one function, `render_config.py`'s model-info builder, which copies them
into LiteLLM's `model_info` block; no verifier, profile, caller or conformance
case touches them. `license` is read by the same builder and nowhere else;
`license_family` does not exist anywhere in `schema/registry.schema.json` or in
either code base — it appears only in the CW-04/CW-05 planning documents that
propose adding it (C6) — so nothing can depend on it, and `open_weight_only`
occurs only in prose in `REVISION-PLAN.md` and `KICKOFF-PROMPT.md`, never in
code. Two small corrections to the prompt's own framing, offered because a
reconciliation that quietly rounds off is not worth recording: `license:
UNVERIFIED` appears on **five registry rows covering four models**, not three —
`z-ai/glm-5.2`, `deepseek/deepseek-v4-flash` (twice, under `code_large` and
`research_synthesis`) and `moonshotai/kimi-k2.6` on OpenRouter, plus
`gemma4:e4b` on `ollama_chat`, which is not an OpenRouter entry and is not
covered by the "three OpenRouter entries" description in the registry's own
header comment. The null result is **structural rather than incidental**, which
is the part worth keeping: the request document has exactly four fields and
`additionalProperties: false`, so there is no field in which a model alias, an
endpoint, a licence class or a benchmark score could travel even if some future
profile wanted one (§5). The only place the two systems touch at all is the
fail-up guard's tiers file, whose model strings must resolve to registry
aliases — and that is upstream of `runner_availability_failure()`, which is
itself upstream of the verifier call, so a model name is already two layers away
from anything the contract sees.

---

## 8. What I do not think will survive a second implementation

Written as an honest list of the loosest joints, worst first.

**8.1 `context` is unconstrained at the contract level, and that is the loosest
joint in the design.** The top-level schema requires only `type: object`. Two
implementations of the same profile can disagree completely about the context
shape and both pass the runner, as long as each is fed its own golden cases. Two
of the four profiles now ship a context schema; `leak` deliberately ships none.
The mitigation that would work — requiring every profile to register a context
schema in this repository — was not taken, because it would make the contract the
owner of Belay's exercise record. I think this is the right call and I also think
it is where a second implementation will diverge first.

**8.2 The 40-character threshold is a heuristic with errors in both directions.**
A legitimate identifier can exceed it (a deep path in a monorepo, a DOI carrying
a title fragment) and a 39-character solution snippet slides under it. §6 says
the threshold is not the rule, but the threshold is what runs. A second
implementer will hit a false positive on a long file path and will be tempted to
special-case identifiers out of the check — at which point the rule is whatever
their allowlist says.

**8.3 The `science` profile's citation syntax is a convention invented here.**
`[@key]` inline plus `[@key]: Title` reference lines is Pandoc-flavoured and
nothing else. A second implementation reading BibTeX, CSL-JSON or numeric
citations produces different verdicts on the same manuscript, and both pass the
suite. The right fix is for the caller to pass a parsed citation list in
`context` and for the profile to stop parsing the candidate at all — that is
where §9.4's "any N-to-1 shape is the caller's" logic actually points. I did not
do it, because it would have meant designing the caller that does not exist yet.

**8.4 Number traceability is the weakest predicate shipped.** It is string
equality against a source's `numbers` list: `0.42`, `0.420` and `42%` are three
different strings, there are no units, no tolerance and no rounding. It will not
survive a real manuscript. It is in because §7.1 registers the code and a
registered code with no predicate is worse than a crude one — but a second
implementation will implement it differently, and both will pass, because the
golden cases only pin the crude behaviour.

**8.5 Evidence shapes are not versioned the way reason codes are.** §7.2 makes
reason codes append-only and says exactly why: consumers branch on them and read
logs written months apart. Evidence is *ordered* (§8) but its field set is
governed by nothing. When Parity Bench preregisters an analysis that reads
`evidence[0]["citation_resolvability"]`, that field becomes as load-bearing as a
reason code, with none of the protection. Either evidence fields join the
registry or a preregistration cannot safely depend on them.

**8.6 Determinism and flaky test suites are in direct tension for `code`.** The
profile is exactly as deterministic as the commands it runs. Running `pytest`
twice against a flaky suite produces two different verdicts, which the contract
calls a conformance failure and the caller calls a Tuesday. The conformance
runner never sees this because its golden cases run `python3 -c 'sys.exit(0)'`.
Nothing in §8 tells an implementer what to do about it, and the two plausible
answers — "run once and cache" and "the verifier is non-conformant" — are very
far apart.

**8.7 `working_dir` resolves relative to the verifier's own working directory.**
That is what keeps golden cases machine-independent, and it means the same
request can produce different verdicts depending on where the caller launched
the process. Deliberate, documented in the context schema, and still a trap.

**8.8 The `code` profile trusts the caller's change set.** `candidate` is the
change set as text and the profile never verifies that it corresponds to
`working_dir`. That is correct layering — the contract must not know that this
caller happens to use git — but a second implementation will be tempted to run
`git status` itself, and then two callers of the "same" profile will disagree
about what an empty diff is.

**8.9 The precedence among simultaneous signals lives in prose.** §4.1 requires a
profile to document its precedence and never vary it, but the precedence is not
machine-readable anywhere. It is pinned only where a golden case happens to
exercise a conjunction — which today is `science` (one case) and, in Belay's own
suite rather than the golden corpus, `leak`. A second implementation could invert
`code`'s lint-before-tests ordering and pass everything, because no golden case
fails both.

---

*Stop here. The Parity Bench preregistration is the next prompt and it depends on
this contract being settled.*
