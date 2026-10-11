# Future confirmatory fact-dependent planning benchmark

Design-only follow-up, 2026-10-11. This is a **new future protocol**, separate from the frozen v0.11 three-fixture / six-allocation integration pilot. Nothing in the pilot is changed or pooled here. No benchmark was generated or executed, no provider calls/tests/installations were run, and no product code was edited for this memo.

## What should be measured

The future trial asks whether **visible cognitive planner context improves task-level business success relative to the identical planner-masked channel**. It does not ask whether masking execution facts helps, whether a new scheduler/attention policy helps, or whether any system has subjective experience. Keep cognition enabled and all selection/capacity/TTL settings identical; vary only `cognition.mask_consumer` between null and `planner`. Freeze attention off, monitoring identical, diagnostics absent, learning disabled, executable skills absent, and solver/certificate mechanisms outside this trial's success oracle. Statistical control is masked and treatment is visible, so a positive effect means visibility helps. Operational baseline naming must not reverse this estimand.

The key design feature is that the **planner's immutable choice of root contract is itself a business decision**. The executor receives the same authorized facts in both arms and can execute the chosen proposal well, but cannot repair a wrong root choice by writing a different proposal, creating every possible artifact, or saying it would have chosen differently. The task-level scorer reads the trusted bound root contract and independently judges its suitability for the frozen facts, then checks the actual output. This makes planner visibility causally capable of affecting success without changing executor permissions or hiding execution facts.

This is a finite planning benchmark with local proposal/handoff artifacts, not real spending, shipment, messages, external transactions, general agent utility, or population-wide correctness.

## Actual APIs and constraints

- `LLMPlanner.plan` returns known `source_id`/`contract_id`, objective and reason, with at most `max_candidates`; it cannot choose arbitrary new contracts or invent a DAG. It receives mission, source metadata, contract IDs and up to 2000 fact characters. Keep each complete source fact serialization below 1500 characters and confirm `facts_truncated=false` in both arms; truncation would add another mechanism.
- `Controller._synthesize` validates the candidate against the selected observation, then `Ledger.create_goal` freezes the candidate, contract and input binding. `max_candidates=1` makes the root decision unambiguous. Use one source per episode, so workspace capacity=1 does not accidentally test source selection or starvation.
- Source claims are marked processed after a successful plan, including `[]`; failed completed planning attempts consume the source attempt counter. With max_attempts=1, do not retry an invalid plan. Deferred/unavailable planning can otherwise retry: a benchmark episode needs a durable explicit one-planning-invocation budget and terminal disposition, rather than inference from a polling timeout.
- Configured contracts support `file_contains`, `json_equals`, the three current `json_reference` families and `argv`. Supervised workers prohibit host-code `argv` verification. Existing `json_reference` rules do not cover the new inputs. A public `json_equals` branch tag can provide a minimal product contract, while an independent host scorer verifies the full conditional business postcondition.
- `workflow.validate_workflows` supports up to eight fixed DAG steps, configured same-source contracts, and one manifest per `(source_id, parent_contract_id)`. Different static root contracts can select different frozen DAGs. `Controller.tick` hides child contract IDs from the planner, and workflows bind every child to the parent's original input. The planner chooses the root workflow; it does not design the DAG.
- Workflow parent goals do not create a normal Runs submission. Child steps have actual Runs and settlement evidence. Historical cognition is presently unavailable on workflow children; native qualification must audit the root planner frame plus the actual child lineage, not demand nonexistent child cognition frames or call this a loss of the root intervention.
- `cognition` currently records `planner_method` input exposure. That is not a durable receipt of the returned plan, `[]`, or invalid/unavailable outcome. A no-goal episode cannot be classified by looking only for a missing goal.

## Exact experimental unit and independent endpoint

One unit is a **frozen business episode**: one source JSON, its public task rules, all allowed root contracts, any static workflow manifests, one actual planner invocation, and at most one chosen root plus its bounded child executions. The matched pair executes this exact episode once under each arm, with fresh logically isolated state and the same physical/normalized authorization scope.

Let the host-only oracle calculate `allowed_root(facts, rules)` and the exact required business artifact(s). Success is the conjunction of:

