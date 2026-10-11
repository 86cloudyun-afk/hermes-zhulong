# Prospective paired native bootstrap and probe amendment

Status: design for independent review before implementation. This amendment addresses two independently reproduced integration mismatches: actual gateway startup seeds bundled skills into a mount required to be empty, and actual prompt construction creates a fixed backend probe whose task identity differs from the native session. Direct terminal fixtures omitted both entry paths. Existing paired batches remain unknown=1/unrun=5 each, stopped and separate; no receipt, denominator or outcome is repaired or pooled. Separate certified results remain separate.

## Paired-only bootstrap control

A newly frozen paired deployment declares a supported `HERMES_BUNDLED_SKILLS` override to an explicitly absent source path under its protected host deployment root. The pinned host resolves that override directly; `sync_skills` returns before writing skill state when that source does not exist. An existing empty source or `.no-bundled-skills` marker is insufficient: those paths can still write a manifest or seed essential skills.

The paired launcher forcibly replaces any inherited override. The exact absent-source role/path and bootstrap policy are declared and hashed before any paid execution, together with the protected launcher, host revision, observer and scope. Validate the deployment root and source parent as canonical protected host paths, reject symlink/alias traversal and any existing source entry (including broken symlinks), and keep the source outside every worker mount. Validate this control before startup, at each creation and at endpoint qualification. The actual profile skills path must be absent or an empty real directory at startup and must remain an empty real directory whenever mounted or qualified; any unexpected file, symlink, alias or populated tree fails closed. Existing actual worker mount/security/resource inspection remains unchanged.

This option is installed only in paired deployments through explicit protected metadata. Ordinary and certified deployments keep their current configuration, environment and default helper behavior. No host checkout patch, provider/model change or broad nonempty-skills allowance is permitted.

## Separate fixed prompt probe purpose

The pinned prompt builder creates a container with exact task label `prompt-backend-probe` for its fixed backend observation. New paired protocols explicitly declare that auxiliary purpose separately from the exact registered native session purpose.

Both purposes require the same protected current service boot and live owner, original frozen submission/Run/request fingerprint/session association, actual real-daemon container ID and inspection, full existing boundary, immutable image and protected launch controls. Record and fsync purpose-bound intent and actual capture before returning the created ID. A requested label selects a restrictive declared category; it never supplies actual identity or a qualification verdict. The inspected label must match that declared purpose, while inspected runtime/boot/owner context and the actual frozen Run association must independently agree. Foreign, ambiguous, replaced, stale or undeclared identities reject.

An auxiliary probe can never satisfy foreground execution or session-worker qualification, including when a forged receipt names its hostname. Only an actual session-purpose capture can join the protected foreground runner receipt and native session. Every auxiliary and session intent must have exactly its corresponding valid capture; duplicate, missing, rejected, malformed or late evidence leaves qualification unknown. Retain all intents and any safe bounded rejection diagnostics. Never erase a failed probe, convert it to a successful session record, silently exempt its boundary, or refill an old batch. All observed runtime containers remain in independently verified cleanup ownership.

## Time and frozen scope

All creation, inspection, durable records and endpoint qualification share the existing persisted actual UTC/monotonic/boot 180-second endpoint. There is no new start time for a probe, retry, second worker or resume. The independent 120-second cleanup grace and settlement/cleanup scope remain unchanged; later cleanup cannot upgrade endpoint evidence.

A new driver/protocol freezes the paired-only bootstrap declaration and typed auxiliary/session purposes, code/host/CLI/launcher hashes and the complete six-cell schedule before any new paid outcome. Both paired arms use identical bootstrap/probe controls; their existing sole mechanism difference remains unchanged. Original and subsequent stopped batches stay distinct and immutable. This amendment authorizes no paid work by the implementer.

## Required zero-provider validation

TDD covers both independently reproduced failures and their controls. An isolated fixture must exercise actual pinned gateway startup skill synchronization, the exact pinned prompt-builder backend probe, then two actual session workers and the actual protected foreground runner through the real cached Docker backend and protected observer. Observe and persist all three actual container boundaries, verify that only the matching session worker supplies the foreground join, and verify owned cleanup independently. This fixture uses explicitly synthetic Ledger/Run/session setup and makes zero provider calls; it is not evidence of paid API admission.

Negative cases include inherited source override, existing/created source path, symlink or parent alias, skills population at each validation phase, probe-only or probe-hostname foreground evidence, foreign session/boot/owner, unmatched auxiliary/session intent, duplicate/replaced capture, actual boundary drift, late observation and unchanged deadline on additional workers. Failed setup and original RED logs remain retained. Independent implementation review and root-owned actual validation precede any distinct paid preregistration.

Planned ownership is limited to `native_worker_capture.py`, `native_trial.py`, `runtime_policy.py`, `tests/test_native_worker_capture.py`, `tests/test_native_paired_trial.py`, and this amendment. Any necessary shared-interface expansion must be explained before editing it. Certified algorithms/helpers, ordinary deployment behavior, cohort, formal proof, CI and original evidence are outside this change.
