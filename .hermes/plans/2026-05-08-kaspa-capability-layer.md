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
- Working branch: `spike/kaspa-node-rpc-readonly`
- Base: upstream `main` at `faa13e49f` originally; current branch has incremental read-only Kaspa commits on Luke's fork.

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

## Phase 1 progress log

Completed on branch `spike/kaspa-node-rpc-readonly`:

- Added the `kaspa` toolset with read-only REST/indexer/KNS helpers.
- Added `kaspa_node_rpc_tcp_health` for TCP reachability without RPC calls.
- Added `kaspa_node_info` as a read-only node metadata boundary that shells out to a local probe/facade command.
- Bundled optional Node probe at `scripts/kaspa-node-probe/node-info.mjs` using `kaspa-wasm` over wRPC WebSocket.
- Kept wallet/seed/signing/broadcast out of scope.
- Targeted verification: `python -m pytest tests/tools/test_kaspa_tools.py -q` currently passes.
- Probe verification: `node --check scripts/kaspa-node-probe/node-info.mjs` and `npm --prefix scripts/kaspa-node-probe audit --audit-level=high` pass.
- Full `python -m pytest tests/ -o 'addopts=' -q` did not complete within 600s and showed broad unrelated failures before timeout; do not treat that as a clean full-suite pass.

Observed local-node state:

- No local `kaspad` process was listening on `127.0.0.1:{16110,17110,18110}` when checked from the isolated workspace.
- The bundled `kaspa_node_info` probe expects wRPC WebSocket, defaulting to `17110`; a gRPC-only `16110` node needs an alternate facade command via `KASPA_NODE_INFO_PROBE_COMMAND` rather than adding gRPC dependencies directly to Hermes core.

## First implementation gate

Before any phase-2 wallet work, report:
- branch,
- files changed,
- tests run,
- exact remaining risk,
- whether the abstraction still feels upstream-quality.
