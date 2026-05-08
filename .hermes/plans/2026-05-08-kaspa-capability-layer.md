# Kaspa/Kasia Capability Layer Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Build Hermes as a safe Kaspa/Kasia operator, not a Telegram replacement.

**Architecture:** Start with read-only Kaspa/Kasia intelligence as a Hermes toolset. Treat the old `kasia-gateway` and `kasia-jobs-skill` branches as reference/prototype material only. Add wallet/signing/gateway work later behind explicit safety gates.

**Tech Stack:** Hermes Agent Python codebase, pytest, Kaspa/Kasia HTTP/wRPC/indexer clients where available, isolated `HERMES_HOME` for all local tests.

---

## Product framing

Build capability in this order:
1. Read-only Kaspa/Kasia intelligence.
2. Dedicated low-value Hermes Kaspa identity.
3. Explicitly allowlisted Kasia send/broadcast actions.
4. Optional Kasia gateway as proof-of-capability, not primary UX.

## Hard safety rules

- Use `/home/luke/repos/hermes-kaspa-capability`, not `/tmp` and not `/home/luke/.hermes/hermes-agent`.
- Use feature branches on `elldeeone/hermes-agent` from current upstream `main`.
- Do not modify `/home/luke/.hermes/config.yaml` or `/home/luke/.hermes/.env`.
- Do not restart or install the live Hermes gateway.
- Use disposable `HERMES_HOME` for tests.
- No seed phrase handling in phase 1.
- No signing, transactions, wallet mutation, or live gateway dogfooding without Luke approval.

## Current workspace

- Local checkout: `/home/luke/repos/hermes-kaspa-capability`
- Origin: `https://github.com/elldeeone/hermes-agent.git`
- Upstream: `https://github.com/NousResearch/hermes-agent.git`
- Working branch: `spike/kaspa-capability-layer-20260508`
- Base: upstream `main` at `faa13e49f`

## Phase 1: Read-only spike

### Task 1: Repo archaeology

**Objective:** Identify reusable code/docs from old branches without porting blindly.

**Files:**
- Read only: old branch refs `origin/kasia-gateway`, `origin/kasia-jobs-skill`
- Create: `.hermes/notes/kasia-branch-archaeology.md`

**Steps:**
1. Diff old branches against upstream main.
2. List files added/changed.
3. Identify concepts worth keeping: config names, bridge protocol, docs, tests.
4. Identify stale code to avoid.
5. Save notes.

**Verify:** Notes clearly separate reusable concepts from rejected implementation.

### Task 2: Locate Hermes toolset patterns

**Objective:** Find the smallest upstream-native way to add a read-only Kaspa toolset.

**Files:**
- Read: `tools/`, `tools/registry.py`, `toolsets.py`, relevant tests.
- Create: `.hermes/notes/toolset-patterns.md`

**Steps:**
1. Inspect existing simple network toolsets.
2. Confirm registration and `check_fn` conventions.
3. Confirm test style for tools.
4. Save recommended file paths and test commands.

**Verify:** Notes name exact files to create/modify.

### Task 3: Define minimal read-only API

**Objective:** Specify phase-1 tools before coding.

**Candidate tools:**
- `kaspa_network_status`
- `kaspa_address_balance`
- `kaspa_transaction_lookup`
- `kasia_indexer_status`

**Steps:**
1. Keep inputs explicit and read-only.
2. Return JSON strings from handlers.
3. Require env/config only for optional endpoints.
4. Avoid wallet/seed/signing fields entirely.

**Verify:** API spec has no mutation path.

### Task 4: Implement first read-only tool + tests

**Objective:** Add the smallest useful tool, likely indexer/node status.

**Files:**
- Create: `tools/kaspa.py` or equivalent after Task 2.
- Modify: `toolsets.py` only if required by current registry pattern.
- Test: matching `tests/tools/...` file.

**Steps:**
1. Write failing tests with mocked HTTP.
2. Implement minimal handler.
3. Run focused tests.
4. Commit.

**Verify:** Focused tests pass with disposable `HERMES_HOME`.

## First implementation gate

Before any phase-2 wallet work, report:
- branch,
- files changed,
- tests run,
- exact remaining risk,
- whether the abstraction still feels upstream-quality.
