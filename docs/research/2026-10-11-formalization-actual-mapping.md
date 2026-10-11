# Appendix: formalization mapped to reviewed Task B

Read-only checkpoint: repository HEAD `6d3a6f60cb1ee794ee6da0bef7ba5099bbd4c16e`, after reviewed product commit `d2ce6b059fbd3e2e1f83c48ce1464ad07cf70cf8`. Sources inspected: `certified_ticket.py`, `certified_bindings.py`, `scripts/native_work_acceptance.py`, and the retained Task B report. No repository edits, tests, installations, proof tools, provider calls, or Docker runs occurred in this refresh. Existing hypotheses are unchanged. **The implementation remains a reviewed custom certificate checker, not a machine-proven Python implementation.**

## Exact implementation-to-Lean mapping

The theorem names below are proposed obligations, not existing proofs. A pure typed Lean core should model the actual operations; a separate correspondence obligation connects this core to the Python facade and protected native bridge.

| Actual function | Planned formal definition / theorem obligation |
|---|---|
| `strict_load` (line 57) | `decodeStrictJson`: immutable byte input, strict UTF-8, duplicate-object-key rejection, integer-token categories, no float/exponent/nonfinite tokens, raw-byte and actual JSON-depth limits. `decodeStrictJson_sound` may initially assume a trusted byte tokenizer/parser, but must name that boundary. |
| `_ast` (line 88) | `decodeTypedExpr` / `typedDecode_sound`: result sorts Int/Bool/Priority and score-reference context, exact arities, validation of **all** branches, immutable tuple representation, combined node/depth/scalar limits. Prove n-ary addition correspondence rather than silently replacing it with binary AST nodes. |
| `_extrema` / `_subtract` (lines 120/125) | `affineBounds`, `affineSubtract`: for every integer age in a nonempty cell, affine value lies between endpoint min/max, for either slope sign. This supplies whole-interval reasoning, not endpoint sampling. |
| `_derive` (line 128) | One sorted `derive` function returning affine pairs, Booleans, or priorities. Prove mutual `deriveInt_sound`, `deriveBool_sound`, `derivePriority_sound` relative to concrete evaluation. Its Bool result is an actual Boolean; Python branch truthiness is justified by this type invariant. Score references require the passed score-affine relation, discharged from the score expression's derivation. |
| `_equal_on_cell` (line 156) | `equalOnCell_sound`: extrema of the affine difference equal `(0,0)` iff values are equal at every age in this closed interval. Do **not** conclude coefficient-pair equality for a singleton. |
| `_check` (line 160) | `checkProgramCertificate`: strict headers/reference ID, all cell/domain/witness types, grouped sorted contiguous cover, independent score relation, witness equality, priority derivation and threshold relation. `cover_sound` concerns exactly one **list occurrence index** per legal row. `cell_sound` and `rowCertificateSound` cover all admitted programs/certificates, not only the supplied fixture. |
| `_verified` / `verify_ticket_certificate` (lines 202/225) | `verifyFacade`: `certified_within_scope` implies complete core acceptance plus successful decoding/version selection. Unsupported/malformed inputs reject; resource/recursion/memory/installed-file-read failures are unavailable. Returned reports are not authorization tokens. Hash generation and exception/status handling remain facade correspondence obligations. |
| `validate_ticket_input` (line 230) | `normalizeAndDecodeInput`: canonicalize a Python JSON-like **data object**, then strict-load and validate the canonical copy. Prove resulting typed rows satisfy exact fields, numeric domain, actual Booleans, unique nonblank Unicode IDs, and bounds. This public API does not accept raw input bytes. |
| `_eval` (line 247) | `eval`: structural, total typed evaluation with selected-only `if`, eager `min`, left operand on equality, n-ary sum, scalar multiplication, and cached row-score lookup. `derive_eval_agree` links accepted symbolic derivation to this concrete interpreter. |
| `execute_ticket_program` (line 263) | `executeChecked`: call `_verified` afresh, use its returned tuple AST directly, normalize the input, map every row preserving IDs, and append/shift insertion-sort the output. Prove row semantics, `insertLoop_refines_insert`, sorted permutation, exact output shape, and totality of finite AST/list/index iteration. |

