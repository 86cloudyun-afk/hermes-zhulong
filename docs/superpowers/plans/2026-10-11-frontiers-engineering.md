# Autonomy Frontiers Engineering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land all five research topics as bounded product mechanisms and verify useful work through actual Hermes.

**Architecture:** Independent SQLite-backed workflow, diagnosis, trial, monitoring and assurance modules integrate with the existing Controller. Frozen inputs, trusted reference checkers and native tool receipts separate business acceptance from model narrative.

**Tech Stack:** Python standard library, SQLite, fixed Hermes PM runtime, Docker, DeepSeek Flash.

**Spec:** `docs/superpowers/specs/2026-10-11-frontiers-engineering-design.md`

## Global Constraints

- Python 3.11/3.12/3.14; no product dependencies; 11 hooks/4 tools/1 command unchanged.
- Hermes revision `73162b00eefde3794bed0afb53d84a19c0eed230`; DeepSeek `deepseek-flash`.
- No credentials/raw reasoning in evidence; no model-controlled contracts/permissions/budgets.
- Unknown recovery precedes admissions; pause, atomic budget and fencing preserved.
- 16384-byte request; 4096-byte/depth-32 business snapshot; wrapper depth handled separately.

## Review Focus

- Duplicate JSON keys/nonfinite values/deep transport wrappers must never silently certify outputs (Task 1).
- Crash between child creation and binding, stale step lease, changed plan and opaque late effects (Task 2).
- Factor interactions, negative controls, missing provenance and unknown cleanup cannot become a cause (Task 3).
- Missing allocations/costs, cross-profile treatment drift and input leakage cannot become a gain claim (Task 4).
- Prediction leakage, old forecasts and pause/publication ordering cannot inflate monitoring/correctness claims (Tasks 1, 5, 6).

### Task 1: strict acceptance and trusted business references

**Files:** `autonomy_checks.py`, `work_reference.py`, `skill_store.py`, `skill_evaluator.py`; tests `test_work_reference.py`, `test_autonomy_checks.py`, `test_skill_store.py`.
**Interfaces:** Produces `reference_output(reference_id,data)` and `Verifier.capture(contract,task_input=None)`, `check(contract,baseline,task_input=None)`; root integrates calls.

- [x] Write duplicate/nonfinite/full-type/depth regressions, reference input/hash/missing/mutation and pause publication tests.
- [x] Run targeted unittest; record expected RED.
- [x] Implement check_version=2 strict JSON and three trusted reference functions; atomic positive publication pause guard; manifest business/envelope separation.
- [x] Run targeted GREEN and compatibility tests; commit only owned files.

### Task 2: durable workflows and local effect outbox

**Files:** `workflow.py`; `tests/test_workflow.py`; root integration `autonomy.py`, configuration/install lists.
**Interfaces:** `validate_workflows(raw,policy)`, `WorkflowStore(ledger,manifests)`, `sync(now)`, `advance(now,admissible)`, `is_parent(goal_id)`, `dispatchable(goal_id)`, `summary()`.

- [x] Test DAG rejection, atomic child binding, restart reuse, frozen input, paused creation, dependency failure, unknown effects and stable operation conflict.
- [x] Verify RED before implementation.
- [x] Implement immutable plans, one child per step and trusted local outbox; exclude parents from ordinary Runs and settle with final verifier.
- [x] Run GREEN plus Controller integration scenarios; commit.

### Task 3: bounded intervention diagnosis

**Files:** `diagnostics.py`; `tests/test_diagnostics.py`; root configuration and runtime wiring.
**Interfaces:** `validate_diagnostics(raw,policy)`, `DiagnosticStore(ledger,catalogue)`, `DiagnosticRunner(store,evaluator,clock)`, `tick(now,admissible)`, `summary()`.

- [x] Test frozen original failure/code/input/plan binding, all factorial cells, negative controls, two interacting causes, missing provenance, pause/budget and unknown cleanup.
- [x] Verify RED.
- [x] Implement isolated evaluator trials with immutable reservations and conservative graded receipts; one experiment per tick.
- [x] Verify GREEN, real Docker factor fixture, commit.

### Task 4: causal trial ledger and native useful-work acceptance

**Files:** `causal_trial.py`, `scripts/native_work_acceptance.py`, `tests/test_causal_trial.py`, `tests/test_native_work_acceptance.py`.
**Interfaces:** Frozen protocol/allocation ledger accepts typed business/native/cost receipts; scripts consume reference functions and existing deployment APIs.

- [x] Test complete allocation denominator, missing/duplicate/hash/scope failures, random order reproducibility, no small-n gain assertion, actual native tool/hash auditing and failure receipt persistence.
- [x] Verify RED.
- [x] Implement replayable protocol and finite actual gateway lifecycle for three variable business inputs; no expected-answer disclosure.
- [ ] Verify GREEN; root runs bounded real paid acceptance after a clean implementation commit and retains exact-version evidence.
- [x] Commit owned files.

### Task 5: attempt-time monitoring

**Files:** `metacognition.py`, `self_model.py`, `tests/test_metacognition.py`, `tests/test_self_model.py`; root integration in Ledger/Controller.
**Interfaces:** `initialize(c)`, `prepare(c,goal,identity,request,now,policy)`, immutable prediction binding and public scoped summary.

- [x] Test no post-outcome leakage, identity/contract/stratum boundaries, ties/reverse/constant AUROC, missing labels, immutable forecast and genuine recheck action receipts.
- [x] Verify RED.
- [x] Implement Laplace attempt estimator/provenance, bounded control decision and metrics; preserve legacy forecast origin.
- [x] Run GREEN and Controller tests; commit.

### Task 6: bounded assurance and operational issue closure

**Files:** `assurance.py`, `tests/test_assurance.py`; root transaction events, deployment docs and `docs/deployment/engineering-closure.md`.
**Interfaces:** `initialize(c)`, `record_event(c,event,payload,now)`, finite `bounded_check`/trace validation and explicit model scope.

- [x] Test stale generations, budget races, pause-publication order, unknown recovery and real SQLite event projection; mutation must yield a counterexample.
- [x] Verify RED; implement independent bounded model and production event journal.
- [x] Verify GREEN; resolve implementable historic issues and list infrastructure/time/service-dependent items with concrete requirements.
- [ ] Commit, run full actual host+Docker suite, installed plugin smoke and exact-code paid native work checks.

### Task 7: review and delivery

- [x] Fresh task review before dependent integration; resolve substantive findings.
- [ ] Fresh whole-branch review on most capable available model; one scoped fix/re-review pass.
- [ ] Update version/README/deployment/evidence with exact supported scope and unrun checks.
- [ ] Push, create and attach PR, confirm Python 3.11/3.12/3.14 CI, record independent review and merge authorized exact head.
- [ ] Refresh installed managed copies and save full tested startup/configuration draft at merged revision; saved draft is not publication.

Implementation note: root batches commits after shared integration; agents never commit concurrently. Actual native useful-work and independent whole-branch review remain separate delivery gates. Same-effective-identity live paired execution and infrastructure/time-dependent targets are listed explicitly in engineering-closure.md.
