# Evidence learning implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Implement inline with one fresh whole-branch reviewer; user has authorized execution and integration.

**Goal:** Turn trusted failures into scoped strategies that influence future execution and automatically activate or retire from independent results.

**Architecture:** Two focused modules share the durable Ledger connection. Native Hermes remains the executor; learned content is bounded data, frozen in submission requests.

**Tech Stack:** Python standard library, SQLite, unittest, pinned Hermes PluginLlm.

**Spec:** `docs/superpowers/specs/2026-10-10-evidence-learning-design.md`

## Global Constraints

- Python 3.11/3.12/3.14; no new SDK/package dependencies.
- Host `73162b00eefde3794bed0afb53d84a19c0eed230`, original eleven hooks/four tools/one command.
- Max guidance 600 characters; two strategies/request; two generated attempts/failure; 120s learning leases, 45s model timeout.
- Shared auxiliary budget, existing frozen requests, verification and unknown-execution occupancy remain authoritative.
- Cloud checkout is already isolated; use feature branch, no extra worktree.

## Review Focus

- Different connections and expired owners must not duplicate learning or accept late responses.
- Unknown, prior artifacts and original-goal retries must not inflate activation evidence.
- Candidate retirement during an in-flight run must preserve original idempotent request replay.
- Learning unavailability and exhausted budgets must preserve recovery and allow later learning.
- Different contracts, sources and execution identity must exclude unrelated guidance.

### Task 1: Durable strategies and trusted evaluation

**Files:** create `experience_store.py`, `tests/test_experience_store.py`.
**Interfaces:** `ExperienceStore(ledger)`; `sync(now)`, `claim(now)`, `begin(job, now)`, `complete(job, guidance, now)`, `defer(job, now, reason)`, `reject(job, now)`, `retrieve(goal, identity)`, `evaluate(now)`, `summary()`.

- [x] Write tests for verified-failure-only learning, scoped immutable guidance, lease takeover, duplicate completion, two independent first-pass successes, original retry exclusion, false result retirement and unknown exclusion.
- [x] Run `zhulong-python -m unittest discover -s tests -p test_experience_store.py -v`; expect failures because module is absent.
- [x] Implement transactional jobs/strategies/evaluations with IDs tied to evidence, frozen guidance and machine-constructed scope. Inspect frozen submission input for use provenance.
- [x] Run the same command; expect all pass. Commit `feat: add evidence-grounded strategy ledger`.

### Task 2: Autonomous generation and actual execution reuse

**Files:** create `experience.py`, `tests/test_experience.py`; modify `autonomy.py`, `self_model.py`, `__init__.py`, `commands.py`, `tests/test_autonomy.py`.
**Interfaces:** `ExperienceLearner(store, llm, budget).tick(now, admissible)`; Controller optional `experience` parameter; SelfModel optional `experience` parameter.

- [x] Write budget/stop/schema tests and Controller behavior tests: failure→lesson→future request; baseline without experience; safe retry after failure uses lesson; lost reply freezes guidance; scope changes omit it; public read-only state and model export.
- [x] Run targeted unittest discovery; expect assertion failures for missing learning/reuse.
- [x] Wire one generation/tick after recovery, before synthesis, with lifecycle checks and fail-open recovery. Include scoped contexts/commitments in planning; freeze retrieved hypotheses in requests, expose `autonomy experience` read-only.
- [x] Run learning and autonomy tests; expect all pass. Commit `feat: learn and reuse scoped strategies autonomously`.

### Task 3: Native integration, documentation and review

**Files:** modify `plugin.yaml`, `scripts/install.sh`, `runtime_policy.py`, README/SPEC; add research/validation docs and finite native learning smoke.

- [x] Verify runtime deployment copies/protects both modules using native smoke and existing policy tests. Update version to 0.6.0 and installer file list.
- [x] Run full `HERMES_AGENT_ROOT=/workspace/.cloud-onboarding/dependencies/hermes-agent zhulong-python -m unittest discover -s tests -v`; expect zero failures/skips in native environment.
- [x] Execute bounded DeepSeek PluginLlm learning smoke, record exact code revision, one charged auxiliary generation and trusted evidence attribution.
- [x] Dispatch fresh whole-branch review; fix Critical/Important with RED→GREEN in one pass, record all rulings/minors.
- [x] Create PR, verify Python matrix CI and review; merge per existing user instruction, refresh cloud setup with exact merged HEAD and report remaining roadmap. No new permission gate.
