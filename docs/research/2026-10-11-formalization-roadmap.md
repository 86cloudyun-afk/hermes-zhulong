# Machine-formalization roadmap for the actual interval-certificate kernel

2026-10-11 UTC. Scope: the planned `certified_ticket.py` APIs `verify_ticket_certificate` and `execute_ticket_program`, the JSON AST grammar in the independently retained design memo and [accepted specification](../superpowers/specs/2026-10-11-core-evidence-kernel-design.md), and the scratch checker's `affine`, `condition`, `text`, and `check`. This original research checkpoint preceded production implementation. The [actual implementation mapping](2026-10-11-formalization-actual-mapping.md) now records the independently reviewed `d2ce6b0` kernel and supersedes hypothetical function/grammar/wrapper choices below; the Lean obligations below describe that historical roadmap checkpoint. The later [formal milestone evidence](evidence/2026-10-11-core-kernel/formal-model-proof.json) records actual compilation and independent replay for a general typed checker model; byte/Python/list/runtime correspondence obligations remain open. This follow-up changes no product code and runs no installation, provider, proof tool, or test.

**The deployed v0.11 Python checker remains a custom checked-certificate implementation with a reviewed soundness argument. A general typed-core model theorem is now kernel-checked; Python/runtime correspondence is still unproved.** The next worthwhile formal artifact proves soundness of the certificate-checking algorithm for this exact language, then its fixed list wrapper. A theorem about the ticket-score formula alone would not prove that the actual certificate checker admits only correct programs.

## 1. Freeze the semantic object before proving it

Pin a grammar/semantics/specification version and retain the final production module's source hash. Freeze opcode arities, integer semantics, `if` laziness, eager `min`, score-reference context, exact priority strings, reference thresholds, interval inclusivity, domain constants, and wrapper sorting. Formalization must follow those choices rather than silently proving a more convenient algorithm.

Use Lean 4 as the first target. Rocq is an equivalent alternative (`Z`, inductive syntax, `Fixpoint`, Boolean checkers, reflection lemmas); selecting both initially creates unnecessary duplication. The definitions and theorem names below are design contracts, not already compiled Lean declarations.

Suggested formal source layout:

- `Syntax.lean`: typed syntax, raw-JSON decoding rules, node/depth/resource predicates.
- `Semantics.lean`: total interpreter, numeric domain, independent business specification.
- `Affine.lean`: affine operations and interval extrema lemmas.
- `Certificate.lean`: the exact symbolic checker, cell checker, grouping/ordering, and coverage algorithm.
- `Soundness.lean`: mutual symbolic soundness and complete row-certificate theorem.
- `Wrapper.lean`: map, actual fixed sorting algorithm, sorted-permutation correctness and uniqueness.
- `Fixtures.lean`: the actual reference/nonidentical programs and serialized certificate fixtures with kernel-checked acceptance examples.
- `Bridge.md`: explicitly unresolved correspondence obligations and the runtime claim they prevent.

Avoid claiming that a theorem about these definitions directly verifies the Python source. A correspondence proof, verified generation, or authoritative execution of the formal implementation is needed for that stronger step.

## 2. Definitions must correspond to the accepted JSON AST

Define an indexed typed syntax with result sorts `Int`, `Bool`, and `Priority`, and contexts `score` and `priority`. Constructors correspond one-to-one to the admitted opcodes:

```text
integer constant, severity, age, priority-context score reference,
n-ary integer add, constant-times-expression multiply, integer min,
Boolean blocked, integer >= comparison,
typed Int/Priority if (Boolean if is rejected), and priority constants urgent/high/normal.
```

Make a score reference unconstructible in score context. `Program` consists of a score-context integer expression and a priority-context priority expression. The three priorities are an inductive type, not arbitrary strings. Typed syntax prevents invalid unreachable branches, mixed Boolean/integer expressions, callbacks, and recursive score references independently of certificate decisions.

Keep n-ary addition if production uses it. If Lean elaborates it into binary addition, prove `decodeAdd_preserves_eval` and the relevant node/depth/cost correspondence; associativity over mathematical integers alone does not establish that the resource validator accepts the same language. The evaluator and symbolic checker can use structural recursion on the nested AST, with a secondary list-length measure for addition arguments. Do not introduce `partial`, unchecked termination, or a user-supplied fuel assumption.