1. A trusted completed planner response selected exactly one legal root whose `(source_id, contract_id)` equals the oracle's prescribed business action. Root identity comes from the immutable Ledger binding, not objective/reason text or the executor's answer.
2. The chosen root's complete business output satisfies the independent frozen oracle: exact schema/types, relevant selected records, arithmetic, bounds, ordering, and required provenance. A superficial product branch-tag contract alone does not suffice.
3. Every required native foreground execution was observed, its request/program/input/artifact binding verified, and its Runs settled by the common deadline. For a workflow, required child contracts were completed in dependency order, with the same immutable input lineage and required intermediate artifact hashes.
4. No second root decision, undeclared child, extra native submission, hedge artifact, fact mutation or control mutation occurred; bounded cleanup is confirmed under the separately frozen grace.

A correctly formatted but unsuitable branch is a **business failure** even if the product goal is marked succeeded. An observed completed `[]` is a known negative for these action-required tasks; it is not silently omitted or a success because the planner avoided work. All three families include an explicit local hold/defer artifact when that is the desirable decision, so success always requires an actual chosen contract and bounded native action. Invalid JSON or an illegal candidate is a known negative only with trusted completed-response and quiescence evidence. Provider receipt ambiguity, missing timing, unknown settlement/cleanup or unobserved response remains unknown.

The receipt reference ID can be `planning_episode_business_v1`, with checker version 1 and frozen independent checker hash, bound to each input. `causal_trial` does not constrain reference IDs to the product's three functions; it binds protocol reference identity. Keep `qualified_success_by_deadline_v1` analysis unchanged, but freeze these task-level business/native semantics and include every proof axis. Do not invent a native runner receipt for `[]`; use explicit completed-plan/no-launch evidence for its known negative native verdict.

Conditional adjudication is deliberately host-side for the first implementation. The oracle may inspect frozen input and bound choice, but **must not make per-case gold decisions available to admission or executor code**. It runs after the frozen decision and artifact snapshot and cannot repair them. An optional later conditional product verifier should expose a rule/reference ID, not instance-specific gold values, and must retain a separately implemented oracle.

## Three task families

### 1. Capacity-constrained queue handoff

Business situation: a team can prepare one queue handoff before a fixed cutoff. The source contains up to six tickets with queue ID, estimated minutes, integer benefit, blocked flag, and a public eligibility flag, plus the preparation-time budget. Three configured root contracts represent the three authorized queue handoffs.

Public rule: for each queue, include eligible unblocked tickets in the declared deterministic priority order, greedily accepting tickets that fit the queue's fixed preparation budget; compute their total benefit. Choose the queue with the greatest resulting benefit; ties follow the public queue ordering. At least one ticket is selected in every generated case. The artifact contains the chosen queue, selected ticket IDs in rule order, total minutes and total benefit, plus a minimal handoff summary.

Product root contract: `json_equals` on `queue` with the public possible queue value and the branch's fixed output path. All three possible values and paths are present for every episode. **Never set the contract to only the winning queue**. Independent business adjudication additionally checks that the bound root selected the maximizing queue and that the entire handoff artifact matches the oracle. An executor producing the maximizing artifact under the wrong immutable root still fails.

Held-out variation: different ticket sets, benefit/time ratios, blocked tickets, exact-fit budget boundaries, skipped oversize tickets, near ties and lexicographic ties; independent permutation of neutral IDs and record order. Development includes the same written rules but different seeds and ticket combinations. This family tests choosing useful authorized work, not synthesizing an otherwise predetermined single-source goal.

### 2. Supplier selection or deliberate hold proposal

Business situation: inventory needs one local purchase proposal, while an external order is never placed. Source facts contain stock, demand by a declared cutoff, two suppliers' unit prices, lead times, minimum order quantities and capacity, and a monetary ceiling.

Public rule: compute the integer shortfall. If none exists, choose the hold contract with quantity zero. Otherwise a supplier is eligible only when its minimum/capacity permits the required order, lead time meets the cutoff and total cost is within the ceiling. Choose the least-cost eligible supplier, using the stated supplier tie rule; if neither is eligible, choose hold with an explicit unmet-demand quantity and constraint reasons. All arithmetic uses bounded integers, not floating-point currency.

Three root contracts represent supplier A, supplier B and hold. Their public branch tags constrain only those possible actions. The independent oracle verifies the immutable chosen action, quantity, cost, unmet demand and reason codes against facts. Hold is an actual generated local report, not an unobserved absence of a goal.