## Grammar and limits to freeze exactly

The actual Boolean grammar is only `blocked` and integer `ge`. `if` is allowed for **Int and Priority only**; Boolean `if` explicitly raises `unsupported_boolean_if`. The earlier roadmap's generic “typed if” must be narrowed. Score references are forbidden throughout the score expression, allowed throughout the priority expression, including its numeric guards. Priorities are exactly urgent/high/normal.

JSON array ASTs become recursively immutable tuples. `add` has at least two arguments and remains n-ary. The score and priority ASTs share one work counter with a combined <=256-node cap; AST depth starts at 0 and rejects depth >24. Integer literals/scalars and affine-witness coefficients lie in [-1,000,000,1,000,000]. These coefficient bounds apply to **supplied witnesses**, not every intermediate derived coefficient: candidate expressions may derive larger coefficients and still prove correct values on singleton cells. The formal checker must not impose an unimplemented intermediate bound.

`strict_load` defaults to 16,384 raw program bytes and JSON depth 28. Certificates use 65,536 raw bytes and depth 28; <=512 cells are admitted. Every integer token is limited to <=8 characters, including its sign, before `int` construction. Float/exponent forms are rejected globally, even when mathematically integral. Raw size and integer-token limits can classify semantically equivalent byte encodings differently. Canonical hashes are identities of decoded/canonicalized values, not raw-format identities.

The separate inline bundle normalizer accepts exactly `{schema,program,certificate}`, canonicalizes a copy, limits it to **6000 canonical bytes**, and strict-loads it at depth 28. The immutable execution intent is capped at 16,384 bytes; `INPUT_ENVELOPE_DEPTH` is 34. The public pure input API canonicalizes `input_data` and applies <=4096 canonical UTF-8 bytes, depth 32, <=64 rows, exact ticket/root fields, unique actual-string IDs with `sid.strip()` nonempty and <=200 Python characters, severity 1..5, age 0..87600, and actual Booleans. Python Unicode whitespace classification and character ordering are explicit bridge/runtime assumptions until modeled.

The native runner adds a raw-input layer: it opens fixed `facts.json` without following symlinks, reads at most 4097 bytes, requires <=4096 bytes and the exact frozen **raw byte hash**, and strict-loads those bytes before calling the data-object API. Thus canonical input-data correctness and exact native byte-use provenance are different obligations; neither substitutes for the other.

## Reference cells and singleton equality

`_check` first validates every cell and the complete cover. For each of the ten fixed severity/Boolean pairs, it uses Python `sorted(cells,key=lo)`, requires `lo=next_age` beginning at 0, advances to `hi+1`, and requires final next age 87601. The formal checker must model sorting/filtering and occurrence-preserving coverage. A theorem assuming producer-sorted certificates would not match this implementation.

Only after coverage succeeds does `_check` derive each score. Its independently encoded reference is:

- `hi < 168`: affine pair `(1,100*severity+50*blocked)`.
- `lo >= 168`: affine pair `(0,100*severity+50*blocked+168)`.
- Otherwise: reject `reference_nonuniform_cell`.

Here the Boolean's internal numeric interpretation is 0/1; that deliberate trusted arithmetic conversion does not allow Booleans in integer-typed input/witness fields.

Both score-versus-reference and score-versus-witness comparisons use `_equal_on_cell`, not coefficient equality. For example, on `[168,168]`, `(1,0)` and `(0,168)` denote the same value; a valid alternative witness representation must not be falsely rejected by a formal model that demands pair equality. Prove zero-extrema difference implies equality at every age, treating singleton and nonsingleton intervals correctly.

Priority is derived using the **candidate derived score pair**. Its independent threshold obligations use the reference pair's extrema, whose values have already been proved equal on the cell: urgent minimum >=500; high minimum >=300 and maximum <500; normal maximum <300. Claimed cell priority must equal the derived text. This precise sequencing supplies the soundness premise for priority-context score references.

## The shipped insertion sort needs a loop correspondence lemma

The implementation appends `result`, keeps it in a local variable, and shifts greater predecessors right while decreasing `index`; then it places `result` in the gap. A functional Lean insertion-sort theorem is useful but must be linked by `insertLoop_refines_insert` to this actual append/shift loop.

