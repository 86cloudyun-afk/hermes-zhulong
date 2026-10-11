# Production Refinement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Catch divergence between production SQLite truth and independently reconstructed operation semantics before new execution or positive publication.

**Architecture:** A separate typed journal and independent projector compare a single transaction snapshot. Admission and positive publication use the current audit; recovery remains available.

**Tech Stack:** Python 3.11+, SQLite, unittest, standard library.

**Spec:** `docs/superpowers/specs/2026-10-11-cognition-refinement-design.md`, sections Common constraints and B.

## Global Constraints

- Python 3.11+, standard library, no new runtime dependencies.
- No HTTP, LLM, Docker, or Verifier I/O inside SQLite write transactions.
- Audit must not call production decision functions or bless actual post-state as expected state.
- Unknown/unavailable/incomplete never authorizes a new execution or positive publication; cleanup/cancellation/recovery remains available.
- Default audit budgets are 100000 events and 33554432 bytes; exceeding either returns unavailable.
- Cloud checkout already supplies isolation; use current feature branch, no extra worktree.

## Review Focus

- Workflow direct SQL writes must not cause normal lifecycle false alarms.
- A restart must retain divergence rather than replace it with a fresh checkpoint.
- Audit rejects before allocation, with no budget or submission side effects.
- Two connections must observe consistent snapshots and atomically fence admission/publication.
- Legacy checkpoint pagination and scan limits must never silently truncate proof scope.

---

### Task 1: Actual state correspondence and transactional gates

**Files:** Create `refinement.py`, `tests/test_refinement.py`; modify `autonomy_store.py`, `workflow.py`, `skill_store.py`, `autonomy.py`, `scripts/install.sh`, `runtime_policy.py`. Existing covering tests may replace unsupported synthetic SQL fixtures with the corresponding supported Ledger lifecycle; they must preserve original behavioral assertions.

**Interfaces:** Produces `initialize(c)`, `record(c, action, payload, now)`, `audit(c, *, max_events=100000, max_bytes=33554432)` and a current Controller refinement status inside assurance. Typed operation names/payloads are local to the module and its explicit mutation hooks; document the mapping in module docstring. Later cognition work must not change covered ledger fields without an appropriate event.

- [ ] Step 1: Write failing tests for a real Ledger `create_goal → claim → prepare → record_admission → result → finish` sequence, asserting actual audit valid and state correspondence after each supported operation. Add fault injections with raw SQLite updates for budget/state/owner/submission/evidence; assert counterexample names changed field, and normal request admission rejects without a new submission or budget debit. Test restart retention including journal loss/clear must not rebootstrap, cancel/recovery after divergence, commit/rollback, two Ledger concurrency, workflow creation/cancel/block paths, positive publication and rollback gates, complete legacy pages, and unavailable schema/scan budgets.
- [ ] Step 2: Run `source /workspace/.cloud-onboarding/env.sh` then `zhulong-python -m unittest discover -s tests -p 'test_refinement.py' -v`; retain expected missing-feature failures.
- [ ] Step 3: Implement strict immutable paged checkpoint/typed operation semantics and independent actual projection. Instrument every covered production write in its transaction. Add pre/post admission audit and same-transaction positive skill activation gate; no blocking negative outcomes/recovery. Expose fresh current audit, keep bounded model evidence separate, and add module to installer.

  Fixed identities and independent guards follow the spec exactly. Add tests for matching journal+SQL invalid domain transitions, post-audit rollback and missing-journal cancellation. A blocked positive fallback must preserve negative retirement. Checkpoint seq/page/count integrity and independent persistent initialization marker are required.
- [ ] Step 4: Run refinement, workflow, skill store, assurance, autonomy and plugin tests; then the complete existing suite. Record exact command/result and skip reasons.
- [ ] Step 5: Self-review and commit only task-owned files; write report with coverage/exclusions and actual commands. Independent task review checks spec and quality before completion.