Held-out variation: stock/demand boundaries, arrival exactly on or just after cutoff, price ties, minimum-quantity constraints, insufficient capacity, exact monetary ceiling, and cases where the cheapest supplier is infeasible. Use disjoint entity/number combinations in development and evaluation. The worker retains terminal-only, no-network local proposal permissions in every branch; choosing a supplier never authorizes payment or outbound communication.

### 3. Direct versus validation-first handoff workflow

Business situation: a frozen change packet can be handed off through one of two trusted two-step workflows. Facts contain counts/totals, a declared checksum or reconciliation value, record-level validity flags, and a public risk threshold. Public rules require validation-first if a reconciliation discrepancy, invalid record or threshold breach exists; otherwise direct is appropriate.

Two root contracts select two preconfigured DAGs, each with two steps and the same ceiling on execution:

- Direct: prepare the clean packet manifest, then package a local handoff containing its actual hash.
- Validation-first: prepare an exception/reconciliation report, then package a local handoff containing its actual hash and declared resolution status. The handoff explicitly marks unresolved exceptions and does not claim they were repaired.

Both DAGs use only configured same-source child contracts and local artifacts. Set the second step's `depends_on` to the first. No dynamic conditional DAG feature is needed: the fact-dependent choice is between the two roots. Use opaque nonretryable step semantics with max_attempts=1; no external effect is authorized. Root/child product contracts can validate their public route/stage tags; the independent scorer checks root appropriateness, complete content, actual intermediate hash, dependency ordering and exact original-input lineage. Creating a direct packet for an inconsistent case is a business failure even if both local steps pass their superficial tags.

Held-out variation: internally consistent versus inconsistent totals, one versus multiple invalid records, threshold equality/one-unit exceedance, distractor irrelevant fields, and record permutations. Public static workflow manifests are identical within a pair and include both routes in all cases; no winning route is omitted or singled out during deployment preparation.

## Gold isolation and held-out generation

Freeze a versioned generator, public rule specification, schema validator, independent oracle, task distribution/strata, dev/evaluation seeds, entity namespaces and output schema before evaluation. Proposed development pool: 120 episodes, 40 per family; proposed final evaluation pool: 2400 entirely new episodes, 800 per family. Development/feasibility runs are separately labelled and never pooled. Do not change a rule, prompt, generator, class prevalence, model setting or code after viewing evaluation outcomes.

The evaluation generator can stratify via host-only rejection sampling to balance target actions, boundary/interior cases and difficulty. This does not leak gold if source IDs, filenames, contract order, random action-token mappings, scheduling metadata, payload lengths and record counts are generated independently of the target label or explicitly counterbalanced. Freeze exact counts; for three-action families distribute 800 as 267/267/266 with a preregistered assignment, and for two-route workflows use 400/400. This defines an intentionally balanced benchmark population, not the prevalence of actual user tasks.

Store gold action, expected outputs and checker only outside all model-readable profile/work mounts. The public mission exposes the task rule and all possible action mappings, as needed to solve it, but no case-specific answer. The worker gets only the public case facts, rules and legal contracts. Do not hide answers in objectives, directions, acceptance values, seed-derived IDs, source metadata, API responses or candidate ordering. An independently reviewed oracle implementation should differ from the generator's construction logic; frozen expected artifacts provide another auditable reference, not a self-reported model score.

Use held-out combinations and boundary patterns, not just new identifiers on identical cases. The finite target remains these three rule families. Family-wise summaries and generalization claims are descriptive unless separately preregistered with multiplicity/power provisions. Related episodes must not be advertised as 2400 independent domains; statistical pair independence is an assumption about isolated executions and provider behavior, not proven by unique hashes.

## Matching, schedule and budgets

Freeze one planner invocation per episode, `max_candidates=1`, max_attempts=1, one shared 180-second monotonic endpoint from unpause, max_active=1, the same provider/model/profile role, max_turns=8, terminal timeout=30, the current protected runner and native approval floors, no worker network, non-root/read-only root, 1 CPU/512 MiB/128 PIDs and unchanged fact/control mounts. All branches stay inside the same authorized output workspace. Root branches in families 1/2 need one foreground Runs submission; family 3 needs two child Runs submissions, with `daily_runs=2` as its declared ceiling. A planning invocation, a Runs submission, an internal model turn and a provider HTTP request are different budget units; record them separately.

