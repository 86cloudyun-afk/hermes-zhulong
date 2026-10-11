# Core evidence kernel implementation plan

Specification: `docs/superpowers/specs/2026-10-11-core-evidence-kernel-design.md`.
Baseline: `705a3f7aabfd89f42ea362da4ee03f5c3d856ecc`.

Use testing and sequential subagent implementation with a fresh implementer per task, independent specification/quality review after each task, and one final complete review. Runtime is stdlib-only. Use `source /workspace/.cloud-onboarding/env.sh` then `zhulong-python -m unittest discover -s tests -v`. Native Docker opt-in is reserved for final integration. Store private raw research, execution and review logs outside the repository; export redacted hashes and counts.

## Preflight

| Pair | Shared interface | Resolution |
| --- | --- | --- |
| A/B | cognition packet, immutable request, Ledger admission | A preserves old frame schema/defaults; B adds a separately typed contract bundle |
| B/C | `execute_allocation`, protected runner, fixture policy | B adds explicit bundle option; C adds explicit arm policy and one endpoint; preserve defaults |
| A/B/C | runtime/install module lists | Each sequential task appends its owned module names; no concurrent implementation |
| B/C | trusted artifact evidence | Native certificate receipt is a separate axis; paired attention study keeps certificate mode off |
| All/evidence | source/control hashes | Freeze after final reviewed product; evidence-only edits do not change product hashes |

- [x] Task A: add prospective attention ledger/control in `attention.py` and `cognition.py`; strict config/storage migration, complete denominators and actual Controller tests. Retain independently frozen disturbances and paired control study. Update runtime/install lists. Commit and independent task review.
- [x] Task B: add `certified_ticket.py` and `certified_bindings.py`; strict total AST and exact interval cover checker; exact execution bridge, optional ticket contract bundle, Controller request and atomic admission. Protected native bundle runner and independent artifact/hash receipt. Meaningful tamper/domain/list/transaction tests. Commit and independent task review.
- [ ] Task C: add real paired adapter/CLI and durable `cohort.py` with bounded zero-provider watch; explicit native helper policy, single endpoint, derived independent proof axes, normalization checks, launch intent/reconciliation/stop rules. Tests for forgery/confounding/ambiguity/deadline/clock/denominators. Commit and independent task review.
- [ ] Freeze and run supplemental certificate all-domain check and actual Controller attention study; record support/null/unknown per prediction.
- [ ] Final product review, close important findings with scoped fixes, update version/docs and run pinned Hermes + real Docker suite.
- [ ] Freeze three native pairs/six cells and one separate certified ticket allocation; execute at most once each with preferred DeepSeek alias, retaining all original failures/unknown/unrun and cleanup. Open observation-only actual-time cohort with explicit pending status.
- [ ] Export portable research/access/evidence; push PR; publish independent review; verify exact-head CI; merge; verify main and refresh tested cloud setup/draft.

Longer paid confirmatory samples and actual 24/72-hour operational usefulness studies require distinct preregistrations with adequate power and elapsed time. Their absence cannot be replaced by unit tests or by user budget authorization.
