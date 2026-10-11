# Executable typed ticket checker proof, milestone 1

This isolated package proves the soundness of a computed, typed model of the
ticket interval-certificate checker. The theorem quantifies over every program
in the modeled grammar, every accepted typed certificate, and every legal row.
It does not assume score correctness, correct witnesses, uniform guards, or
semantic coverage: those facts follow from the computed acceptance premise.

The final theorem is `HermesTicket.rowCertificateSound`:

```text
checkTyped program cells = true -> validRow row ->
  evalScore program row = specScore row /\
  evalRowPriority program row = businessPriority (specScore row)
```

`businessPriority` is the independent specification with thresholds 500 and
300. Priority evaluation uses the candidate score actually evaluated by the
program. `accepted_coverage_unique` proves exactly one original certificate
occurrence covers each legal row; `accepted_resources` extracts computed
program/certificate limits. All evaluators and derivations are total recursive
Lean definitions, accepted by Lean's termination checker. There is no theorem
about arbitrary Python programs or an unrestricted correctness decider.

## Source structure

- `Interfaces`: fixed version/reference identity; integer domain, cell
  validation, affine arithmetic, score/priority specification, endpoint tests.
- `Syntax`: exact typed expression grammar and evaluator; n-ary operands as a
  mutual `Terms` representation; both branches count toward budgets; root depth
  zero, depth 24 accepted, combined 256 nodes, scalar/literal bounds.
- `Affine`: interval bounds for any integer slope, value equality on cells,
  reference/spec and endpoint priority soundness.
- `Derive`: general mutually recursive soundness for every integer, Boolean,
  n-ary term and priority constructor, including score-context compatibility.
- `Coverage`: the exact ten groups, stable lower-endpoint insertion sort,
  occurrence-preserving permutation, contiguous checked chain, count-one and
  original-index uniqueness proofs.
- `Certificate`: conjunction of resource checks, all-cell validation, computed
  coverage and all-cell derivation/equality/priority checks; final theorem.
- `Fixtures`: two different accepted programs, a 26-cell complete certificate,
  unsorted acceptance, and adversarial/boundary kernel-reduction proofs.
- `KernelAudit`: actual dependency-closure output for general/supporting
  theorems and concrete positive/negative examples.

## Toolchain and replay

Only Lean's bundled `Std` libraries are used; there is no Mathlib or other
external package. Toolchain: official Lean 4.19.0 Linux x86_64 release, source
commit `6caaee842e9495688c1567e78c0e68dbb96942aa`. The release archive has
343842845 bytes and locally computed SHA-256
`6fe3ce97a58f44e2b3567d455b994eacec5bfe9ae7774f2a573444480ba813fe`.
Official download metadata supplied no publisher digest. Distribution trust is
the official release obtained over verified TLS, followed by local artifact
pinning; this is not an independently authenticated publisher checksum.
Download/installation records are retained in `toolchain/provenance`. The
installation record's `proof_sources_compiled: false` is the historical setup
checkpoint, not the final proof result.

`frozen-sources.json` pins formal sources, replay driver and configuration.
`evidence/toolchain-tree.json` pins the extracted official toolchain files.
Replay verifies those bytes, copies only frozen source/configuration into a
new directory, builds every local proof module afresh, runs the separate
kernel dependency audit and checks both source/toolchain bytes again:

```sh
python3 replay.py \
  --toolchain /absolute/path/to/the/recorded/toolchain \
  --workdir /absolute/path/to/a/new/replay-directory
```

The directory must not exist. Full output and separate exit statuses are
retained under its `replay-evidence`. No local compiled proof objects are
copied. The official compiler/bootstrap binaries and bundled foundational
libraries remain trusted. `#print axioms` must show only the predeclared
allowlist `propext`, `Quot.sound`, `Classical.choice` when actually used. The
audit rejects any other dependency, including `sorryAx`, added user axioms,
or unchecked evaluation/oracle dependencies. Positive fixture proofs use
ordinary kernel reduction, not native evaluation.

## Scope and correspondence boundary

The model is mapped by source inspection to `certified_ticket.py` with SHA-256
`232a90b524f8c248d764950bc021ab9fe2cc731c379fe5519b58bc99862fbbd2`.
It represents fixed schema/reference identity by construction. This proof does
not establish a refinement theorem from Python execution or JSON bytes to Lean
values. The inspection mapping and public typed fixtures are evidence of the
intended relationship, not a proof of that missing bridge.

The strict UTF-8/JSON parser, duplicate-key/type/byte/depth checks, conversion
to immutable tuple ASTs, fixed schema/header rejection, Python integer and
Unicode behavior, data-object input canonicalization, Python exceptions and
resource availability, same-AST interpreter integration, hash/artifact/session
binding, fixed insertion-sort ticket wrapper, list permutation/order/ID
semantics, native admission, filesystem/SQLite/IO, real wall-clock completion,
and source-to-executable compiler/host integrity remain outside this theorem.
The Python insertion sort's append/shift algorithm is not the functional cell
sort proved in `Coverage`; proving that runtime wrapper requires a separate
hole invariant and string-order/input refinement.

No claim about consciousness, benefit, or universal correctness follows from
this bounded theorem. The unchanged Python report remains
`reviewed_argument_not_machine_formalized` until a separately reviewed bridge
can justify a stronger deployed-runtime claim. Earlier research milestones
remain historical UNRUN checkpoints; this package records actual subsequent
proof execution without retroactively changing those checkpoints.