Give each matched arm the same task-specific ceilings and allowed operations. Actual usage may differ as an effect of the intervention; do not add dummy paid calls to equalize it. Include native guardian, internal retries and auxiliary usage where observable, and retain complete billing unknowns rather than assuming max_turns or plugin counters account for all costs. Preparation/oracle-generation costs are separately reported.

Use randomized pair order and balanced AB/BA within family/difficulty strata in a newly versioned frozen schedule, with paired cells close in time. If reusing the existing globally shuffled cell allocator, retain its exact order and report that it is not balanced. Fresh logical profiles/history prevent cross-arm carryover; physical slot reuse/archive/reset must preserve the actual authorization checks. Only predeclared provenance roles may be normalized, while actual identities/bindings remain verified. Unexplained provider identity drift or unconfirmed resource quiescence stops the protocol.

Before freeze, show that real planning, generation and settlement of two-step workflows can normally fit 180 seconds on disjoint development episodes. This is a feasibility check, not permission to exclude slow evaluation cases. If it cannot fit, redesign the future task before registration or introduce a separately versioned deadline protocol; do not stretch this analysis's validated 180-second limit after outcomes.

## Before-outcome sample size and power

Keep the current two-sided exact paired McNemar test AND Hoeffding lower-bound criterion, alpha=.05, fixed-N-only stopping, complete qualified pairs and no protocol stop. Define `D_i = success_visible - success_masked`, in {-1,0,1}, and target the mean paired improvement `delta=0.10`. The design alternative is an assumption, not a result.

The current interval radius is `r_N = sqrt(2*log(40)/N)`. N>=738 merely makes r_N below .10 and does not assure useful power. For independent bounded pair outcomes with average true delta at least .10, Hoeffding gives:

`P(Dbar <= r_N) <= exp(-N*(.10-r_N)^2/2)` when r_N<.10.

Thus a conservative sufficient conditional-power choice is:

`N > ((sqrt(2*log(40)) + sqrt(2*log(1/beta))) / .10)^2`.

Approximately 2035 pairs suffice for the bound to exceed 80% power; approximately 2365 for 90%. **Recommend N=2400 pairs**, 800 per family: radius≈.05545 and the bound gives power at least about 90.8%, conditional on all existing qualification assumptions. This uses no distributional variance estimate and remains within the existing 4096-pair cap.

The McNemar requirement does not invalidate this sufficient bound: if the observed net discordance is d=N*Dbar and total discordance m<=N, the exact two-sided binomial tail is bounded by `2*exp(-d^2/(2*m))`. Whenever Dbar>r_N, this bound is below .05. Retain the actual exact p calculation in the report.

For planning intuition only, an example alternative is masked success=.60, visible=.70, treatment-only=.20, control-only=.10, ties=.70, so discordance q=.30 and Var(D)=q-delta^2=.29. These are hypothetical preregistration inputs, not observed rates. The conservative N recommendation does not depend on them. A smaller variance-based design would require its own before-outcome justification and retained power calculation, not a post hoc analysis replacement.

Power is **conditional on the ledger's all-qualified gate**. With 4800 arm cells, even rare unknowns can prevent every inference: under a simplistic independent unqualification rate u, complete qualification is `(1-u)^4800`; at u=.001 it is only about .8%, and at u=.0001 about 62%. Keeping qualification probability at least .80 would require u roughly <=.0000465 per cell under that model. These are sensitivity calculations, not a claim that failures are independent or that such reliability is achieved.

Therefore obtain trustworthy negative receipts for genuine known failures rather than discarding them, and use disjoint feasibility runs to establish instrumentation/settlement reliability before a large registration. A genuine unknown remains unknown; any incomplete/unqualified pair or protocol stop keeps `causal_gain_supported=false` under current rules. Do not drop cells, refill the cohort, count repeated attempts as fresh cases, pool pilot runs or change the estimator to escape this gate. If the all-qualified design proves operationally impractical, report that limitation and design a separate future missing-data/estimand protocol before outcomes.

The conditional power statement assumes the required evidence is available for the original study; it is **not permission to analyze only the subset of qualified pairs**. Qualification, dropout and settlement can depend on the arm and outcome. Selecting a qualified subset does not preserve the original causal estimand or randomization assumptions.

