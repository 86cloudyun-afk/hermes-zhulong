# Cognitive Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Put a bounded, persistent and experimentally controllable workspace in the actual Hermes planning and execution path without claiming subjective experience.

**Architecture:** Immutable metadata frames select actual Planner observations; goal bindings deliver the same historical frame to execution and monitor packets. Consumer masks and constant selection provide controlled negative conditions; all original contracts/inputs/permissions stay binding.

**Tech Stack:** Python 3.11+, SQLite, unittest, standard library.

**Spec:** `docs/superpowers/specs/2026-10-11-cognition-refinement-design.md`, sections Common constraints and A.

## Global Constraints

- Python 3.11+, standard library, no new runtime dependencies.
- No HTTP, LLM, Docker, or Verifier I/O inside SQLite write transactions.
- `enabled=false`, `capacity=3` in 1..8, `ttl_seconds=120` in 1..3600, `mask_consumer=null|planner|executor|monitor`, `selection_mode=adaptive|constant`.
- No raw observation facts in the new journal; use source/revision/input/facts hashes, explicitly permitted existing task_input stays unchanged.
- Mask only the workspace mechanism; never alter task inputs, acceptance, permissions, budgets, stop/recovery or existing monitoring authorization.
- Subjective experience remains unidentified; receipts establish context delivery, not hidden model use or a complete GWT/AST implementation.
- Cloud checkout already supplies isolation; use current feature branch, no extra worktree.

## Review Focus

- Facts must not bypass selection through the self-model/experience payload.
- Stale frames must not authorize new goals while historical recovery still works.
- Multi-controller selection and consumer receipt binding must persist atomically across restart.
- Masking a single consumer must preserve other packets and original task inputs.
- Disabled cognition must preserve current product behavior and prevent secret/raw-fact persistence.

---

### Task 1: Real capacity selection and bound consumer delivery

**Files:** Create `cognition.py`, `tests/test_cognition.py`; modify `autonomy.py`, `autonomy_store.py`, `autonomy_checks.py`, `metacognition.py`, `__init__.py`, `commands.py`, `scripts/install.sh`, `runtime_policy.py`.

**Interfaces:** Consume the existing Ledger and refinement hooks unchanged; produce `validate_cognition(raw)`, `initialize(c)`, `Workspace(ledger, policy, identity)` with `select(observations, now)`, `planner_view(frame, observations, now)`, `bind_goal(goal_id, frame, now, *, connection=None)`, `execution_packet(goal_id)`, `monitor_packet(goal_id)`, `summary()`. Extend `Ledger.create_goal` with an optional cognition frame; bind and recheck TTL/source/revision/input hash in the same transaction as goal creation. Packets use JSON dictionaries with schema/frame identity/source metadata/visibility and delivery-only limitations. Exact internal table fields can follow repository conventions while meeting the spec.

- [ ] Step 1: Write failing actual Controller/LLMPlanner tests asserting at most K observations enter Planner, omitted source facts cannot enter context, adaptive rotates across persistent interference and constant misses the tail, planner-mask removes facts and restoration recovers a controlled fact-dependent decision, executor/monitor mask affects only its packet, and same frame binding appears in execution/attempt monitor. Test a source beyond max_candidates receives a turn, unavailable source claims cause no falsely recorded exposure, TTL expiration before atomic goal creation rolls back the goal, restart immutability/privacy, duplicate binding conflicts, concurrent selection, strict config rejection and disabled baseline.
- [ ] Step 2: Run `source /workspace/.cloud-onboarding/env.sh` then `zhulong-python -m unittest discover -s tests -p 'test_cognition.py' -v`; retain expected missing-feature failures.
- [ ] Step 3: Implement bounded frame selection with persisted selection history and preselection forecast, strict configuration and consumer receipts. Integrate real planning input/context filtering and bind accepted goals before any execution. Deliver frozen packets in request and monitor provenance. Expose read-only `zhulong_autonomy action=cognition`; add module to installer, avoid side-channel raw facts.

  Frame policy/mask freezes historical packets; dedupe preserves original goal binding; legacy/manual goals expose unavailable, workflow children explicitly historical/inherited or unavailable. Omit non-source-scoped domains/contexts as well as commitments/hypotheses/experience. Recompute observations before planner_view. Receipts distinguish constructed/delivered/prepared/actual-call boundaries and prepared requests bind submission ID/hash. Test these boundaries.

  The `/zhulong autonomy cognition` command must expose the same read-only summary. Planner masking must remove source facts in all delivered fields, including any task_input data; preserve input/contract only on original validation/execution paths. Controlled comparisons use separate frozen frames with matching source/revision/input, compare semantic contents after excluding intervention provenance, and retain masks on historical frames.
- [ ] Step 4: Run cognition/autonomy/metacognition/plugin/refinement tests and full suite. Provider-free controlled consumer experiments are functional evidence; do not describe them as a live model causal gain or consciousness measurement.
- [ ] Step 5: Self-review and commit only task-owned files; report exact commands and limitations. Independent task review checks spec and quality before completion.