Define a concrete environment containing integer severity/age, Boolean blocked, and the already evaluated row score in priority context. Define `evalInt`, `evalBool`, and `evalPriority` exactly as production: `if` selects one branch, `min` evaluates both, multiplication is by an integer constant, score references read the previously computed score.

`numericValid r` means `1 <= severity <= 5` and `0 <= age <= 87600`; Boolean validity follows from the typed representation. `specScore r` is the independent mathematical expression `100*severity + min(age,168) + (if blocked then 50 else 0)`. `specPriority q` is urgent for `q>=500`, high for `300<=q<500`, normal for `q<300`. These definitions must not call the candidate evaluator or the certificate producer.

The first semantic target is:

```text
rowCertificateSound:
  verifyCore program certificate = accepted ->
  forall r, numericValid r ->
    evalScore program r = specScore r /\
    evalRowPriority program r = specPriority (specScore r)
```

This quantifies over every typed program and certificate admitted by the checker, not just the shipped reference program.

## 3. Function-to-definition and theorem mapping

| Planned production behavior / current probe function | Formal definition | Required theorem |
|---|---|---|
| Whole-AST grammar/type/resource validation | `decodeProgram`, `wellFormed`, `withinBudget` | Accepted decoding produces the exact typed context and opcode semantics; every branch is well-typed and budgets are checked. |
| Integer symbolic derivation / `affine` | `deriveInt : Cell -> Expr Int -> Option Affine` | `deriveInt_sound`: a returned affine function equals concrete evaluation at **every** age in the cell. |
| Boolean uniformity / `condition` | `deriveBool : Cell -> Expr Bool -> Option Bool` | `deriveBool_sound`: a returned Boolean equals concrete evaluation throughout the interval. |
| Priority symbolic derivation / `text` | `derivePriority : Cell -> Expr Priority -> Option Priority` | `derivePriority_sound`: a returned priority equals concrete evaluation throughout the interval. |
| Independent score and priority obligations / per-cell `check` body | `checkCell` | `checkCell_sound`: accepted cell yields the business score/priority for every row it contains. |
| Ten-pair grouping, ordering, contiguous range checks / `check` coverage loop | `checkCover` | `cover_sound`: every valid numeric row belongs to exactly one accepted cell occurrence. |
| Full acceptance and report construction / `verify_ticket_certificate` | `verifyCore`, then `verifyDecoded` | `rowCertificateSound`, then `verifyDecoded_sound`; only the `accepted` constructor supplies the theorem premise. |
| Concrete row interpreter / planned execution core | `evalRow` | `evalRow_correct` from certificate soundness; structural totality is built into the definition. |
| Fixed mapping/sort/output / `execute_ticket_program` | `mapRows`, `insert`, `sortRows`, `runTickets` | Total computation; exact row preservation, permutation, sorted order, output shape, and business-spec satisfaction. |

The proof generator is absent from the trusted theorem. Its choices are merely inputs to `verifyCore`.

### Affine extrema and uniform branches

Define `Affine := {slope : Int, intercept : Int}` and `at f a := f.slope*a+f.intercept`. For a nonempty integer interval `[lo,hi]`, prove:

```text
affine_bounds:
  lo <= age -> age <= hi ->
  min (at f lo) (at f hi) <= at f age /\
  at f age <= max (at f lo) (at f hi)
```

Prove this for positive, zero, and negative slopes using ordered-integer multiplication facts. An assertion that candidates are monotone is too weak: negative constants and differences of affine functions are admitted. Endpoint evaluation becomes a proof rule only after this affine lemma and symbolic derivation are established.

Then prove:

- `affine_add_sound` and `affine_scale_sound`, matching actual coefficient operations.
- `uniform_ge_true`: if the difference's minimum is >=0, `L>=R` holds at every age.
- `uniform_ge_false`: if its maximum is <0, `L>=R` is false at every age. Retain the strict/non-strict boundary exactly.
- `uniform_min_left` and `uniform_min_right`: checked extrema prove one operand is the minimum throughout. Equality ties are harmless if both choices have the same value.
- `uniform_if_sound`: a proved uniform Boolean justifies selecting one branch for all ages in the cell.