One useful **separate future protocol alternative**, not a change to v0.11, is worst-case partial identification for missing binary business endpoints over the ORIGINAL fixed N. Give each arm endpoint an interval `[y_low,y_high]`: a known endpoint is `[y,y]`, an unresolved endpoint is `[0,1]`. For pair i, its possible difference is `[l_i,u_i]=[treatment_low-control_high, treatment_high-control_low]`. Report `[L,U]=[sum(l_i)/N,sum(u_i)/N]` without replacing N by the number observed. If preregistered with justified independent-pair concentration assumptions, a conservative uncertainty interval can expand it to `[max(-1,L-r_N),min(1,U+r_N)]`. Missingness may be outcome-dependent: the worst-case bounds do not assume missing-at-random. A positive lower bound would need to survive every allowed missing endpoint assignment. Freeze this estimand, construction and decision rule before any new trial outcomes; never retrofit it to obtain a positive result from the current trial.

Keep missing outcome measurement separate from **missing model/exposure/mechanism identification**. A business-output interval does not prove that the randomized arm reached the declared model, that exactly one factor differed, or that the tested execution identity/authorization was matched. Unknown exposure, model drift or arm contamination requires explicit identification exclusions/assumptions; it cannot be cured by endpoint imputation, interval arithmetic or a qualified-only filter. Retain both evidence axes and the original denominator. At most, a separately defined assignment-policy effect could be studied under its own assumptions; it is not automatically the effect of the declared delivered cognitive mechanism.

At N=2400, six-way/three-family summaries do not acquire confirmatory power automatically. The primary claim is the frozen pooled equally weighted family endpoint. Intermediate results can be monitored for operations, but never stop for significance or extend N until a positive interval appears.

## Smallest implementation gaps and a staged next step

1. Generalize native execution/qualification from one fixture/contract/goal to an episode containing multiple legal root contracts and, optionally, a configured fixed workflow. Preserve policy, scope and actual identity checks; independently validate selected root, complete output and every child Runs boundary.
2. Persist an immutable actual planner-response disposition, including candidate identity/count, input/request/frame hash, returned/invalid/unavailable status and observed times, plus an episode terminal/no-launch receipt. Existing input exposure alone cannot prove `[]` or a completed incorrect decision. Seal the first invocation budget durably and reconcile ambiguous launches without auto-retry.
3. Add a trusted **host-side** conditional business scorer and private gold manifest, bound into the receipt reference identity. Existing generic `json_equals` contracts suffice for first integration; no generic dynamic DAG engine, wider executor permissions, hidden label admission gate or external judge is needed. Clearly distinguish product tag acceptance from full independent business acceptance.
4. Generalize the protected foreground runner/auditor to per-step frozen output paths and strict JSON schemas without adding allowed arbitrary shell commands. Every existing native guard floor remains in force. Workflow evidence uses the root cognition frame plus child lineage; adding child cognition inheritance is unnecessary for this trial.
5. Freeze a manifest-based large task set and a new randomized balanced schedule before calls. Keep the frozen N=3 pilot intact, and keep attention/solver-certificate/monitoring changes outside this mechanism and endpoint.

Suggested order: independently review the public rules/generator/oracle and gold isolation; develop the episode evidence using provider-free verification; run a separately frozen small real feasibility set, such as 18 pairs / six per family, on development-only cases; finalize code/model/budgets and reliability evidence; then freeze the N=2400 confirmatory protocol. These are planned future operations, not activities executed here. The actual 24/72-hour durability cohort remains another separately preregistered experiment, with real elapsed follow-up and original cohort denominators.

## Methods grounding

Source access/hashes are retained in `sources/source-index.json` from the earlier read-only memo. CONSORT crossover guidance supports randomized AB/BA order, carryover prevention, paired analysis and sample-size planning; Howard et al.'s confidence-sequence paper explains why repeated fixed-N inspection is not an anytime-valid stopping rule; Hernán/Robins motivate explicit units, interventions, interference and sustained histories; *AI Agents That Matter* supports holdouts, cost control and reproducibility; AgentBench/SWE-bench support independent mechanical execution endpoints. These principles inform this design. None establishes that the planned Hermes study satisfies its assumptions or has achieved benefit.