During shifting the array temporarily duplicates a predecessor, so “the whole current array is a permutation” is **not** a correct inner-loop invariant. Use a gap invariant: excluding the current gap at `index`, the stored prefix/suffix together with local `result` have exactly the required multiset; the shifted suffix contains the appropriate greater elements in order. Each iteration moves the gap left and strictly decreases `index`. At termination, filling the gap restores a sorted permutation. Compose with the outer processed-row invariant and exact ID preservation. The comparator is strict lexicographic `(-score,id)`; Python integer and Unicode-string comparison must agree with the formal order. Unique input IDs make the resulting key order unique.

Structural termination proves no mathematical divergence of accepted AST/list evaluation. It does not prove wall-clock availability, Python stack/memory survival, filesystem success, or external workflow liveness. Runtime grammar/input caps make the work bounded, while those process assumptions remain named.

## Same-AST execution, hashes, and the actual bridge boundary

`execute_ticket_program` does not accept a caller's success report: it rechecks the immutable program/certificate bytes and receives ASTs directly from that same `_verified` call. `_ast` built the tuple ASTs used by both `_derive` and `_eval`. A later theorem should state this concrete success/dataflow relation, not merely equality of an arbitrary Python file's hash with a mathematical function's name.

Actual reports compute `program_hash`, `certificate_hash`, fixed `semantics_hash`, `domain_hash`, `reference_hash`, and installed `checker_hash` from the kernel's own source file. The file includes parser, checker, interpreter, and wrapper. Hashes track artifact identity; they do not prove any of their semantics. A failed own-file read yields unavailable. SHA-256 collision resistance and protected deployment are operational assumptions, not axioms needed for the pure affine theorem.

The protected runner is **generated by `certified_runner_body()` in `scripts/native_work_acceptance.py`**, not a separate checked-in `certified_runner.py`. `prepare_certified_runner` installs read-only runner/kernel/bundle/scope siblings, binds them in the deployment manifest and exact command allowlist, and the existing container cache bind is read-only. Execution uses `python3 -I` and a fixed sibling kernel rather than candidate workspace imports. The runner checks fixed work/kernel/bundle/input identities, executes the interpreter, atomically replaces fixed `result.json`, and emits actual value/hash metadata. `audit_native_certified` subsequently ties installed files to the actual immutable admission, native idempotency/session record, exactly one successful foreground invocation, receipt, and independently read reference-checked artifact.

Those controls are real reviewed implementation, but the parser/Python runtime, fixed import/runner generation, filesystem/mount protection, registry/SQLite admission, transcript association, output replacement, and final verifier are not thereby formalized. No live provider/native run was performed by this appendix. A future Lean core theorem applies to runtime only conditionally on proven or explicitly trusted Python/serialization/bridge correspondence, or after making the formally defined checker/interpreter authoritative in deployed execution.

## Corrections for the tracked roadmap

1. Preserve its earlier research checkpoint as history, then add this actual mapping and product commit; replace future-facing helper-name assumptions with the unified `_derive`/`_check` mapping.
2. Narrow generic typed `if` to Int/Priority; record n-ary addition, tuple ASTs, context restrictions, and shared AST-node accounting.
3. Select actual zero-extrema **value equality** for score/reference/witness obligations; remove coefficient equality as the assumed shipped behavior and retain singleton representations.
4. Record actual JSON/integer-token/inline-bundle caps and separate raw-byte parser, canonical data-object input, immutable request, and native fixed-source boundaries.
5. Replace optional sorting alternatives with the actual append/shift wrapper plus its gap-invariant refinement obligation; retain Python sorting as a dependency for **certificate coverage ordering**.
6. Replace hypothetical future runner descriptions with the generated protected runner and post-run native audit, while keeping their TCB/correspondence limits explicit.

The next credible machine artifact remains a general `rowCertificateSound` theorem for these actual decoding/core rules, followed by the exact loop/wrapper theorem. Fixture reduction, exhaustive row tests, supplied report success, source hashes, or a formula-only proof do not replace checker soundness or Python refinement. No proof result or evidence label should be upgraded by this mapping refresh.