Prove `deriveInt_sound`, `deriveBool_sound`, and `derivePriority_sound` by mutual structural induction on typed expressions. For a priority-context score reference, explicitly assume that the supplied score-affine representation equals the already evaluated score throughout this cell; discharge that assumption from score derivation before checking priority. Do not assume the target business formula to justify candidate score references.

The derivation may return `none` on a nonuniform cell. Soundness does not require accepting every correct program or finding a partition. A certificate with a well-formed but insufficient split can be rejected honestly.

### Independent cell obligations

Define `Cell` with exact severity/blocked values, integer lower/upper bounds, claimed affine coefficients, and claimed priority. Raw decoding enforces real integer coefficients and actual Boolean tags; typed mathematical values alone do not establish Python's `type(x) is int` rule.

`checkCell` validates bounds, symbolic derivation, witness equality, and independent business obligations. Define `referenceAffine` only for cells wholly below 168 or wholly at/above 168. Prove it equals `specScore` over that cell. The shipped checker compares whole-cell values using zero extrema of the affine difference; it does not require equal coefficient pairs on a singleton.

The formal algorithm must implement the shipped zero-extrema equality and prove `affine_endpoint_eq`: equality at both endpoints gives equality throughout; singleton intervals need their own case and do not imply equal coefficient pairs. Reject intervals crossing the reference `min` boundary unless the implementation explicitly proves another sound representation. Do not formalize coefficient comparison while falsely calling a different endpoint-based Python checker verified.

For priority, prove the accepted relational obligations imply `specPriority`: urgent requires minimum score >=500; high requires minimum >=300 and maximum <500; normal requires maximum <300. These are obligations over the entire interval, not a supplied Boolean witness or an assertion about one sample age.

### Complete cover, including actual occurrences

Formalize the actual grouping/filtering and interval ordering. If production sorts certificate cells, use a proved sorting algorithm in the formal checker or prove its output is the required permutation/order. Do not silently require producer-sorted certificates if Python accepts arbitrary ordering.

For each fixed severity 1..5 and Boolean value, check a contiguous chain beginning at 0, with each lower bound exactly previous upper bound +1, and final upper bound 87600. Prove by list induction that an accepted chain covers each integer in the domain and contains no overlapping interval occurrences. Compose with grouping/filter membership and the ten-pair enumeration.

The precise theorem is `exists exactly one index i in certificate.cells such that cell[i] contains r`. Uniqueness of a cell **value** is insufficient to detect duplicated occurrences in a list. Existence is enough to derive functional row soundness; occurrence uniqueness additionally substantiates the checker’s stated no-overlap/no-duplicate guarantee.

Finally, `verifyCore` must require all cell obligations and all coverage obligations. Resource-exhaustion/unsupported/error constructors cannot satisfy `verifyCore=accepted`. No theorem premise should be phrased as merely `status != rejected`.

## 4. Total interpreter and the full list task

Totality of the formal AST evaluator is enforced by Lean's checked structural/well-founded recursion. A total logical function does not establish that an actual process survives memory exhaustion or finishes before a wall-clock deadline. Keep those runtime assumptions explicit.

Define ticket IDs as finite sequences of Unicode scalar values with lexicographic code-point order, matching the admitted UTF-8/Python string semantics. The pure correctness proof can quantify over every finite ID sequence and numeric-valid row list, which is stronger than the admitted <=64-row/<=4096-byte subset. Byte budget, nonblank-string policy, and character-length restrictions remain decoding/admission obligations; they need not complicate arithmetic soundness. Unpaired surrogates must be rejected at the UTF-8 canonicalization boundary rather than silently converted to a different ID.

Define output rows with exactly `id`, `score`, and `priority` fields, retaining the input ID. The order is lexicographic on `(-score,id)`. Prove that this comparison is a total, antisymmetric, transitive order. No locale, normalization, case folding, or different Unicode-byte order may enter the Python bridge.

The shipped wrapper uses append-and-shift insertion sort; prove its gap invariant and `insertLoop_refines_insert` before using the functional insertion-sort theorem. Prove `insert_perm`, `insert_sorted`, `sort_perm`, and `sort_sorted` by induction; termination decreases the remaining list or sorted-prefix length. Prove `mapRows_preserves_ids` and that every mapped row satisfies the row specification. Define the independent full business specification relationally:

