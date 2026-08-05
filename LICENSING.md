# Licensing

Status: prepared, not yet in force. This repository is published, and its
license takes effect, only once the University of Arizona IP release for the
personal-time work has cleared. Until then this file is a plan, not a grant.
See `portage/LICENSING.md` and `belay/LICENSING.md` for the same status on
the sibling repos.

## Why this repo is Apache-2.0 only

Unlike Portage and Belay, this repository has no engine to keep copyleft.
Its entire purpose is to be a portable contract — a request/verdict schema
and a conformance suite — that a third party can implement against in any
language without taking on copyleft. A permissive-only grant is not a
simplification of the dual-license pattern; it is the pattern applied to a
repo that is 100% contract and 0% implementation. Implementations of the
contract (Belay's leak profile, Portage's `code` profile, a future Go
implementation in Cairn) live in their own repos under those repos' own
licenses, exactly as `portage/LICENSING.md` and `belay/LICENSING.md`
describe for their own Apache-2.0 boundaries.

## Placement (at publish time)

- Apache-2.0 full text at the repository root as `LICENSE`. Drop in the
  verbatim text from apache.org; do not modify it.
- Per-file SPDX headers (`SPDX-License-Identifier: Apache-2.0`) once the
  grant is in force.
- The repository visibility flips from private to public in the same step
  the license text is dropped in. Not before.

## Contributions: DCO, not a CLA

Contributions are accepted under the Developer Certificate of Origin, with a
`Signed-off-by` line on each commit, matching the pattern in `portage` and
`belay`. There is no copyright assignment and no contributor license
agreement.

## Until the release clears

This repository stays **private**. Nothing in it should be treated as
licensed for use outside this org, and no code here should be copied into a
public repo under the assumption that the grant is already in force.
