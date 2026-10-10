# Supervised runtime implementation plan

> Executor: use superpowers:executing-plans and TDD. Existing cloud checkout is
> isolated; implementation uses a feature branch without another worktree.

**Goal:** Deploy the native autonomy controller with measured lifecycle and
Docker enforcement, preserving v0.4 recovery and evidence invariants.

**Spec:** `docs/superpowers/specs/2026-10-10-supervised-runtime-design.md`

**Architecture:** stdlib foreground supervisor → pinned native Hermes gateway
→ current Zhulong Controller → public Runs API → terminal/process Docker worker.
Protected local files carry boot-tagged control/health. Retained SQLite remains
the authority for goals, evidence and occupancy; service state never rewrites it.

**Global constraints:** no edits to pinned Hermes; official PM dependencies only;
no credentials in git/logs; no new cognitive loop; data-only host verification;
all cleanup scoped to own labels; finite fault evidence, no availability claim.

## Task 1: durable crash and truth accounting

Files: `autonomy_store.py`, `tests/test_autonomy_store.py`.
Produces: crash-only source lease recovery and immutable verified outcome.
Consumes: v0.4 ledger contracts.

1. Write tests for repeated expired source leases, completed failure cap,
   legacy in-progress migration and successful/unsettled tracking errors.
2. Run focused tests. Expected: new crash and truth assertions fail.
3. Count completed source plans and preserve final evidence outcome in finish.
4. Run entire suite. Expected: existing and new tests pass.
5. Commit `fix: preserve source recovery and verified truth across crashes`.

## Task 2: progress and stop protocol

Files: `autonomy.py`, `runtime_channel.py`, `__init__.py`, plugin tests.
Produces: boot-tagged health, service admission gate, nonblocking stop request.
Consumes: Task 1 ledger; existing plugin cleanup and native on_unload.

1. Tests: starting/stopping never plan/dispatch, recovery remains available,
   stale control denied, progress/error codes visible, join reports liveness.
2. Run focused tests. Expected: absent gate/channel/progress failures.
3. Implement atomic private channel; gate planner and final dispatch; publish
   progress at bounded phases; monitor shared scheduler stop event and close
   resources only when both owned loops exit.
4. Full suite. Expected: green; legacy unsupervised plugin unchanged.
5. Commit `feat: add boot-scoped lifecycle and autonomy progress health`.

## Task 3: deployment policy and native worker verification

Files: `runtime_policy.py`, `scripts/runtime_probe.py`, policy/probe tests,
`scripts/install.sh`.
Produces: protected profile generator/validator, forced child environment,
native final schema and Docker enforcement probe, scoped worker cleanup.
Consumes: Task 2 channel settings, validated core policy and host Docker backend.

1. Tests: overlapping controls/work rejected, argv verifier denied,
   unpinned images rejected, inherited local backend cannot override Docker,
   unknown mounts/tool schemas/network/user/resources fail closed.
2. Focused tests. Expected: policy/probe missing assertions fail.
3. Generate dedicated profile and nonsecret manifest, preserve secrets outside
   reports; validate pinned code/config, constrain child env; check actual native
   tool definitions and native Docker snapshot plus denied-action probes.
4. Full suite and real Docker probe. Expected: all policy checks pass, own
   worker removed, work artifact persists, control and source writes fail.
5. Commit `feat: enforce a pinned Docker runtime for autonomous execution`.

## Task 4: supervisor and process fault campaign

Files: `runtime_supervisor.py`, `scripts/runtime.py`, fresh-process tests.
Produces: `init/check/run/status/stop`, exclusive inherited lock, persisted
launch limit, authenticated readiness, bounded stop/restart and status.
Consumes: Tasks 2–3 boot channel, protected manifest, worker probe and cleanup.

1. Tests with actual stdlib fixture children: cold readiness; stale/wrong boot;
   child crash/restart; persisted exhaustion; duplicate/orphan flock; stopping
   acknowledgement before drain; bounded escalation; lost-admission recovery.
2. Run focused tests. Expected: supervisor missing/failing behavior.
3. Implement foreground supervisor with one owned child process group;
   lifecycle reasons and state have no provider/chat/credential payloads.
4. Full suite plus real native gateway start/stop. Expected: ready is parsed
   from authenticated body/capabilities/plugin progress; clean bounded exit.
5. Commit `feat: supervise the native gateway with bounded durable recovery`.

## Task 5: deployment evidence, independent review and integration

Files: docs, README, plugin version, evidence and example Linux service.
Produces: reproducible commands, finite campaign report and reviewed PR.
Consumes: all preceding tasks.

1. Run full native suite, native offline smoke, real Docker boundary checks,
   gateway lifecycle and finite fresh-process campaign; capture safe counters.
   Expected: green with explicit native/Docker prerequisites and scope.
2. If available, run one bounded DeepSeek Flash autonomous terminal task and
   independent data acceptance; capture successful usage separately from fees.
3. Write deployment docs/systemd example and evidence; commit.
4. Fresh whole-branch reviewer on most capable model. Regrade by effect; fix
   Critical/Important in one root TDD pass; ledger deferred Minors/rulings.
5. Full verification, PR, CI, authorized merge; preserve helpers and update
   cloud configuration draft to exact merged commit. Expected: GitHub merge
   and CI verified; cloud draft saved, publication status stated accurately.

## Review Focus

Check worker code escaping through host-side verifiers or automatic mounts;
additive toolsets and environment/config fallback; supervisor death with orphan
child and lock lifetime; stop/dispatch races; stale boot health; identity and
idempotency continuity; finite launch-budget persistence; quiescence claims;
late verified outcome vs tracking errors; filesystem TOCTOU and path overlaps;
cleanup of other profiles; measured evidence vs untested long-term claims.