```text
output rows are exactly a permutation of the correctly transformed input rows,
every ID and row is preserved with multiplicity,
rows are sorted by descending score then ascending ID,
and the JSON output contains exactly the tickets field and exact row fields.
```

Then prove `runTickets_satisfies_spec`. Unique input IDs give distinct keys even at equal scores, allowing a `sorted_output_unique` theorem that establishes the one deterministic business result without defining the specification by calling the candidate's sorting function.

Python `sorted` is used for certificate-cell ordering, while the output wrapper is the append-and-shift loop; both correspondence obligations remain distinct. Either change the runtime to the same proved algorithm and justify its Python correspondence, prove the relevant library implementation, or disclose Python sorting as trusted and use only its documented sorted-permutation contract as a bridge assumption. The last option gives a conditional full-task theorem, not formal verification of Timsort.

A separate syntactic-cost theorem can bound AST steps by node count, mapping by row count, and insertion-sort comparisons by a quadratic list bound. Exact wall-clock time and big-integer bit costs require a separate cost model. Accepted AST literal/depth bounds constrain intermediate bit sizes, but must be proved from the actual grammar if used to promise a resource bound.

## 5. Raw JSON, canonical bytes, and Python are real obligations

Use a raw JSON representation that preserves object key occurrences and numeric lexical categories. A JSON library that discards duplicate keys before decoding cannot support a duplicate-rejection theorem by itself. Distinguish `true` from numeric `1`, and integer tokens from floating/exponent forms such as `1.0`/`1e0`. The formal decoder must match production's exact field sets, arities, versions, malformed branches, and budget handling.

Required decoder/representation lemmas:

- `decodeProgram_sound`, `decodeCertificate_sound`: successful decode produces the exact accepted typed objects and well-formed cell fields.
- `decodeInput_sound`: every admitted raw input yields the corresponding typed ticket list satisfying numeric validity, unique IDs, and the frozen-domain restrictions.
- `encode_decode_roundtrip`: decoding canonical encoding gives the same typed program/certificate/input; certificate ordering is preserved unless explicitly normalized.
- `canonical_semantics`: permissible JSON formatting/key-order variation canonicalizes to the same semantics; rejected ambiguity cannot collapse into an accepted representation.
- Budget/depth/node checks cover the complete envelope and all AST branches. Parsing errors and size exhaustion fail closed before authorization.

These decoder theorems can initially start at a trustworthy `RawJson` value boundary. State that the byte-to-`RawJson` tokenizer/UTF-8/parser remains trusted until separately verified. A proof from typed `Program` is valid but does not prove JSON parser behavior.

For the existing Python path, the needed correspondence statement is:

```text
PythonParseAndVerify(programBytes,certificateBytes)=accepted
  -> decodeFormal(programBytes,certificateBytes)=(program,certificate)
     and verifyCore(program,certificate)=accepted

PythonExecute(the same bytes, frozenInputBytes) returns outputBytes
  -> decodeOutput(outputBytes)=runTickets(program,decodeInput(frozenInputBytes))
```

This is an obligation, not something hashes or ordinary differential tests prove. It includes Python integer/Boolean checks, every opcode/branch, score caching, grouping/sorting/coverage, array ordering, Unicode conversion, exception/resource handling, canonicalization, and output construction. Verify and execute must consume the same normalized AST bytes; the bridge cannot execute arbitrary Python carrying a certificate for another program.

Two honest development options:

1. Formal reference checker/interpreter with the Python version retained: the theorem proves the formal model; Python correspondence remains a documented trusted assumption. Differential/negative tests can strengthen implementation confidence but do not turn that assumption into a proof.
2. Make the formally defined checker/interpreter authoritative at runtime, compiled from the pinned formal source and invoked by the protected Python bridge. Then Python routes immutable bytes/input and performs IO only; it does not override proof acceptance or recompute unverified semantics. This reduces the Python correspondence burden, while adding the compiler/runtime/serialization bridge to the trusted base. A build-time theorem next to an independent Python implementation is not this option.

