# SPDX-License-Identifier: Apache-2.0
"""Reference profile implementations for profiles that have no host repository.

The CONTRACT is `SPEC.md`, `schema/` and `conformance/`. It decides nothing and
imports nothing from here. A profile belongs in the repository of the caller
that owns its predicate:

  leak     Belay      backend/app/agent/leak_profile.py
  code     Portage    src/portage/code_profile.py
  science  (here)     no host yet — see profiles/science.py
  design   (here)     an explicit not_implemented stub

`science_live` is NOT imported here. Importing this package must not be able to
pull a network client into the process; see profiles/science_live.py.
"""