The receipt must originate in the protected runner and bind actual consumed program/certificate/input/output and runner version. It cannot come from the model. Correct output semantics do not prove an artifact was written, a lease remained current, or a provider used the program. Keep atomic admission/request binding, current pause/refinement/identity checks, confined filesystem IO, and final `json_reference` artifact verification as separately tested/trusted operational layers. The formal theorem's scope must name these boundaries rather than absorbing them into an unstated “system correctness” claim.

Hash equality is an artifact-identity guard, not a theorem of semantic equivalence. Keep cryptographic collision resistance outside the pure arithmetic theorem. Compare actual normalized bytes where practical; if relying on hashes for retrieval/identity, name that security assumption and the protected-artifact boundary.

## 6. Smallest credible mechanized artifact and release evidence

The first credible increment is `Syntax` + `Semantics` + `Affine` + `Certificate` + `Soundness`, with a kernel-checked **general** `rowCertificateSound` theorem for the actual checker and accepted AST grammar, plus the actual 26-cell fixture and the nonidentical equivalent program as acceptance examples. This machine-proves all-domain row checker soundness in the formal model. It does not yet machine-prove the list wrapper, raw JSON parser, Python implementation, admission protocol, or IO.

The next increment adds `Wrapper` and `runTickets_satisfies_spec`, then decoder correspondence. Only after authoritative runtime integration or a genuine Python refinement proof may the runtime claim be strengthened beyond “formal model proved; Python/bridge correspondence trusted.” Do not mark all-input program execution mechanically verified solely because the first increment passed.

Required retained proof/check output before claiming any increment complete:

- Exact formal source commit/hash, pinned Lean version/toolchain, dependency lock/hashes, and the grammar/specification version tied to the production artifact.
- Actual clean proof-check/build command, timestamp, exit status, and complete stdout/stderr. No source containing a theorem statement counts as a successful proof.
- Axioms printed for `rowCertificateSound` and `runTickets_satisfies_spec`; reject `sorry` dependencies, new axioms, and unapproved oracle/native-evaluation dependencies. A text search alone is insufficient.
- Ordinary tactic-produced proof terms checked by the Lean kernel. External automation can suggest proofs; its success status must not replace a kernel-checked term.
- Actual fixture acceptance checked through proof-producing kernel reduction or a justified checked computation theorem. `#eval` output alone is runtime evaluation, not a logical acceptance proof.
- Independent replay from pinned source/dependencies rather than trusting an unreviewed imported compiled artifact. Retain the replay result, theorem names, and exact proved scope.
- For a compiled authoritative runner, executable/build/toolchain hashes, deployed path and protection evidence, byte/semantic conversion specification, and actual bridge integration evidence. Successful compilation alone does not establish deployment or use.

Lean’s kernel, elaborated imports/base theory, theorem-checking executable, and relevant standard-library definitions are trusted. Prefer constructive definitions and proofs; if classical choice/propositional extensionality/quotient axioms appear, disclose the actual dependency list rather than claiming “axiom-free.” Normal proof-generating tactics are not separate trusted oracles when their terms are kernel-checked. Unchecked native evaluation, new assumptions, or proof holes cannot be silently accepted.

Compiled runtime use additionally trusts Lean code generation, C/toolchain/backend as applicable, linking/runtime, OS/hardware, protected deployment, and the IO bridge. Kernel proof checking and compiled execution are different trust boundaries. The current official Lean Introduction and Axioms/Computation sources retained in this directory support that distinction; no new source retrieval or formal tool execution occurred in this follow-up.

## 7. Why this is meaningful, and what it cannot decide

The row domain has 876,010 numeric combinations, but the certificate proves them through 26 complete integer intervals and checked affine rules rather than enumerated cases. The formal theorem can quantify over every accepted DSL AST/certificate and every row in that domain. Structural recursion also handles every finite list in the formal wrapper, with the deployment limiting rows/bytes for resources. Universal quantification inside these explicit restrictions is useful and legitimate.

This remains an incomplete certificate system for a terminating, effect-free language. A correct candidate can be rejected because its cells are insufficient, its syntax is unsupported, or resources are exceeded. The checker does not decide semantic correctness for arbitrary Python, nontermination, external state, or natural-language goals. Machine-formalizing its soundness strengthens the scoped guarantee; it does not remove those limits, prove subjective consciousness, or prove long-term benefit.
